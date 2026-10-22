"""The seeded cycle stored in neo4j-test matches what build_seeded_cycle reports."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.conftest import NEO4J_TEST_DATABASE
from tests.support.seed_builder import (
    HUB_CITATIONS,
    SEED_ENTITIES,
    SHOCK_ROUND,
    SHOCK_TEXT,
    SeededCycle,
    build_seeded_cycle,
)

if TYPE_CHECKING:
    from neo4j import AsyncDriver

    from alphaswarm.graph import GraphStateManager

pytestmark = pytest.mark.neo4j

_DISCARDED: list[str] = []


async def _rows(driver: AsyncDriver, query: str, **params: object) -> list[dict[str, object]]:
    async with driver.session(database=NEO4J_TEST_DATABASE) as session:
        result = await session.run(query, **params)
        return [dict(record) async for record in result]


async def test_decisions_and_citations_round_trip(
    seeded_cycle: SeededCycle, neo4j_test_driver: AsyncDriver
) -> None:
    rows = await _rows(
        neo4j_test_driver,
        "MATCH (a:Agent)-[:MADE]->(d:Decision {cycle_id: $cid}) "
        "RETURN d.round AS round, a.id AS agent_id, d.signal AS signal "
        "ORDER BY round, agent_id",
        cid=seeded_cycle.cycle_id,
    )
    expected = sorted(
        (round_num, agent_id, decision.signal.value)
        for round_num, decisions in seeded_cycle.decisions.items()
        for agent_id, decision in decisions
    )
    assert [(r["round"], r["agent_id"], r["signal"]) for r in rows] == expected
    cited = await _rows(
        neo4j_test_driver,
        "MATCH (a:Agent)-[:MADE]->(d:Decision {cycle_id: $cid})-[:CITED]->(t:Agent) "
        "RETURN d.round AS round, a.id AS source, t.id AS target",
        cid=seeded_cycle.cycle_id,
    )
    for round_num in range(1, seeded_cycle.num_rounds + 1):
        got = {(r["source"], r["target"]) for r in cited if r["round"] == round_num}
        assert got == seeded_cycle.cited_pairs[round_num]


async def test_episodes_shock_metrics_and_mentions_round_trip(
    seeded_cycle: SeededCycle, neo4j_test_driver: AsyncDriver
) -> None:
    cid = seeded_cycle.cycle_id
    episodes = await _rows(
        neo4j_test_driver,
        "MATCH (:Decision {cycle_id: $cid})-[:HAS_EPISODE]->(re:RationaleEpisode) "
        "RETURN count(re) AS n",
        cid=cid,
    )
    assert episodes == [{"n": 100 * seeded_cycle.num_rounds}]
    shocks = await _rows(
        neo4j_test_driver,
        "MATCH (:Cycle {cycle_id: $cid})-[:HAS_SHOCK]->(se:ShockEvent) "
        "RETURN se.shock_text AS text, se.injected_before_round AS round",
        cid=cid,
    )
    assert shocks == [{"text": SHOCK_TEXT, "round": SHOCK_ROUND}]
    cycle = await _rows(
        neo4j_test_driver,
        "MATCH (c:Cycle {cycle_id: $cid}) RETURN c.num_rounds AS num_rounds, "
        "c.agent_count AS agent_count, c.metrics_recorded_at IS NOT NULL AS stamped",
        cid=cid,
    )
    assert cycle == [{"num_rounds": 3, "agent_count": 100, "stamped": True}]
    mentions = await _rows(
        neo4j_test_driver,
        "MATCH (:Cycle {cycle_id: $cid})-[:MENTIONS]->(e:Entity) RETURN e.name AS name "
        "ORDER BY name",
        cid=cid,
    )
    assert [r["name"] for r in mentions] == sorted(e.name for e in SEED_ENTITIES)


async def test_cleanup_1_a_function_scoped_cycle_is_built(
    graph_manager_test: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    other = await build_seeded_cycle(graph_manager_test, num_rounds=2)
    assert other.cycle_id != seeded_cycle.cycle_id
    _DISCARDED.append(other.cycle_id)


async def test_cleanup_2_seeded_cycle_survived_the_previous_teardown(
    seeded_cycle: SeededCycle, neo4j_test_driver: AsyncDriver
) -> None:
    """graph_manager_test's teardown removed the cycle above and nothing of the seeded one."""
    if not _DISCARDED:
        pytest.skip("needs test_cleanup_1 earlier in the same session")
    gone = await _rows(
        neo4j_test_driver,
        "MATCH (c:Cycle {cycle_id: $cid}) RETURN count(c) AS n",
        cid=_DISCARDED[-1],
    )
    assert gone == [{"n": 0}]
    cid = seeded_cycle.cycle_id
    decisions = await _rows(
        neo4j_test_driver, "MATCH (d:Decision {cycle_id: $cid}) RETURN count(d) AS n", cid=cid
    )
    assert decisions == [{"n": 100 * seeded_cycle.num_rounds}]
    edges = await _rows(
        neo4j_test_driver,
        "MATCH ()-[e:INFLUENCED_BY {cycle_id: $cid}]->() "
        "RETURN e.round AS round, count(e) AS n ORDER BY round",
        cid=cid,
    )
    round_2 = sum(total // 2 for _, total in HUB_CITATIONS)
    round_3 = sum(total for _, total in HUB_CITATIONS)
    assert edges == [{"round": 2, "n": round_2}, {"round": 3, "n": round_3}]
    mentions = await _rows(
        neo4j_test_driver,
        "MATCH (:Cycle {cycle_id: $cid})-[:MENTIONS]->(e:Entity) RETURN count(e) AS n",
        cid=cid,
    )
    assert mentions == [{"n": len(SEED_ENTITIES)}]
