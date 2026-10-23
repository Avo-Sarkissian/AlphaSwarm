"""Write-path behaviour against neo4j-test (replaces tests that only matched Cypher text)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from alphaswarm.episodes import EpisodeRecord
from alphaswarm.types import AgentDecision, EntityType, SeedEntity, SeedEvent, SignalType
from tests.conftest import NEO4J_TEST_DATABASE

if TYPE_CHECKING:
    from neo4j import AsyncDriver

    from alphaswarm.graph import GraphStateManager

pytestmark = pytest.mark.neo4j

_RUMOR = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."
_EVENT = SeedEvent(
    raw_rumor=_RUMOR,
    entities=[SeedEntity(name="ZZZT Holdings", type=EntityType.COMPANY, relevance=0.95, sentiment=0.6)],
    overall_sentiment=0.45,
)


def _decision(signal: SignalType, cited: tuple[str, ...] = (), rationale: str = "r") -> AgentDecision:
    return AgentDecision(signal=signal, confidence=0.5, sentiment=0.0, rationale=rationale, cited_agents=list(cited))


async def _rows(driver: AsyncDriver, query: str, **params: object) -> list[dict[str, object]]:
    async with driver.session(database=NEO4J_TEST_DATABASE) as session:
        result = await session.run(query, **params)
        return [dict(record) async for record in result]


async def test_cycle_with_seed_event_stores_sentiment_and_mention_properties(
    graph_manager_test: GraphStateManager, neo4j_test_driver: AsyncDriver
) -> None:
    cycle_id = await graph_manager_test.create_cycle_with_seed_event(_RUMOR, _EVENT, num_rounds=3)
    rows = await _rows(
        neo4j_test_driver,
        "MATCH (c:Cycle {cycle_id: $cid})-[m:MENTIONS]->(e:Entity) "
        "RETURN c.overall_sentiment AS overall, c.seed_rumor AS rumor, "
        "m.relevance AS relevance, m.sentiment AS sentiment, e.name AS name, e.type AS type",
        cid=cycle_id,
    )
    assert rows == [
        {
            "overall": 0.45,
            "rumor": _RUMOR,
            "relevance": 0.95,
            "sentiment": 0.6,
            "name": "ZZZT Holdings",
            "type": "company",
        }
    ]


async def test_influence_edges_skip_self_citations_and_collapse_duplicates(
    graph_manager_test: GraphStateManager, neo4j_test_driver: AsyncDriver
) -> None:
    cycle_id = await graph_manager_test.create_cycle_with_seed_event(_RUMOR, _EVENT, num_rounds=3)
    decisions = [
        ("quants_01", _decision(SignalType.BUY, ("quants_01", "sell_side_01", "sell_side_01"))),
        ("degens_01", _decision(SignalType.SELL, ("sell_side_01",))),
        ("sell_side_01", _decision(SignalType.HOLD)),
    ]
    await graph_manager_test.write_decisions(decisions, cycle_id, 2)
    weights = await graph_manager_test.compute_influence_edges(cycle_id, up_to_round=2, total_agents=3)
    assert weights == {"sell_side_01": pytest.approx(2 / 3)}
    rows = await _rows(
        neo4j_test_driver,
        "MATCH (s:Agent)-[e:INFLUENCED_BY {cycle_id: $cid}]->(t:Agent) "
        "RETURN s.id AS source, t.id AS target, e.round AS round, e.weight AS weight "
        "ORDER BY source",
        cid=cycle_id,
    )
    assert rows == [
        {
            "source": "degens_01",
            "target": "sell_side_01",
            "round": 2,
            "weight": pytest.approx(2 / 3),
        },
        {
            "source": "quants_01",
            "target": "sell_side_01",
            "round": 2,
            "weight": pytest.approx(2 / 3),
        },
    ]


async def test_influence_edges_are_cumulative_and_stamped_per_round(
    graph_manager_test: GraphStateManager, neo4j_test_driver: AsyncDriver
) -> None:
    cycle_id = await graph_manager_test.create_cycle_with_seed_event(_RUMOR, _EVENT, num_rounds=3)
    await graph_manager_test.write_decisions([("quants_01", _decision(SignalType.BUY, ("macro_01",)))], cycle_id, 2)
    await graph_manager_test.compute_influence_edges(cycle_id, up_to_round=2, total_agents=4)
    await graph_manager_test.write_decisions([("degens_01", _decision(SignalType.SELL, ("macro_01",)))], cycle_id, 3)
    weights = await graph_manager_test.compute_influence_edges(cycle_id, up_to_round=3, total_agents=4)
    assert weights == {"macro_01": pytest.approx(2 / 4)}
    rows = await _rows(
        neo4j_test_driver,
        "MATCH (s:Agent)-[e:INFLUENCED_BY {cycle_id: $cid}]->(:Agent {id: 'macro_01'}) "
        "RETURN e.round AS round, s.id AS source ORDER BY round, source",
        cid=cycle_id,
    )
    assert [(r["round"], r["source"]) for r in rows] == [
        (2, "quants_01"),
        (3, "degens_01"),
        (3, "quants_01"),
    ]


async def test_rationale_episodes_are_stamped_from_each_record(
    graph_manager_test: GraphStateManager, neo4j_test_driver: AsyncDriver
) -> None:
    cycle_id = await graph_manager_test.create_cycle_with_seed_event(_RUMOR, _EVENT, num_rounds=3)
    first = await graph_manager_test.write_decisions([("quants_01", _decision(SignalType.BUY))], cycle_id, 1)
    second = await graph_manager_test.write_decisions([("quants_01", _decision(SignalType.SELL))], cycle_id, 2)
    records = [
        EpisodeRecord(first[0], "quants_01", "r", "", "none", 1, cycle_id),
        EpisodeRecord(second[0], "quants_01", "r", "peers", "buy_to_sell", 2, cycle_id),
    ]
    await graph_manager_test.write_rationale_episodes(records)  # one batch, two rounds
    rows = await _rows(
        neo4j_test_driver,
        "MATCH (d:Decision {cycle_id: $cid})-[:HAS_EPISODE]->(re:RationaleEpisode) "
        "RETURN d.round AS decision_round, re.round AS round, re.cycle_id AS cycle, "
        "re.flip_type AS flip ORDER BY round",
        cid=cycle_id,
    )
    assert rows == [
        {"decision_round": 1, "round": 1, "cycle": cycle_id, "flip": "none"},
        {"decision_round": 2, "round": 2, "cycle": cycle_id, "flip": "buy_to_sell"},
    ]


async def test_narrative_edges_link_decisions_case_insensitively(
    graph_manager_test: GraphStateManager, neo4j_test_driver: AsyncDriver
) -> None:
    cycle_id = await graph_manager_test.create_cycle_with_seed_event(_RUMOR, _EVENT, num_rounds=3)
    ids = await graph_manager_test.write_decisions(
        [("quants_01", _decision(SignalType.BUY, rationale="zzzt holdings looks cheap"))],
        cycle_id,
        1,
    )
    record = EpisodeRecord(ids[0], "quants_01", "zzzt holdings looks cheap", "", "none", 1, cycle_id)
    await graph_manager_test.write_narrative_edges([record], ["ZZZT Holdings"])
    rows = await _rows(
        neo4j_test_driver,
        "MATCH (d:Decision {decision_id: $did})-[r:REFERENCES]->(e:Entity) "
        "RETURN e.name AS name, r.match_type AS match_type",
        did=ids[0],
    )
    assert rows == [{"name": "ZZZT Holdings", "match_type": "substring"}]
