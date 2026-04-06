"""Tests for Phase 16 ticker extraction: types, parsing, and prompt.

Tests are organized in two groups:
  - Task 1: Type model tests (ExtractedTicker, SeedEvent.tickers, ParsedSeedResult.dropped_tickers)
  - Task 2: Parsing pipeline tests (_try_parse_seed_json, parse_seed_event, ORCHESTRATOR_SYSTEM_PROMPT)
"""

from __future__ import annotations

import pytest
import pydantic

from alphaswarm.types import ExtractedTicker, SeedEvent, ParsedSeedResult


# ---------------------------------------------------------------------------
# Task 1: Type model tests
# ---------------------------------------------------------------------------


def test_extracted_ticker_valid() -> None:
    """ExtractedTicker validates correctly with all fields."""
    t = ExtractedTicker(symbol="AAPL", company_name="Apple Inc.", relevance=0.95)
    assert t.symbol == "AAPL"
    assert t.company_name == "Apple Inc."
    assert t.relevance == 0.95


def test_extracted_ticker_relevance_too_high() -> None:
    """ExtractedTicker with relevance > 1.0 raises ValidationError."""
    with pytest.raises(pydantic.ValidationError):
        ExtractedTicker(symbol="AAPL", company_name="Apple Inc.", relevance=1.1)


def test_extracted_ticker_relevance_too_low() -> None:
    """ExtractedTicker with relevance < 0.0 raises ValidationError."""
    with pytest.raises(pydantic.ValidationError):
        ExtractedTicker(symbol="TSLA", company_name="Tesla Inc.", relevance=-0.1)


def test_seed_event_default_tickers() -> None:
    """SeedEvent with no tickers argument defaults to empty list -- backward compatible."""
    event = SeedEvent(raw_rumor="test rumor", entities=[], overall_sentiment=0.0)
    assert event.tickers == []


def test_seed_event_with_tickers() -> None:
    """SeedEvent accepts and stores a list of ExtractedTicker objects."""
    ticker = ExtractedTicker(symbol="MSFT", company_name="Microsoft Corporation", relevance=0.8)
    event = SeedEvent(
        raw_rumor="test rumor",
        entities=[],
        tickers=[ticker],
        overall_sentiment=0.2,
    )
    assert len(event.tickers) == 1
    assert event.tickers[0].symbol == "MSFT"


def test_parsed_seed_result_without_dropped_tickers() -> None:
    """ParsedSeedResult(seed_event=..., parse_tier=1) works without dropped_tickers -- backward compat."""
    event = SeedEvent(raw_rumor="test", entities=[], overall_sentiment=0.0)
    result = ParsedSeedResult(seed_event=event, parse_tier=1)
    assert result.parse_tier == 1
    assert result.dropped_tickers == ()


def test_parsed_seed_result_with_dropped_tickers() -> None:
    """ParsedSeedResult stores dropped_tickers as a tuple of dicts."""
    event = SeedEvent(raw_rumor="test", entities=[], overall_sentiment=0.0)
    dropped = ({"symbol": "X", "reason": "invalid"},)
    result = ParsedSeedResult(seed_event=event, parse_tier=1, dropped_tickers=dropped)
    assert result.dropped_tickers == ({"symbol": "X", "reason": "invalid"},)
    assert result.dropped_tickers[0]["reason"] == "invalid"
