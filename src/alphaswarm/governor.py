"""ResourceGovernor stub for Phase 1. Full implementation in Phase 3."""

from __future__ import annotations

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
    """Stub ResourceGovernor for Phase 1. No-op implementation.

    Implements async context manager protocol so downstream code can use:
        async with governor:
            await do_inference()

    Full psutil-based monitoring added in Phase 3.
    """

    def __init__(self, baseline_parallel: int = 8) -> None:
        self._baseline = baseline_parallel
        self._current_limit = baseline_parallel
        self._active_count = 0

    async def acquire(self) -> None:
        """Acquire a concurrency slot. No-op in Phase 1."""

    def release(self) -> None:
        """Release a concurrency slot. No-op in Phase 1."""

    async def start_monitoring(self) -> None:
        """Start psutil memory monitoring loop. No-op in Phase 1."""

    async def stop_monitoring(self) -> None:
        """Stop monitoring loop. No-op in Phase 1."""

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
