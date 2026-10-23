"""Prompt layout for KV-prefix reuse: shared text first, agent text last (docs/DECISIONS.md#adr-prefix-reuse)."""

from __future__ import annotations

from collections import defaultdict

from alphaswarm.interview import _strip_json_instructions
from alphaswarm.personas import (
    BRACKET_MODIFIERS,
    DEFAULT_BRACKETS,
    generate_personas,
    persona_to_worker_config,
)
from alphaswarm.prompts.decision import JSON_OUTPUT_INSTRUCTIONS
from alphaswarm.types import AgentPersona, BracketType
from tests.inference.fakes import AGENT_HEADER_RE

RULES = JSON_OUTPUT_INSTRUCTIONS.strip()
FOCUS = {bt: f"fictional {bt.value} catalyst watcher" for bt in BracketType}


def _personas() -> list[AgentPersona]:
    return generate_personas(DEFAULT_BRACKETS, modifiers=FOCUS)


def test_every_prompt_starts_with_the_json_rules() -> None:
    assert all(p.system_prompt.startswith(RULES) for p in _personas())


def test_agent_header_is_the_last_line() -> None:
    for p in _personas():
        last = p.system_prompt.rstrip().splitlines()[-1]
        match = AGENT_HEADER_RE.fullmatch(last)
        assert match is not None and match.group("name") == p.name


def test_shared_prefix_is_identical_within_a_bracket() -> None:
    prefixes: dict[BracketType, set[str]] = defaultdict(set)
    for p in _personas():
        prefixes[p.bracket].add(p.system_prompt[: p.shared_prompt_chars])
    assert len(prefixes) == len(BracketType)
    assert all(len(found) == 1 for found in prefixes.values())


def test_shared_prefix_holds_template_and_focus_but_no_agent_text() -> None:
    templates = {b.bracket_type: b.system_prompt_template.strip() for b in DEFAULT_BRACKETS}
    for p in _personas():
        shared = p.system_prompt[: p.shared_prompt_chars]
        assert templates[p.bracket] in shared
        assert f"This cycle you are focused as a {FOCUS[p.bracket]}." in shared
        assert f"[{p.name} |" not in shared
        assert not any(f"You are a {m}." in shared for m in BRACKET_MODIFIERS.get(p.bracket, []))


def test_split_without_generated_focus() -> None:
    for p in generate_personas(DEFAULT_BRACKETS):
        shared = p.system_prompt[: p.shared_prompt_chars]
        assert shared.startswith(RULES) and shared.endswith("\n")
        assert "This cycle" not in p.system_prompt


def test_worker_config_carries_the_split() -> None:
    p = _personas()[0]
    assert persona_to_worker_config(p)["shared_prompt_chars"] == p.shared_prompt_chars > 0


def test_interview_prompt_drops_the_rules_in_their_new_position() -> None:
    stripped = _strip_json_instructions(_personas()[0].system_prompt)
    assert "Respond ONLY with a JSON object" not in stripped
    assert stripped == stripped.strip()
    assert AGENT_HEADER_RE.search(stripped) is not None
