"""SimulationManager: singleton guard for concurrent simulation requests."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import httpx
import structlog

from alphaswarm.errors import InferenceConfigError, run_error_from_exception
from alphaswarm.types import SimulationPhase

if TYPE_CHECKING:
    from fastapi import FastAPI

    from alphaswarm.app import AppState
    from alphaswarm.inference.factory import BuiltProviders
    from alphaswarm.types import BracketConfig
    from alphaswarm.web.replay_manager import ReplayManager

log = structlog.get_logger(component="web.simulation_manager")

_ROUND_PHASES = frozenset(
    {SimulationPhase.ROUND_1, SimulationPhase.ROUND_2, SimulationPhase.ROUND_3}
)


def _error_code(resp: httpx.Response) -> str | None:
    """Return the `detail.error` code of an error response, or None."""
    try:
        body = resp.json()
    except ValueError:
        return None
    detail = body.get("detail") if isinstance(body, dict) else None
    code = detail.get("error") if isinstance(detail, dict) else None
    return code if isinstance(code, str) else None


async def _auto_trigger_advisory(app: FastAPI, cycle_id: str) -> None:
    """POST /api/advisory/{cycle_id} in-process after simulation completes.

    Uses httpx.ASGITransport to call the FastAPI ASGI app directly — no
    network socket, no port assumption. All route guards (409, 503) are
    re-used. Non-202 responses are swallowed: 409 means another task is
    already running (fine), 503 means portfolio unavailable (advisory
    impossible — expected degraded mode). Any network-level exception is
    logged and swallowed so it never surfaces as an unhandled exception.
    """
    try:
        transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post(f"/api/advisory/{cycle_id}")
        if resp.status_code == 202:
            log.info("auto_advisory_trigger_accepted", cycle_id=cycle_id)
        elif resp.status_code == 409 and _error_code(resp) == "cloud_advisory_disabled":
            # Cloud or remote orchestrator without the opt-in: the portfolio stays local
            # (docs/DECISIONS.md#adr-advisory-pipeline).
            log.info("auto_advisory_skipped_cloud", cycle_id=cycle_id)
        elif resp.status_code == 409:
            log.info("auto_advisory_trigger_skipped_conflict", cycle_id=cycle_id)
        elif resp.status_code == 503:
            log.warning("auto_advisory_trigger_skipped_unavailable", cycle_id=cycle_id)
        else:
            log.warning(
                "auto_advisory_trigger_unexpected_status",
                cycle_id=cycle_id,
                status=resp.status_code,
            )
    except Exception:
        log.exception("auto_advisory_trigger_failed", cycle_id=cycle_id)


class SimulationAlreadyRunningError(Exception):
    """Raised when start() is called while a simulation is already active."""


class NoSimulationRunningError(Exception):
    """Raised when stop/shock called with no active simulation."""


class ShockAlreadyQueuedError(Exception):
    """Raised when inject_shock called while a shock is already queued."""


class ReplayActiveError(Exception):
    """Raised when start() is called while a replay session is active."""


class SimulationManager:
    """Thin wrapper enforcing single-simulation concurrency via asyncio.Lock.

    Created inside FastAPI lifespan. Uses fire-and-forget pattern with
    create_task + done-callback so start() returns immediately (HTTP 202).

    CRITICAL LOCK LIFECYCLE:
    - start() acquires the lock via ``await self._lock.acquire()`` -- NOT
      ``async with self._lock``. The lock is held for the entire duration
      of the background simulation task.
    - The lock is ONLY released inside ``_on_task_done`` callback, which
      fires when the task completes, fails, or is cancelled.
    - If ``async with self._lock`` were used, the lock would release
      immediately after ``create_task()`` returns, allowing concurrent
      starts to slip through.
    """

    def __init__(
        self,
        app_state: AppState,
        brackets: list[BracketConfig],
        on_start: Callable[[], None] | None = None,
        replay_manager: ReplayManager | None = None,
        on_complete: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._app_state = app_state
        self._brackets = brackets
        self._on_start = on_start
        self._replay_manager = replay_manager
        self._on_complete = on_complete
        self._lock = asyncio.Lock()
        self._is_running: bool = False
        self._task: asyncio.Task[None] | None = None
        self._pending_shock: str | None = None
        self._last_cycle_id: str | None = None
        # Strong references to fire-and-forget callback tasks (on_complete
        # trigger). The event loop holds only weak refs to tasks; without
        # this set the auto-advisory trigger can be GC'd before it runs.
        self._bg_tasks: set[asyncio.Task[None]] = set()

    @property
    def is_running(self) -> bool:
        """True when a simulation is currently executing."""
        return self._is_running

    @property
    def pending_shock(self) -> str | None:
        """Current pending shock text, or None if no shock queued."""
        return self._pending_shock

    async def start(self, seed: str) -> None:
        """Start a simulation. Raises SimulationAlreadyRunningError if one is active.

        Raises ReplayActiveError if a replay session is currently active (B4).
        The replay-active check fires BEFORE the already-running check so a
        concurrent replay takes precedence over a concurrent-start error.

        Uses lock.locked() as a fast non-blocking check before acquiring.
        The lock is acquired here but ONLY released in _on_task_done.
        """
        # B4 sim-side: bi-directional guard — prevent live sim start during replay.
        # Use getattr chain so tests passing MagicMock as app_state (without explicit
        # replay_manager) continue to work when _replay_manager is None.
        if self._replay_manager is not None and getattr(self._replay_manager, "is_active", False):
            raise ReplayActiveError("Cannot start simulation while replay is active")
        if self._lock.locked():
            raise SimulationAlreadyRunningError("Simulation already running")
        # Review fix: Clear interview sessions (and any other start hooks) before pipeline begins.
        # on_start is set in app.py lifespan to lambda: app.state.interview_sessions.clear()
        if self._on_start is not None:
            self._on_start()
        await self._lock.acquire()
        try:
            # A new run starts with an empty error slot, before the first frame.
            await self._app_state.state_store.set_last_error(None)
        except BaseException:
            self._lock.release()
            raise
        self._is_running = True
        self._pending_shock = None  # Reset shock state
        log.info("simulation_started", seed_length=len(seed))
        self._task = asyncio.create_task(self._run(seed))
        self._task.add_done_callback(self._on_task_done)

    async def _run(self, seed: str) -> None:
        """Execute the simulation pipeline in a background task.

        B8: Phase reset on CancelledError / Exception happens INSIDE this
        coroutine (before the done-callback fires), not as a separate
        fire-and-forget task. This guarantees phase is IDLE before the
        lock is released, closing the race where a concurrent start()
        could slip between lock-release and the async reset.

        B10 (docs/DECISIONS.md#b10): COMPLETE is set by run_simulation as the single source of
        truth — no duplicate set_phase(COMPLETE) here.
        """
        import asyncio as _asyncio
        import contextlib as _ctx

        from alphaswarm.config import load_inference_config
        from alphaswarm.inference.factory import build_controller, build_providers, inference_mode
        from alphaswarm.simulation import run_simulation

        # `built` may remain None if cancelled before build_providers completes.
        # The finally block guards aclose() accordingly.
        built: BuiltProviders | None = None

        try:
            try:
                # Load inference config off the event loop (sync file I/O).
                cfg = await _asyncio.to_thread(load_inference_config, self._app_state.settings)
                built = build_providers(
                    cfg,
                    ollama_client=self._app_state.ollama_client,
                    ollama_model_manager=self._app_state.model_manager,
                )
            except ValueError as exc:
                # The ValueError text can quote the file path and raw config
                # values, API keys included, so neither the UI nor the log gets
                # it (docs/DECISIONS.md#adr-local-first-inference).
                log.error("inference_config_invalid", error_type=type(exc).__name__)
                raise InferenceConfigError(
                    "The saved inference configuration is invalid. "
                    "Open Settings and save a valid configuration."
                ) from None
            controller = build_controller(
                cfg,
                self._app_state.settings.governor,
                state_store=self._app_state.state_store,
            )

            # Store budget meter + inference mode on app_state for telemetry/estimates.
            self._app_state.budget_meter = built.budget_meter  # type: ignore[attr-defined]
            self._app_state.inference_mode = inference_mode(cfg)  # type: ignore[attr-defined]

            log.info(
                "inference_config_loaded",
                mode=self._app_state.inference_mode,  # type: ignore[attr-defined]
            )

            result = await run_simulation(
                rumor=seed,
                settings=self._app_state.settings,
                ollama_client=self._app_state.ollama_client,
                model_manager=self._app_state.model_manager,
                graph_manager=self._app_state.graph_manager,
                governor=controller,
                personas=list(self._app_state.personas),
                brackets=list(self._brackets),
                state_store=self._app_state.state_store,
                consume_shock=self.consume_shock,
                market_provider=self._app_state.market_provider,
                news_provider=self._app_state.news_provider,
                orchestrator_provider=built.orchestrator,
                worker_provider=built.worker,
            )
            self._last_cycle_id = result.cycle_id
            # B10: do NOT set COMPLETE here — run_simulation is the single
            # source of truth and sets it before this await returns.
        except asyncio.CancelledError:
            # B8: reset phase synchronously BEFORE re-raising; the done-callback
            # fires after _run returns, so the phase is guaranteed IDLE before
            # the lock is released.
            try:
                await self._app_state.state_store.set_phase(SimulationPhase.IDLE)
            except Exception:
                log.error("failed_to_reset_phase_to_idle_on_cancel")
            raise
        except Exception as exc:
            await self._publish_failure(exc)
            try:
                await self._app_state.state_store.set_phase(SimulationPhase.IDLE)
            except Exception:
                log.error("failed_to_reset_phase_to_idle_on_error")
            raise
        finally:
            # aclose providers so cloud clients (httpx/anthropic) release connections.
            # OllamaProvider.aclose is a documented no-op — safe for the local path.
            # Guard: built may be None if cancelled before build_providers completed.
            if built is not None:
                async with _ctx.AsyncExitStack() as stack:
                    stack.push_async_callback(built.orchestrator.aclose)
                    stack.push_async_callback(built.worker.aclose)

    async def _publish_failure(self, exc: BaseException) -> None:
        """Put a UI-safe RunError on the StateStore and log the failure once.

        Never raises: a broken store must not stop the phase reset that follows
        (docs/DECISIONS.md#adr-taskgroup-dispatch).
        """
        store = self._app_state.state_store
        try:
            snap = store.snapshot()
            round_num = snap.round_num if snap.phase in _ROUND_PHASES else None
            err = run_error_from_exception(exc, round_num=round_num)
            await store.set_last_error(err)
        except Exception:
            log.warning("last_error_publish_failed", exc_info=True)
            return
        log.error(
            "simulation_run_failed",
            error_code=err.code,
            round_num=err.round_num,
            exc_info=exc,
        )

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        """Synchronous done-callback: releases lock and logs outcome.

        B8: Phase reset on cancel/exception is now handled inside _run's
        try/except (awaited before the task completes). This callback no
        longer schedules a fire-and-forget reset task — that created a
        race where a concurrent start() could slip between lock-release
        and the async phase reset.
        """
        self._is_running = False
        self._task = None
        self._pending_shock = None
        self._lock.release()
        if not task.cancelled() and task.exception() is None:
            cycle_id = self._last_cycle_id
            self._last_cycle_id = None  # reset for next run
            if cycle_id is not None and self._on_complete is not None:
                trigger: asyncio.Task[None] = asyncio.create_task(
                    self._run_on_complete(cycle_id),
                    name=f"auto_advisory_{cycle_id}",
                )
                self._bg_tasks.add(trigger)
                trigger.add_done_callback(self._bg_tasks.discard)
            log.info("simulation_completed")
        elif task.cancelled():
            log.info("simulation_cancelled")
        else:
            exc = task.exception()
            # Details were logged by _publish_failure; keep this line text-free.
            log.info("simulation_task_failed", error_type=type(exc).__name__)

    def stop(self) -> None:
        """Stop the running simulation by cancelling the background task.

        Raises NoSimulationRunningError if no simulation is active.
        """
        if not self._is_running or self._task is None:
            raise NoSimulationRunningError("No simulation is running")
        self._task.cancel()
        log.info("simulation_stop_requested")

    def inject_shock(self, shock_text: str) -> None:
        """Queue a shock for the next simulation round.

        Raises NoSimulationRunningError if no simulation is active.
        Raises ShockAlreadyQueuedError if a shock is already pending.
        """
        if not self._is_running:
            raise NoSimulationRunningError("No simulation is running")
        if self._pending_shock is not None:
            raise ShockAlreadyQueuedError("A shock is already queued")
        self._pending_shock = shock_text
        log.info("shock_queued", shock_length=len(shock_text))

    def consume_shock(self) -> str | None:
        """Return and clear the pending shock text."""
        shock = self._pending_shock
        self._pending_shock = None
        return shock

    async def _run_on_complete(self, cycle_id: str) -> None:
        """Await the on_complete callback (typed coroutine wrapper for create_task)."""
        assert self._on_complete is not None
        await self._on_complete(cycle_id)

    async def shutdown(self) -> None:
        """Cancel any running simulation and pending trigger tasks (lifespan teardown).

        Awaits cancellation so the graph manager can be closed safely afterward
        without orphaned tasks mid-Neo4j-write.
        """
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        for bg in list(self._bg_tasks):
            if not bg.done():
                bg.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await bg
