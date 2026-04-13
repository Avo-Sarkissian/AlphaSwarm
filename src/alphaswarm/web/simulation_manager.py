"""SimulationManager: singleton guard for concurrent simulation requests."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from alphaswarm.app import AppState

log = structlog.get_logger(component="web.simulation_manager")


class SimulationAlreadyRunningError(Exception):
    """Raised when start() is called while a simulation is already active."""


class SimulationManager:
    """Thin wrapper enforcing single-simulation concurrency via asyncio.Lock.

    Created inside FastAPI lifespan. Phase 32 wires actual simulation call.
    """

    def __init__(self, app_state: AppState) -> None:
        self._app_state = app_state
        self._lock = asyncio.Lock()
        self._is_running: bool = False

    @property
    def is_running(self) -> bool:
        """True when a simulation is currently executing."""
        return self._is_running

    async def start(self, seed: str) -> None:
        """Start a simulation. Raises SimulationAlreadyRunningError if one is active.

        Uses lock.locked() as a fast non-blocking check before acquiring.
        Phase 32 will add the actual run_simulation() call inside the lock body.
        """
        if self._lock.locked():
            raise SimulationAlreadyRunningError("Simulation already running")
        async with self._lock:
            self._is_running = True
            log.info("simulation_started", seed_length=len(seed))
            try:
                # Phase 32: wire actual simulation call here
                pass
            finally:
                self._is_running = False
                log.info("simulation_stopped")

    def stop(self) -> None:
        """Stop the running simulation. Phase 32: cancel the simulation task."""
        pass
