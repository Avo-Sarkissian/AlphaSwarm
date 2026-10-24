"""Peer lines without authority cues (docs/DECISIONS.md#adr-diverse-peer-context)."""

from __future__ import annotations

import pytest

from alphaswarm.peers import RankedPost, build_peer_contexts, format_peer_context
from alphaswarm.personas import DEFAULT_BRACKETS, generate_personas
from alphaswarm.settings import SimulationSettings
from alphaswarm.types import AgentDecision, SignalType
from tests.inference.fakes import PEER_LINE_RE


def _post(
    agent_id: str,
    bracket: str,
    *,
    signal: str = "buy",
    confidence: float = 0.82,
    content: str = "accretive deal",
) -> RankedPost:
    return RankedPost(
        post_id="",
        agent_id=agent_id,
        bracket=bracket,
        signal=signal,
        confidence=confidence,
        content=content,
        influence_weight=0.5,
        round_num=1,
    )


POSTS = [
    _post("sell_side_03", "sell_side"),
    _post("degens_07", "degens", signal="sell", confidence=0.4, content="priced in"),
]


def _peer_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line[:1].isdigit()]


def test_default_lines_keep_bracket_and_confidence() -> None:
    text, shown = format_peer_context(POSTS, 1)

    assert _peer_lines(text)[0].startswith("1. [sell_side_03|sell_side] BUY (conf: 0.82) ")
    assert shown == ("sell_side_03", "degens_07")


@pytest.mark.parametrize(
    ("show_bracket", "show_confidence", "expected_prefix"),
    [
        (False, True, "1. [sell_side_03] BUY (conf: 0.82) "),
        (True, False, "1. [sell_side_03|sell_side] BUY "),
        (False, False, "1. [sell_side_03] BUY "),
    ],
)
def test_knobs_drop_authority_cues(show_bracket: bool, show_confidence: bool, expected_prefix: str) -> None:
    text, shown = format_peer_context(POSTS, 1, show_bracket=show_bracket, show_confidence=show_confidence)
    lines = _peer_lines(text)

    assert lines[0].startswith(expected_prefix)
    assert all(("(conf:" in line) is show_confidence for line in lines)
    assert all(("|" in line.split("]")[0]) is show_bracket for line in lines)
    assert [m.group("agent_id") for m in PEER_LINE_RE.finditer(text)] == ["sell_side_03", "degens_07"]
    assert shown == ("sell_side_03", "degens_07")


def test_builder_passes_the_knobs_through() -> None:
    personas = generate_personas(DEFAULT_BRACKETS)
    decisions = [
        (p.id, AgentDecision(signal=SignalType.BUY, confidence=0.7, rationale=f"view of {p.id}")) for p in personas
    ]
    sim = SimulationSettings(show_bracket_labels=False, show_confidence=False)

    result = build_peer_contexts(personas, decisions, 1, sim=sim, run_seed="run-1")
    lines = [line for block in result.contexts if block for line in _peer_lines(block)]

    assert lines
    assert all("(conf:" not in line and "|" not in line.split("]")[0] for line in lines)
