"""Pure shock-impact aggregation: pre/post majority, pivots, failures excluded upstream."""

from __future__ import annotations

import pytest

from alphaswarm.graph.manager import GraphStateManager, _majority


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
    assert _majority(["SELL", "BUY"]) == "BUY"
    assert _majority(["SELL", "HOLD"]) == "SELL"
    assert _majority(["HOLD"]) == "HOLD"
    assert _majority([]) is None


def test_aggregate_reports_dominants_pivots_and_bracket_order() -> None:
    rows = [
        _row("degens_01", "degens", "SELL", "SELL"),
        _row("quants_01", "quants", "BUY", "SELL"),
        _row("quants_02", "quants", "BUY", "BUY"),
    ]

    result = GraphStateManager._aggregate_shock_impact(rows)

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
    assert GraphStateManager._aggregate_shock_impact([]) == {
        "shock_text": "",
        "injected_before_round": 0,
        "pre_dominant": None,
        "post_dominant": None,
        "pivot_count": 0,
        "pivot_rate": 0.0,
        "bracket_pivots": [],
    }
