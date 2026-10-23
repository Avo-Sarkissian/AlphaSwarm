"""Replay maps raw rows onto the live frame's bracket shape."""

from __future__ import annotations

from alphaswarm.graph import BracketRoundRow, RationaleRoundRow
from alphaswarm.personas import DEFAULT_BRACKETS
from alphaswarm.state import BracketSummary, RationaleEntry
from alphaswarm.types import SignalType
from alphaswarm.web.replay_manager import _bracket_summaries_from_rows, _rationale_entries_from_rows


def test_rows_map_to_all_configured_brackets_in_order() -> None:
    rows: list[BracketRoundRow] = [
        {
            "bracket": "degens",
            "buy_count": 2,
            "sell_count": 1,
            "hold_count": 0,
            "total": 3,
            "avg_confidence": 0.7,
            "avg_sentiment": 0.1,
        },
        {
            "bracket": "legacy_suits",
            "buy_count": 1,
            "sell_count": 0,
            "hold_count": 0,
            "total": 1,
            "avg_confidence": 0.5,
            "avg_sentiment": 0.0,
        },
    ]

    summaries = _bracket_summaries_from_rows(rows)

    assert [s.bracket for s in summaries] == [
        *(b.bracket_type.value for b in DEFAULT_BRACKETS),
        "legacy_suits",
    ]
    assert next(s for s in summaries if s.bracket == "degens") == BracketSummary(
        bracket="degens",
        display_name="Degens",
        buy_count=2,
        sell_count=1,
        hold_count=0,
        total=3,
        avg_confidence=0.7,
        avg_sentiment=0.1,
    )
    assert next(s for s in summaries if s.bracket == "quants").total == 0
    assert summaries[-1].display_name == "legacy_suits"


def test_rationale_rows_become_typed_entries() -> None:
    rows: list[RationaleRoundRow] = [
        {"agent_id": "quants_01", "signal": "buy", "rationale": "fictional", "round_num": 1},
    ]

    assert _rationale_entries_from_rows(rows) == (
        RationaleEntry(
            agent_id="quants_01",
            signal=SignalType.BUY,
            rationale="fictional",
            round_num=1,
            seq=1,
            ts=0.0,
        ),
    )
