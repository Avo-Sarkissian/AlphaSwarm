"""Smoke tests for the deterministic run_simulation harness itself."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from alphaswarm.types import SimulationPhase
from tests.engine.scenario import (
    SCENARIO_CYCLE_ID,
    RecordingStateStore,
    RunScenario,
    persisted_rounds,
    round_calls,
)
from tests.inference.fakes import ScriptedProvider
from tests.support.controllers import ImmediateController

FULL_RUN = [
    SimulationPhase.IDLE,
    SimulationPhase.SEEDING,
    SimulationPhase.ROUND_1,
    SimulationPhase.ROUND_2,
    SimulationPhase.ROUND_3,
    SimulationPhase.COMPLETE,
]


async def test_scripted_three_round_run_completes(
    run_scenario: RunScenario,
    scenario_store: RecordingStateStore,
    scripted_worker: ScriptedProvider,
    scripted_orchestrator: ScriptedProvider,
    scenario_controller: ImmediateController,
    fake_graph: MagicMock,
) -> None:
    result = await run_scenario()
    assert result.cycle_id == SCENARIO_CYCLE_ID
    assert scenario_store.phases == FULL_RUN
    assert [len(round_calls(scripted_worker, r)) for r in (1, 2, 3)] == [100, 100, 100]
    assert len(scripted_worker.calls_for("narrative")) == 100
    assert len(scripted_orchestrator.calls_for("orchestrator")) == 2
    assert persisted_rounds(fake_graph) == [1, 2, 3]
    assert scenario_controller.acquired == scenario_controller.released == 400
    assert scenario_controller.in_use == 0


async def test_forbid_real_sleep_records_positive_delays(forbid_real_sleep: list[float]) -> None:
    await asyncio.sleep(0)
    await asyncio.sleep(0.25)
    assert forbid_real_sleep == [0.25]
    forbid_real_sleep.clear()  # keep the fixture's teardown assertion green


async def test_fake_graph_rejects_calls_that_break_the_real_signature(
    fake_graph: MagicMock,
) -> None:
    with pytest.raises(TypeError):
        await fake_graph.write_decisions([], "cycle", 1, "unexpected-extra-positional")
