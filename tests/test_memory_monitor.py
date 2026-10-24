"""Tests for MemoryMonitor, MemoryReading, PressureLevel, GovernorSettings extensions, and GovernorCrisisError."""

from __future__ import annotations

import asyncio
import sys

import pytest
from pydantic import ValidationError

from alphaswarm.errors import GovernorCrisisError
from alphaswarm.memory_monitor import MemoryMonitor, MemoryReading, PressureLevel
from alphaswarm.settings import GovernorSettings

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

    def test_zero_jitter_accepted(self) -> None:
        """Jitter 0..0 is valid: deterministic harnesses disable jitter entirely."""
        s = GovernorSettings(jitter_min_seconds=0.0, jitter_max_seconds=0.0)
        assert (s.jitter_min_seconds, s.jitter_max_seconds) == (0.0, 0.0)

    def test_negative_jitter_max_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GovernorSettings(jitter_min_seconds=0.0, jitter_max_seconds=-0.1)

    def test_zero_jitter_max_with_default_min_rejected(self) -> None:
        """The field bound now allows max 0.0, so only the min <= max validator refuses it
        next to the default 0.5 s min (random.uniform would accept the reversed bounds)."""
        with pytest.raises(ValidationError, match="jitter_min_seconds must be <= jitter_max"):
            GovernorSettings(jitter_max_seconds=0.0)

    def test_default_jitter_unchanged(self) -> None:
        s = GovernorSettings()
        assert (s.jitter_min_seconds, s.jitter_max_seconds) == (0.5, 1.5)

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

    def test_baseline_above_max_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="baseline_parallel must be <= max_parallel"):
            GovernorSettings(baseline_parallel=12, max_parallel=8)

    def test_baseline_equal_to_max_is_accepted(self) -> None:
        s = GovernorSettings(baseline_parallel=4, max_parallel=4)
        assert (s.baseline_parallel, s.max_parallel) == (4, 4)


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
        used_percent: float = 50.0,
        pressure_level: PressureLevel = PressureLevel.GREEN,
    ) -> MemoryReading:
        """Helper to create a MemoryReading with default thresholds."""
        return MemoryReading(
            used_percent=used_percent,
            pressure_level=pressure_level,
            timestamp=0.0,
            throttle_threshold=80.0,
            pause_threshold=90.0,
            scale_up_threshold=60.0,
        )

    def test_is_throttle_zone_true_when_psutil_ge_80_and_green(self) -> None:
        r = self._reading(used_percent=80.0, pressure_level=PressureLevel.GREEN)
        assert r.is_throttle_zone is True

    def test_is_throttle_zone_false_when_psutil_below_80(self) -> None:
        r = self._reading(used_percent=79.9)
        assert r.is_throttle_zone is False

    def test_is_pause_zone_true_when_psutil_ge_90_and_green(self) -> None:
        r = self._reading(used_percent=90.0, pressure_level=PressureLevel.GREEN)
        assert r.is_pause_zone is True

    def test_is_pause_zone_false_when_psutil_below_90(self) -> None:
        r = self._reading(used_percent=89.9)
        assert r.is_pause_zone is False

    def test_is_crisis_true_when_yellow(self) -> None:
        r = self._reading(used_percent=50.0, pressure_level=PressureLevel.YELLOW)
        assert r.is_crisis is True

    def test_is_crisis_true_when_red(self) -> None:
        r = self._reading(used_percent=50.0, pressure_level=PressureLevel.RED)
        assert r.is_crisis is True

    def test_is_crisis_false_when_green(self) -> None:
        r = self._reading(used_percent=95.0, pressure_level=PressureLevel.GREEN)
        assert r.is_crisis is False

    def test_is_scale_up_eligible_true_when_low_and_green(self) -> None:
        r = self._reading(used_percent=55.0, pressure_level=PressureLevel.GREEN)
        assert r.is_scale_up_eligible is True

    def test_is_scale_up_eligible_false_when_psutil_high(self) -> None:
        r = self._reading(used_percent=65.0, pressure_level=PressureLevel.GREEN)
        assert r.is_scale_up_eligible is False

    def test_is_scale_up_eligible_false_when_yellow(self) -> None:
        r = self._reading(used_percent=30.0, pressure_level=PressureLevel.YELLOW)
        assert r.is_scale_up_eligible is False

    # --- Dual-signal precedence tests ---

    def test_crisis_overrides_throttle_zone(self) -> None:
        """sysctl=YELLOW, psutil=75% => is_crisis=True, is_throttle_zone=False."""
        r = self._reading(used_percent=75.0, pressure_level=PressureLevel.YELLOW)
        assert r.is_crisis is True
        assert r.is_throttle_zone is False

    def test_crisis_overrides_pause_zone(self) -> None:
        """sysctl=RED, psutil=85% => is_crisis=True, is_pause_zone=False."""
        r = self._reading(used_percent=85.0, pressure_level=PressureLevel.RED)
        assert r.is_crisis is True
        assert r.is_pause_zone is False

    def test_crisis_yellow_high_psutil_overrides_throttle(self) -> None:
        """sysctl=YELLOW, psutil=85% => is_crisis=True, is_throttle_zone=False."""
        r = self._reading(used_percent=85.0, pressure_level=PressureLevel.YELLOW)
        assert r.is_crisis is True
        assert r.is_throttle_zone is False

    def test_green_high_psutil_is_throttle_not_crisis(self) -> None:
        """sysctl=GREEN, psutil=85% => is_crisis=False, is_throttle_zone=True."""
        r = self._reading(used_percent=85.0, pressure_level=PressureLevel.GREEN)
        assert r.is_crisis is False
        assert r.is_throttle_zone is True


