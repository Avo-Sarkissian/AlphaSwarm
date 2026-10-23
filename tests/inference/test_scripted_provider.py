"""Unit tests for ScriptedProvider and the prompt regexes."""

from __future__ import annotations

import json

import pytest

from alphaswarm.config import DEFAULT_BRACKETS, generate_personas
from alphaswarm.errors import InferenceError
from alphaswarm.inference.provider import InferenceProvider
from alphaswarm.inference.types import InferenceMessage, ProviderRole
from alphaswarm.interview import _strip_json_instructions
from alphaswarm.parsing import parse_agent_decision
from alphaswarm.types import AgentDecision, AgentPersona, SignalType
from alphaswarm.worker import DECISION_JSON_SCHEMA
from tests.inference.fakes import (
    AGENT_HEADER_RE,
    PEER_LINE_RE,
    ScriptedCall,
    ScriptedProvider,
    default_decision_script,
)

PERSONAS = generate_personas(list(DEFAULT_BRACKETS))
BY_ID = {p.id: p for p in PERSONAS}
RUMOR = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."


def _decision_messages(persona: AgentPersona, peers: str | None = None) -> list[InferenceMessage]:
    messages: list[InferenceMessage] = [{"role": "system", "content": persona.system_prompt}]
    if peers is not None:
        messages.append({"role": "system", "content": f"Peer context:\n{peers}"})
    messages.append({"role": "user", "content": RUMOR})
    return messages


def test_agent_header_regex_names_every_generated_persona() -> None:
    for persona in PERSONAS:
        match = AGENT_HEADER_RE.search(persona.system_prompt)
        assert match is not None, persona.id
        assert match.group("name") == persona.name


def test_peer_line_regex_reads_ids_and_brackets_but_not_headers() -> None:
    text = 'Peer Decisions (Round 1):\n1. [sell_side_03|sell_side] BUY (conf: 0.82) "momentum"\n2. [degens_11] SELL'
    found = [(m.group("agent_id"), m.group("bracket")) for m in PEER_LINE_RE.finditer(text)]
    assert found == [("sell_side_03", "sell_side"), ("degens_11", None)]
    assert PEER_LINE_RE.search(BY_ID["sell_side_03"].system_prompt) is None


async def test_satisfies_inference_provider_protocol() -> None:
    worker = ScriptedProvider(personas=PERSONAS)
    assert isinstance(worker, InferenceProvider)
    await worker.prepare()
    await worker.teardown()
    assert (worker.prepare_calls, worker.teardown_calls) == (1, 1)


async def test_decision_call_returns_llm_fields_only_and_counts_rounds() -> None:
    worker = ScriptedProvider(personas=PERSONAS)
    persona = BY_ID["quants_02"]
    first = await worker.chat(_decision_messages(persona), response_schema=DECISION_JSON_SCHEMA)
    second = await worker.chat(
        _decision_messages(persona, '1. [degens_04|degens] HOLD (conf: 0.50) "wait"'),
        response_schema=DECISION_JSON_SCHEMA,
    )
    calls = worker.calls_for("decision")
    assert [(c.agent_id, c.round_num) for c in calls] == [("quants_02", 1), ("quants_02", 2)]
    assert calls[1].shown_peer_ids == ("degens_04",)
    assert set(json.loads(first.content)) == {
        "signal",
        "confidence",
        "sentiment",
        "rationale",
        "cited_agents",
    }
    assert parse_agent_decision(second.content) == default_decision_script("quants_02", 2, calls[1])
    assert len(worker.calls) == 2  # inherited FakeInferenceProvider recording still works


async def test_round_source_overrides_the_per_agent_counter() -> None:
    worker = ScriptedProvider(personas=PERSONAS, round_source=lambda: 3)
    await worker.chat(_decision_messages(BY_ID["macro_01"]), response_schema=DECISION_JSON_SCHEMA)
    assert worker.calls_for("decision")[0].round_num == 3


async def test_classifies_narrative_and_interview_calls() -> None:
    worker = ScriptedProvider(personas=PERSONAS)
    narrative = await worker.chat(
        [
            {"role": "system", "content": "You are a concise financial analyst narrator."},
            {
                "role": "user",
                "content": "Summarize.\n\nAgent: Sell-Side 3 (sell_side)\nRound 1: BUY",
            },
        ]
    )
    interview = await worker.chat(
        [
            {
                "role": "system",
                "content": _strip_json_instructions(BY_ID["shorts_02"].system_prompt),
            },
            {"role": "user", "content": "Why did you sell?"},
        ]
    )
    assert [(c.kind, c.agent_id) for c in worker.scripted_calls] == [
        ("narrative", "sell_side_03"),
        ("chat", "shorts_02"),
    ]
    assert narrative.content == "Scripted narrative for sell_side_03."
    assert interview.content == "Scripted interview reply from shorts_02."


async def test_orchestrator_script_is_consumed_in_order_then_exhausts() -> None:
    orch = ScriptedProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="scripted-orchestrator",
        personas=PERSONAS,
        orchestrator_script=["first", "second"],
    )
    msgs: list[InferenceMessage] = [{"role": "user", "content": RUMOR}]
    assert (await orch.chat(msgs, json_mode=True)).content == "first"
    assert (await orch.chat(msgs, json_mode=True)).content == "second"
    with pytest.raises(AssertionError, match="orchestrator script exhausted"):
        await orch.chat(msgs, json_mode=True)
    assert [c.kind for c in orch.scripted_calls] == ["orchestrator"] * 3


async def test_returned_exception_is_raised_from_chat() -> None:
    def _decide(agent_id: str, round_num: int, call: ScriptedCall) -> AgentDecision | BaseException:
        return InferenceError("ollama died", provider="ollama", model="scripted-worker")

    worker = ScriptedProvider(personas=PERSONAS, decide=_decide)
    with pytest.raises(InferenceError, match="ollama died"):
        await worker.chat(_decision_messages(BY_ID["algos_01"]), response_schema=DECISION_JSON_SCHEMA)
    assert worker.calls_for("decision")[0].round_num == 1  # the failed call still counted


async def test_unknown_persona_name_fails_loudly() -> None:
    worker = ScriptedProvider(personas=PERSONAS[:5])
    with pytest.raises(AssertionError, match="unknown persona name 'Shorts 7'"):
        await worker.chat(_decision_messages(BY_ID["shorts_07"]), response_schema=DECISION_JSON_SCHEMA)


def test_default_decision_script_is_deterministic_and_cites_shown_peers() -> None:
    call = ScriptedCall(
        kind="decision",
        agent_id="institutions_01",
        round_num=1,
        shown_peer_ids=("sell_side_01", "narrators_02", "macro_03"),
        messages=[],
        kwargs={},
    )
    first = default_decision_script("institutions_01", 1, call)
    assert first == default_decision_script("institutions_01", 1, call)
    assert first.signal is SignalType.HOLD
    assert (first.confidence, first.sentiment) == (0.91, 0.76)
    assert first.cited_agents == ["sell_side_01", "narrators_02"]
    assert first.rationale == "institutions_01 round 1: scripted hold view"
