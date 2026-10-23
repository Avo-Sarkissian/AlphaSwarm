"""Rationale and citation caps: decode schema and instructions only (docs/DECISIONS.md#adr-output-caps)."""

from __future__ import annotations

import json

from alphaswarm.inference.caps import DECISION_CITED_AGENTS_MAX_ITEMS, DECISION_RATIONALE_MAX_CHARS
from alphaswarm.parsing import parse_agent_decision
from alphaswarm.prompts.decision import JSON_OUTPUT_INSTRUCTIONS
from alphaswarm.types import SignalType
from alphaswarm.worker import DECISION_JSON_SCHEMA


def test_cap_values() -> None:
    assert (DECISION_RATIONALE_MAX_CHARS, DECISION_CITED_AGENTS_MAX_ITEMS) == (280, 5)


def test_schema_carries_the_caps() -> None:
    props = DECISION_JSON_SCHEMA["properties"]
    assert props["rationale"] == {"type": "string", "maxLength": DECISION_RATIONALE_MAX_CHARS}
    assert props["cited_agents"] == {
        "type": "array",
        "items": {"type": "string"},
        "maxItems": DECISION_CITED_AGENTS_MAX_ITEMS,
    }


def test_instructions_state_the_caps() -> None:
    assert "at most 40 words" in JSON_OUTPUT_INSTRUCTIONS
    assert f"at most {DECISION_CITED_AGENTS_MAX_ITEMS} agent ids" in JSON_OUTPUT_INSTRUCTIONS
    assert "brief reasoning" not in JSON_OUTPUT_INSTRUCTIONS


def test_overlong_reply_still_parses() -> None:
    # A backend may ignore maxLength/maxItems; the parser must accept what the
    # schema only asked for (docs/DECISIONS.md#adr-output-caps).
    reply = json.dumps(
        {
            "signal": "buy",
            "confidence": 0.7,
            "sentiment": 0.4,
            "rationale": "ZZZT deal is accretive. " * 20,
            "cited_agents": [f"quants_{i:02d}" for i in range(1, 8)],
        }
    )
    decision = parse_agent_decision(reply)
    assert (decision.signal, decision.parse_tier) == (SignalType.BUY, 1)
    assert len(decision.rationale) > DECISION_RATIONALE_MAX_CHARS
    assert len(decision.cited_agents) == 7
