"""persist_round stores exposure, holdout, invalid citations and the shock arm on neo4j-test."""

from __future__ import annotations

from typing import Any

import pytest
from neo4j import AsyncDriver

from alphaswarm.episodes import new_decision_ids
from alphaswarm.graph import GraphStateManager
from alphaswarm.types import AgentDecision, AgentPersona, EntityType, SeedEntity, SeedEvent, SignalType
from tests.conftest import NEO4J_TEST_DATABASE

pytestmark = pytest.mark.neo4j

RUMOR = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."
SEED = SeedEvent(
    raw_rumor=RUMOR,
    entities=[SeedEntity(name="ZZZT Holdings", type=EntityType.COMPANY, relevance=0.9, sentiment=0.5)],
    overall_sentiment=0.4,
)


async def _decision_props(driver: AsyncDriver, cycle_id: str) -> dict[str, dict[str, Any]]:
    async with driver.session(database=NEO4J_TEST_DATABASE) as session:
        result = await session.run(
            "MATCH (a:Agent)-[:MADE]->(d:Decision {cycle_id: $cid}) RETURN a.id AS agent_id, properties(d) AS props",
            cid=cycle_id,
        )
        return {record["agent_id"]: dict(record["props"]) async for record in result}


def _three(personas: list[AgentPersona]) -> tuple[str, str, str, list[tuple[str, AgentDecision]]]:
    a, b, c = (p.id for p in personas[:3])
    decisions = [
        (a, AgentDecision(signal=SignalType.BUY, confidence=0.7, cited_agents=[b])),
        (b, AgentDecision(signal=SignalType.HOLD, confidence=0.5)),
        (c, AgentDecision(signal=SignalType.SELL, confidence=0.6)),
    ]
    return a, b, c, decisions


async def test_new_properties_round_trip(
    graph_manager_test: GraphStateManager,
    neo4j_test_driver: AsyncDriver,
    all_personas: list[AgentPersona],
) -> None:
    cycle_id = await graph_manager_test.create_cycle_with_seed_event(RUMOR, SEED, num_rounds=3)
    a, b, c, decisions = _three(all_personas)

    await graph_manager_test.persist_round(
        cycle_id,
        2,
        decisions,
        decision_ids=new_decision_ids(3),
        episodes=[],
        entity_matches=[],
        exposures={a: [b, c], b: []},
        control_ids=[b],
        citations_invalid={a: 2},
        shock_treated_ids=[a],
    )
    props = await _decision_props(neo4j_test_driver, cycle_id)

    assert [props[x]["peer_ids"] for x in (a, b, c)] == [[b, c], [], []]
    assert [props[x]["control"] for x in (a, b, c)] == [False, True, False]
    assert [props[x]["citations_invalid"] for x in (a, b, c)] == [2, 0, 0]
    assert [props[x]["shock_treated"] for x in (a, b, c)] == [True, False, False]


async def test_legacy_call_leaves_unknowns_absent(
    graph_manager_test: GraphStateManager,
    neo4j_test_driver: AsyncDriver,
    all_personas: list[AgentPersona],
) -> None:
    cycle_id = await graph_manager_test.create_cycle_with_seed_event(RUMOR, SEED, num_rounds=3)
    a, _, _, decisions = _three(all_personas)

    await graph_manager_test.persist_round(
        cycle_id,
        1,
        decisions,
        decision_ids=new_decision_ids(3),
        episodes=[],
        entity_matches=[],
    )
    props = await _decision_props(neo4j_test_driver, cycle_id)

    assert "peer_ids" not in props[a]
    assert "citations_invalid" not in props[a]
    assert "shock_treated" not in props[a]
    assert props[a]["control"] is False
