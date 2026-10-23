"""persist_round marks the seeded holdout as d.control (fast track; neo4j-test)."""

from __future__ import annotations

import inspect

import pytest
from neo4j import AsyncDriver

from alphaswarm.episodes import new_decision_ids
from alphaswarm.graph import GraphStateManager
from alphaswarm.types import (
    AgentDecision,
    AgentPersona,
    EntityType,
    SeedEntity,
    SeedEvent,
    SignalType,
)
from tests.conftest import NEO4J_TEST_DATABASE

pytestmark = pytest.mark.neo4j

RUMOR = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."
SEED = SeedEvent(
    raw_rumor=RUMOR,
    entities=[SeedEntity(name="ZZZT Holdings", type=EntityType.COMPANY, relevance=0.9, sentiment=0.5)],
    overall_sentiment=0.4,
)


async def _new_cycle(gm: GraphStateManager) -> str:
    """Works whether or not ``num_rounds`` is a required keyword."""
    params = inspect.signature(gm.create_cycle_with_seed_event).parameters
    kwargs = {"num_rounds": 3} if "num_rounds" in params else {}
    return await gm.create_cycle_with_seed_event(RUMOR, SEED, **kwargs)


async def _control_flags(driver: AsyncDriver, cycle_id: str) -> dict[str, object]:
    async with driver.session(database=NEO4J_TEST_DATABASE) as session:
        result = await session.run(
            "MATCH (a:Agent)-[:MADE]->(d:Decision {cycle_id: $cid}) RETURN a.id AS agent_id, d.control AS control",
            cid=cycle_id,
        )
        return {record["agent_id"]: record["control"] async for record in result}


def _three(personas: list[AgentPersona]) -> list[tuple[str, AgentDecision]]:
    a, b, c = (p.id for p in personas[:3])
    return [
        (a, AgentDecision(signal=SignalType.BUY, confidence=0.7)),
        (b, AgentDecision(signal=SignalType.HOLD, confidence=0.5)),
        (c, AgentDecision(signal=SignalType.SELL, confidence=0.6)),
    ]


async def test_control_ids_become_decision_properties(
    graph_manager_test: GraphStateManager,
    neo4j_test_driver: AsyncDriver,
    all_personas: list[AgentPersona],
) -> None:
    cycle_id = await _new_cycle(graph_manager_test)
    decisions = _three(all_personas)
    a, b, c = (agent_id for agent_id, _ in decisions)

    await graph_manager_test.persist_round(
        cycle_id, 2, decisions, decision_ids=new_decision_ids(3), episodes=[], entity_matches=[], control_ids=[b]
    )

    assert await _control_flags(neo4j_test_driver, cycle_id) == {a: False, b: True, c: False}


async def test_default_marks_nobody(
    graph_manager_test: GraphStateManager,
    neo4j_test_driver: AsyncDriver,
    all_personas: list[AgentPersona],
) -> None:
    cycle_id = await _new_cycle(graph_manager_test)

    await graph_manager_test.persist_round(
        cycle_id, 1, _three(all_personas), decision_ids=new_decision_ids(3), episodes=[], entity_matches=[]
    )

    assert set((await _control_flags(neo4j_test_driver, cycle_id)).values()) == {False}
