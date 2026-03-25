"""Integration tests for GraphStateManager against real Neo4j.

Requires: docker compose up -d
Skip: Automatically skipped if Neo4j is not available.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import TYPE_CHECKING

import pytest

from alphaswarm.types import AgentDecision, SignalType

if TYPE_CHECKING:
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.types import AgentPersona


@pytest.mark.asyncio()
async def test_ensure_schema_idempotent(graph_manager: GraphStateManager) -> None:
    """ensure_schema can be called twice without errors. Constraints and indexes exist."""
    # graph_manager fixture already called ensure_schema once; call again
    await graph_manager.ensure_schema()

    async with graph_manager._driver.session(database="neo4j") as session:
        # Verify constraints
        result = await session.run("SHOW CONSTRAINTS")
        constraints = [dict(record) async for record in result]
        constraint_names = [c["name"] for c in constraints]
        assert "agent_id_unique" in constraint_names
        assert "cycle_id_unique" in constraint_names

        # Verify indexes
        result = await session.run("SHOW INDEXES")
        indexes = [dict(record) async for record in result]
        index_names = [idx["name"] for idx in indexes]
        assert "decision_cycle_round" in index_names
        assert "agent_id_idx" in index_names
        assert "decision_id_idx" in index_names


@pytest.mark.asyncio()
async def test_seed_agents_creates_100_nodes(graph_manager: GraphStateManager) -> None:
    """ensure_schema seeds all 100 agents."""
    async with graph_manager._driver.session(database="neo4j") as session:
        result = await session.run("MATCH (a:Agent) RETURN count(a) AS c")
        record = await result.single()
        assert record["c"] == 100


@pytest.mark.asyncio()
async def test_seed_agents_idempotent(
    graph_manager: GraphStateManager, all_personas: list[AgentPersona]
) -> None:
    """Calling seed_agents again does not create duplicates (MERGE)."""
    await graph_manager.seed_agents(all_personas)

    async with graph_manager._driver.session(database="neo4j") as session:
        result = await session.run("MATCH (a:Agent) RETURN count(a) AS c")
        record = await result.single()
        assert record["c"] == 100


@pytest.mark.asyncio()
async def test_create_cycle_returns_uuid(graph_manager: GraphStateManager) -> None:
    """create_cycle returns a valid uuid4 and persists the Cycle node."""
    cycle_id = await graph_manager.create_cycle("Test rumor")

    uuid4_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    assert re.match(uuid4_pattern, cycle_id), f"Not a valid UUID4: {cycle_id}"

    async with graph_manager._driver.session(database="neo4j") as session:
        result = await session.run(
            "MATCH (c:Cycle {cycle_id: $cid}) RETURN c.seed_rumor AS sr",
            cid=cycle_id,
        )
        record = await result.single()
        assert record is not None
        assert record["sr"] == "Test rumor"


@pytest.mark.asyncio()
async def test_batch_write_100_decisions(
    graph_manager: GraphStateManager, all_personas: list[AgentPersona]
) -> None:
    """write_decisions persists 100 Decision nodes in a single batch."""
    cycle_id = await graph_manager.create_cycle("Batch write test")

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

    await graph_manager.write_decisions(decisions, cycle_id, 1)

    async with graph_manager._driver.session(database="neo4j") as session:
        result = await session.run(
            "MATCH (d:Decision {cycle_id: $cid}) RETURN count(d) AS c",
            cid=cycle_id,
        )
        record = await result.single()
        assert record["c"] == 100


@pytest.mark.asyncio()
async def test_write_decisions_creates_cited_relationships(
    graph_manager: GraphStateManager, all_personas: list[AgentPersona]
) -> None:
    """write_decisions creates CITED relationships when cited_agents is non-empty."""
    cycle_id = await graph_manager.create_cycle("Citation test")

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

    await graph_manager.write_decisions(decisions, cycle_id, 1)

    async with graph_manager._driver.session(database="neo4j") as session:
        result = await session.run(
            'MATCH (d:Decision)-[:CITED]->(a:Agent {id: "degens_01"}) RETURN count(d) AS c'
        )
        record = await result.single()
        assert record["c"] == 1


@pytest.mark.asyncio()
async def test_write_decisions_empty_citations_still_persists(
    graph_manager: GraphStateManager, all_personas: list[AgentPersona]
) -> None:
    """Decisions with empty cited_agents still persist. Zero CITED relationships."""
    cycle_id = await graph_manager.create_cycle("Empty citations test")

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

    await graph_manager.write_decisions(decisions, cycle_id, 1)

    async with graph_manager._driver.session(database="neo4j") as session:
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


@pytest.mark.asyncio()
async def test_read_peer_decisions_top5(
    graph_manager: GraphStateManager, all_personas: list[AgentPersona]
) -> None:
    """read_peer_decisions returns top-5 peers by influence_weight_base, excluding self."""
    cycle_id = await graph_manager.create_cycle("Peer read test")

    decisions = [
        (
            persona.id,
            AgentDecision(
                signal=SignalType.BUY,
                confidence=0.7,
                sentiment=0.3,
                rationale="test read",
                cited_agents=[],
            ),
        )
        for persona in all_personas
    ]

    await graph_manager.write_decisions(decisions, cycle_id, 1)

    peers = await graph_manager.read_peer_decisions("quants_01", cycle_id, 1, limit=5)

    assert len(peers) == 5
    # None should be the requesting agent
    assert all(p.agent_id != "quants_01" for p in peers)
    # Ordered by influence_weight_base DESC: Sovereigns (0.9) first
    assert peers[0].bracket == "sovereigns"


@pytest.mark.asyncio()
async def test_peer_read_latency(
    graph_manager: GraphStateManager, all_personas: list[AgentPersona]
) -> None:
    """read_peer_decisions averages under 5ms over 10 iterations (INFRA-05)."""
    cycle_id = await graph_manager.create_cycle("Latency test")

    decisions = [
        (
            persona.id,
            AgentDecision(
                signal=SignalType.HOLD,
                confidence=0.5,
                sentiment=0.0,
                rationale="latency test",
                cited_agents=[],
            ),
        )
        for persona in all_personas
    ]
    await graph_manager.write_decisions(decisions, cycle_id, 1)

    # Warm-up read
    await graph_manager.read_peer_decisions("quants_01", cycle_id, 1, limit=5)

    # Timed reads
    durations: list[float] = []
    for _ in range(10):
        start = time.perf_counter()
        await graph_manager.read_peer_decisions("quants_01", cycle_id, 1, limit=5)
        durations.append(time.perf_counter() - start)

    avg_ms = (sum(durations) / len(durations)) * 1000
    assert avg_ms < 5.0, f"Average peer read latency {avg_ms:.2f}ms exceeds 5ms"


@pytest.mark.asyncio()
async def test_concurrent_peer_reads(
    graph_manager: GraphStateManager, all_personas: list[AgentPersona]
) -> None:
    """10 concurrent read_peer_decisions calls all return correct data (D-07)."""
    cycle_id = await graph_manager.create_cycle("Concurrent read test")

    decisions = [
        (
            persona.id,
            AgentDecision(
                signal=SignalType.BUY,
                confidence=0.7,
                sentiment=0.3,
                rationale="concurrent test",
                cited_agents=[],
            ),
        )
        for persona in all_personas
    ]
    await graph_manager.write_decisions(decisions, cycle_id, 1)

    agent_ids = [f"quants_{i:02d}" for i in range(1, 11)]

    results = await asyncio.gather(
        *[
            graph_manager.read_peer_decisions(aid, cycle_id, 1, limit=5)
            for aid in agent_ids
        ]
    )

    assert len(results) == 10
    for peers in results:
        assert len(peers) == 5
