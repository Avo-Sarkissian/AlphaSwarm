"""The worker writes its reasoning before it votes (docs/DECISIONS.md#adr-decision-prompt)."""

from __future__ import annotations

import json

from alphaswarm.parsing import parse_agent_decision
from alphaswarm.prompts.decision import JSON_OUTPUT_INSTRUCTIONS
from alphaswarm.types import SignalType
from alphaswarm.worker import DECISION_JSON_SCHEMA

ORDER = ["rationale", "signal", "confidence", "sentiment", "cited_agents"]


def test_schema_lists_the_rationale_first() -> None:
    assert list(DECISION_JSON_SCHEMA["properties"]) == ORDER
    assert DECISION_JSON_SCHEMA["required"] == ORDER


def test_serialised_schema_keeps_that_order() -> None:
    text = json.dumps(DECISION_JSON_SCHEMA)
    assert text.index('"rationale"') < text.index('"signal"') < text.index('"cited_agents"')


def test_instructions_ask_for_reasoning_before_the_vote() -> None:
    assert "Write the rationale first" in JSON_OUTPUT_INSTRUCTIONS
    assert JSON_OUTPUT_INSTRUCTIONS.index('"rationale"') < JSON_OUTPUT_INSTRUCTIONS.index('"signal"')


def test_a_rationale_first_reply_parses() -> None:
    decision = parse_agent_decision(
        '{"rationale": "Deal accretive", "signal": "buy", "confidence": 0.7, "sentiment": 0.2, "cited_agents": []}'
    )
    assert decision.signal is SignalType.BUY
    assert decision.rationale == "Deal accretive"
