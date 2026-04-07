"""Type model tests for TickerDecision and AgentDecision extensions (Phase 18).

Tests verify:
- TickerDecision model validation and frozen behavior
- AgentDecision.ticker_decisions field backward compatibility
"""

from __future__ import annotations

import pytest

from alphaswarm.types import AgentDecision, SignalType, TickerDecision


# --- TickerDecision model tests ---


def test_ticker_decision_all_fields() -> None:
    """TickerDecision with all fields validates correctly."""
    td = TickerDecision(
        ticker="AAPL",
        direction=SignalType.BUY,
        expected_return_pct=5.2,
        time_horizon="1w",
    )
    assert td.ticker == "AAPL"
    assert td.direction == SignalType.BUY
    assert td.expected_return_pct == 5.2
    assert td.time_horizon == "1w"


def test_ticker_decision_required_only() -> None:
    """TickerDecision with only required fields (ticker, direction) validates; optional fields default to None."""
    td = TickerDecision(ticker="TSLA", direction=SignalType.SELL)
    assert td.ticker == "TSLA"
    assert td.direction == SignalType.SELL
    assert td.expected_return_pct is None
    assert td.time_horizon is None


def test_ticker_decision_frozen() -> None:
    """TickerDecision is frozen -- assignment raises."""
    td = TickerDecision(ticker="AAPL", direction=SignalType.BUY)
    with pytest.raises(Exception):
        td.ticker = "MSFT"  # type: ignore[misc]


# --- AgentDecision.ticker_decisions field tests ---


def test_agent_decision_ticker_decisions_default() -> None:
    """AgentDecision without ticker_decisions field defaults to empty list."""
    d = AgentDecision(signal=SignalType.HOLD, confidence=0.5)
    assert d.ticker_decisions == []


def test_agent_decision_with_empty_ticker_decisions() -> None:
    """AgentDecision with explicit empty ticker_decisions=[] validates."""
    d = AgentDecision(
        signal=SignalType.BUY,
        confidence=0.85,
        ticker_decisions=[],
    )
    assert d.ticker_decisions == []


def test_agent_decision_with_ticker_decisions() -> None:
    """AgentDecision with populated ticker_decisions list validates."""
    td1 = TickerDecision(ticker="AAPL", direction=SignalType.BUY, expected_return_pct=5.2)
    td2 = TickerDecision(ticker="TSLA", direction=SignalType.SELL, time_horizon="1m")
    d = AgentDecision(
        signal=SignalType.BUY,
        confidence=0.85,
        ticker_decisions=[td1, td2],
    )
    assert len(d.ticker_decisions) == 2
    assert d.ticker_decisions[0].ticker == "AAPL"
    assert d.ticker_decisions[1].direction == SignalType.SELL
