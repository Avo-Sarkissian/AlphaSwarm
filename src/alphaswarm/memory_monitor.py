"""Dual-signal memory monitoring for macOS (psutil + sysctl kernel pressure).

Phase 3: Reads both psutil virtual_memory percent and macOS
kern.memorystatus_vm_pressure_level via sysctl to provide a combined
MemoryReading with threshold-aware properties.

Key design: sysctl kernel pressure is the MASTER signal. If it reports
YELLOW or RED, the system is in CRISIS regardless of psutil readings.
psutil-based zones (throttle, pause) only apply when kernel says GREEN.
"""

from __future__ import annotations

import asyncio
import enum
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import psutil
import structlog

if TYPE_CHECKING:
    from alphaswarm.config import GovernorSettings

log = structlog.get_logger(component="memory_monitor")


class PressureLevel(enum.Enum):
    """macOS kernel memory pressure level from sysctl."""

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


# Maps sysctl kern.memorystatus_vm_pressure_level integer to PressureLevel.
# Unknown values fall back to GREEN (fail-open per D-12).
_SYSCTL_PRESSURE_MAP: dict[int, PressureLevel] = {
    1: PressureLevel.GREEN,
    2: PressureLevel.YELLOW,
    4: PressureLevel.RED,
}


@dataclass(frozen=True)
class MemoryReading:
    """Immutable snapshot of memory state with threshold-aware properties.

    CRITICAL: Dual-signal precedence (addresses review concern #3).
    sysctl kernel pressure is MASTER. If pressure_level is YELLOW or RED,
    the system is in CRISIS regardless of psutil. The psutil-based zones
    (throttle, pause) only apply when pressure_level is GREEN.
    """

    psutil_percent: float
    pressure_level: PressureLevel
    timestamp: float  # monotonic
    throttle_threshold: float
    pause_threshold: float
    scale_up_threshold: float

    @property
    def is_crisis(self) -> bool:
        """True when kernel reports YELLOW or RED -- master signal, checked FIRST."""
        return self.pressure_level in (PressureLevel.YELLOW, PressureLevel.RED)

    @property
    def is_throttle_zone(self) -> bool:
        """True when psutil >= throttle threshold AND kernel says GREEN.

        sysctl is master: if crisis, this returns False even if psutil is high.
        """
        return not self.is_crisis and self.psutil_percent >= self.throttle_threshold

    @property
    def is_pause_zone(self) -> bool:
        """True when psutil >= pause threshold AND kernel says GREEN.

        sysctl is master: if crisis, this returns False even if psutil is high.
        """
        return not self.is_crisis and self.psutil_percent >= self.pause_threshold

    @property
    def is_scale_up_eligible(self) -> bool:
        """True when psutil < scale_up threshold AND kernel says GREEN."""
        return (
            not self.is_crisis
            and self.psutil_percent < self.scale_up_threshold
            and self.pressure_level == PressureLevel.GREEN
        )


class MemoryMonitor:
    """Reads dual memory signals: psutil percent + macOS sysctl pressure level.

    Constructor takes GovernorSettings for threshold values used in MemoryReading.
    All reads are async to avoid blocking the event loop.
    """

    def __init__(self, settings: GovernorSettings) -> None:
        self._settings = settings

    async def read_psutil_percent(self) -> float:
        """Read psutil virtual_memory percent (0-100)."""
        return float(psutil.virtual_memory().percent)

    async def read_macos_pressure(self) -> PressureLevel:
        """Read macOS kernel memory pressure via sysctl.

        Uses asyncio.create_subprocess_exec to avoid blocking the event loop.
        Falls back to GREEN on any error (fail-open per D-12).
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "sysctl",
                "-n",
                "kern.memorystatus_vm_pressure_level",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            value = int(stdout.decode().strip())
            level = _SYSCTL_PRESSURE_MAP.get(value, PressureLevel.GREEN)
            return level
        except Exception:
            log.debug("sysctl pressure read failed, defaulting to GREEN")
            return PressureLevel.GREEN

    async def read_combined(self) -> MemoryReading:
        """Read both psutil and sysctl signals, return combined MemoryReading.

        Thresholds are sourced from GovernorSettings.
        """
        psutil_pct = await self.read_psutil_percent()
        pressure = await self.read_macos_pressure()
        return MemoryReading(
            psutil_percent=psutil_pct,
            pressure_level=pressure,
            timestamp=time.monotonic(),
            throttle_threshold=self._settings.memory_throttle_percent,
            pause_threshold=self._settings.memory_pause_percent,
            scale_up_threshold=self._settings.scale_up_threshold_percent,
        )
