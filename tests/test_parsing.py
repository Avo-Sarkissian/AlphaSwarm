"""Structured output parsing tests for 3-tier fallback (INFRA-08).

Tests verify:
- Tier 1: Direct JSON validation via Pydantic
- Tier 2: Regex extraction of embedded JSON with code-fence stripping
- Tier 3: PARSE_ERROR sentinel fallback
- AgentDecision model validation
"""

from __future__ import annotations

import pytest

from alphaswarm.types import AgentDecision, SignalType


# --- AgentDecision model tests (no parsing module needed) ---


def test_agent_decision_model() -> None:
    """AgentDecision validates correctly with all fields."""
    d = AgentDecision(
        signal=SignalType.BUY,
        confidence=0.85,
        sentiment=0.6,
        rationale="Strong earnings signal",
        cited_agents=["quant_01", "macro_03"],
    )
    assert d.signal == SignalType.BUY
    assert d.confidence == 0.85
    assert d.cited_agents == ["quant_01", "macro_03"]


def test_agent_decision_defaults() -> None:
    """AgentDecision has correct defaults for optional fields."""
    d = AgentDecision(signal=SignalType.HOLD, confidence=0.5)
    assert d.sentiment == 0.0
    assert d.rationale == ""
    assert d.cited_agents == []


def test_agent_decision_validation_bounds() -> None:
    """AgentDecision rejects out-of-bounds confidence and sentiment."""
    with pytest.raises(Exception):
        AgentDecision(signal=SignalType.BUY, confidence=1.5)
    with pytest.raises(Exception):
        AgentDecision(signal=SignalType.BUY, confidence=0.5, sentiment=2.0)


def test_agent_decision_parse_error_signal() -> None:
    """AgentDecision accepts PARSE_ERROR signal type."""
    d = AgentDecision(
        signal=SignalType.PARSE_ERROR,
        confidence=0.0,
        rationale="Parse failed: invalid json",
    )
    assert d.signal == SignalType.PARSE_ERROR


# --- Parsing function tests ---


def test_tier1_json_parse() -> None:
    """Tier 1: parse_agent_decision succeeds on valid JSON string."""
    from alphaswarm.parsing import parse_agent_decision

    raw = '{"signal": "buy", "confidence": 0.85, "sentiment": 0.6, "rationale": "Strong earnings"}'
    result = parse_agent_decision(raw)
    assert result.signal == SignalType.BUY
    assert result.confidence == 0.85
    assert result.sentiment == 0.6
    assert result.rationale == "Strong earnings"


def test_tier2_regex_extract() -> None:
    """Tier 2: parse_agent_decision extracts JSON from surrounding text."""
    from alphaswarm.parsing import parse_agent_decision

    raw = 'Here is my analysis:\n{"signal": "sell", "confidence": 0.7, "rationale": "Weak outlook"}\nThat is all.'
    result = parse_agent_decision(raw)
    assert result.signal == SignalType.SELL
    assert result.confidence == 0.7


def test_tier2_nested_json() -> None:
    """Tier 2: regex extraction handles JSON with list values."""
    from alphaswarm.parsing import parse_agent_decision

    raw = 'Analysis: {"signal": "hold", "confidence": 0.5, "cited_agents": ["quant_01", "macro_03"]}'
    result = parse_agent_decision(raw)
    assert result.signal == SignalType.HOLD
    assert result.cited_agents == ["quant_01", "macro_03"]


def test_tier2_code_fence() -> None:
    """Tier 2: parse_agent_decision strips markdown code fences before extraction."""
    from alphaswarm.parsing import parse_agent_decision

    raw = '```json\n{"signal": "buy", "confidence": 0.9, "rationale": "Momentum"}\n```'
    result = parse_agent_decision(raw)
    assert result.signal == SignalType.BUY
    assert result.confidence == 0.9


def test_tier2_code_fence_with_text() -> None:
    """Tier 2: handles code fences embedded in explanation text."""
    from alphaswarm.parsing import parse_agent_decision

    raw = 'My decision:\n```\n{"signal": "sell", "confidence": 0.6}\n```\nThat is final.'
    result = parse_agent_decision(raw)
    assert result.signal == SignalType.SELL
    assert result.confidence == 0.6


