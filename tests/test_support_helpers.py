"""Self-tests for the shared test helpers in tests/support/."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from alphaswarm.inference.concurrency import ConcurrencyController
from alphaswarm.memory_monitor import MemoryReader, PressureLevel
from alphaswarm.settings import GovernorSettings
from tests.support.aio import eventually
from tests.support.controllers import ImmediateController
from tests.support.log_capture import RenderedLog
from tests.support.monitor import ScriptedMonitor, fast_governor_settings, reading


async def test_eventually_returns_once_predicate_holds() -> None:
    state = {"turns": 0}

    def _ready() -> bool:
        state["turns"] += 1
        return state["turns"] >= 3

    await eventually(_ready, what="third turn")
    assert state["turns"] == 3


async def test_eventually_names_the_condition_on_timeout() -> None:
    with pytest.raises(AssertionError, match="flag set did not become true within 3"):
        await eventually(lambda: False, max_yields=3, what="flag set")


async def test_immediate_controller_counts_and_satisfies_protocol() -> None:
    ctrl = ImmediateController()
    assert isinstance(ctrl, ConcurrencyController)
    await ctrl.start_monitoring()
    await ctrl.acquire()
    await ctrl.acquire()
    ctrl.release()
    ctrl.release(success=False)
    ctrl.report_wave_failures(98, 2)
    await ctrl.stop_monitoring()
    assert (ctrl.acquired, ctrl.released, ctrl.failures) == (2, 2, 1)
    assert (ctrl.max_in_use, ctrl.in_use) == (2, 0)
    assert ctrl.wave_reports == [(98, 2)]
    assert (ctrl.monitoring_starts, ctrl.monitoring_stops) == (1, 1)


async def test_immediate_controller_context_manager_marks_failures() -> None:
    ctrl = ImmediateController()
    with pytest.raises(RuntimeError):
        async with ctrl:
            raise RuntimeError("boom")
    async with ctrl:
        pass
    assert (ctrl.acquired, ctrl.released, ctrl.failures) == (2, 2, 1)


def test_rendered_log_renders_tracebacks_with_the_exception_text() -> None:
    """Positive control: a leak through exc_info would show up in RenderedLog.text."""
    log = RenderedLog()
    canary = "".join(["fictional", "-", "CANARY"])
    try:
        raise ValueError(f"config at /fictional/inference.json quoted {canary}")
    except ValueError:
        log.error("job_failed", exc_info=True, cycle_id="c1")
    log.info("job_done")
    assert log.events == ["job_failed", "job_done"]
    assert canary in log.text
    assert '"exc_type": "ValueError"' in log.text
    assert '"locals"' not in log.text


def test_reading_uses_settings_thresholds() -> None:
    custom = GovernorSettings(memory_throttle_percent=70.0, memory_pause_percent=85.0, scale_up_threshold_percent=50.0)
    r = reading(72.0, settings=custom)
    assert (r.throttle_threshold, r.pause_threshold, r.scale_up_threshold) == (70.0, 85.0, 50.0)
    assert r.is_throttle_zone and not r.is_pause_zone
    assert reading(50.0, PressureLevel.RED).is_crisis


async def test_scripted_monitor_replays_in_order_then_repeats_last() -> None:
    monitor = ScriptedMonitor([reading(10.0), reading(20.0)])
    assert isinstance(monitor, MemoryReader)
    got = [(await monitor.read_combined()).used_percent for _ in range(4)]
    assert got == [10.0, 20.0, 20.0, 20.0]
    assert monitor.reads == 4


async def test_scripted_monitor_raises_exception_items() -> None:
    monitor = ScriptedMonitor([RuntimeError("sysctl exploded")])
    with pytest.raises(RuntimeError, match="sysctl exploded"):
        await monitor.read_combined()
    assert monitor.reads == 1


async def test_scripted_monitor_blocks_until_push_when_not_repeating() -> None:
    monitor = ScriptedMonitor([reading(10.0)], repeat_last=False)
    await monitor.read_combined()
    pending = asyncio.create_task(monitor.read_combined())
    for _ in range(5):
        await asyncio.sleep(0)
    assert not pending.done()
    monitor.push(reading(95.0))
    await eventually(pending.done, what="read after push")
    assert pending.result().used_percent == 95.0


def test_fast_governor_settings_bypasses_only_the_test_knobs() -> None:
    s = fast_governor_settings(baseline_parallel=2, crisis_timeout_seconds=-1.0)
    assert (s.baseline_parallel, s.check_interval_seconds, s.crisis_timeout_seconds) == (2, 0.0, -1.0)
    with pytest.raises(ValidationError):
        fast_governor_settings(baseline_parallel=0)
