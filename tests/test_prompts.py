"""The modifier prompt is rendered from the bracket registry."""

from __future__ import annotations

from alphaswarm.personas import DEFAULT_BRACKETS
from alphaswarm.prompts.modifiers import (
    BRACKET_MODIFIER_HINTS,
    MODIFIER_GENERATION_PROMPT,
    render_modifier_generation_prompt,
)
from alphaswarm.types import BracketType


def test_hints_follow_default_brackets_order() -> None:
    assert list(BRACKET_MODIFIER_HINTS) == [b.bracket_type for b in DEFAULT_BRACKETS]


def test_every_bracket_has_a_hint() -> None:
    assert set(BRACKET_MODIFIER_HINTS) == set(BracketType)


def test_prompt_lists_each_bracket_key_once_in_order() -> None:
    keyed = [
        line[2:].split(":", 1)[0]
        for line in MODIFIER_GENERATION_PROMPT.splitlines()
        if line.startswith("- ") and not line.startswith('- "')
    ]
    assert keyed == [b.bracket_type.value for b in DEFAULT_BRACKETS]


def test_rendering_follows_the_registry() -> None:
    hints = {BracketType.QUANTS: "Quantitative analysts", BracketType.SHORTS: "Forensic sellers"}

    prompt = render_modifier_generation_prompt(hints)

    assert "for each of the 2 market participant brackets" in prompt
    assert "- quants: Quantitative analysts\n- shorts: Forensic sellers\n" in prompt
    assert 'Example: {"quants": "...", "shorts": "..."}' in prompt
    assert "All 2 keys must be present." in prompt
