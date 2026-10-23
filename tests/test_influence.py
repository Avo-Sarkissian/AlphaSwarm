"""Pure influence and shock-impact maths: pre/post majority, pivots, failures excluded upstream."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from alphaswarm.influence import aggregate_shock_impact, citation_weights, majority


def _row(agent_id: str, bracket: str, pre: str, post: str) -> dict[str, object]:
    return {
        "agent_id": agent_id,
        "bracket": bracket,
        "pre_signal": pre,
        "post_signal": post,
        "shock_round": 2,
        "shock_text": "Fictional regulator opens a review",
    }


def test_majority_tie_break_and_empty() -> None:
    assert majority(["SELL", "BUY"]) == "BUY"
    assert majority(["SELL", "HOLD"]) == "SELL"
    assert majority(["HOLD"]) == "HOLD"
    assert majority([]) is None


def test_aggregate_reports_dominants_pivots_and_bracket_order() -> None:
    rows = [
        _row("degens_01", "degens", "SELL", "SELL"),
        _row("quants_01", "quants", "BUY", "SELL"),
        _row("quants_02", "quants", "BUY", "BUY"),
    ]

    result = aggregate_shock_impact(rows)

    assert result["shock_text"] == "Fictional regulator opens a review"
    assert result["injected_before_round"] == 2
    assert result["pre_dominant"] == "BUY"
    assert result["post_dominant"] == "SELL"
    assert result["pivot_count"] == 1
    assert result["pivot_rate"] == pytest.approx(1 / 3)
    quants, degens = result["bracket_pivots"]  # config order: quants before degens
    assert quants == {
        "bracket": "quants",
        "display_name": "Quants",
        "comparable": 2,
        "pivots": 1,
        "pre_dominant": "BUY",
        "post_dominant": "BUY",
        "pre_buy_pct": 100.0,
        "post_buy_pct": 50.0,
        "delta_buy_pct": -50.0,
        "dominant_arrow": "▼",
        "agents": [{"agent_id": "quants_01", "pre_signal": "BUY", "post_signal": "SELL"}],
    }
    assert degens["pivots"] == 0 and degens["agents"] == [] and degens["dominant_arrow"] == "·"


def test_aggregate_without_rows_is_zero_filled() -> None:
    assert aggregate_shock_impact([]) == {
        "shock_text": "",
        "injected_before_round": 0,
        "pre_dominant": None,
        "post_dominant": None,
        "pivot_count": 0,
        "pivot_rate": 0.0,
        "bracket_pivots": [],
    }


def test_citation_weights_divide_distinct_citers_by_active_agents() -> None:
    weights = citation_weights(["sell_side_01", "narrators_02", "sell_side_01"], 4)

    assert weights == {"sell_side_01": 0.5, "narrators_02": 0.25}
    assert list(weights) == ["sell_side_01", "narrators_02"]  # first-seen order


def test_citation_weights_reject_a_zero_denominator() -> None:
    with pytest.raises(ValueError, match="total_agents must be positive"):
        citation_weights(["quants_01"], 0)


@given(
    targets=st.lists(st.sampled_from(["quants_01", "degens_02", "macro_03"]), max_size=30),
    total=st.integers(min_value=1, max_value=100),
)
def test_citation_weights_sum_to_pairs_over_agents(targets: list[str], total: int) -> None:
    assert sum(citation_weights(targets, total).values()) == pytest.approx(len(targets) / total)


def test_shock_types_are_defined_in_influence_and_reexported() -> None:
    from alphaswarm import influence
    from alphaswarm.graph import rows

    for name in ("ShockImpactRow", "BracketPivotRow", "PivotAgentRow"):
        assert getattr(rows, name) is getattr(influence, name)
        assert getattr(influence, name).__module__ == "alphaswarm.influence"


def test_bracket_order_and_display_names_come_from_personas() -> None:
    from alphaswarm.personas import BRACKET_DISPLAY_NAMES, DEFAULT_BRACKETS, bracket_sort_key

    keys = [b.bracket_type.value for b in DEFAULT_BRACKETS]
    assert sorted(reversed(keys), key=bracket_sort_key) == keys
    assert bracket_sort_key("legacy_suits") == (len(keys), "legacy_suits")
    assert BRACKET_DISPLAY_NAMES["sell_side"] == "Sell-Side"
