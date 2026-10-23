"""Worker parse tiers are recorded on the decision (docs/DECISIONS.md#adr-structured-output)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import alphaswarm.parsing as parsing_module
from alphaswarm.parsing import parse_agent_decision
from alphaswarm.types import AgentDecision, SignalType

VALID = (
    '{"signal": "buy", "confidence": 0.7, "sentiment": 0.2, '
    '"rationale": "ZZZT Holdings deal is accretive", "cited_agents": []}'
)


def test_default_is_none() -> None:
    assert AgentDecision(signal=SignalType.HOLD, confidence=0.5).parse_tier is None


def test_direct_json_is_tier_1() -> None:
    assert parse_agent_decision(VALID).parse_tier == 1


@pytest.mark.parametrize("raw", [f"```json\n{VALID}\n```", f"Here is my view: {VALID} done."])
def test_extracted_json_is_tier_2(raw: str) -> None:
    decision = parse_agent_decision(raw)
    assert (decision.signal, decision.parse_tier) == (SignalType.BUY, 2)


def test_garbage_is_tier_3_and_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_log = MagicMock()
    monkeypatch.setattr(parsing_module, "logger", fake_log)
    decision = parse_agent_decision("the model rambled about QQQX Robotics")
    assert (decision.signal, decision.error_kind, decision.parse_tier) == (
        SignalType.PARSE_ERROR,
        "parse",
        3,
    )
    fake_log.warning.assert_called_once()
    args, kwargs = fake_log.warning.call_args
    assert args == ("decision_parse_failed",)
    assert kwargs["parse_tier"] == 3
    assert kwargs["raw_preview"].startswith("the model rambled")


def test_model_cannot_claim_a_tier() -> None:
    echoed = VALID[:-1] + ', "parse_tier": 3}'
    assert parse_agent_decision(echoed).parse_tier == 1


def test_parse_error_answer_is_tier_3() -> None:
    decision = parse_agent_decision('{"signal": "parse_error", "confidence": 0.0, "parse_tier": 1}')
    assert (decision.error_kind, decision.parse_tier) == ("parse", 3)


def test_parse_tier_metrics_counts_each_tier_and_ignores_untiered() -> None:
    from alphaswarm.rounds import parse_tier_metrics

    decisions = [
        ("quants_01", AgentDecision(signal=SignalType.BUY, confidence=0.6, parse_tier=1)),
        ("quants_02", AgentDecision(signal=SignalType.HOLD, confidence=0.5, parse_tier=1)),
        ("degens_01", AgentDecision(signal=SignalType.SELL, confidence=0.4, parse_tier=2)),
        ("macro_01", AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0, parse_tier=3)),
        ("algos_01", AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0, error_kind="inference")),
    ]
    assert parse_tier_metrics(2, decisions) == {
        "r2_parse_tier1": 2,
        "r2_parse_tier2": 1,
        "r2_parse_tier3": 1,
    }
