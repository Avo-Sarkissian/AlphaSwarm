"""persist_round against neo4j-test: atomic, counted, error_kind persisted (docs/DECISIONS.md#p4-d-08)."""

from __future__ import annotations

from typing import Any

import pytest
from neo4j import AsyncDriver

from alphaswarm.episodes import EpisodeRecord, match_entities, new_decision_ids
from alphaswarm.errors import Neo4jWriteError
from alphaswarm.graph import GraphStateManager, PersistRoundResult
from alphaswarm.types import AgentDecision, AgentPersona, EntityType, SeedEntity, SeedEvent, SignalType
from tests.conftest import NEO4J_TEST_DATABASE
from tests.support.mini_cycle import cypher

pytestmark = pytest.mark.neo4j

RUMOR = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."
SEED = SeedEvent(
    raw_rumor=RUMOR,
    entities=[SeedEntity(name="ZZZT Holdings", type=EntityType.COMPANY, relevance=0.9, sentiment=0.5)],
    overall_sentiment=0.4,
)


async def _count(driver: AsyncDriver, query: str, **params: Any) -> int:
    async with driver.session(database=NEO4J_TEST_DATABASE) as session:
        result = await session.run(query, **params)
        record = await result.single()
        return int(record["n"]) if record else 0


def _episodes(
    cycle_id: str,
    round_num: int,
    ids: list[str],
    decisions: list[tuple[str, AgentDecision]],
) -> list[EpisodeRecord]:
    return [
        EpisodeRecord(did, aid, d.rationale, "", "none", round_num, cycle_id)
        for did, (aid, d) in zip(ids, decisions, strict=True)
    ]


async def test_persist_round_writes_the_whole_round(
    graph_manager_test: GraphStateManager,
    neo4j_test_driver: AsyncDriver,
    all_personas: list[AgentPersona],
) -> None:
    gm = graph_manager_test
    cycle_id = await gm.create_cycle_with_seed_event(RUMOR, SEED, num_rounds=3)
    entities = await gm.read_cycle_entities(cycle_id)
    n = len(all_personas)
    decisions = [
        (
            p.id,
            AgentDecision(
                signal=SignalType.BUY,
                confidence=0.7,
                rationale=f"ZZZT Holdings looks accretive ({p.id})",
                cited_agents=[all_personas[(i + 1) % n].id],
            ),
        )
        for i, p in enumerate(all_personas)
    ]
    ids = new_decision_ids(n)
    episodes = _episodes(cycle_id, 1, ids, decisions)

    result = await gm.persist_round(
        cycle_id,
        1,
        decisions,
        decision_ids=ids,
        episodes=episodes,
        entity_matches=match_entities(episodes, entities),
    )

    assert result == PersistRoundResult(tuple(ids), n, n, n, 0, n)
    q = "MATCH (d:Decision {cycle_id: $cid, round: 1})"
    assert await _count(neo4j_test_driver, f"{q} RETURN count(d) AS n", cid=cycle_id) == n
    assert await _count(neo4j_test_driver, f"{q}-[:HAS_EPISODE]->(e) RETURN count(e) AS n", cid=cycle_id) == n
    assert await _count(neo4j_test_driver, f"{q}-[r:CITED]->() RETURN count(r) AS n", cid=cycle_id) == n
    assert await _count(neo4j_test_driver, f"{q}-[r:REFERENCES]->() RETURN count(r) AS n", cid=cycle_id) == n
    assert await _count(neo4j_test_driver, f"{q} WHERE d.control = false RETURN count(d) AS n", cid=cycle_id) == n


