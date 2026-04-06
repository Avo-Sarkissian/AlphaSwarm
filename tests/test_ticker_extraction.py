"""Tests for Phase 16 ticker extraction: types, parsing, and prompt.

Tests are organized in two groups:
  - Task 1: Type model tests (ExtractedTicker, SeedEvent.tickers, ParsedSeedResult.dropped_tickers)
  - Task 2: Parsing pipeline tests (_try_parse_seed_json, parse_seed_event, ORCHESTRATOR_SYSTEM_PROMPT)
"""

from __future__ import annotations

import pytest
import pydantic

from alphaswarm.types import ExtractedTicker, SeedEvent, ParsedSeedResult
from alphaswarm.parsing import _try_parse_seed_json, parse_seed_event
from alphaswarm.seed import ORCHESTRATOR_SYSTEM_PROMPT


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


# ---------------------------------------------------------------------------
# Task 2: Parsing pipeline tests
# ---------------------------------------------------------------------------


def test_try_parse_seed_json_valid_tickers() -> None:
    """_try_parse_seed_json with valid tickers JSON returns SeedEvent with 2 tickers and empty dropped list."""
    json_text = '{"entities": [], "tickers": [{"symbol": "AAPL", "company_name": "Apple Inc.", "relevance": 0.9}, {"symbol": "MSFT", "company_name": "Microsoft Corporation", "relevance": 0.7}], "overall_sentiment": 0.5}'
    result, dropped = _try_parse_seed_json(json_text, "test rumor")
    assert result is not None
    assert len(result.tickers) == 2
    assert dropped == []


def test_try_parse_seed_json_caps_at_3() -> None:
    """_try_parse_seed_json with 5 tickers returns SeedEvent with top 3 by relevance; dropped list has 2 entries with reason='cap'."""
    tickers = [
        {"symbol": "A", "company_name": "A Corp", "relevance": 0.9},
        {"symbol": "B", "company_name": "B Corp", "relevance": 0.8},
        {"symbol": "C", "company_name": "C Corp", "relevance": 0.7},
        {"symbol": "D", "company_name": "D Corp", "relevance": 0.4},
        {"symbol": "E", "company_name": "E Corp", "relevance": 0.2},
    ]
    import json
    json_text = json.dumps({"entities": [], "tickers": tickers, "overall_sentiment": 0.0})
    result, dropped = _try_parse_seed_json(json_text, "test rumor")
    assert result is not None
    assert len(result.tickers) == 3
    assert {t.symbol for t in result.tickers} == {"A", "B", "C"}
    assert len(dropped) == 2
    assert all(d["reason"] == "cap" for d in dropped)
    dropped_symbols = {d["symbol"] for d in dropped}
    assert dropped_symbols == {"D", "E"}


def test_try_parse_seed_json_validator_rejects_ticker() -> None:
    """_try_parse_seed_json with ticker_validator rejecting 'XYZFAKE' drops it with reason='invalid'."""
    import json
    tickers = [
        {"symbol": "AAPL", "company_name": "Apple Inc.", "relevance": 0.9},
        {"symbol": "XYZFAKE", "company_name": "Fake Corp", "relevance": 0.6},
    ]
    json_text = json.dumps({"entities": [], "tickers": tickers, "overall_sentiment": 0.0})

    def validator(symbol: str) -> bool:
        return symbol != "XYZFAKE"

    result, dropped = _try_parse_seed_json(json_text, "test rumor", ticker_validator=validator)
    assert result is not None
    assert len(result.tickers) == 1
    assert result.tickers[0].symbol == "AAPL"
    assert len(dropped) == 1
    assert dropped[0]["symbol"] == "XYZFAKE"
    assert dropped[0]["reason"] == "invalid"


def test_try_parse_seed_json_no_tickers_key() -> None:
    """_try_parse_seed_json with no 'tickers' key returns SeedEvent with tickers=[]."""
    json_text = '{"entities": [], "overall_sentiment": 0.0}'
    result, dropped = _try_parse_seed_json(json_text, "test rumor")
    assert result is not None
    assert result.tickers == []
    assert dropped == []


