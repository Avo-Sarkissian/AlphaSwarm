"""Integration tests for GraphStateManager against the throwaway neo4j-test database.

Requires: scripts/neo4j_test.sh up (127.0.0.1:7688, tmpfs).
Skip: automatically skipped when neo4j-test is unreachable, unless --require-neo4j.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from alphaswarm.types import AgentDecision, SignalType
from tests.support.graph_fakes import write_round

# The `neo4j` marker adds enable_socket and the session event loop (tests/conftest.py).
pytestmark = pytest.mark.neo4j

if TYPE_CHECKING:
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.types import AgentPersona


async def _new_cycle(gm: GraphStateManager, rumor: str) -> str:
    """Create a Cycle through the production write path (create_cycle was removed)."""
    from alphaswarm.types import SeedEvent

    seed = SeedEvent(raw_rumor=rumor, entities=[], overall_sentiment=0.0)
    return await gm.create_cycle_with_seed_event(rumor, seed, num_rounds=3)


async def test_ensure_schema_idempotent(graph_manager_test: GraphStateManager) -> None:
    """ensure_schema can be called twice without errors. Constraints and indexes exist."""
    # graph_manager_test fixture already called ensure_schema once; call again
    await graph_manager_test.ensure_schema()

    async with graph_manager_test._driver.session(database="neo4j") as session:
        # Verify constraints
        result = await session.run("SHOW CONSTRAINTS")
        constraints = [dict(record) async for record in result]
        constraint_names = [c["name"] for c in constraints]
        assert "agent_id_unique" in constraint_names
        assert "cycle_id_unique" in constraint_names

        # Verify indexes. Neo4j 5.x silently no-ops `CREATE INDEX agent_id_idx`
        # because the `agent_id_unique` UNIQUE constraint already provides a
        # backing index on (:Agent.id) — so we just check that lookup-by-id is
        # backed by SOMETHING (constraint OR index), not specifically by the
        # redundant index name.
        result = await session.run("SHOW INDEXES")
        indexes = [dict(record) async for record in result]
        index_names = [idx["name"] for idx in indexes]
        assert "decision_cycle_round" in index_names
        assert "decision_id_idx" in index_names
        agent_id_backed = "agent_id_idx" in index_names or "agent_id_unique" in constraint_names
        assert agent_id_backed, (
            "Expected a backing index for (:Agent.id) via either 'agent_id_idx' index or 'agent_id_unique' constraint"
        )


async def test_seed_agents_creates_100_nodes(graph_manager_test: GraphStateManager) -> None:
    """ensure_schema seeds all 100 agents."""
    async with graph_manager_test._driver.session(database="neo4j") as session:
        result = await session.run("MATCH (a:Agent) RETURN count(a) AS c")
        record = await result.single()
        assert record["c"] == 100


async def test_seed_agents_idempotent(graph_manager_test: GraphStateManager, all_personas: list[AgentPersona]) -> None:
    """Calling seed_agents again does not create duplicates (MERGE)."""
    await graph_manager_test.seed_agents(all_personas)

    async with graph_manager_test._driver.session(database="neo4j") as session:
        result = await session.run("MATCH (a:Agent) RETURN count(a) AS c")
        record = await result.single()
        assert record["c"] == 100


async def test_create_cycle_returns_uuid(graph_manager_test: GraphStateManager) -> None:
    """create_cycle_with_seed_event returns a valid uuid4 and persists the Cycle node."""
    cycle_id = await _new_cycle(graph_manager_test, "Test rumor")

    uuid4_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    assert re.match(uuid4_pattern, cycle_id), f"Not a valid UUID4: {cycle_id}"

    async with graph_manager_test._driver.session(database="neo4j") as session:
        result = await session.run(
            "MATCH (c:Cycle {cycle_id: $cid}) RETURN c.seed_rumor AS sr",
            cid=cycle_id,
        )
        record = await result.single()
        assert record is not None
        assert record["sr"] == "Test rumor"


async def test_batch_write_100_decisions(
    graph_manager_test: GraphStateManager, all_personas: list[AgentPersona]
) -> None:
    """persist_round persists 100 Decision nodes in a single batch."""
    cycle_id = await _new_cycle(graph_manager_test, "Batch write test")

    decisions = [
        (
            persona.id,
            AgentDecision(
                signal=SignalType.HOLD,
                confidence=0.5,
                sentiment=0.0,
                rationale="test",
                cited_agents=[],
            ),
        )
        for persona in all_personas
    ]

    await write_round(graph_manager_test, cycle_id, 1, decisions)

    async with graph_manager_test._driver.session(database="neo4j") as session:
        result = await session.run(
            "MATCH (d:Decision {cycle_id: $cid}) RETURN count(d) AS c",
            cid=cycle_id,
        )
        record = await result.single()
        assert record["c"] == 100


async def test_persist_round_creates_cited_relationships(
    graph_manager_test: GraphStateManager, all_personas: list[AgentPersona]
) -> None:
    """persist_round creates CITED relationships when cited_agents is non-empty."""
    cycle_id = await _new_cycle(graph_manager_test, "Citation test")

    decisions = [
        (
            "quants_01",
            AgentDecision(
                signal=SignalType.BUY,
                confidence=0.8,
                sentiment=0.5,
                rationale="cites degens",
                cited_agents=["degens_01"],
            ),
        ),
        (
            "degens_01",
            AgentDecision(
                signal=SignalType.SELL,
                confidence=0.6,
                sentiment=-0.3,
                rationale="no citations",
                cited_agents=[],
            ),
        ),
    ]

    await write_round(graph_manager_test, cycle_id, 1, decisions)

    async with graph_manager_test._driver.session(database="neo4j") as session:
        result = await session.run(
            'MATCH (d:Decision {cycle_id: $cid})-[:CITED]->(a:Agent {id: "degens_01"}) RETURN count(d) AS c',
            cid=cycle_id,
        )
        record = await result.single()
        assert record["c"] == 1


async def test_persist_round_empty_citations_still_persists(
    graph_manager_test: GraphStateManager, all_personas: list[AgentPersona]
) -> None:
    """Decisions with empty cited_agents still persist. Zero CITED relationships."""
    cycle_id = await _new_cycle(graph_manager_test, "Empty citations test")

    decisions = [
        (
            f"quants_{i:02d}",
            AgentDecision(
                signal=SignalType.HOLD,
                confidence=0.5,
                sentiment=0.0,
                rationale="no citations",
                cited_agents=[],
            ),
        )
        for i in range(1, 6)
    ]

    await write_round(graph_manager_test, cycle_id, 1, decisions)

    async with graph_manager_test._driver.session(database="neo4j") as session:
        # All 5 decisions exist
        result = await session.run(
            "MATCH (d:Decision {cycle_id: $cid}) RETURN count(d) AS c",
            cid=cycle_id,
        )
        record = await result.single()
        assert record["c"] == 5

        # Zero CITED relationships
        result = await session.run(
            "MATCH (d:Decision {cycle_id: $cid})-[r:CITED]->() RETURN count(r) AS c",
            cid=cycle_id,
        )
        record = await result.single()
        assert record["c"] == 0


# ---------------------------------------------------------------------------
# Phase 11 Plan 03: Complete reasoning arc integration tests (SC-3, GRAPH-03, D-10)
# ---------------------------------------------------------------------------


async def test_complete_reasoning_arc(
    graph_manager_test: GraphStateManager, all_personas: list[AgentPersona], sample_seed_event
) -> None:
    """After writing decisions and episodes for 3 rounds, a Cypher query returns
    a complete reasoning arc for any agent: decisions, rationale episodes,
    influence relationships, and entity references (SC-3)."""
    from alphaswarm.types import SignalType

    # 1. Create cycle with seed event (Entity nodes created via MENTIONS edges)
    cycle_id = await graph_manager_test.create_cycle_with_seed_event(
        sample_seed_event.raw_rumor,
        sample_seed_event,
        num_rounds=3,
    )

    # 2. Write decisions and episodes for 3 rounds (use first 3 personas for speed)
    test_personas = all_personas[:3]
    entities = await graph_manager_test.read_cycle_entities(cycle_id)
    previous: list[tuple[str, AgentDecision]] | None = None

    for round_num in range(1, 4):
        decisions = [
            (
                p.id,
                AgentDecision(
                    signal=SignalType.BUY if round_num < 3 else SignalType.SELL,
                    confidence=0.8,
                    sentiment=0.5,
                    rationale=f"NVIDIA looks strong in round {round_num}",
                    cited_agents=[],
                ),
            )
            for p in test_personas
        ]
        # 3. One persist_round per round: decisions, episodes and REFERENCES
        await write_round(
            graph_manager_test,
            cycle_id,
            round_num,
            decisions,
            prev=previous,
            entities=entities,
            peer_context="Peer context here",  # stored as "" in round 1
        )
        previous = decisions

    # 4. Query complete reasoning arc for first agent
    agent_id = test_personas[0].id
    async with graph_manager_test._driver.session(database="neo4j") as session:
        result = await session.run(
            """
            MATCH (a:Agent {id: $agent_id})-[:MADE]->(d:Decision)-[:HAS_EPISODE]->(re:RationaleEpisode)
            WHERE d.cycle_id = $cycle_id
            OPTIONAL MATCH (d)-[:REFERENCES]->(e:Entity)
            RETURN d.round AS round,
                   d.signal AS signal,
                   d.rationale AS rationale,
                   re.peer_context_received AS peer_context,
                   re.flip_type AS flip_type,
                   collect(DISTINCT e.name) AS referenced_entities
            ORDER BY d.round
            """,
            agent_id=agent_id,
            cycle_id=cycle_id,
        )
        records_list = [dict(record) async for record in result]

    # 5. Assertions
    assert len(records_list) == 3, f"Expected 3 rounds, got {len(records_list)}"
    # Round 1: no flip, no peer context
    assert records_list[0]["round"] == 1
    assert records_list[0]["flip_type"] == "none"
    assert records_list[0]["peer_context"] == ""
    # Round 3: BUY_TO_SELL flip
    assert records_list[2]["round"] == 3
    assert records_list[2]["flip_type"] == "buy_to_sell"
    # Entity references: "NVIDIA" should be in referenced_entities (Round 1 rationale mentions NVIDIA)
    assert "NVIDIA" in records_list[0]["referenced_entities"]


async def test_references_edges_case_insensitive(
    graph_manager_test: GraphStateManager, all_personas: list[AgentPersona], sample_seed_event
) -> None:
    """REFERENCES edges match entity names case-insensitively (D-08).

    Entity stored as 'NVIDIA', rationale mentions 'nvidia' lowercase.
    """
    from alphaswarm.types import SignalType

    cycle_id = await graph_manager_test.create_cycle_with_seed_event(
        sample_seed_event.raw_rumor,
        sample_seed_event,
        num_rounds=3,
    )
    decisions = [
        (
            all_personas[0].id,
            AgentDecision(
                signal=SignalType.BUY,
                confidence=0.9,
                sentiment=0.7,
                rationale="i think nvidia will dominate the market",  # lowercase match
                cited_agents=[],
            ),
        )
    ]
    entities = await graph_manager_test.read_cycle_entities(cycle_id)
    ids = await write_round(graph_manager_test, cycle_id, 1, decisions, entities=entities)

    # Verify REFERENCES edge exists with original entity casing preserved
    async with graph_manager_test._driver.session(database="neo4j") as session:
        result = await session.run(
            """
            MATCH (d:Decision)-[:REFERENCES]->(e:Entity)
            WHERE d.decision_id = $did
            RETURN e.name AS entity_name
            """,
            did=ids[0],
        )
        entities = [dict(r)["entity_name"] async for r in result]
    assert "NVIDIA" in entities  # Original casing preserved, not "nvidia"
