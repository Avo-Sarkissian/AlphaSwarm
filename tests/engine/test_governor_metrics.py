"""Governor time-in-state reaches the cycle metrics through the real run."""

from __future__ import annotations

from unittest.mock import MagicMock

from alphaswarm.governor import ResourceGovernor
from tests.engine.scenario import RunScenario
from tests.support.monitor import ScriptedMonitor, fast_governor_settings, reading


async def test_governor_time_in_state_reaches_the_cycle_metrics(
    run_scenario: RunScenario, fake_graph: MagicMock
) -> None:
    governor = ResourceGovernor(fast_governor_settings(), monitor=ScriptedMonitor([reading(50.0)]))
    await run_scenario(controller=governor)
    m = dict(fake_graph.write_cycle_metrics.await_args.args[1])
    seconds = (m["governor_throttled_seconds"], m["governor_paused_seconds"], m["governor_crisis_seconds"])
    assert seconds == (0.0, 0.0, 0.0)
    assert m["governor_peak_memory_percent"] == 50.0


async def test_controllers_without_telemetry_add_no_keys(run_scenario: RunScenario, fake_graph: MagicMock) -> None:
    await run_scenario()  # ImmediateController, like the cloud RateLimitController, has no time-in-state
    m = dict(fake_graph.write_cycle_metrics.await_args.args[1])
    assert not [k for k in m if k.startswith("governor_")]