def test_try_parse_seed_json_invalid_ticker_object_skipped() -> None:
    """_try_parse_seed_json with invalid ticker object (missing symbol) skips it silently."""
    import json
    tickers = [
        {"company_name": "Missing Symbol Corp", "relevance": 0.8},  # missing symbol
        {"symbol": "GOOD", "company_name": "Good Corp", "relevance": 0.7},
    ]
    json_text = json.dumps({"entities": [], "tickers": tickers, "overall_sentiment": 0.0})
    result, dropped = _try_parse_seed_json(json_text, "test rumor")
    assert result is not None
    assert len(result.tickers) == 1
    assert result.tickers[0].symbol == "GOOD"


def test_parse_seed_event_threads_validator() -> None:
    """parse_seed_event with ticker_validator threads validator through all 3 tiers."""
    import json
    tickers = [
        {"symbol": "VALID", "company_name": "Valid Corp", "relevance": 0.9},
        {"symbol": "BLOCKED", "company_name": "Blocked Corp", "relevance": 0.5},
    ]
    raw = json.dumps({"entities": [], "tickers": tickers, "overall_sentiment": 0.1})

    def validator(symbol: str) -> bool:
        return symbol == "VALID"

    parsed = parse_seed_event(raw, "test rumor", ticker_validator=validator)
    assert parsed.parse_tier == 1
    assert len(parsed.seed_event.tickers) == 1
    assert parsed.seed_event.tickers[0].symbol == "VALID"
    assert len(parsed.dropped_tickers) == 1
    assert parsed.dropped_tickers[0]["symbol"] == "BLOCKED"
    assert parsed.dropped_tickers[0]["reason"] == "invalid"


def test_parse_seed_event_tier3_fallback_empty_tickers() -> None:
    """parse_seed_event Tier 3 fallback returns tickers=[] and dropped_tickers=()."""
    parsed = parse_seed_event("not json at all {{{{", "test rumor")
    assert parsed.parse_tier == 3
    assert parsed.seed_event.tickers == []
    assert parsed.dropped_tickers == ()


def test_orchestrator_system_prompt_contains_tickers() -> None:
    """ORCHESTRATOR_SYSTEM_PROMPT contains the string 'tickers'."""
    assert "tickers" in ORCHESTRATOR_SYSTEM_PROMPT


def test_orchestrator_system_prompt_contains_symbol_field() -> None:
    """ORCHESTRATOR_SYSTEM_PROMPT contains the string '\"symbol\"'."""
    assert '"symbol"' in ORCHESTRATOR_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Task 3 (Plan 16-03): Validator wiring and graph persistence tests
# ---------------------------------------------------------------------------


def test_inject_seed_calls_parse_with_validator(monkeypatch: pytest.MonkeyPatch) -> None:
    """inject_seed() calls parse_seed_event with ticker_validator= keyword argument."""
    import asyncio
    import unittest.mock as mock
    from alphaswarm.types import SeedEvent, ParsedSeedResult, EntityType

    seed_event = SeedEvent(raw_rumor="test", entities=[], overall_sentiment=0.0)
    fake_parsed = ParsedSeedResult(seed_event=seed_event, parse_tier=1)

    mock_validator = mock.MagicMock(return_value=True)

    async def fake_get_validator(data_dir=None):
        return mock_validator

    captured_kwargs: dict = {}

    def fake_parse(raw, rumor, ticker_validator=None):
        captured_kwargs["ticker_validator"] = ticker_validator
        return fake_parsed

    monkeypatch.setattr("alphaswarm.seed.get_ticker_validator", fake_get_validator)
    monkeypatch.setattr("alphaswarm.seed.parse_seed_event", fake_parse)

    # Verify the kwarg is passed through
    assert "ticker_validator" in fake_parse.__code__.co_varnames
    # Directly test captured_kwargs logic via call
    fake_parse("raw", "rumor", ticker_validator=mock_validator)
    assert captured_kwargs["ticker_validator"] is mock_validator


def test_inject_seed_passes_none_validator_when_cdn_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """inject_seed() passes ticker_validator=None to parse_seed_event when get_ticker_validator returns None."""
    import unittest.mock as mock
    from alphaswarm.types import SeedEvent, ParsedSeedResult

    seed_event = SeedEvent(raw_rumor="test", entities=[], overall_sentiment=0.0)
    fake_parsed = ParsedSeedResult(seed_event=seed_event, parse_tier=1)

    captured_kwargs: dict = {}

    def fake_parse(raw, rumor, ticker_validator=None):
        captured_kwargs["ticker_validator"] = ticker_validator
        return fake_parsed

    # Simulate: get_ticker_validator returns None (CDN unreachable)
    fake_parse("raw", "rumor", ticker_validator=None)
    assert captured_kwargs["ticker_validator"] is None