def test_tier3_parse_error() -> None:
    """Tier 3: parse_agent_decision returns PARSE_ERROR on garbage input."""
    from alphaswarm.parsing import parse_agent_decision

    raw = "I don't know what to say about this rumor"
    result = parse_agent_decision(raw)
    assert result.signal == SignalType.PARSE_ERROR
    assert result.confidence == 0.0
    assert result.rationale.startswith("Parse failed:")


def test_tier3_invalid_json_values() -> None:
    """Tier 3: JSON is valid but field values fail Pydantic validation."""
    from alphaswarm.parsing import parse_agent_decision

    raw = '{"signal": "buy", "confidence": 5.0}'  # confidence > 1.0
    result = parse_agent_decision(raw)
    assert result.signal == SignalType.PARSE_ERROR
    assert result.confidence == 0.0


# --- parse_seed_event tests ---


def test_seed_parse_tier1_valid_json() -> None:
    """Tier 1: Valid JSON with entities returns ParsedSeedResult with parse_tier=1."""
    from alphaswarm.parsing import parse_seed_event

    raw = '{"entities": [{"name": "NVIDIA", "type": "company", "relevance": 0.95, "sentiment": 0.8}], "overall_sentiment": 0.6}'
    result = parse_seed_event(raw, original_rumor="NVIDIA quantum breakthrough")
    assert result.parse_tier == 1
    assert result.seed_event.raw_rumor == "NVIDIA quantum breakthrough"
    assert len(result.seed_event.entities) == 1
    assert result.seed_event.entities[0].name == "NVIDIA"
    assert result.seed_event.overall_sentiment == 0.6


def test_seed_parse_tier1_no_raw_rumor_in_json() -> None:
    """Tier 1: JSON without raw_rumor field still parses (raw_rumor comes from parameter)."""
    from alphaswarm.parsing import parse_seed_event

    raw = '{"entities": [], "overall_sentiment": 0.0}'
    result = parse_seed_event(raw, original_rumor="my rumor")
    assert result.parse_tier == 1
    assert result.seed_event.raw_rumor == "my rumor"


def test_seed_parse_tier2_code_fenced_json() -> None:
    """Tier 2: Code-fenced JSON extracts correctly."""
    from alphaswarm.parsing import parse_seed_event

    raw = '```json\n{"entities": [{"name": "TSLA", "type": "company", "relevance": 0.8, "sentiment": -0.3}], "overall_sentiment": -0.2}\n```'
    result = parse_seed_event(raw, original_rumor="Tesla rumor")
    assert result.parse_tier == 2
    assert result.seed_event.entities[0].name == "TSLA"


def test_seed_parse_tier2_embedded_in_prose() -> None:
    """Tier 2: JSON embedded in prose text extracts via regex."""
    from alphaswarm.parsing import parse_seed_event

    raw = 'Here is my analysis:\n{"entities": [{"name": "Apple", "type": "company", "relevance": 0.7, "sentiment": 0.4}], "overall_sentiment": 0.3}\nThat is all.'
    result = parse_seed_event(raw, original_rumor="Apple rumor")
    assert result.parse_tier == 2
    assert len(result.seed_event.entities) == 1


def test_seed_parse_tier3_garbage_input() -> None:
    """Tier 3: Complete garbage returns parse_tier=3 with empty entities."""
    from alphaswarm.parsing import parse_seed_event

    raw = "I don't know what to say about this rumor at all"
    result = parse_seed_event(raw, original_rumor="original")
    assert result.parse_tier == 3
    assert result.seed_event.entities == []
    assert result.seed_event.overall_sentiment == 0.0
    assert result.seed_event.raw_rumor == "original"


def test_seed_parse_tier3_empty_string() -> None:
    """Tier 3: Empty string returns parse_tier=3."""
    from alphaswarm.parsing import parse_seed_event

    result = parse_seed_event("", original_rumor="rumor")
    assert result.parse_tier == 3
    assert result.seed_event.entities == []


