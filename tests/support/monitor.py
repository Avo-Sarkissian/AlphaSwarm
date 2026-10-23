"""Scripted memory readings for governor tests (docs/DECISIONS.md#adr-governor)."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Sequence
from typing import Any, Final

from alphaswarm.memory_monitor import MemoryReading, PressureLevel
from alphaswarm.settings import GovernorSettings

_UNVALIDATED_TEST_KNOBS: Final = ("check_interval_seconds", "crisis_timeout_seconds")


def reading(
    percent: float,
    pressure: PressureLevel = PressureLevel.GREEN,
    *,
    settings: GovernorSettings | None = None,
) -> MemoryReading:
    """A MemoryReading whose thresholds come from ``settings`` (defaults 80/90/60)."""
    s = settings if settings is not None else GovernorSettings()
    return MemoryReading(
        psutil_percent=percent,
        pressure_level=pressure,
        timestamp=time.monotonic(),
        throttle_threshold=s.memory_throttle_percent,
        pause_threshold=s.memory_pause_percent,
        scale_up_threshold=s.scale_up_threshold_percent,
    )


class ScriptedMonitor:
    """MemoryReader that replays scripted readings, or raises scripted exceptions.

    Items are consumed in order. When they run out: with ``repeat_last=True``
    (default) the last item repeats forever; with ``repeat_last=False``
    ``read_combined`` blocks until ``push()`` adds another item, which lets a
    test step the governor exactly one reading at a time.
    """

    def __init__(self, items: Sequence[MemoryReading | BaseException], *, repeat_last: bool = True) -> None:
        self._items: deque[MemoryReading | BaseException] = deque(items)
        self._repeat_last = repeat_last
        self._last: MemoryReading | BaseException | None = None
        self._pushed = asyncio.Event()
        self.reads = 0

    async def read_combined(self) -> MemoryReading:
        while not self._items and not (self._repeat_last and self._last is not None):
            self._pushed.clear()
            await self._pushed.wait()
        item = self._items.popleft() if self._items else self._last
        assert item is not None
        self._last = item
        self.reads += 1
        if isinstance(item, BaseException):
            raise item
        return item

    def push(self, item: MemoryReading | BaseException) -> None:
        self._items.append(item)
        self._pushed.set()


def fast_governor_settings(**overrides: Any) -> GovernorSettings:
    """GovernorSettings for tests: validated fields plus two unvalidated test knobs.

    ``check_interval_seconds`` defaults to 0.0 so the monitor loop never sleeps on
    wall time, and ``crisis_timeout_seconds`` may go below its 30 s floor (-1.0
    means "already timed out"). Both bypass validation through
    ``model_copy(update=...)``; every other key goes through the validators.
    """
    unvalidated: dict[str, Any] = {"check_interval_seconds": 0.0}
    for key in _UNVALIDATED_TEST_KNOBS:
        if key in overrides:
            unvalidated[key] = overrides.pop(key)
    return GovernorSettings(**overrides).model_copy(update=unvalidated)
