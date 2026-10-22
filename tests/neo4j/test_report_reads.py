"""Report read models against real Cypher: final-round resolution and parse-error counts."""

from __future__ import annotations

import pytest

from alphaswarm.graph import GraphStateManager
from alphaswarm.types import EntityType, SeedEntity, SignalType
from tests.support.mini_cycle import cypher, dec, write_mini_cycle

pytestmark = pytest.mark.neo4j

BUY, SELL, HOLD, PERR = SignalType.BUY, SignalType.SELL, SignalType.HOLD, SignalType.PARSE_ERROR
ZERO_SUMMARY = {
    "buy_count": 0,
    "sell_count": 0,
    "hold_count": 0,
    "parse_error_count": 0,
    "total": 0,
}


async def _two_round_cycle(gm: GraphStateManager) -> str:
    return await write_mini_cycle(
        gm,
        num_rounds=2,
        rounds={
            1: [("quants_01", dec(SELL)), ("quants_02", dec(SELL)), ("quants_03", dec(SELL))],
            2: [("quants_01", dec(BUY)), ("quants_02", dec(HOLD)), ("quants_03", dec(PERR, 0.0))],
        },
    )


async def test_consensus_counts_final_round_with_parse_errors(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await _two_round_cycle(graph_manager_test)

    summary = await graph_manager_test.read_consensus_summary(cycle_id)

    assert summary == {
        "buy_count": 1,
        "sell_count": 0,
        "hold_count": 1,
        "parse_error_count": 1,
        "total": 3,
    }


async def test_round_timeline_counts_parse_errors(graph_manager_test: GraphStateManager) -> None:
    cycle_id = await _two_round_cycle(graph_manager_test)

    timeline = await graph_manager_test.read_round_timeline(cycle_id)

    assert timeline == [
        {
            "round_num": 1,
            "buy_count": 0,
            "sell_count": 3,
            "hold_count": 0,
            "parse_error_count": 0,
            "total": 3,
        },
        {
            "round_num": 2,
            "buy_count": 1,
            "sell_count": 0,
            "hold_count": 1,
            "parse_error_count": 1,
            "total": 3,
        },
    ]


async def test_legacy_cycle_without_num_rounds_defaults_to_round_3(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await write_mini_cycle(
        graph_manager_test,
        num_rounds=3,
        rounds={
            1: [("quants_01", dec(BUY))],
            2: [("quants_01", dec(BUY))],
            3: [("quants_01", dec(SELL))],
        },
    )
    await cypher(
        graph_manager_test,
        "MATCH (c:Cycle {cycle_id: $id}) REMOVE c.num_rounds",
        id=cycle_id,
    )

    summary = await graph_manager_test.read_consensus_summary(cycle_id)

    assert summary == {**ZERO_SUMMARY, "sell_count": 1, "total": 1}


async def test_unknown_cycle_returns_zero_summary(graph_manager_test: GraphStateManager) -> None:
    summary = await graph_manager_test.read_consensus_summary(
        "00000000-0000-4000-8000-00000000dead",
    )

    assert summary == ZERO_SUMMARY


async def test_all_failed_bracket_has_no_majority_and_no_dissenters(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await write_mini_cycle(
        graph_manager_test,
        num_rounds=2,
        rounds={
            1: [("quants_01", dec(BUY)), ("degens_01", dec(BUY))],
            2: [
                ("quants_01", dec(PERR, 0.0)),
                ("quants_02", dec(PERR, 0.0)),
                ("degens_01", dec(BUY)),
                ("degens_02", dec(BUY)),
                ("degens_03", dec(SELL)),
            ],
        },
    )

    narratives = await graph_manager_test.read_bracket_narratives(cycle_id)
    dissenters = await graph_manager_test.read_key_dissenters(cycle_id)

    assert [r["bracket"] for r in narratives] == ["quants", "degens"]  # config order
    assert narratives[0] == {
        "bracket": "quants",
        "display_name": "Quants",
        "buy_count": 0,
        "sell_count": 0,
        "hold_count": 0,
        "total": 0,
        "avg_confidence": 0.0,
        "avg_sentiment": 0.0,
        "majority": None,
    }
    assert narratives[1] == {
        "bracket": "degens",
        "display_name": "Degens",
        "buy_count": 2,
        "sell_count": 1,
        "hold_count": 0,
        "total": 3,
        "avg_confidence": pytest.approx(0.7),
        "avg_sentiment": pytest.approx(0.1),
        "majority": "BUY",
    }
    assert dissenters == [
        {
            "agent_id": "degens_03",
            "name": "Degens 3",
            "bracket": "degens",
            "signal": "SELL",
            "bracket_majority": "BUY",
        }
    ]


async def test_majority_tie_break_is_buy_then_sell_then_hold(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await write_mini_cycle(
        graph_manager_test,
        num_rounds=2,
        rounds={
            1: [("macro_01", dec(HOLD))],
            2: [("macro_01", dec(SELL)), ("macro_02", dec(HOLD)), ("shorts_01", dec(HOLD))],
        },
    )

    rows = await graph_manager_test.read_bracket_narratives(cycle_id)
    narratives = {r["bracket"]: r for r in rows}

    assert narratives["macro"]["majority"] == "SELL"  # SELL 1 vs HOLD 1 -> SELL
    assert narratives["shorts"]["majority"] == "HOLD"


async def test_influence_share_is_citations_over_active_final_round(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await write_mini_cycle(
        graph_manager_test,
        num_rounds=2,
        rounds={
            1: [
                ("sell_side_01", dec(BUY)),
                ("narrators_01", dec(BUY)),
                ("quants_01", dec(BUY)),
                ("quants_02", dec(SELL)),
                ("degens_01", dec(HOLD)),
            ],
            2: [
                ("sell_side_01", dec(BUY)),
                ("narrators_01", dec(BUY)),
                ("quants_01", dec(BUY, cited=["sell_side_01", "narrators_01"])),
                ("quants_02", dec(BUY, cited=["sell_side_01"])),
                ("degens_01", dec(PERR, 0.0)),
            ],
        },
    )

    leaders = await graph_manager_test.read_influence_leaders(cycle_id)

    assert leaders == [
        {
            "agent_id": "sell_side_01",
            "name": "Sell-Side 1",
            "bracket": "sell_side",
            "citation_count": 2,
            "influence_share": pytest.approx(0.5),
        },
        {
            "agent_id": "narrators_01",
            "name": "Narrators 1",
            "bracket": "narrators",
            "citation_count": 1,
            "influence_share": pytest.approx(0.25),
        },
    ]


async def test_signal_flips_are_ordered_and_uppercase(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await write_mini_cycle(
        graph_manager_test,
        num_rounds=2,
        rounds={
            1: [("quants_02", dec(BUY)), ("quants_01", dec(BUY)), ("degens_01", dec(HOLD))],
            2: [("quants_02", dec(SELL)), ("quants_01", dec(HOLD)), ("degens_01", dec(HOLD))],
        },
    )

    flips = await graph_manager_test.read_signal_flips(cycle_id)

    assert flips == [
        {
            "agent_id": "quants_01",
            "name": "Quants 1",
            "bracket": "quants",
            "round_num": 2,
            "flip_type": "buy_to_hold",
            "final_signal": "HOLD",
        },
        {
            "agent_id": "quants_02",
            "name": "Quants 2",
            "bracket": "quants",
            "round_num": 2,
            "flip_type": "buy_to_sell",
            "final_signal": "SELL",
        },
    ]


async def test_entity_impact_uses_final_round_and_skips_failures(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await write_mini_cycle(
        graph_manager_test,
        num_rounds=2,
        rounds={
            1: [("quants_01", dec(BUY, rationale="ZZZT Holdings looks cheap"))],
            2: [
                ("quants_01", dec(SELL, rationale="ZZZT Holdings is overpriced now")),
                ("quants_02", dec(PERR, 0.0, rationale="raw ZZZT Holdings output")),
                ("quants_03", dec(HOLD, rationale="waiting on QQQX Robotics")),
            ],
        },
    )

    rows = await graph_manager_test.read_entity_impact(cycle_id)

    assert rows == [
        {
            "entity_name": "QQQX Robotics",
            "entity_type": "company",
            "avg_sentiment": pytest.approx(0.1),
            "mention_count": 1,
            "buy_mentions": 0,
            "sell_mentions": 0,
            "hold_mentions": 1,
        },
        {
            "entity_name": "ZZZT Holdings",
            "entity_type": "company",
            "avg_sentiment": pytest.approx(0.1),
            "mention_count": 1,
            "buy_mentions": 0,
            "sell_mentions": 1,
            "hold_mentions": 0,
        },
    ]


async def test_entity_impact_counts_each_decision_once_for_the_cycles_own_entities(
    graph_manager_test: GraphStateManager,
) -> None:
    zzzt = SeedEntity(name="ZZZT Holdings", type=EntityType.COMPANY, relevance=0.9, sentiment=0.6)
    zzzt_sector = SeedEntity(
        name="ZZZT Holdings", type=EntityType.SECTOR, relevance=0.5, sentiment=0.2
    )
    # Another cycle MENTIONS a same-name entity of another type. It is written first,
    # so the name-matched REFERENCES of the cycle under test reach it as well.
    other_id = await write_mini_cycle(
        graph_manager_test,
        num_rounds=2,
        rounds={2: [("quants_04", dec(BUY, sentiment=0.9, rationale="ZZZT Holdings sector bid"))]},
        entities=[zzzt_sector],
    )
    # The orchestrator listed the same entity twice; seed parsing keeps both.
    cycle_id = await write_mini_cycle(
        graph_manager_test,
        num_rounds=2,
        rounds={
            1: [("quants_01", dec(BUY, rationale="ZZZT Holdings looks cheap"))],
            2: [
                ("quants_01", dec(SELL, sentiment=-0.4, rationale="ZZZT Holdings is overpriced")),
                ("quants_02", dec(BUY, sentiment=0.6, rationale="ZZZT Holdings closes the deal")),
            ],
        },
        entities=[zzzt, zzzt],
    )
    # The setup must hold both hazards, or the reads below prove nothing: two MENTIONS
    # of one entity, and REFERENCES to an entity this cycle never MENTIONS.
    mentions = await cypher(
        graph_manager_test,
        "MATCH (:Cycle {cycle_id: $cid})-[m:MENTIONS]->(e:Entity) "
        "RETURN e.type AS type, count(m) AS n",
        cid=cycle_id,
    )
    assert mentions == [{"type": "company", "n": 2}]
    stray = await cypher(
        graph_manager_test,
        "MATCH (d:Decision {cycle_id: $cid})-[:REFERENCES]->(:Entity {type: 'sector'}) "
        "RETURN count(DISTINCT d) AS n",
        cid=cycle_id,
    )
    assert stray == [{"n": 3}]

    rows = await graph_manager_test.read_entity_impact(cycle_id)
    other_rows = await graph_manager_test.read_entity_impact(other_id)

    assert rows == [
        {
            "entity_name": "ZZZT Holdings",
            "entity_type": "company",
            "avg_sentiment": pytest.approx(0.1),
            "mention_count": 2,
            "buy_mentions": 1,
            "sell_mentions": 1,
            "hold_mentions": 0,
        },
    ]
    # The other cycle counts only its own decision, not the stray REFERENCES above.
    assert other_rows == [
        {
            "entity_name": "ZZZT Holdings",
            "entity_type": "sector",
            "avg_sentiment": pytest.approx(0.9),
            "mention_count": 1,
            "buy_mentions": 1,
            "sell_mentions": 0,
            "hold_mentions": 0,
        },
    ]


async def test_shock_impact_reports_pre_and_post_majority_without_failures(
    graph_manager_test: GraphStateManager,
) -> None:
    from alphaswarm.report import ReportAssembler

    cycle_id = await write_mini_cycle(
        graph_manager_test,
        num_rounds=2,
        shock=(2, "Fictional regulator opens a review | of the deal"),
        rounds={
            1: [
                ("quants_01", dec(BUY)),
                ("quants_02", dec(BUY)),
                ("degens_01", dec(SELL)),
                ("degens_02", dec(BUY)),
            ],
            2: [
                ("quants_01", dec(SELL)),
                ("quants_02", dec(BUY)),
                ("degens_01", dec(SELL)),
                ("degens_02", dec(PERR, 0.0)),
            ],
        },
    )

    row = await graph_manager_test.read_shock_impact(cycle_id)
    md = ReportAssembler().render_section("11_shock_impact.j2", data=row, cycle_id=cycle_id)

    assert (row["pre_dominant"], row["post_dominant"], row["pivot_count"]) == ("BUY", "SELL", 1)
    # degens_02 failed in the shocked round, so it is not comparable
    assert sum(int(str(bp["comparable"])) for bp in row["bracket_pivots"]) == 3
    assert "**Event:** Fictional regulator opens a review \\| of the deal" in md
    assert "**Comparable Agents:** 3" in md
    assert "| Quants | BUY | BUY | ▼ | -50.0% |" in md
    assert "| Quants | quants_01 | BUY | SELL |" in md


async def test_completed_cycles_rows_are_typed(graph_manager_test: GraphStateManager) -> None:
    from datetime import datetime

    cycle_id = await write_mini_cycle(
        graph_manager_test,
        num_rounds=2,
        rounds={1: [("quants_01", dec(BUY))], 2: [("quants_01", dec(HOLD))]},
    )
    await graph_manager_test.write_cycle_metrics(cycle_id, {"num_rounds": 2})

    rows = await graph_manager_test.read_completed_cycles(limit=100)

    row = next(r for r in rows if r["cycle_id"] == cycle_id)
    assert set(row) == {"cycle_id", "created_at", "seed_rumor", "round_count"}
    assert row["round_count"] == 2
    assert isinstance(row["created_at"], str)
    datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