def test_seed_parse_adversarial_multiple_json() -> None:
    """Adversarial: Multiple JSON objects -- does not crash, returns valid result."""
    from alphaswarm.parsing import parse_seed_event

    raw = '{"entities": [{"name": "A", "type": "company", "relevance": 0.5, "sentiment": 0.1}], "overall_sentiment": 0.2} {"entities": [{"name": "B", "type": "sector", "relevance": 0.3, "sentiment": -0.1}], "overall_sentiment": -0.1}'
    result = parse_seed_event(raw, original_rumor="test")
    # Must not crash; graceful fallback is acceptable
    assert result.parse_tier in (1, 2, 3)
    assert result.seed_event.raw_rumor == "test"


def test_seed_parse_adversarial_truncated_json() -> None:
    """Adversarial: Truncated JSON falls to Tier 3."""
    from alphaswarm.parsing import parse_seed_event

    raw = '{"entities": [{"name": "NVIDIA"'
    result = parse_seed_event(raw, original_rumor="test")
    assert result.parse_tier == 3


def test_seed_parse_adversarial_unknown_entity_type() -> None:
    """Adversarial: Unknown entity type skips invalid entity, keeps valid ones."""
    from alphaswarm.parsing import parse_seed_event

    raw = '{"entities": [{"name": "NVIDIA", "type": "company", "relevance": 0.9, "sentiment": 0.8}, {"name": "Paris", "type": "location", "relevance": 0.5, "sentiment": 0.0}], "overall_sentiment": 0.5}'
    result = parse_seed_event(raw, original_rumor="test")
    assert result.parse_tier in (1, 2)
    # Valid entity kept, invalid skipped
    assert len(result.seed_event.entities) == 1
    assert result.seed_event.entities[0].name == "NVIDIA"


def test_seed_parse_adversarial_null_fields() -> None:
    """Adversarial: Null entities field falls to Tier 3."""
    from alphaswarm.parsing import parse_seed_event

    raw = '{"entities": null, "overall_sentiment": 0.5}'
    result = parse_seed_event(raw, original_rumor="test")
    assert result.parse_tier == 3


def test_seed_parse_adversarial_out_of_range_values() -> None:
    """Adversarial: Out-of-range relevance/sentiment in entities -- bad entities skipped."""
    from alphaswarm.parsing import parse_seed_event

    raw = '{"entities": [{"name": "NVIDIA", "type": "company", "relevance": 1.5, "sentiment": 0.8}, {"name": "AMD", "type": "company", "relevance": 0.7, "sentiment": 0.5}], "overall_sentiment": 0.4}'
    result = parse_seed_event(raw, original_rumor="test")
    # NVIDIA entity has relevance=1.5 (out of range) -> skipped; AMD is valid
    assert result.parse_tier in (1, 2)
    assert len(result.seed_event.entities) == 1
    assert result.seed_event.entities[0].name == "AMD"


def test_seed_parse_adversarial_duplicate_entities() -> None:
    """Adversarial: Duplicate entities (same name twice) do not crash."""
    from alphaswarm.parsing import parse_seed_event

    raw = '{"entities": [{"name": "NVIDIA", "type": "company", "relevance": 0.9, "sentiment": 0.8}, {"name": "NVIDIA", "type": "company", "relevance": 0.9, "sentiment": 0.8}], "overall_sentiment": 0.5}'
    result = parse_seed_event(raw, original_rumor="test")
    assert result.parse_tier in (1, 2)
    assert len(result.seed_event.entities) == 2


def test_seed_parse_adversarial_extra_prose_with_braces() -> None:
    """Adversarial: Prose with stray braces before actual JSON."""
    from alphaswarm.parsing import parse_seed_event

    raw = 'I think {the market} will... {"entities": [{"name": "NVIDIA", "type": "company", "relevance": 0.9, "sentiment": 0.8}], "overall_sentiment": 0.5}'
    result = parse_seed_event(raw, original_rumor="test")
    # Should eventually find valid JSON via regex
    assert result.parse_tier in (1, 2, 3)
    # If it parses, entities should be present
    if result.parse_tier in (1, 2):
        assert len(result.seed_event.entities) >= 1


