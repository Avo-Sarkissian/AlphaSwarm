"""SimulationManager: singleton guard for concurrent simulation requests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from alphaswarm.app import AppState
    from alphaswarm.types import BracketConfig

log = structlog.get_logger(component="web.simulation_manager")


class SimulationAlreadyRunningError(Exception):
    """Raised when start() is called while a simulation is already active."""


class NoSimulationRunningError(Exception):
    """Raised when stop/shock called with no active simulation."""


class ShockAlreadyQueuedError(Exception):
    """Raised when inject_shock called while a shock is already queued."""


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
    ) -> None:
        self._app_state = app_state
        self._brackets = brackets
        self._on_start = on_start
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

        Uses lock.locked() as a fast non-blocking check before acquiring.
        The lock is acquired here but ONLY released in _on_task_done.
        """
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
        """Execute the simulation pipeline in a background task."""
        from alphaswarm.simulation import run_simulation
        from alphaswarm.types import SimulationPhase

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
        )
        # Caller (TUI) is responsible for setting COMPLETE, replicate that here
        await self._app_state.state_store.set_phase(SimulationPhase.COMPLETE)

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        """Synchronous done-callback: releases lock unconditionally.

        CRITICAL STATE RESET:
        - When the task is cancelled or raises an exception, StateStore.phase
          may be stuck at round_2 or round_3. The done-callback resets
          phase to IDLE in these cases so the UI returns to idle state.
        - For successful completion, _run() already sets COMPLETE, so no
          additional phase reset is needed.
        """
        self._is_running = False
        self._task = None
        self._pending_shock = None
        self._lock.release()
        if task.cancelled():
            log.info("simulation_cancelled")
            # Reset phase to IDLE so UI does not stay stuck on round_2/round_3
            asyncio.create_task(self._reset_phase_to_idle())
        elif task.exception() is not None:
            exc = task.exception()
            log.error("simulation_failed", error=str(exc))
            # Reset phase to IDLE on failure too
            asyncio.create_task(self._reset_phase_to_idle())
        else:
            log.info("simulation_completed")

    async def _reset_phase_to_idle(self) -> None:
        """Reset StateStore phase to IDLE after cancellation or failure."""
        from alphaswarm.types import SimulationPhase

        try:
            await self._app_state.state_store.set_phase(SimulationPhase.IDLE)
        except Exception:
            log.error("failed_to_reset_phase_to_idle")

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
