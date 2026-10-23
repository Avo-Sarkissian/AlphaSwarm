"""Per-cycle decision narratives and interview context (docs/DECISIONS.md#p11-d-10)."""

from __future__ import annotations

import pytest

from alphaswarm.graph import GraphStateManager
from alphaswarm.types import SignalType
from tests.support.mini_cycle import cypher, dec, write_mini_cycle

pytestmark = pytest.mark.neo4j

BUY, HOLD = SignalType.BUY, SignalType.HOLD


async def _two_rounds(gm: GraphStateManager, *agents: str) -> str:
    return await write_mini_cycle(
        gm,
        num_rounds=2,
        rounds={1: [(a, dec(BUY)) for a in agents], 2: [(a, dec(HOLD)) for a in agents]},
    )


async def test_decision_narrative_round_trip_on_final_round(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await _two_rounds(graph_manager_test, "quants_01")

    assert await graph_manager_test.read_decision_narrative(cycle_id, "quants_01") is None
    await graph_manager_test.write_decision_narrative(
        cycle_id,
        "quants_01",
        "Fictional arc: bought, then held.",
    )

    assert await graph_manager_test.read_decision_narrative(cycle_id, "quants_01") == (
        "Fictional arc: bought, then held."
    )
    rows = await cypher(
        graph_manager_test,
        "MATCH (:Agent {id: 'quants_01'})-[:MADE]->(d:Decision {cycle_id: $id}) "
        "RETURN d.round AS round, d.narrative AS narrative ORDER BY d.round",
        id=cycle_id,
    )
    assert rows == [
        {"round": 1, "narrative": None},
        {"round": 2, "narrative": "Fictional arc: bought, then held."},
    ]


async def test_batch_narratives_land_on_each_agents_final_decision(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await _two_rounds(graph_manager_test, "quants_01", "degens_01")

    await graph_manager_test.write_decision_narratives(
        cycle_id,
        [("quants_01", "q arc"), ("degens_01", "d arc")],
    )

    assert await graph_manager_test.read_decision_narrative(cycle_id, "quants_01") == "q arc"
    assert await graph_manager_test.read_decision_narrative(cycle_id, "degens_01") == "d arc"


async def test_narrative_write_without_decision_is_a_no_op(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await _two_rounds(graph_manager_test, "quants_01")

    await graph_manager_test.write_decision_narrative(cycle_id, "degens_09", "orphan")

    assert await graph_manager_test.read_decision_narrative(cycle_id, "degens_09") is None


async def test_ensure_schema_removes_agent_level_narrative(
    graph_manager_test: GraphStateManager,
) -> None:
    await cypher(
        graph_manager_test,
        "MATCH (a:Agent {id: 'quants_01'}) SET a.decision_narrative = 'legacy text'",
    )

    await graph_manager_test.ensure_schema()

    rows = await cypher(
        graph_manager_test,
        "MATCH (a:Agent) WHERE a.decision_narrative IS NOT NULL RETURN count(a) AS n",
    )
    assert rows == [{"n": 0}]