def test_seed_parse_adversarial_extra_fields_tolerated() -> None:
    """Adversarial: JSON with extra fields (e.g. reasoning) is tolerated."""
    from alphaswarm.parsing import parse_seed_event

    raw = '{"entities": [{"name": "NVIDIA", "type": "company", "relevance": 0.9, "sentiment": 0.8, "reasoning": "leading chip maker"}], "overall_sentiment": 0.5, "summary": "bullish"}'
    result = parse_seed_event(raw, original_rumor="test")
    assert result.parse_tier in (1, 2)
    assert result.seed_event.entities[0].name == "NVIDIA"


def test_seed_parse_raw_rumor_always_from_parameter() -> None:
    """raw_rumor from LLM output is ALWAYS overridden by the original_rumor parameter."""
    from alphaswarm.parsing import parse_seed_event

    raw = '{"raw_rumor": "LLM fabricated rumor", "entities": [], "overall_sentiment": 0.0}'
    result = parse_seed_event(raw, original_rumor="the real rumor")
    assert result.seed_event.raw_rumor == "the real rumor"


def test_seed_parse_adversarial_out_of_range_overall_sentiment() -> None:
    """Adversarial: Out-of-range overall_sentiment falls to Tier 3."""
    from alphaswarm.parsing import parse_seed_event

    raw = '{"entities": [], "overall_sentiment": 5.0}'
    result = parse_seed_event(raw, original_rumor="test")
    assert result.parse_tier == 3


# --- Phase 13: parse_modifier_response tests ---

import json as json_mod

from alphaswarm.types import BracketType


def _make_full_modifier_json() -> str:
    """Helper: build valid JSON with all 10 BracketType keys."""
    return json_mod.dumps({bt.value: f"modifier for {bt.value}" for bt in BracketType})


def test_parse_modifiers_tier1() -> None:
    """Tier 1: direct JSON parse with all 10 keys succeeds."""
    from alphaswarm.parsing import parse_modifier_response

    raw = _make_full_modifier_json()
    result = parse_modifier_response(raw)
    assert result.parse_tier == 1
    assert len(result.modifiers) == 10
    for bt in BracketType:
        assert bt in result.modifiers
        assert f"modifier for {bt.value}" in result.modifiers[bt]


def test_parse_modifiers_tier2() -> None:
    """Tier 2: JSON wrapped in code fence is extracted."""
    from alphaswarm.parsing import parse_modifier_response

    raw = f"```json\n{_make_full_modifier_json()}\n```"
    result = parse_modifier_response(raw)
    assert result.parse_tier == 2
    assert len(result.modifiers) == 10


def test_parse_modifiers_tier3_fallback() -> None:
    """Tier 3: garbage text falls back to static BRACKET_MODIFIERS[bracket][0]."""
    from alphaswarm.config import BRACKET_MODIFIERS
    from alphaswarm.parsing import parse_modifier_response

    result = parse_modifier_response("this is not json at all")
    assert result.parse_tier == 3
    assert len(result.modifiers) == 10
    for bt in BracketType:
        assert result.modifiers[bt] == BRACKET_MODIFIERS[bt][0]


def test_parse_modifiers_partial_fallback() -> None:
    """Partial JSON: present keys use generated value, missing keys use static fallback."""
    from alphaswarm.config import BRACKET_MODIFIERS
    from alphaswarm.parsing import parse_modifier_response

    partial = {bt.value: f"custom {bt.value}" for bt in list(BracketType)[:7]}
    result = parse_modifier_response(json_mod.dumps(partial))
    assert result.parse_tier == 1  # Valid JSON, just missing some keys
    assert len(result.modifiers) == 10
    # First 7 brackets have custom modifiers
    for bt in list(BracketType)[:7]:
        assert result.modifiers[bt] == f"custom {bt.value}"
    # Last 3 brackets fall back to static
    for bt in list(BracketType)[7:]:
        assert result.modifiers[bt] == BRACKET_MODIFIERS[bt][0]


