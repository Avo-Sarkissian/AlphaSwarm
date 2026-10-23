"""REFERENCES are typed and scoped to the cycle's own entities (docs/DECISIONS.md#p11-d-08)."""

from __future__ import annotations

import pytest

from alphaswarm.episodes import EpisodeRecord, match_entities, new_decision_ids
from alphaswarm.graph import GraphStateManager
from alphaswarm.types import EntityType, SeedEntity, SeedEvent, SignalType
from tests.support.mini_cycle import MINI_RUMOR, cypher, dec, write_mini_cycle

pytestmark = pytest.mark.neo4j


async def test_references_link_only_the_cycles_typed_entity(
    graph_manager_test: GraphStateManager,
) -> None:
    await write_mini_cycle(
        graph_manager_test,
        num_rounds=2,
        rounds={1: [("macro_01", dec(SignalType.HOLD, rationale="no entity here"))]},
        entities=[SeedEntity(name="ZZZT Holdings", type=EntityType.SECTOR, relevance=0.5, sentiment=0.0)],
    )
    cycle_id = await write_mini_cycle(
        graph_manager_test,
        num_rounds=2,
        rounds={1: [("quants_01", dec(SignalType.BUY, rationale="ZZZT Holdings looks cheap"))]},
        entities=[SeedEntity(name="ZZZT Holdings", type=EntityType.COMPANY, relevance=0.9, sentiment=0.5)],
    )

    rows = await cypher(
        graph_manager_test,
        "MATCH (:Decision {cycle_id: $id})-[r:REFERENCES]->(e:Entity) "
        "RETURN e.name AS name, e.type AS type, r.match_type AS match_type",
        id=cycle_id,
    )

    assert rows == [{"name": "ZZZT Holdings", "type": "company", "match_type": "token"}]


async def test_said_does_not_reference_ai(graph_manager_test: GraphStateManager) -> None:
    cycle_id = await write_mini_cycle(
        graph_manager_test,
        num_rounds=2,
        rounds={1: [("quants_01", dec(SignalType.BUY, rationale="She said again it closes"))]},
        entities=[SeedEntity(name="AI", type=EntityType.SECTOR, relevance=0.5, sentiment=0.1)],
    )

    rows = await cypher(
        graph_manager_test,
        "MATCH (:Decision {cycle_id: $id})-[r:REFERENCES]->() RETURN count(r) AS n",
        id=cycle_id,
    )

    assert rows == [{"n": 0}]


async def test_entity_listed_twice_gets_one_reference_per_decision(
    graph_manager_test: GraphStateManager,
) -> None:
    # A seed that lists an entity twice leaves two MENTIONS edges to one node;
    # each decision must still get exactly one REFERENCES edge, and the count
    # persist_round reports must equal the edges written.
    zzzt = SeedEntity(name="ZZZT Holdings", type=EntityType.COMPANY, relevance=0.9, sentiment=0.5)
    cycle_id = await graph_manager_test.create_cycle_with_seed_event(
        MINI_RUMOR,
        SeedEvent(raw_rumor=MINI_RUMOR, entities=[zzzt, zzzt], overall_sentiment=0.3),
        num_rounds=2,
    )
    entities = await graph_manager_test.read_cycle_entities(cycle_id)
    decisions = [
        ("quants_01", dec(SignalType.BUY, rationale="ZZZT Holdings looks cheap")),
        ("macro_01", dec(SignalType.HOLD, rationale="zzzt holdings is fairly priced")),
    ]
    ids = new_decision_ids(len(decisions))
    episodes = [
        EpisodeRecord(
            decision_id=did,
            agent_id=agent_id,
            rationale=d.rationale,
            peer_context_received="",
            flip_type="none",
            round_num=1,
            cycle_id=cycle_id,
        )
        for did, (agent_id, d) in zip(ids, decisions, strict=True)
    ]

    summary = await graph_manager_test.persist_round(
        cycle_id,
        1,
        decisions,
        decision_ids=ids,
        episodes=episodes,
        entity_matches=match_entities(episodes, entities),
    )

    rows = await cypher(
        graph_manager_test,
        "MATCH (a:Agent)-[:MADE]->(d:Decision {cycle_id: $id})-[r:REFERENCES]->(:Entity) "
        "RETURN a.id AS agent, count(r) AS n ORDER BY agent",
        id=cycle_id,
    )
    assert rows == [{"agent": "macro_01", "n": 1}, {"agent": "quants_01", "n": 1}]
    assert summary.references_written == 2