def test_memory_reading_names_the_figure_used_percent() -> None:
    """The figure is the kernel's on macOS (docs/DECISIONS.md#p3-d-12), so the name is neutral."""
    from dataclasses import fields

    assert [f.name for f in fields(MemoryReading)][0] == "used_percent"


# ---------------------------------------------------------------------------
# Kernel signal via ctypes, psutil fallback (docs/DECISIONS.md#p3-d-12)
# ---------------------------------------------------------------------------


class _FakeSysctl:
    """Scripted sysctlbyname: values or OSError per name, consumed in order."""

    def __init__(self, script: dict[str, list[int | OSError]]) -> None:
        self._script = {name: list(items) for name, items in script.items()}
        self.calls: list[str] = []

    def __call__(self, name: str) -> int:
        self.calls.append(name)
        items = self._script[name]
        item = items.pop(0) if len(items) > 1 else items[0]
        if isinstance(item, OSError):
            raise item
        return item


def _monitor(script: dict[str, list[int | OSError]], *, psutil_value: float = 61.7):

    fake = _FakeSysctl(script)
    monitor = MemoryMonitor(GovernorSettings(), kernel=True, sysctl=fake, psutil_percent=lambda: psutil_value)
    return monitor, fake


class TestKernelSignal:
    async def test_used_percent_is_100_minus_memorystatus_level(self) -> None:
        monitor, _ = _monitor({"kern.memorystatus_level": [77]})
        assert await monitor.read_used_percent() == 23.0
        assert monitor.signal_source == "kernel"

    @pytest.mark.parametrize(
        ("raw", "level"),
        [(1, PressureLevel.GREEN), (2, PressureLevel.YELLOW), (4, PressureLevel.RED), (99, PressureLevel.GREEN)],
    )
    async def test_pressure_levels_map(self, raw: int, level: PressureLevel) -> None:
        monitor, _ = _monitor({"kern.memorystatus_vm_pressure_level": [raw]})
        assert await monitor.read_macos_pressure() is level

    async def test_pressure_read_failure_is_fail_stale(self) -> None:
        """F-17: a failed read after RED stays RED instead of clearing the crisis."""
        monitor, _ = _monitor({"kern.memorystatus_vm_pressure_level": [4, OSError(1, "denied")]})
        assert await monitor.read_macos_pressure() is PressureLevel.RED
        assert await monitor.read_macos_pressure() is PressureLevel.RED

    async def test_level_failure_falls_back_to_psutil_and_warns_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        events: list[str] = []

        class _RecordingLog:
            def warning(self, event: str, **context: object) -> None:
                events.append(event)

        # A recording stand-in instead of capture_logs: structlog caches loggers
        # once configure_logging() has run elsewhere in the session.
        monkeypatch.setattr("alphaswarm.memory_monitor.log", _RecordingLog())
        monitor, _ = _monitor({"kern.memorystatus_level": [OSError(1, "denied")]}, psutil_value=64.0)
        values = [await monitor.read_used_percent() for _ in range(3)]
        assert values == [64.0, 64.0, 64.0]
        assert events.count("memory_level_read_failed") == 1

    async def test_out_of_range_level_falls_back_to_psutil(self) -> None:
        monitor, _ = _monitor({"kern.memorystatus_level": [140]}, psutil_value=55.5)
        assert await monitor.read_used_percent() == 55.5

    async def test_read_combined_carries_thresholds_and_both_signals(self) -> None:
        monitor, _ = _monitor({"kern.memorystatus_level": [30], "kern.memorystatus_vm_pressure_level": [2]})
        r = await monitor.read_combined()
        assert (r.used_percent, r.pressure_level) == (70.0, PressureLevel.YELLOW)
        assert (r.throttle_threshold, r.pause_threshold, r.scale_up_threshold) == (80.0, 90.0, 60.0)

    async def test_non_macos_uses_psutil_and_never_calls_sysctl(self) -> None:
        """glibc has no sysctlbyname; Linux/CI must never touch it."""

        def _explode(name: str) -> int:
            raise AssertionError(f"sysctl called off macOS: {name}")

        monitor = MemoryMonitor(GovernorSettings(), kernel=False, sysctl=_explode, psutil_percent=lambda: 48.0)
        r = await monitor.read_combined()
        assert (r.used_percent, r.pressure_level) == (48.0, PressureLevel.GREEN)
        assert monitor.signal_source == "psutil"

    def test_default_signal_follows_platform(self, monkeypatch: pytest.MonkeyPatch) -> None:

        monkeypatch.setattr("alphaswarm.memory_monitor.sys.platform", "linux")
        assert MemoryMonitor(GovernorSettings()).signal_source == "psutil"
        monkeypatch.setattr("alphaswarm.memory_monitor.sys.platform", "darwin")
        assert MemoryMonitor(GovernorSettings()).signal_source == "kernel"

    async def test_reads_never_spawn_a_subprocess(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Zero sysctl subprocesses during a run (was ~1,800 forks per hour)."""
        import subprocess

        async def _no_exec(*args: object, **kwargs: object) -> None:
            raise AssertionError("subprocess spawned")

        def _no_popen(*args: object, **kwargs: object) -> None:
            raise AssertionError("subprocess spawned")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _no_exec)
        monkeypatch.setattr(subprocess, "Popen", _no_popen)
        monitor, fake = _monitor({"kern.memorystatus_level": [70], "kern.memorystatus_vm_pressure_level": [1]})
        for _ in range(50):
            await monitor.read_combined()
        assert len(fake.calls) == 100

    @pytest.mark.skipif(sys.platform != "darwin", reason="real sysctlbyname exists only on macOS")
    async def test_real_kernel_read_on_macos(self) -> None:
        from alphaswarm.memory_monitor import memory_used_percent

        monitor = MemoryMonitor(GovernorSettings())
        r = await monitor.read_combined()
        assert monitor.signal_source == "kernel"
        assert 0.0 <= r.used_percent <= 100.0
        assert 0.0 <= memory_used_percent() <= 100.0

    def test_memory_used_percent_falls_back_off_macos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from types import SimpleNamespace

        from alphaswarm.memory_monitor import memory_used_percent

        monkeypatch.setattr("alphaswarm.memory_monitor.sys.platform", "linux")
        monkeypatch.setattr(
            "alphaswarm.memory_monitor.psutil.virtual_memory",
            lambda: SimpleNamespace(percent=42.0),
        )
        assert memory_used_percent() == 42.0