def test_parse_modifiers_case_insensitive() -> None:
    """Keys with mixed case are normalized to lowercase before BracketType lookup."""
    from alphaswarm.parsing import parse_modifier_response

    mixed_case = {bt.value.upper(): f"upper {bt.value}" for bt in BracketType}
    result = parse_modifier_response(json_mod.dumps(mixed_case))
    assert result.parse_tier == 1
    for bt in BracketType:
        assert result.modifiers[bt] == f"upper {bt.value}"


# --- Phase 18: ticker_decisions parse tests ---


def test_parse_with_ticker_decisions() -> None:
    """JSON with valid ticker_decisions parses correctly."""
    from alphaswarm.parsing import parse_agent_decision

    raw = json_mod.dumps({
        "signal": "buy",
        "confidence": 0.85,
        "sentiment": 0.6,
        "rationale": "Strong earnings",
        "cited_agents": [],
        "ticker_decisions": [
            {"ticker": "AAPL", "direction": "buy", "expected_return_pct": 5.2, "time_horizon": "1w"},
            {"ticker": "TSLA", "direction": "sell", "expected_return_pct": -3.1, "time_horizon": "1m"},
        ],
    })
    result = parse_agent_decision(raw)
    assert result.signal == SignalType.BUY
    assert len(result.ticker_decisions) == 2
    assert result.ticker_decisions[0].ticker == "AAPL"
    assert result.ticker_decisions[1].direction == SignalType.SELL


def test_parse_without_ticker_decisions_backward_compat() -> None:
    """JSON without ticker_decisions field -> ticker_decisions=[] (backward compat)."""
    from alphaswarm.parsing import parse_agent_decision

    raw = '{"signal": "hold", "confidence": 0.5, "rationale": "neutral"}'
    result = parse_agent_decision(raw)
    assert result.signal == SignalType.HOLD
    assert result.ticker_decisions == []


def test_parse_error_fallback_has_empty_ticker_decisions() -> None:
    """Tier 3 fallback produces ticker_decisions=[]."""
    from alphaswarm.parsing import parse_agent_decision

    raw = "completely unparseable garbage text"
    result = parse_agent_decision(raw)
    assert result.signal == SignalType.PARSE_ERROR
    assert result.ticker_decisions == []


def test_parse_malformed_ticker_decisions_wrong_direction() -> None:
    """JSON with malformed direction in ticker_decisions -> top-level preserved, entry dropped, NOT PARSE_ERROR."""
    from alphaswarm.parsing import parse_agent_decision

    raw = json_mod.dumps({
        "signal": "buy",
        "confidence": 0.85,
        "sentiment": 0.6,
        "rationale": "Strong earnings",
        "cited_agents": [],
        "ticker_decisions": [
            {"ticker": "AAPL", "direction": "YOLO"},
        ],
    })
    result = parse_agent_decision(raw)
    assert result.signal == SignalType.BUY
    assert result.confidence == 0.85
    assert result.ticker_decisions == []  # malformed entry dropped


def test_parse_malformed_ticker_decisions_wrong_type() -> None:
    """JSON with non-numeric expected_return_pct -> entry dropped, top-level preserved."""
    from alphaswarm.parsing import parse_agent_decision

    raw = json_mod.dumps({
        "signal": "sell",
        "confidence": 0.7,
        "sentiment": -0.3,
        "rationale": "Weak outlook",
        "cited_agents": [],
        "ticker_decisions": [
            {"ticker": "AAPL", "direction": "buy", "expected_return_pct": "not_a_number"},
        ],
    })
    result = parse_agent_decision(raw)
    assert result.signal == SignalType.SELL
    assert result.confidence == 0.7
    assert result.ticker_decisions == []  # malformed entry dropped


