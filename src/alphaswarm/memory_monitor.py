"""Memory signals for the governor: macOS kernel counters, psutil elsewhere.

On macOS both numbers come straight from the kernel through ``sysctlbyname``
(ctypes, about 2 microseconds, no subprocess):

- used % = 100 - ``kern.memorystatus_level`` (the kernel's "memory available" %),
- pressure = ``kern.memorystatus_vm_pressure_level`` (1 green, 2 yellow, 4 red).

psutil's ``virtual_memory().percent`` counts cached and compressed pages as used
(61.7% at idle while the kernel reported 77% available), so it is only the
fallback: on Linux/CI, or for one reading when the kernel call fails
(docs/DECISIONS.md#p3-d-12). Kernel pressure stays the master signal: YELLOW or
RED is a crisis whatever the percentage says (docs/DECISIONS.md#p3-d-13).
"""

from __future__ import annotations

import contextlib
import ctypes
import ctypes.util
import enum
import functools
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, Protocol, runtime_checkable

import psutil
import structlog

if TYPE_CHECKING:
    from alphaswarm.settings import GovernorSettings

log = structlog.get_logger(component="memory_monitor")

MEMORY_LEVEL_SYSCTL: Final = "kern.memorystatus_level"
PRESSURE_LEVEL_SYSCTL: Final = "kern.memorystatus_vm_pressure_level"

SignalSource = Literal["kernel", "psutil"]


class PressureLevel(enum.StrEnum):
    """macOS kernel memory pressure level."""

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


# kern.memorystatus_vm_pressure_level values. Unknown values map to GREEN
# (fail-open, docs/DECISIONS.md#p3-d-12); a failed READ is fail-stale instead.
_SYSCTL_PRESSURE_MAP: Final[dict[int, PressureLevel]] = {
    1: PressureLevel.GREEN,
    2: PressureLevel.YELLOW,
    4: PressureLevel.RED,
}


@functools.cache
def _libc() -> ctypes.CDLL:
    return ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)


def _sysctl_int(name: str) -> int:
    """Read a 32-bit integer sysctl through ``sysctlbyname`` (macOS only).

    Raises OSError when the call fails (unknown name, sandbox, size mismatch).
    """
    value = ctypes.c_int(0)
    size = ctypes.c_size_t(ctypes.sizeof(value))
    rc = _libc().sysctlbyname(name.encode("ascii"), ctypes.byref(value), ctypes.byref(size), None, ctypes.c_size_t(0))
    if rc != 0:
        raise OSError(ctypes.get_errno(), f"sysctlbyname({name}) failed")
    return int(value.value)


def _psutil_used_percent() -> float:
    return float(psutil.virtual_memory().percent)


def memory_used_percent() -> float:
    """Used-memory % from the same source the governor uses (sync, microseconds).

    For the UI overlay and /api/health, so they show what the governor sees.
    """
    if sys.platform == "darwin":
        with contextlib.suppress(OSError):
            level = _sysctl_int(MEMORY_LEVEL_SYSCTL)
            if 0 <= level <= 100:
                return float(100 - level)
    return _psutil_used_percent()


@dataclass(frozen=True)
class MemoryReading:
    """One combined reading with threshold-aware properties.

    Kernel pressure is the master signal: YELLOW or RED is a crisis, and the
    percentage zones (throttle, pause) only apply while the kernel says GREEN.
    """

    used_percent: float
    pressure_level: PressureLevel
    timestamp: float  # monotonic
    throttle_threshold: float
    pause_threshold: float
    scale_up_threshold: float

    @property
    def is_crisis(self) -> bool:
        return self.pressure_level in (PressureLevel.YELLOW, PressureLevel.RED)

    @property
    def is_throttle_zone(self) -> bool:
        return not self.is_crisis and self.used_percent >= self.throttle_threshold

    @property
    def is_pause_zone(self) -> bool:
        return not self.is_crisis and self.used_percent >= self.pause_threshold

    @property
    def is_scale_up_eligible(self) -> bool:
        return (
            not self.is_crisis
            and self.used_percent < self.scale_up_threshold
            and self.pressure_level == PressureLevel.GREEN
        )


@runtime_checkable
class MemoryReader(Protocol):
    """Anything that produces a combined MemoryReading (contracts C-TEST-15)."""

    async def read_combined(self) -> MemoryReading: ...


class MemoryMonitor:
    """Reads used % and kernel pressure; never spawns a subprocess.

    ``kernel=None`` picks the kernel signal on macOS and psutil elsewhere.
    ``sysctl`` and ``psutil_percent`` are seams for tests.
    """

    def __init__(
        self,
        settings: GovernorSettings,
        *,
        kernel: bool | None = None,
        sysctl: Callable[[str], int] = _sysctl_int,
        psutil_percent: Callable[[], float] = _psutil_used_percent,
    ) -> None:
        self._settings = settings
        self._kernel = (sys.platform == "darwin") if kernel is None else kernel
        self._sysctl = sysctl
        self._psutil_percent = psutil_percent
        # Last successfully-read pressure level, for fail-stale reads (F-17).
        self._last_pressure: PressureLevel = PressureLevel.GREEN
        self._warned: set[str] = set()

    @property
    def signal_source(self) -> SignalSource:
        return "kernel" if self._kernel else "psutil"

    def _warn_once(self, event: str, **context: object) -> None:
        """Log a degraded read once per monitor, not every 2 s (T11.3 step 3)."""
        if event not in self._warned:
            self._warned.add(event)
            log.warning(event, **context)

    async def read_used_percent(self) -> float:
        if self._kernel:
            try:
                level = self._sysctl(MEMORY_LEVEL_SYSCTL)
            except OSError as exc:
                self._warn_once(
                    "memory_level_read_failed",
                    sysctl=MEMORY_LEVEL_SYSCTL,
                    errno=exc.errno,
                    fallback="psutil",
                )
            else:
                if 0 <= level <= 100:
                    return float(100 - level)
                self._warn_once("memory_level_rejected", value=level, fallback="psutil")
        return self._psutil_percent()

    async def read_macos_pressure(self) -> PressureLevel:
        if not self._kernel:
            return PressureLevel.GREEN
        try:
            raw = self._sysctl(PRESSURE_LEVEL_SYSCTL)
        except OSError as exc:
            # Fail-stale: a failed read must not clear an active crisis (F-17).
            self._warn_once(
                "pressure_level_read_failed",
                sysctl=PRESSURE_LEVEL_SYSCTL,
                errno=exc.errno,
                last_pressure=self._last_pressure.value,
            )
            return self._last_pressure
        level = _SYSCTL_PRESSURE_MAP.get(raw, PressureLevel.GREEN)
        self._last_pressure = level
        return level

    async def read_combined(self) -> MemoryReading:
        used = await self.read_used_percent()
        pressure = await self.read_macos_pressure()
        return MemoryReading(
            used_percent=used,
            pressure_level=pressure,
            timestamp=time.monotonic(),
            throttle_threshold=self._settings.memory_throttle_percent,
            pause_threshold=self._settings.memory_pause_percent,
            scale_up_threshold=self._settings.scale_up_threshold_percent,
        )