async def test_persist_round_rolls_back_when_an_agent_is_missing(
    graph_manager_test: GraphStateManager,
    neo4j_test_driver: AsyncDriver,
    all_personas: list[AgentPersona],
) -> None:
    gm = graph_manager_test
    cycle_id = await gm.create_cycle_with_seed_event(RUMOR, SEED, num_rounds=3)
    decisions = [
        (all_personas[0].id, AgentDecision(signal=SignalType.HOLD, confidence=0.5, rationale="ok")),
        ("ghost_99", AgentDecision(signal=SignalType.HOLD, confidence=0.5, rationale="ghost")),
    ]
    ids = new_decision_ids(2)
    with pytest.raises(Neo4jWriteError) as exc_info:
        await gm.persist_round(
            cycle_id,
            1,
            decisions,
            decision_ids=ids,
            episodes=_episodes(cycle_id, 1, ids, decisions),
            entity_matches=[],
        )
    assert exc_info.value.op == "persist_round"
    assert (
        await _count(
            neo4j_test_driver,
            "MATCH (d:Decision {cycle_id: $cid}) RETURN count(d) AS n",
            cid=cycle_id,
        )
        == 0
    )


async def test_unknown_citation_is_dropped_not_raised(
    graph_manager_test: GraphStateManager,
    all_personas: list[AgentPersona],
) -> None:
    gm = graph_manager_test
    cycle_id = await gm.create_cycle_with_seed_event(RUMOR, SEED, num_rounds=3)
    decisions = [
        (
            all_personas[0].id,
            AgentDecision(
                signal=SignalType.BUY,
                confidence=0.6,
                rationale="x",
                cited_agents=["ghost_99", all_personas[1].id],
            ),
        )
    ]
    ids = new_decision_ids(1)
    result = await gm.persist_round(
        cycle_id,
        2,
        decisions,
        decision_ids=ids,
        episodes=_episodes(cycle_id, 2, ids, decisions),
        entity_matches=[],
    )
    assert (result.citations_written, result.citations_dropped) == (1, 1)


async def test_error_kind_is_persisted(
    graph_manager_test: GraphStateManager,
    neo4j_test_driver: AsyncDriver,
    all_personas: list[AgentPersona],
) -> None:
    gm = graph_manager_test
    cycle_id = await gm.create_cycle_with_seed_event(RUMOR, SEED, num_rounds=3)
    decisions = [
        (
            all_personas[0].id,
            AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0, error_kind="inference"),
        ),
        (all_personas[1].id, AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0, error_kind="parse")),
        (all_personas[2].id, AgentDecision(signal=SignalType.SELL, confidence=0.4)),
    ]
    ids = new_decision_ids(3)
    await gm.persist_round(
        cycle_id,
        1,
        decisions,
        decision_ids=ids,
        episodes=_episodes(cycle_id, 1, ids, decisions),
        entity_matches=[],
    )
    async with neo4j_test_driver.session(database=NEO4J_TEST_DATABASE) as session:
        result = await session.run(
            "MATCH (d:Decision {cycle_id: $cid}) RETURN d.decision_id AS id, d.error_kind AS kind",
            cid=cycle_id,
        )
        kinds = {r["id"]: r["kind"] async for r in result}
    assert kinds == {ids[0]: "inference", ids[1]: "parse", ids[2]: None}


async def test_persist_round_writes_parse_tier(graph_manager_test: GraphStateManager) -> None:
    gm = graph_manager_test
    cycle_id = await gm.create_cycle_with_seed_event(RUMOR, SEED, num_rounds=3)
    decisions = [
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.6, parse_tier=1)),
        ("quants_02", AgentDecision(signal=SignalType.SELL, confidence=0.4, parse_tier=2)),
        (
            "quants_03",
            AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0, error_kind="parse", parse_tier=3),
        ),
        ("quants_04", AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0, error_kind="inference")),
    ]
    await gm.persist_round(
        cycle_id,
        1,
        decisions,
        decision_ids=new_decision_ids(len(decisions)),
        episodes=[],
        entity_matches=[],
    )
    rows = await cypher(
        gm,
        "MATCH (a:Agent)-[:MADE]->(d:Decision {cycle_id: $cid}) RETURN a.id AS id, d.parse_tier AS tier",
        cid=cycle_id,
    )
    assert {r["id"]: r["tier"] for r in rows} == {
        "quants_01": 1,
        "quants_02": 2,
        "quants_03": 3,
        "quants_04": None,
    }
