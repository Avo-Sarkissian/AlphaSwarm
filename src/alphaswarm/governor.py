"""ResourceGovernor with semaphore-based concurrency control.

Phase 1: No-op stub.
Phase 2: Real BoundedSemaphore for backpressure.
Phase 3: Dynamic slot adjustment based on memory pressure.
"""

from __future__ import annotations

import asyncio
from typing import Protocol


class ResourceGovernorProtocol(Protocol):
    """Interface contract for ResourceGovernor. Full impl in Phase 3."""

    async def acquire(self) -> None: ...
    def release(self) -> None: ...
    async def start_monitoring(self) -> None: ...
    async def stop_monitoring(self) -> None: ...

    @property
    def current_limit(self) -> int: ...

    @property
    def active_count(self) -> int: ...


class ResourceGovernor:
    """Semaphore-backed concurrency governor.

    Phase 2: Fixed BoundedSemaphore(baseline_parallel).
    Phase 3: Dynamic adjustment via psutil memory sensing.
    """

    def __init__(self, baseline_parallel: int = 8) -> None:
        self._baseline = baseline_parallel
        self._current_limit = baseline_parallel
        self._active_count = 0
        self._semaphore = asyncio.BoundedSemaphore(baseline_parallel)

    async def acquire(self) -> None:
        """Acquire a concurrency slot. Blocks if all slots are held."""
        await self._semaphore.acquire()
        self._active_count += 1

    def release(self) -> None:
        """Release a concurrency slot."""
        self._semaphore.release()
        self._active_count = max(0, self._active_count - 1)

    async def start_monitoring(self) -> None:
        """Start psutil memory monitoring loop. No-op until Phase 3."""

    async def stop_monitoring(self) -> None:
        """Stop monitoring loop. No-op until Phase 3."""

    @property
    def current_limit(self) -> int:
        return self._current_limit

    @property
    def active_count(self) -> int:
        return self._active_count

    async def __aenter__(self) -> ResourceGovernor:
        await self.acquire()
        return self

    async def __aexit__(self, *args: object) -> None:
        self.release()
