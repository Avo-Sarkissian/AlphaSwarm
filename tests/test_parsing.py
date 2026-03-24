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
