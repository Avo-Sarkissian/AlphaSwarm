"""Governor time-in-state and peak memory (docs/DECISIONS.md#adr-inference-telemetry)."""

from __future__ import annotations

import pytest
import structlog

import alphaswarm.governor as governor_module
from alphaswarm.governor import GovernorState, ResourceGovernor
from alphaswarm.memory_monitor import PressureLevel
from tests.support.aio import eventually
from tests.support.monitor import ScriptedMonitor, fast_governor_settings, reading


class _ManualClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _ManualClock:
    fake = _ManualClock()
    monkeypatch.setattr(governor_module, "_clock", fake)
    return fake


@pytest.fixture(autouse=True)
def _fresh_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    # capture_logs cannot see a module logger that an earlier test cached under
    # another structlog configuration; a fresh proxy is never cached here.
    monkeypatch.setattr(governor_module, "log", structlog.get_logger(component="governor"))


async def _step(
    gov: ResourceGovernor,
    monitor: ScriptedMonitor,
    percent: float,
    expected: GovernorState,
    pressure: PressureLevel = PressureLevel.GREEN,
) -> None:
    monitor.push(reading(percent, pressure))
    await eventually(lambda: gov.state is expected, what=f"governor {expected.value}")


async def test_time_in_state_accumulates_per_state(clock: _ManualClock) -> None:
    monitor = ScriptedMonitor([], repeat_last=False)
    gov = ResourceGovernor(fast_governor_settings(), monitor=monitor)
    await gov.start_monitoring()
    try:
        clock.now = 10.0
        await _step(gov, monitor, 85.0, GovernorState.THROTTLED)
        clock.now = 40.0
        await _step(gov, monitor, 92.0, GovernorState.PAUSED)
        clock.now = 45.0
        await _step(gov, monitor, 50.0, GovernorState.RUNNING)
        clock.now = 100.0
        assert gov.time_in_state() == {"throttled": 30.0, "paused": 5.0, "crisis": 0.0}
        assert gov.peak_memory_percent == 92.0
    finally:
        await gov.stop_monitoring()


async def test_crisis_time_counts_until_recovery(clock: _ManualClock) -> None:
    monitor = ScriptedMonitor([], repeat_last=False)
    gov = ResourceGovernor(fast_governor_settings(), monitor=monitor)
    await gov.start_monitoring()
    try:
        clock.now = 5.0
        await _step(gov, monitor, 70.0, GovernorState.CRISIS, PressureLevel.RED)
        clock.now = 8.0
        await _step(gov, monitor, 70.0, GovernorState.RECOVERING)
        clock.now = 20.0
        assert gov.time_in_state()["crisis"] == 3.0
    finally:
        await gov.stop_monitoring()


async def test_open_interval_counts_until_stop_then_freezes(clock: _ManualClock) -> None:
    monitor = ScriptedMonitor([], repeat_last=False)
    gov = ResourceGovernor(fast_governor_settings(), monitor=monitor)
    await gov.start_monitoring()
    clock.now = 10.0
    await _step(gov, monitor, 85.0, GovernorState.THROTTLED)
    clock.now = 25.0
    assert gov.time_in_state()["throttled"] == 15.0
    clock.now = 30.0
    await gov.stop_monitoring()
    clock.now = 50.0
    assert gov.time_in_state() == {"throttled": 20.0, "paused": 0.0, "crisis": 0.0}


async def test_a_new_session_starts_from_zero(clock: _ManualClock) -> None:
    monitor = ScriptedMonitor([], repeat_last=False)
    gov = ResourceGovernor(fast_governor_settings(), monitor=monitor)
    await gov.start_monitoring()
    clock.now = 10.0
    await _step(gov, monitor, 85.0, GovernorState.THROTTLED)
    await gov.stop_monitoring()
    await gov.start_monitoring()
    try:
        assert gov.time_in_state() == {"throttled": 0.0, "paused": 0.0, "crisis": 0.0}
        assert gov.peak_memory_percent == 0.0
    finally:
        await gov.stop_monitoring()
