"""Read-model row TypedDicts carry exactly the keys the read_* queries return."""

from __future__ import annotations

import pytest

from alphaswarm import graph

EXPECTED_KEYS: dict[str, set[str]] = {
    "ConsensusSummaryRow": {"buy_count", "sell_count", "hold_count", "parse_error_count", "total"},
    "RoundTimelineRow": {
        "round_num",
        "buy_count",
        "sell_count",
        "hold_count",
        "parse_error_count",
        "total",
    },
    "BracketNarrativeRow": {
        "bracket",
        "display_name",
        "buy_count",
        "sell_count",
        "hold_count",
        "total",
        "avg_confidence",
        "avg_sentiment",
        "majority",
    },
    "KeyDissenterRow": {"agent_id", "name", "bracket", "signal", "bracket_majority"},
    "InfluenceLeaderRow": {"agent_id", "name", "bracket", "citation_count", "influence_share"},
    "SignalFlipRow": {"agent_id", "name", "bracket", "round_num", "flip_type", "final_signal"},
    "EntityImpactRow": {
        "entity_name",
        "entity_type",
        "avg_sentiment",
        "mention_count",
        "buy_mentions",
        "sell_mentions",
        "hold_mentions",
    },
    "ShockImpactRow": {
        "shock_text",
        "injected_before_round",
        "pre_dominant",
        "post_dominant",
        "pivot_count",
        "pivot_rate",
        "bracket_pivots",
    },
    "InfluenceEdgeRow": {"source_id", "target_id", "weight"},
    "CompletedCycleRow": {
        "cycle_id",
        "created_at",
        "seed_rumor",
        "round_count",
        "status",
        "final_buy",
        "final_sell",
        "final_hold",
        "total_flips",
        "total_seconds",
        "agent_count",
    },
    "BracketRoundRow": {
        "bracket",
        "buy_count",
        "sell_count",
        "hold_count",
        "total",
        "avg_confidence",
        "avg_sentiment",
    },
    "RationaleRoundRow": {"agent_id", "signal", "rationale", "round_num"},
    "AgentDecisionRow": {
        "round_num",
        "signal",
        "confidence",
        "sentiment",
        "rationale",
        "cited_agents",
    },
}


@pytest.mark.parametrize("name", sorted(EXPECTED_KEYS))
def test_row_typeddict_keys_match_contract(name: str) -> None:
    row_type = getattr(graph, name)
    assert set(row_type.__required_keys__) == EXPECTED_KEYS[name]
    assert not row_type.__optional_keys__


ROWS_MODULE_NAMES = (
    "AgentDecisionRow",
    "BracketNarrativeRow",
    "BracketRoundRow",
    "CompletedCycleRow",
    "ConsensusSummaryRow",
    "EntityImpactRow",
    "InfluenceEdgeRow",
    "InfluenceLeaderRow",
    "KeyDissenterRow",
    "PersistRoundResult",
    "RationaleRoundRow",
    "RoundTimelineRow",
    "ShockImpactRow",
    "SignalFlipRow",
)


@pytest.mark.parametrize("name", ROWS_MODULE_NAMES)
def test_row_types_are_defined_in_graph_rows(name: str) -> None:
    from alphaswarm.graph import rows

    assert getattr(graph, name) is getattr(rows, name)
    assert getattr(rows, name).__module__ == "alphaswarm.graph.rows"


def test_cycle_status_and_tx_runner_live_in_graph_rows() -> None:
    from typing import get_args

    from alphaswarm.graph import rows

    assert get_args(rows.CycleStatus) == ("running", "complete", "failed", "cancelled")
    assert graph.CycleStatus is rows.CycleStatus
    assert rows.TxRunner.__module__ == "alphaswarm.graph.rows"