def test_parse_mixed_valid_invalid_ticker_decisions() -> None:
    """JSON with 2 valid + 1 invalid ticker_decisions -> keeps 2, drops 1."""
    from alphaswarm.parsing import parse_agent_decision

    raw = json_mod.dumps({
        "signal": "buy",
        "confidence": 0.85,
        "sentiment": 0.6,
        "rationale": "Mixed tickers",
        "cited_agents": [],
        "ticker_decisions": [
            {"ticker": "AAPL", "direction": "buy", "expected_return_pct": 5.2},
            {"ticker": "BAD", "direction": "YOLO"},  # invalid direction
            {"ticker": "TSLA", "direction": "sell", "time_horizon": "1m"},
        ],
    })
    result = parse_agent_decision(raw)
    assert result.signal == SignalType.BUY
    assert len(result.ticker_decisions) == 2
    assert result.ticker_decisions[0].ticker == "AAPL"
    assert result.ticker_decisions[1].ticker == "TSLA"


# --- Phase 18: seed ticker extraction parse tests ---


def test_parse_seed_with_tickers() -> None:
    """JSON with tickers array -> SeedEvent.tickers populated."""
    from alphaswarm.parsing import parse_seed_event

    raw = json_mod.dumps({
        "entities": [
            {"name": "Apple", "type": "company", "relevance": 0.9, "sentiment": 0.5},
        ],
        "overall_sentiment": 0.5,
        "tickers": [
            {"symbol": "AAPL", "company_name": "Apple Inc", "relevance": 0.9},
        ],
    })
    result = parse_seed_event(raw, original_rumor="Apple rumor")
    assert result.parse_tier == 1
    assert len(result.seed_event.tickers) == 1
    assert result.seed_event.tickers[0].symbol == "AAPL"
    assert result.seed_event.tickers[0].company_name == "Apple Inc"


def test_parse_seed_without_tickers() -> None:
    """JSON without tickers key -> SeedEvent.tickers=[]."""
    from alphaswarm.parsing import parse_seed_event

    raw = json_mod.dumps({
        "entities": [
            {"name": "NVIDIA", "type": "company", "relevance": 0.9, "sentiment": 0.8},
        ],
        "overall_sentiment": 0.6,
    })
    result = parse_seed_event(raw, original_rumor="NVIDIA rumor")
    assert result.parse_tier == 1
    assert result.seed_event.tickers == []


def test_parse_seed_tickers_capped_at_3() -> None:
    """JSON with 5 tickers -> keeps top 3 by relevance."""
    from alphaswarm.parsing import parse_seed_event

    raw = json_mod.dumps({
        "entities": [],
        "overall_sentiment": 0.0,
        "tickers": [
            {"symbol": "LOW", "company_name": "Low Co", "relevance": 0.1},
            {"symbol": "HIGH", "company_name": "High Co", "relevance": 0.9},
            {"symbol": "MED", "company_name": "Med Co", "relevance": 0.5},
            {"symbol": "VHIGH", "company_name": "Very High Co", "relevance": 1.0},
            {"symbol": "VLOW", "company_name": "Very Low Co", "relevance": 0.05},
        ],
    })
    result = parse_seed_event(raw, original_rumor="multi ticker rumor")
    assert len(result.seed_event.tickers) == 3
    # Top 3 by relevance: VHIGH (1.0), HIGH (0.9), MED (0.5)
    symbols = [t.symbol for t in result.seed_event.tickers]
    assert symbols == ["VHIGH", "HIGH", "MED"]


def test_parse_logs_tier_used() -> None:
    """Successful tier 1 parse produces structlog DEBUG log containing parse_tier key."""
    import structlog

    from alphaswarm.parsing import parse_agent_decision

    # Capture structlog output
    captured: list[dict[str, object]] = []

    def capture_log(
        logger: object, method_name: str, event_dict: dict[str, object]
    ) -> dict[str, object]:
        captured.append(event_dict)
        raise structlog.DropEvent

    # Configure structlog with our capture processor
    structlog.configure(
        processors=[capture_log],
        wrapper_class=structlog.BoundLogger,
        cache_logger_on_first_use=False,
    )
    try:
        raw = '{"signal": "buy", "confidence": 0.85}'
        parse_agent_decision(raw)

        # Check that at least one captured log has parse_tier key
        tier_logs = [e for e in captured if "parse_tier" in e]
        assert len(tier_logs) > 0, f"No logs with parse_tier found. Captured: {captured}"
        assert tier_logs[0]["parse_tier"] == 1
    finally:
        # Reset structlog to default
        structlog.reset_defaults()
