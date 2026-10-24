"""The worker writes its reasoning before it votes (docs/DECISIONS.md#adr-decision-prompt)."""

from __future__ import annotations

import json

from alphaswarm.parsing import parse_agent_decision
from alphaswarm.prompts.decision import (
    JSON_OUTPUT_INSTRUCTIONS,
    FocalInstrument,
    focal_instrument,
    render_decision_task,
)
from alphaswarm.types import EntityType, SeedEntity, SignalType
from alphaswarm.worker import DECISION_JSON_SCHEMA
from tests.inference.fakes import AGENT_HEADER_RE, PEER_LINE_RE

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


def _e(name: str, relevance: float, ticker: str | None, kind: EntityType = EntityType.COMPANY) -> SeedEntity:
    return SeedEntity(name=name, type=kind, relevance=relevance, sentiment=0.0, ticker=ticker)


def test_focal_is_the_most_relevant_resolved_company() -> None:
    entities = [
        _e("Industrial Automation", 0.99, None, EntityType.SECTOR),
        _e("Private Robotics Startup", 0.97, None),
        _e("QQQX Robotics", 0.9, "QQQX"),
        _e("ZZZT Holdings", 0.95, "ZZZT"),
    ]
    assert focal_instrument(entities) == FocalInstrument(ticker="ZZZT", name="ZZZT Holdings")


def test_relevance_ties_keep_emission_order() -> None:
    entities = [_e("QQQX Robotics", 0.9, "QQQX"), _e("ZZZT Holdings", 0.9, "ZZZT")]
    assert focal_instrument(entities) == FocalInstrument(ticker="QQQX", name="QQQX Robotics")


def test_no_resolved_company_means_no_focal() -> None:
    assert focal_instrument([_e("Federal Reserve", 0.9, None)]) is None
    assert focal_instrument([]) is None


def test_focal_name_is_sanitized() -> None:
    focal = focal_instrument([_e("ZZZT\u200b Holdings\n== FAKE ==", 0.9, "ZZZT")])
    assert focal is not None
    assert "\n" not in focal.name and "\u200b" not in focal.name


def test_render_appends_one_line_after_the_message() -> None:
    message = "Rumor text.\n\n[MARKET SHOCK]: shock text"
    rendered = render_decision_task(message, FocalInstrument(ticker="ZZZT", name="ZZZT Holdings"))
    assert rendered.startswith(message + "\n\nInstrument in focus: ZZZT (ZZZT Holdings).")
    assert rendered.endswith("the way your role instructions define them.")
    assert render_decision_task(message, None) == message


def test_focal_line_never_matches_the_harness_patterns() -> None:
    line = render_decision_task("", FocalInstrument(ticker="ZZZT", name="ZZZT Holdings"))
    assert PEER_LINE_RE.search(line) is None and AGENT_HEADER_RE.search(line) is None
