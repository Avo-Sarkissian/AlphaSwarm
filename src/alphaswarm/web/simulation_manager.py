"""SimulationManager: singleton guard for concurrent simulation requests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from alphaswarm.app import AppState
    from alphaswarm.types import BracketConfig
    from alphaswarm.web.replay_manager import ReplayManager

log = structlog.get_logger(component="web.simulation_manager")


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
    ) -> None:
        self._app_state = app_state
        self._brackets = brackets
        self._on_start = on_start
        self._replay_manager = replay_manager
        self._lock = asyncio.Lock()
        self._is_running: bool = False
        self._task: asyncio.Task[None] | None = None
        self._pending_shock: str | None = None

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

        B10: COMPLETE is set by simulation.py:1109 as the single source of
        truth — no duplicate set_phase(COMPLETE) here.
        """
        from alphaswarm.simulation import run_simulation
        from alphaswarm.types import SimulationPhase

        try:
            await run_simulation(
                rumor=seed,
                settings=self._app_state.settings,
                ollama_client=self._app_state.ollama_client,
                model_manager=self._app_state.model_manager,
                graph_manager=self._app_state.graph_manager,
                governor=self._app_state.governor,
                personas=list(self._app_state.personas),
                brackets=list(self._brackets),
                state_store=self._app_state.state_store,
                consume_shock=self.consume_shock,
            )
            # B10: do NOT set COMPLETE here — simulation.py:1109 is the single
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
        except Exception:
            try:
                await self._app_state.state_store.set_phase(SimulationPhase.IDLE)
            except Exception:
                log.error("failed_to_reset_phase_to_idle_on_error")
            raise

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
        if task.cancelled():
            log.info("simulation_cancelled")
        elif task.exception() is not None:
            exc = task.exception()
            log.error("simulation_failed", error=str(exc))
        else:
            log.info("simulation_completed")

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