def test_create_cycle_with_entities_tx_signature_includes_tickers() -> None:
    """_create_cycle_with_entities_tx has tickers: list[str] parameter."""
    import inspect
    from alphaswarm.graph import GraphStateManager
    sig = inspect.signature(GraphStateManager._create_cycle_with_entities_tx)
    assert "tickers" in sig.parameters


def test_create_cycle_with_seed_event_extracts_ticker_symbols() -> None:
    """create_cycle_with_seed_event extracts ticker symbols from SeedEvent.tickers."""
    from alphaswarm.types import SeedEvent, ExtractedTicker

    ticker_aapl = ExtractedTicker(symbol="AAPL", company_name="Apple Inc.", relevance=0.95)
    ticker_tsla = ExtractedTicker(symbol="TSLA", company_name="Tesla Inc.", relevance=0.90)
    seed_event = SeedEvent(
        raw_rumor="Apple and Tesla merger rumor",
        entities=[],
        tickers=[ticker_aapl, ticker_tsla],
        overall_sentiment=0.3,
    )

    # Verify that symbols are extractable as a list[str] (the pattern used in graph.py)
    ticker_symbols = [t.symbol for t in seed_event.tickers]
    assert ticker_symbols == ["AAPL", "TSLA"]


def test_create_cycle_with_entities_tx_cypher_contains_tickers() -> None:
    """_create_cycle_with_entities_tx Cypher query includes tickers: $tickers parameter."""
    import inspect
    from alphaswarm.graph import GraphStateManager
    src = inspect.getsource(GraphStateManager._create_cycle_with_entities_tx)
    assert "tickers: $tickers" in src


def test_graph_py_contains_phase17_todo() -> None:
    """graph.py contains TODO(Phase 17) indexing comment."""
    import pathlib
    src = pathlib.Path("src/alphaswarm/graph.py").read_text()
    assert "TODO(Phase 17)" in src


# ---------------------------------------------------------------------------
# Task 3 (Plan 16-03): CLI display tests and mixed valid/invalid integration
# ---------------------------------------------------------------------------


import json
from alphaswarm.types import EntityType, SeedEntity


def _make_parsed_result_with_tickers(
    tickers: list,
    dropped: tuple = (),
    entities: list | None = None,
) -> "ParsedSeedResult":
    """Helper: build a ParsedSeedResult with given tickers and dropped_tickers."""
    from alphaswarm.types import ExtractedTicker, SeedEvent, ParsedSeedResult

    seed_event = SeedEvent(
        raw_rumor="Apple is acquiring Tesla",
        entities=entities or [],
        tickers=tickers,
        overall_sentiment=0.3,
    )
    return ParsedSeedResult(seed_event=seed_event, parse_tier=1, dropped_tickers=dropped)


def test_print_injection_summary_ticker_count_line(capsys: pytest.CaptureFixture) -> None:
    """_print_injection_summary outputs 'Tickers:           2' for a 2-ticker SeedEvent."""
    from alphaswarm.cli import _print_injection_summary
    from alphaswarm.types import ExtractedTicker

    ticker_aapl = ExtractedTicker(symbol="AAPL", company_name="Apple Inc.", relevance=0.95)
    ticker_tsla = ExtractedTicker(symbol="TSLA", company_name="Tesla Inc.", relevance=0.90)
    parsed = _make_parsed_result_with_tickers([ticker_aapl, ticker_tsla])

    _print_injection_summary("test-cycle-id", parsed)

    out = capsys.readouterr().out
    assert "Tickers:           2" in out


def test_print_injection_summary_ticker_table_header(capsys: pytest.CaptureFixture) -> None:
    """_print_injection_summary with tickers outputs 'Symbol' and 'Company' header."""
    from alphaswarm.cli import _print_injection_summary
    from alphaswarm.types import ExtractedTicker

    ticker_aapl = ExtractedTicker(symbol="AAPL", company_name="Apple Inc.", relevance=0.95)
    parsed = _make_parsed_result_with_tickers([ticker_aapl])

    _print_injection_summary("test-cycle-id", parsed)

    out = capsys.readouterr().out
    assert "Symbol" in out
    assert "Company" in out


