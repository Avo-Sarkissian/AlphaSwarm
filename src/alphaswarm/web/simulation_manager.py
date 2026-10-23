"""SimulationManager: singleton guard for concurrent simulation requests."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import structlog

from alphaswarm.errors import (
    INFERENCE_CONFIG_INCOMPLETE_MESSAGE,
    INFERENCE_CONFIG_INVALID_MESSAGE,
    InferenceConfigError,
    InferenceConfigIncompleteError,
    run_error_from_exception,
)
from alphaswarm.types import SimulationPhase

if TYPE_CHECKING:
    from alphaswarm.app import AppState
    from alphaswarm.inference.factory import BuiltProviders
    from alphaswarm.types import BracketConfig
    from alphaswarm.web.replay_manager import ReplayManager

log = structlog.get_logger(component="web.simulation_manager")

# Phases whose failures carry the store's round number in the RunError.
# FINALIZING is not a round: it runs after the last one, so a failure there
# names no round (docs/DECISIONS.md#p7-d-07).
_ROUND_PHASES = frozenset({SimulationPhase.ROUND_1, SimulationPhase.ROUND_2, SimulationPhase.ROUND_3})


class SimulationAlreadyRunningError(Exception):
    """Raised when start() is called while a simulation is already active."""


class NoSimulationRunningError(Exception):
    """Raised when stop/shock called with no active simulation."""


class ShockAlreadyQueuedError(Exception):
    """Raised when inject_shock called while a shock is already queued."""


class ShockWindowClosedError(Exception):
    """Raised when a shock arrives after the last gated round has started."""


class ReplayActiveError(Exception):
    """Raised when start() is called while a replay session is active."""


class PostRunJobsInProgressError(Exception):
    """Raised when start() is called while post-run jobs hold the orchestrator.

    Covers the post-run pipeline task (from the end of a run until its report
    finishes) and manual report/advisory jobs (docs/DECISIONS.md#adr-sequential-model-lifecycle).
    """


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
        on_complete: Callable[[str], Awaitable[object]] | None = None,
        orchestrator_busy: Callable[[], bool] | None = None,
    ) -> None:
        self._app_state = app_state
        self._brackets = brackets
        self._on_start = on_start
        self._replay_manager = replay_manager
        self._on_complete = on_complete
        self._orchestrator_busy = orchestrator_busy
        self._lock = asyncio.Lock()
        self._is_running: bool = False
        self._task: asyncio.Task[None] | None = None
        self._pending_shock: str | None = None
        self._last_cycle_id: str | None = None
        # The failure _publish_failure already logged with its traceback, so
        # _on_task_done logs only failures raised outside _run's handler.
        self._logged_failure: BaseException | None = None
        # Strong references to the post-run pipeline task (on_complete). The
        # loop holds only weak refs; the set also tells start() that post-run
        # jobs are still pending (docs/DECISIONS.md#adr-sequential-model-lifecycle).
        self._bg_tasks: set[asyncio.Task[None]] = set()

    @property
    def is_running(self) -> bool:
        """True when a simulation is currently executing."""
        return self._is_running

    def _post_run_active(self) -> bool:
        """True from the end of a run until its post-run pipeline task finishes."""
        return any(not task.done() for task in self._bg_tasks)

    @property
    def pending_shock(self) -> str | None:
        """Current pending shock text, or None if no shock queued."""
        return self._pending_shock

    async def start(self, seed: str) -> None:
        """Start a simulation. Raises SimulationAlreadyRunningError if one is active.

        Raises ReplayActiveError if a replay session is currently active (B4).
        The replay-active check fires BEFORE the already-running check so a
        concurrent replay takes precedence over a concurrent-start error.

        Raises PostRunJobsInProgressError while the post-run pipeline or an
        orchestrator job runs (checked after the already-running check, before
        the lock is taken).

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
        if self._post_run_active() or (self._orchestrator_busy is not None and self._orchestrator_busy()):
            raise PostRunJobsInProgressError(
                "The advisory/report jobs are using the orchestrator; retry when they finish"
            )
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
        self._app_state.state_store.set_pending_shock(None)
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

        from alphaswarm.errors import Neo4jUnavailableError
        from alphaswarm.inference.config import load_inference_config
        from alphaswarm.inference.factory import build_controller, build_providers, inference_mode
        from alphaswarm.simulation import SimulationDeps, run_simulation

        # `built` may remain None if cancelled before build_providers completes.
        # The finally block guards aclose() accordingly.
        built: BuiltProviders | None = None

        try:
            try:
                # Load inference config off the event loop (sync file I/O).
                cfg = await _asyncio.to_thread(load_inference_config, self._app_state.settings)
            except (ValueError, OSError) as exc:
                # The load error text can quote the file path, so neither the
                # UI nor the log gets it; the fix is the file itself
                # (docs/DECISIONS.md#adr-local-first-inference).
                log.error("inference_config_invalid", error_type=type(exc).__name__)
                raise InferenceConfigError(INFERENCE_CONFIG_INVALID_MESSAGE) from None
            try:
                built = build_providers(
                    cfg,
                    ollama_client=self._app_state.ollama_client,
                    ollama_model_manager=self._app_state.model_manager,
                )
            except ValueError as exc:
                # The file loads (the health check reports it ok), but a cloud
                # role lacks its API key or base URL: the fix is in Settings.
                log.error(
                    "inference_config_incomplete",
                    error_type=type(exc).__name__,
                    orchestrator_provider=cfg.orchestrator.provider.value,
                    worker_provider=cfg.worker.provider.value,
                )
                raise InferenceConfigIncompleteError(INFERENCE_CONFIG_INCOMPLETE_MESSAGE) from None
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

            graph = self._app_state.graph_manager
            if graph is None:
                raise Neo4jUnavailableError("Neo4j is not connected; cannot start a simulation", op="simulation_start")
            deps = SimulationDeps(
                settings=self._app_state.settings,
                graph=graph,
                controller=controller,
                orchestrator=built.orchestrator,
                worker=built.worker,
                state=self._app_state.state_store,
                market=self._app_state.market_provider,
                news=self._app_state.news_provider,
            )
            result = await run_simulation(
                rumor=seed,
                deps=deps,
                personas=list(self._app_state.personas),
                brackets=list(self._brackets),
                consume_shock=self.consume_shock,
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

        The failure is logged with its traceback whether or not the store takes
        the RunError, and this method never raises: a broken store must cost
        neither the traceback nor the phase reset that follows
        (docs/DECISIONS.md#adr-taskgroup-dispatch).
        """
        store = self._app_state.state_store
        err = run_error_from_exception(exc, round_num=None)
        try:
            snap = store.snapshot()
            if snap.phase in _ROUND_PHASES:
                err = dataclasses.replace(err, round_num=snap.round_num)
            await store.set_last_error(err)
        except Exception:
            log.warning("last_error_publish_failed", exc_info=True)
        log.error(
            "simulation_run_failed",
            error_code=err.code,
            round_num=err.round_num,
            exc_info=exc,
        )
        self._logged_failure = exc

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
        self._app_state.state_store.set_pending_shock(None)
        logged_failure, self._logged_failure = self._logged_failure, None
        self._lock.release()
        if not task.cancelled() and task.exception() is None:
            cycle_id = self._last_cycle_id
            self._last_cycle_id = None  # reset for next run
            if cycle_id is not None and self._on_complete is not None:
                trigger: asyncio.Task[None] = asyncio.create_task(
                    self._run_on_complete(cycle_id),
                    name=f"post_run_{cycle_id}",
                )
                self._bg_tasks.add(trigger)
                trigger.add_done_callback(self._bg_tasks.discard)
            log.info("simulation_completed")
        elif task.cancelled():
            log.info("simulation_cancelled")
        else:
            exc = task.exception()
            if exc is logged_failure:
                # Details were logged by _publish_failure; keep this line text-free.
                log.info("simulation_task_failed", error_type=type(exc).__name__)
            else:
                # Raised outside _run's failure handler (a provider aclose in its
                # finally, say), so this is the only record of the traceback.
                log.error("simulation_task_failed", error_type=type(exc).__name__, exc_info=exc)

    def stop(self) -> None:
        """Stop the running simulation by cancelling the background task.

        Raises NoSimulationRunningError if no simulation is active.
        """
        if not self._is_running or self._task is None:
            raise NoSimulationRunningError("No simulation is running")
        self._task.cancel()
        log.info("simulation_stop_requested")

    def inject_shock(self, shock_text: str) -> None:
        """Queue a shock for the next gated round while the shock window is open.

        Raises NoSimulationRunningError when idle, ShockWindowClosedError once the
        last gated round has started (the text could never reach a prompt), and
        ShockAlreadyQueuedError while an earlier shock is still pending.
        """
        if not self._is_running:
            raise NoSimulationRunningError("No simulation is running")
        store = self._app_state.state_store
        if not store.shock_window_open():
            raise ShockWindowClosedError("The shock window is closed: the last round has already started")
        if self._pending_shock is not None:
            raise ShockAlreadyQueuedError("A shock is already queued")
        self._pending_shock = shock_text
        store.set_pending_shock(shock_text)
        log.info("shock_queued", shock_length=len(shock_text))

    def consume_shock(self) -> str | None:
        """Return and clear the pending shock text (called by the round runner)."""
        shock = self._pending_shock
        self._pending_shock = None
        if shock is not None:
            self._app_state.state_store.set_pending_shock(None)
        return shock

    async def _run_on_complete(self, cycle_id: str) -> None:
        """Await the post-run pipeline for *cycle_id*; its outcome is logged there."""
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
