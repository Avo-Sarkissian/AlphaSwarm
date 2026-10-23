"""Structured output parsing tests for 3-tier fallback (INFRA-08).

Tests verify:
- Tier 1: Direct JSON validation via Pydantic
- Tier 2: Regex extraction of embedded JSON with code-fence stripping
- Tier 3: PARSE_ERROR sentinel fallback
- AgentDecision model validation
"""

from __future__ import annotations

import json as json_mod

import pytest
from pydantic import ValidationError

from alphaswarm.types import AgentDecision, BracketType, SignalType

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
    """Out-of-range numbers are clamped (docs/DECISIONS.md#adr-structured-output); unknown signals still fail."""
    assert AgentDecision(signal=SignalType.BUY, confidence=1.2).confidence == 1.0
    assert AgentDecision(signal=SignalType.BUY, confidence=0.5, sentiment=2.0).sentiment == 1.0
    with pytest.raises(ValidationError):
        AgentDecision.model_validate({"signal": "strong_buy", "confidence": 0.5})


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


def test_tier2_brace_in_rationale_with_trailing_brace() -> None:
    """F-09: prose-wrapped JSON whose rationale contains '}' plus a later stray
    '}' must still parse (string-aware brace scan), not silently become PARSE_ERROR."""
    from alphaswarm.parsing import parse_agent_decision

    raw = 'My take: {"signal": "buy", "confidence": 0.7, "rationale": "the set} looks bullish"} -- end of analysis }'
    result = parse_agent_decision(raw)
    assert result.signal == SignalType.BUY
    assert result.confidence == 0.7
    assert "looks bullish" in result.rationale


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
    """Tier 3: JSON is valid but a value cannot be normalised (unknown signal)."""
    from alphaswarm.parsing import parse_agent_decision

    raw = '{"signal": "strong_buy", "confidence": 0.5}'
    result = parse_agent_decision(raw)
    assert result.signal == SignalType.PARSE_ERROR
    assert result.confidence == 0.0


# --- Phase 13: parse_modifier_response tests ---


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
    from alphaswarm.parsing import parse_modifier_response
    from alphaswarm.personas import BRACKET_MODIFIERS

    result = parse_modifier_response("this is not json at all")
    assert result.parse_tier == 3
    assert len(result.modifiers) == 10
    for bt in BracketType:
        assert result.modifiers[bt] == BRACKET_MODIFIERS[bt][0]


def test_parse_modifiers_partial_fallback() -> None:
    """Partial JSON: present keys use generated value, missing keys use static fallback."""
    from alphaswarm.parsing import parse_modifier_response
    from alphaswarm.personas import BRACKET_MODIFIERS

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


def test_parse_logs_tier_used() -> None:
    """Successful tier 1 parse produces structlog DEBUG log containing parse_tier key."""
    import importlib

    import structlog

    import alphaswarm.parsing as parsing_module

    # Reset BEFORE reload so a cached logger from a prior test doesn't keep
    # using its frozen processor chain. Reload then reimports the module,
    # rebinding `parsing_module.logger` to a logger that honors the new
    # configuration set below.
    structlog.reset_defaults()

    # Capture structlog output
    captured: list[dict[str, object]] = []

    def capture_log(logger: object, method_name: str, event_dict: dict[str, object]) -> dict[str, object]:
        captured.append(event_dict)
        raise structlog.DropEvent

    # Configure structlog with our capture processor
    structlog.configure(
        processors=[capture_log],
        wrapper_class=structlog.BoundLogger,
        cache_logger_on_first_use=False,
    )
    # Reload parsing so its module-level `logger = structlog.get_logger(...)`
    # binds against the freshly-configured processor chain. Without the
    # reload, the module's logger reference is from whatever config was
    # active at first import (often another test's configuration), and our
    # capture_log processor is bypassed.
    importlib.reload(parsing_module)
    parse_agent_decision = parsing_module.parse_agent_decision

    try:
        raw = '{"signal": "buy", "confidence": 0.85}'
        parse_agent_decision(raw)

        # Check that at least one captured log has parse_tier key
        tier_logs = [e for e in captured if "parse_tier" in e]
        assert len(tier_logs) > 0, f"No logs with parse_tier found. Captured: {captured}"
        assert tier_logs[0]["parse_tier"] == 1
    finally:
        # Reset structlog to default and reload again so the module's logger
        # is rebound to a normal logger for subsequent tests.
        structlog.reset_defaults()
        importlib.reload(parsing_module)


def test_successful_parse_has_no_error_kind() -> None:
    from alphaswarm.parsing import parse_agent_decision

    raw = (
        '{"signal": "buy", "confidence": 0.7, "sentiment": 0.2, '
        '"rationale": "ZZZT Holdings deal is accretive", "cited_agents": []}'
    )
    assert parse_agent_decision(raw).error_kind is None


def test_tier3_fallback_is_a_parse_error_kind() -> None:
    from alphaswarm.parsing import parse_agent_decision
    from alphaswarm.types import SignalType

    decision = parse_agent_decision("the model rambled and produced no JSON at all")
    assert decision.signal is SignalType.PARSE_ERROR
    assert decision.error_kind == "parse"


def test_model_cannot_claim_an_engine_error_kind() -> None:
    from alphaswarm.parsing import parse_agent_decision
    from alphaswarm.types import SignalType

    raw = (
        '{"signal": "hold", "confidence": 0.5, "sentiment": 0.0, "rationale": "wait", '
        '"cited_agents": [], "error_kind": "inference"}'
    )
    decision = parse_agent_decision(raw)
    assert decision.signal is SignalType.HOLD
    assert decision.error_kind is None


def test_model_answering_parse_error_signal_is_classified_as_parse() -> None:
    from alphaswarm.parsing import parse_agent_decision
    from alphaswarm.types import SignalType

    decision = parse_agent_decision('{"signal": "parse_error", "confidence": 0.0}')
    assert decision.signal is SignalType.PARSE_ERROR
    assert decision.error_kind == "parse"