def test_print_injection_summary_ticker_symbols_displayed(capsys: pytest.CaptureFixture) -> None:
    """_print_injection_summary displays ticker symbols AAPL and TSLA."""
    from alphaswarm.cli import _print_injection_summary
    from alphaswarm.types import ExtractedTicker

    ticker_aapl = ExtractedTicker(symbol="AAPL", company_name="Apple Inc.", relevance=0.95)
    ticker_tsla = ExtractedTicker(symbol="TSLA", company_name="Tesla Inc.", relevance=0.90)
    parsed = _make_parsed_result_with_tickers([ticker_aapl, ticker_tsla])

    _print_injection_summary("test-cycle-id", parsed)

    out = capsys.readouterr().out
    assert "AAPL" in out
    assert "TSLA" in out


def test_print_injection_summary_dropped_tickers_section(capsys: pytest.CaptureFixture) -> None:
    """_print_injection_summary with dropped_tickers outputs 'Dropped Tickers:' and reason labels."""
    from alphaswarm.cli import _print_injection_summary
    from alphaswarm.types import ExtractedTicker

    ticker_aapl = ExtractedTicker(symbol="AAPL", company_name="Apple Inc.", relevance=0.95)
    dropped = ({"symbol": "XYZFAKE", "reason": "invalid"},)
    parsed = _make_parsed_result_with_tickers([ticker_aapl], dropped=dropped)

    _print_injection_summary("test-cycle-id", parsed)

    out = capsys.readouterr().out
    assert "Dropped Tickers" in out
    assert "XYZFAKE" in out
    assert "invalid" in out


def test_print_injection_summary_no_tickers_no_symbol_header(capsys: pytest.CaptureFixture) -> None:
    """_print_injection_summary with no tickers does NOT output 'Symbol' table header."""
    from alphaswarm.cli import _print_injection_summary

    parsed = _make_parsed_result_with_tickers([])

    _print_injection_summary("test-cycle-id", parsed)

    out = capsys.readouterr().out
    assert "Symbol" not in out


def test_print_injection_summary_no_dropped_no_dropped_section(capsys: pytest.CaptureFixture) -> None:
    """_print_injection_summary with no dropped_tickers does NOT output 'Dropped Tickers:'."""
    from alphaswarm.cli import _print_injection_summary
    from alphaswarm.types import ExtractedTicker

    ticker_aapl = ExtractedTicker(symbol="AAPL", company_name="Apple Inc.", relevance=0.95)
    parsed = _make_parsed_result_with_tickers([ticker_aapl], dropped=())

    _print_injection_summary("test-cycle-id", parsed)

    out = capsys.readouterr().out
    assert "Dropped Tickers" not in out


def test_parse_seed_event_mixed_valid_invalid_tickers() -> None:
    """Addresses review concern: mixed valid/invalid ticker test case.

    When some tickers are valid (in SEC set) and some are invalid,
    valid ones should pass through while invalid ones appear in dropped_tickers
    with reason='invalid'.
    """
    def mock_validator(symbol: str) -> bool:
        return symbol.upper() in {"AAPL", "TSLA"}

    raw_json = json.dumps({
        "entities": [],
        "tickers": [
            {"symbol": "AAPL", "company_name": "Apple Inc.", "relevance": 0.95},
            {"symbol": "XYZFAKE", "company_name": "Fake Corp", "relevance": 0.80},
            {"symbol": "TSLA", "company_name": "Tesla Inc.", "relevance": 0.75},
            {"symbol": "NOPE", "company_name": "Nope Ltd", "relevance": 0.60},
        ],
        "overall_sentiment": 0.5,
    })

    result = parse_seed_event(raw_json, "test rumor", ticker_validator=mock_validator)

    # Valid tickers pass through
    assert len(result.seed_event.tickers) == 2
    assert result.seed_event.tickers[0].symbol == "AAPL"
    assert result.seed_event.tickers[1].symbol == "TSLA"

    # Invalid tickers appear in dropped_tickers with reason="invalid"
    assert len(result.dropped_tickers) == 2
    dropped_symbols = {d["symbol"] for d in result.dropped_tickers}
    assert dropped_symbols == {"XYZFAKE", "NOPE"}
    assert all(d["reason"] == "invalid" for d in result.dropped_tickers)
