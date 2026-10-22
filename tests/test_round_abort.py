"""Round-level failure policy (docs/DECISIONS.md#adr-taskgroup-dispatch)."""

from __future__ import annotations

import pytest

from alphaswarm.errors import RoundFailedError
from alphaswarm.simulation import _raise_if_round_failed
from alphaswarm.types import AgentDecision, SignalType


def _round(failed: int, total: int) -> list[tuple[str, AgentDecision]]:
    ok = AgentDecision(signal=SignalType.HOLD, confidence=0.5)
    bad = AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0, error_kind="inference")
    return [(f"agent_{i:03d}", bad if i < failed else ok) for i in range(total)]


def test_exactly_at_threshold_passes() -> None:
    _raise_if_round_failed(2, _round(50, 100), 50.0)


def test_one_over_threshold_aborts_with_counts() -> None:
    with pytest.raises(RoundFailedError) as exc_info:
        _raise_if_round_failed(2, _round(51, 100), 50.0)
    err = exc_info.value
    assert (err.round_num, err.failed, err.total, err.threshold_percent) == (2, 51, 100, 50.0)


def test_parse_errors_count_as_failures_too() -> None:
    decisions = [
        ("a1", AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0, error_kind="parse")),
        ("a2", AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0, error_kind="parse")),
        ("a3", AgentDecision(signal=SignalType.BUY, confidence=0.8)),
    ]
    with pytest.raises(RoundFailedError):
        _raise_if_round_failed(1, decisions, 50.0)


def test_empty_round_always_aborts() -> None:
    with pytest.raises(RoundFailedError) as exc_info:
        _raise_if_round_failed(1, [], 100.0)
    assert exc_info.value.total == 0


def test_threshold_100_never_aborts_a_non_empty_round() -> None:
    _raise_if_round_failed(3, _round(7, 7), 100.0)
