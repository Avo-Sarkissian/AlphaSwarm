"""A fresh database persists decisions once the schema is applied.

Startup applies the schema (docs/DECISIONS.md#adr-web-lifespan). Runs against the
throwaway neo4j-test database only (tests/conftest.py guards).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from alphaswarm.errors import Neo4jWriteError
from alphaswarm.types import AgentDecision, SeedEvent, SignalType

if TYPE_CHECKING:
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.types import AgentPersona

pytestmark = pytest.mark.neo4j

RUMOR = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."


async def _new_cycle(gm: GraphStateManager) -> str:
    seed = SeedEvent(raw_rumor=RUMOR, entities=[], overall_sentiment=0.2)
    return await gm.create_cycle_with_seed_event(RUMOR, seed, num_rounds=3)


async def _decision_count(gm: GraphStateManager, cycle_id: str) -> int:
    async with gm._driver.session(database="neo4j") as session:
        result = await session.run("MATCH (d:Decision {cycle_id: $cid}) RETURN count(d) AS n", cid=cycle_id)
        record = await result.single()
    return int(record["n"]) if record is not None else 0


async def test_verify_connectivity_succeeds_on_neo4j_test(
    graph_manager_test: GraphStateManager,
) -> None:
    await graph_manager_test.verify_connectivity()


async def test_schema_applied_then_100_decisions_persist(
    graph_manager_test: GraphStateManager, all_personas: list[AgentPersona]
) -> None:
    """graph_manager_test ran ensure_schema(), which seeds the 100 Agent nodes."""
    cycle_id = await _new_cycle(graph_manager_test)
    decisions = [
        (p.id, AgentDecision(signal=SignalType.HOLD, confidence=0.5, rationale="fresh install")) for p in all_personas
    ]

    ids = await graph_manager_test.write_decisions(decisions, cycle_id, 1)

    assert len(ids) == 100
    assert await _decision_count(graph_manager_test, cycle_id) == 100


async def test_writes_for_agents_without_nodes_raise_instead_of_vanishing(
    graph_manager_test: GraphStateManager,
) -> None:
    """The pre-fix failure mode: no Agent nodes (as on a database where
    ensure_schema() never ran), so every MATCH drops its row. Agent ids outside
    the seeded roster reproduce that on the shared test database."""
    cycle_id = await _new_cycle(graph_manager_test)
    decisions = [(f"unseeded_{i:03d}", AgentDecision(signal=SignalType.BUY, confidence=0.7)) for i in range(100)]

    with pytest.raises(Neo4jWriteError, match="Wrote 0 of 100 decisions"):
        await graph_manager_test.write_decisions(decisions, cycle_id, 1)
    assert await _decision_count(graph_manager_test, cycle_id) == 0
