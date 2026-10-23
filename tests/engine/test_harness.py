"""Smoke tests for the deterministic run_simulation harness itself."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from alphaswarm.graph import GraphStateManager
from alphaswarm.types import AgentDecision, SignalType, SimulationPhase
from tests.engine.scenario import (
    SCENARIO_CYCLE_ID,
    RecordingStateStore,
    RunScenario,
    influence_weights_from_writes,
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
    SimulationPhase.FINALIZING,
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
    assert scripted_worker.calls_for("narrative") == []  # narratives are lazy, per interview
    assert len(scripted_orchestrator.calls_for("orchestrator")) == 2
    assert persisted_rounds(fake_graph) == [1, 2, 3]
    assert scenario_controller.acquired == scenario_controller.released == 300
    assert scenario_controller.in_use == 0


async def test_forbid_real_sleep_records_positive_delays(forbid_real_sleep: list[float]) -> None:
    await asyncio.sleep(0)
    await asyncio.sleep(0.25)
    assert forbid_real_sleep == [0.25]
    forbid_real_sleep.clear()  # keep the fixture's teardown assertion green


async def test_fake_graph_rejects_calls_that_break_the_real_signature(
    fake_graph: MagicMock,
) -> None:
    # write_cycle_metrics has no side_effect, so only the autospec can refuse the call;
    # the match keeps an unrelated TypeError (awaiting a plain MagicMock) from passing.
    with pytest.raises(TypeError, match="missing a required argument: 'metrics'"):
        await fake_graph.write_cycle_metrics("cycle")


def _citing(*cited: str) -> AgentDecision:
    return AgentDecision(signal=SignalType.HOLD, confidence=0.5, cited_agents=list(cited))


async def _record_citations(graph: MagicMock) -> None:
    """Round 2 holds a self-citation; round 3 repeats a pair and names one agent twice."""
    await _persist(graph, 2, [("quants_01", _citing("sell_side_01", "quants_01"))])
    await _persist(
        graph,
        3,
        [
            ("quants_01", _citing("sell_side_01")),
            ("degens_01", _citing("sell_side_01", "sell_side_01")),
        ],
    )


async def _persist(graph: MagicMock, round_num: int, decisions: list[tuple[str, AgentDecision]]) -> None:
    """One round through the autospecced persist_round, the engine's only decision write."""
    await graph.persist_round(
        "cycle",
        round_num,
        decisions,
        decision_ids=[f"dec-r{round_num}-{i}" for i in range(len(decisions))],
        episodes=[],
        entity_matches=[],
    )


async def _real_weights(pairs: list[tuple[str, str]], total_agents: int) -> dict[str, float]:
    """Run the real compute_influence_edges on a fake session that serves these pairs."""
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.execute_read.return_value = [{"source_id": s, "target_id": t} for s, t in pairs]
    driver = MagicMock()
    driver.session.return_value = session
    manager = GraphStateManager(driver=driver, personas=[])
    return await manager.compute_influence_edges("cycle", 3, total_agents)


async def test_influence_stand_in_counts_distinct_pairs_without_self_citations(
    fake_graph: MagicMock,
) -> None:
    await _record_citations(fake_graph)
    # Like the real query: DISTINCT (author, cited) pairs across rounds, self-citations dropped.
    assert influence_weights_from_writes(fake_graph, up_to_round=2, total_agents=4) == {"sell_side_01": 0.25}
    assert influence_weights_from_writes(fake_graph, up_to_round=3, total_agents=4) == {"sell_side_01": 0.5}


@pytest.mark.parametrize("total_agents", [4, 0])
async def test_influence_stand_in_matches_compute_influence_edges(fake_graph: MagicMock, total_agents: int) -> None:
    """Given the pairs its query returns for the same writes, the real method agrees with the
    stand-in, the zero-agent guard included. When compute_influence_edges changes, so must the
    stand-in."""
    await _record_citations(fake_graph)
    query_rows = [("quants_01", "sell_side_01"), ("degens_01", "sell_side_01")]
    expected = await _real_weights(query_rows, total_agents)
    actual = influence_weights_from_writes(fake_graph, up_to_round=3, total_agents=total_agents)
    assert actual == expected
