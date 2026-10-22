"""ConcurrencyController test doubles."""

from __future__ import annotations


class ImmediateController:
    """A ConcurrencyController that never waits and never monitors anything.

    Used by engine scenarios so run_simulation exercises the real dispatch path
    without a memory governor. Counters let tests assert slot balance
    (acquired == released), failure accounting and monitoring-session counts.
    """

    def __init__(self) -> None:
        self.acquired = 0
        self.released = 0
        self.failures = 0
        self.wave_reports: list[tuple[int, int]] = []
        self.monitoring_starts = 0
        self.monitoring_stops = 0
        self.max_in_use = 0
        self._in_use = 0

    @property
    def in_use(self) -> int:
        """Slots currently held (acquired minus released)."""
        return self._in_use

    async def acquire(self) -> None:
        self.acquired += 1
        self._in_use += 1
        self.max_in_use = max(self.max_in_use, self._in_use)

    def release(self, *, success: bool = True, result_tokens: int | None = None) -> None:
        self.released += 1
        self._in_use -= 1
        if not success:
            self.failures += 1

    def report_wave_failures(self, success_count: int, failure_count: int) -> None:
        self.wave_reports.append((success_count, failure_count))

    async def start_monitoring(self) -> None:
        self.monitoring_starts += 1

    async def stop_monitoring(self) -> None:
        self.monitoring_stops += 1

    async def __aenter__(self) -> ImmediateController:
        await self.acquire()
        return self

    async def __aexit__(self, *args: object) -> None:
        # args = (exc_type, exc, tb); a raised exception counts as a failed call.
        self.release(success=not args or args[0] is None)
