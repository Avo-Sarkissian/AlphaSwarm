"""Tests for MemoryMonitor, MemoryReading, PressureLevel, GovernorSettings extensions, and GovernorCrisisError."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from alphaswarm.config import GovernorSettings
from alphaswarm.errors import GovernorCrisisError
from alphaswarm.memory_monitor import MemoryMonitor, MemoryReading, PressureLevel


# ---------------------------------------------------------------------------
# GovernorSettings new fields
# ---------------------------------------------------------------------------


class TestGovernorSettingsExtensions:
    """Test the 7 new fields added to GovernorSettings for Phase 3."""

    def test_default_scale_up_threshold_percent(self) -> None:
        s = GovernorSettings()
        assert s.scale_up_threshold_percent == 60.0

    def test_default_scale_up_consecutive_checks(self) -> None:
        s = GovernorSettings()
        assert s.scale_up_consecutive_checks == 3

    def test_default_crisis_timeout_seconds(self) -> None:
        s = GovernorSettings()
        assert s.crisis_timeout_seconds == 300.0

    def test_default_slot_adjustment_step(self) -> None:
        s = GovernorSettings()
        assert s.slot_adjustment_step == 2

    def test_default_batch_failure_threshold_percent(self) -> None:
        s = GovernorSettings()
        assert s.batch_failure_threshold_percent == 20.0

    def test_default_jitter_min_seconds(self) -> None:
        s = GovernorSettings()
        assert s.jitter_min_seconds == 0.5

    def test_default_jitter_max_seconds(self) -> None:
        s = GovernorSettings()
        assert s.jitter_max_seconds == 1.5

    def test_custom_values_accepted(self) -> None:
        s = GovernorSettings(
            scale_up_threshold_percent=50.0,
            scale_up_consecutive_checks=5,
            crisis_timeout_seconds=120.0,
            slot_adjustment_step=3,
            batch_failure_threshold_percent=30.0,
            jitter_min_seconds=1.0,
            jitter_max_seconds=3.0,
        )
        assert s.scale_up_threshold_percent == 50.0
        assert s.scale_up_consecutive_checks == 5
        assert s.crisis_timeout_seconds == 120.0
        assert s.slot_adjustment_step == 3
        assert s.batch_failure_threshold_percent == 30.0
        assert s.jitter_min_seconds == 1.0
        assert s.jitter_max_seconds == 3.0

    def test_out_of_range_scale_up_threshold_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GovernorSettings(scale_up_threshold_percent=90.0)  # max is 80

    def test_out_of_range_crisis_timeout_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GovernorSettings(crisis_timeout_seconds=700.0)  # max is 600

    def test_out_of_range_slot_adjustment_step_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GovernorSettings(slot_adjustment_step=5)  # max is 4


# ---------------------------------------------------------------------------
# GovernorCrisisError
# ---------------------------------------------------------------------------


class TestGovernorCrisisError:
    """Test GovernorCrisisError exception."""

    def test_stores_duration_seconds(self) -> None:
        err = GovernorCrisisError("crisis timeout", duration_seconds=300.5)
        assert err.duration_seconds == 300.5

    def test_stores_message(self) -> None:
        err = GovernorCrisisError("crisis timeout", duration_seconds=120.0)
        assert str(err) == "crisis timeout"

    def test_is_exception(self) -> None:
        err = GovernorCrisisError("test", duration_seconds=0.0)
        assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# PressureLevel enum
# ---------------------------------------------------------------------------


class TestPressureLevel:
    """Test PressureLevel enum values."""

    def test_green_value(self) -> None:
        assert PressureLevel.GREEN.value == "green"

    def test_yellow_value(self) -> None:
        assert PressureLevel.YELLOW.value == "yellow"

    def test_red_value(self) -> None:
        assert PressureLevel.RED.value == "red"

    def test_has_three_members(self) -> None:
        assert len(PressureLevel) == 3


# ---------------------------------------------------------------------------
# MemoryReading properties
# ---------------------------------------------------------------------------


class TestMemoryReading:
    """Test MemoryReading threshold-aware properties with dual-signal precedence."""

    def _reading(
        self,
        psutil_percent: float = 50.0,
        pressure_level: PressureLevel = PressureLevel.GREEN,
    ) -> MemoryReading:
        """Helper to create a MemoryReading with default thresholds."""
        return MemoryReading(
            psutil_percent=psutil_percent,
            pressure_level=pressure_level,
            timestamp=0.0,
            throttle_threshold=80.0,
            pause_threshold=90.0,
            scale_up_threshold=60.0,
        )

    def test_is_throttle_zone_true_when_psutil_ge_80_and_green(self) -> None:
        r = self._reading(psutil_percent=80.0, pressure_level=PressureLevel.GREEN)
        assert r.is_throttle_zone is True

    def test_is_throttle_zone_false_when_psutil_below_80(self) -> None:
        r = self._reading(psutil_percent=79.9)
        assert r.is_throttle_zone is False

    def test_is_pause_zone_true_when_psutil_ge_90_and_green(self) -> None:
        r = self._reading(psutil_percent=90.0, pressure_level=PressureLevel.GREEN)
        assert r.is_pause_zone is True

    def test_is_pause_zone_false_when_psutil_below_90(self) -> None:
        r = self._reading(psutil_percent=89.9)
        assert r.is_pause_zone is False

    def test_is_crisis_true_when_yellow(self) -> None:
        r = self._reading(psutil_percent=50.0, pressure_level=PressureLevel.YELLOW)
        assert r.is_crisis is True

    def test_is_crisis_true_when_red(self) -> None:
        r = self._reading(psutil_percent=50.0, pressure_level=PressureLevel.RED)
        assert r.is_crisis is True

    def test_is_crisis_false_when_green(self) -> None:
        r = self._reading(psutil_percent=95.0, pressure_level=PressureLevel.GREEN)
        assert r.is_crisis is False

    def test_is_scale_up_eligible_true_when_low_and_green(self) -> None:
        r = self._reading(psutil_percent=55.0, pressure_level=PressureLevel.GREEN)
        assert r.is_scale_up_eligible is True

    def test_is_scale_up_eligible_false_when_psutil_high(self) -> None:
        r = self._reading(psutil_percent=65.0, pressure_level=PressureLevel.GREEN)
        assert r.is_scale_up_eligible is False

    def test_is_scale_up_eligible_false_when_yellow(self) -> None:
        r = self._reading(psutil_percent=30.0, pressure_level=PressureLevel.YELLOW)
        assert r.is_scale_up_eligible is False

    # --- Dual-signal precedence tests ---

    def test_crisis_overrides_throttle_zone(self) -> None:
        """sysctl=YELLOW, psutil=75% => is_crisis=True, is_throttle_zone=False."""
        r = self._reading(psutil_percent=75.0, pressure_level=PressureLevel.YELLOW)
        assert r.is_crisis is True
        assert r.is_throttle_zone is False

    def test_crisis_overrides_pause_zone(self) -> None:
        """sysctl=RED, psutil=85% => is_crisis=True, is_pause_zone=False."""
        r = self._reading(psutil_percent=85.0, pressure_level=PressureLevel.RED)
        assert r.is_crisis is True
        assert r.is_pause_zone is False

    def test_crisis_yellow_high_psutil_overrides_throttle(self) -> None:
        """sysctl=YELLOW, psutil=85% => is_crisis=True, is_throttle_zone=False."""
        r = self._reading(psutil_percent=85.0, pressure_level=PressureLevel.YELLOW)
        assert r.is_crisis is True
        assert r.is_throttle_zone is False

    def test_green_high_psutil_is_throttle_not_crisis(self) -> None:
        """sysctl=GREEN, psutil=85% => is_crisis=False, is_throttle_zone=True."""
        r = self._reading(psutil_percent=85.0, pressure_level=PressureLevel.GREEN)
        assert r.is_crisis is False
        assert r.is_throttle_zone is True


# ---------------------------------------------------------------------------
# MemoryMonitor
# ---------------------------------------------------------------------------


class TestMemoryMonitor:
    """Test MemoryMonitor methods with mocked psutil and sysctl."""

    @pytest.fixture()
    def settings(self) -> GovernorSettings:
        return GovernorSettings()

    async def test_read_psutil_percent_returns_float(self, settings: GovernorSettings) -> None:
        monitor = MemoryMonitor(settings)
        mock_vmem = MagicMock()
        mock_vmem.percent = 72.5
        with patch("alphaswarm.memory_monitor.psutil") as mock_psutil:
            mock_psutil.virtual_memory.return_value = mock_vmem
            result = await monitor.read_psutil_percent()
        assert result == 72.5
        assert isinstance(result, float)

    async def test_read_macos_pressure_green_on_sysctl_1(
        self, settings: GovernorSettings
    ) -> None:
        monitor = MemoryMonitor(settings)
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"1\n", b"")
        mock_proc.returncode = 0
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await monitor.read_macos_pressure()
        assert result == PressureLevel.GREEN

    async def test_read_macos_pressure_yellow_on_sysctl_2(
        self, settings: GovernorSettings
    ) -> None:
        monitor = MemoryMonitor(settings)
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"2\n", b"")
        mock_proc.returncode = 0
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await monitor.read_macos_pressure()
        assert result == PressureLevel.YELLOW

    async def test_read_macos_pressure_red_on_sysctl_4(
        self, settings: GovernorSettings
    ) -> None:
        monitor = MemoryMonitor(settings)
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"4\n", b"")
        mock_proc.returncode = 0
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await monitor.read_macos_pressure()
        assert result == PressureLevel.RED

    async def test_read_macos_pressure_green_on_subprocess_failure(
        self, settings: GovernorSettings
    ) -> None:
        """Fail-open: subprocess error returns GREEN."""
        monitor = MemoryMonitor(settings)
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=OSError("sysctl not found"),
        ):
            result = await monitor.read_macos_pressure()
        assert result == PressureLevel.GREEN

    async def test_read_macos_pressure_green_on_unknown_value(
        self, settings: GovernorSettings
    ) -> None:
        """Unknown sysctl value (e.g. 99) returns GREEN (fail-open)."""
        monitor = MemoryMonitor(settings)
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"99\n", b"")
        mock_proc.returncode = 0
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await monitor.read_macos_pressure()
        assert result == PressureLevel.GREEN

    async def test_read_combined_returns_memory_reading(
        self, settings: GovernorSettings
    ) -> None:
        monitor = MemoryMonitor(settings)
        mock_vmem = MagicMock()
        mock_vmem.percent = 65.0
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"1\n", b"")
        mock_proc.returncode = 0
        with (
            patch("alphaswarm.memory_monitor.psutil") as mock_psutil,
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        ):
            mock_psutil.virtual_memory.return_value = mock_vmem
            result = await monitor.read_combined()
        assert isinstance(result, MemoryReading)
        assert result.psutil_percent == 65.0
        assert result.pressure_level == PressureLevel.GREEN
        assert result.throttle_threshold == 80.0
        assert result.pause_threshold == 90.0
        assert result.scale_up_threshold == 60.0
