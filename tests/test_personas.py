"""Tests for persona generation."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from alphaswarm.types import BracketType

if TYPE_CHECKING:
    from alphaswarm.types import AgentPersona, BracketConfig


def test_persona_count(all_personas: list[AgentPersona]) -> None:
    """Exactly 100 personas are generated."""
    assert len(all_personas) == 100


def test_persona_unique_ids(all_personas: list[AgentPersona]) -> None:
    """All 100 persona IDs are unique."""
    ids = [p.id for p in all_personas]
    assert len(set(ids)) == 100


def test_persona_id_format(all_personas: list[AgentPersona]) -> None:
    """Each persona ID matches the expected pattern."""
    pattern = re.compile(r"^[a-z_]+_\d{2}$")
    for p in all_personas:
        assert pattern.match(p.id), f"ID '{p.id}' does not match expected format"


def test_persona_bracket_distribution(all_personas: list[AgentPersona]) -> None:
    """Persona counts per bracket match expected distribution."""
    counts: dict[BracketType, int] = {}
    for p in all_personas:
        counts[p.bracket] = counts.get(p.bracket, 0) + 1

    assert counts[BracketType.QUANTS] == 10
    assert counts[BracketType.DEGENS] == 20
    assert counts[BracketType.SOVEREIGNS] == 10
    assert counts[BracketType.MACRO] == 10
    assert counts[BracketType.SUITS] == 10
    assert counts[BracketType.INSIDERS] == 10
    assert counts[BracketType.AGENTS] == 15
    assert counts[BracketType.DOOM_POSTERS] == 5
    assert counts[BracketType.POLICY_WONKS] == 5
    assert counts[BracketType.WHALES] == 5


def test_persona_immutability(all_personas: list[AgentPersona]) -> None:
    """Frozen persona model rejects attribute mutation."""
    with pytest.raises(ValidationError):
        all_personas[0].name = "changed"  # type: ignore[misc]


def test_persona_inherits_bracket_values(
    all_brackets: list[BracketConfig],
    all_personas: list[AgentPersona],
) -> None:
    """Each persona inherits risk, temperature, and influence from its bracket."""
    bracket_map = {b.bracket_type: b for b in all_brackets}
    for p in all_personas:
        b = bracket_map[p.bracket]
        assert p.risk_profile == b.risk_profile, f"{p.id} risk mismatch"
        assert p.temperature == b.temperature, f"{p.id} temperature mismatch"
        assert p.influence_weight_base == b.influence_weight_base, f"{p.id} influence mismatch"


# --- Phase 5: Enriched persona prompt tests ---


def test_persona_unique_system_prompts(all_personas: list[AgentPersona]) -> None:
    """All 100 personas have unique system_prompt strings."""
    prompts = [p.system_prompt for p in all_personas]
    assert len(set(prompts)) == 100, (
        f"Expected 100 unique prompts, got {len(set(prompts))}"
    )


def test_persona_contains_json_instructions(all_personas: list[AgentPersona]) -> None:
    """Each persona's system_prompt contains the JSON field name 'signal'."""
    for p in all_personas:
        assert "signal" in p.system_prompt, (
            f"{p.id} system_prompt missing JSON field 'signal'"
        )


def test_persona_same_bracket_different_modifiers(all_personas: list[AgentPersona]) -> None:
    """Personas within same bracket have different modifiers (first 2 Quants differ)."""
    quants = [p for p in all_personas if p.bracket == BracketType.QUANTS]
    assert len(quants) >= 2
    assert quants[0].system_prompt != quants[1].system_prompt, (
        "First two Quants personas should have different system prompts"
    )


def test_persona_deterministic_generation() -> None:
    """Round-robin assignment is deterministic: generating twice yields identical prompts."""
    from alphaswarm.config import generate_personas, load_bracket_configs

    brackets = load_bracket_configs()
    run1 = generate_personas(brackets)
    run2 = generate_personas(brackets)
    for p1, p2 in zip(run1, run2):
        assert p1.system_prompt == p2.system_prompt, (
            f"{p1.id} prompt differs between generations"
        )


def test_persona_word_count_under_350(all_personas: list[AgentPersona]) -> None:
    """Each persona's total system_prompt word count stays under 350 words."""
    for p in all_personas:
        word_count = len(p.system_prompt.split())
        assert word_count < 350, (
            f"{p.id} system_prompt has {word_count} words, expected <350"
        )


def test_bracket_modifiers_completeness() -> None:
    """BRACKET_MODIFIERS has an entry for every BracketType (10 entries)."""
    from alphaswarm.config import BRACKET_MODIFIERS

    assert len(BRACKET_MODIFIERS) == 10
    for bt in BracketType:
        assert bt in BRACKET_MODIFIERS, f"BRACKET_MODIFIERS missing {bt.value}"


def test_bracket_modifiers_count_range() -> None:
    """Each bracket has 3-5 modifiers."""
    from alphaswarm.config import BRACKET_MODIFIERS

    for bt, mods in BRACKET_MODIFIERS.items():
        assert 3 <= len(mods) <= 5, (
            f"{bt.value} has {len(mods)} modifiers, expected 3-5"
        )


def test_persona_first_modifier_assignment() -> None:
    """Each bracket's first persona contains the first modifier from BRACKET_MODIFIERS."""
    from alphaswarm.config import BRACKET_MODIFIERS, generate_personas, load_bracket_configs

    personas = generate_personas(load_bracket_configs())
    # Group by bracket
    by_bracket: dict[BracketType, list[AgentPersona]] = {}
    for p in personas:
        by_bracket.setdefault(p.bracket, []).append(p)

    for bt, mods in BRACKET_MODIFIERS.items():
        first_persona = by_bracket[bt][0]
        assert mods[0] in first_persona.system_prompt, (
            f"{bt.value} first persona missing first modifier: '{mods[0][:40]}...'"
        )


# --- Phase 13: generate_personas with modifiers tests ---


def test_generate_personas_with_modifiers_count() -> None:
    """generate_personas with modifiers kwarg still produces exactly 100 personas."""
    from alphaswarm.config import generate_personas, load_bracket_configs
    from alphaswarm.types import BracketType

    brackets = load_bracket_configs()
    modifiers = {bt: f"custom modifier for {bt.value}" for bt in BracketType}
    personas = generate_personas(brackets, modifiers=modifiers)
    assert len(personas) == 100


def test_generate_personas_with_modifiers_content() -> None:
    """When modifiers provided, personas use generated modifier, not static."""
    from alphaswarm.config import BRACKET_MODIFIERS, generate_personas, load_bracket_configs
    from alphaswarm.types import BracketType

    brackets = load_bracket_configs()
    modifiers = {bt: f"entity-aware {bt.value} specialist" for bt in BracketType}
    personas = generate_personas(brackets, modifiers=modifiers)
    quants = [p for p in personas if p.bracket == BracketType.QUANTS]
    for p in quants:
        assert "entity-aware quants specialist" in p.system_prompt
        # Verify static modifier is NOT present
        assert BRACKET_MODIFIERS[BracketType.QUANTS][0] not in p.system_prompt


def test_generate_personas_with_modifiers_same_bracket_same_modifier() -> None:
    """Per D-02: all agents in same bracket share one entity-aware modifier."""
    from alphaswarm.config import generate_personas, load_bracket_configs
    from alphaswarm.types import BracketType

    brackets = load_bracket_configs()
    modifiers = {bt: f"shared modifier for {bt.value}" for bt in BracketType}
    personas = generate_personas(brackets, modifiers=modifiers)
    quants = [p for p in personas if p.bracket == BracketType.QUANTS]
    # All Quants should have the same modifier line
    for p in quants:
        assert "You are a shared modifier for quants." in p.system_prompt


def test_generate_personas_backward_compatible() -> None:
    """generate_personas() without modifiers kwarg matches original output exactly."""
    from alphaswarm.config import generate_personas, load_bracket_configs

    brackets = load_bracket_configs()
    original = generate_personas(brackets)
    with_none = generate_personas(brackets, modifiers=None)
    assert len(original) == len(with_none)
    for p1, p2 in zip(original, with_none):
        assert p1.system_prompt == p2.system_prompt, f"{p1.id} prompt differs"


def test_generate_personas_partial_modifiers() -> None:
    """Partial modifiers dict: provided brackets get generated modifier, missing get static round-robin."""
    from alphaswarm.config import BRACKET_MODIFIERS, generate_personas, load_bracket_configs
    from alphaswarm.types import BracketType

    brackets = load_bracket_configs()
    # Only provide modifiers for QUANTS and DEGENS
    partial = {
        BracketType.QUANTS: "custom quants modifier",
        BracketType.DEGENS: "custom degens modifier",
    }
    personas = generate_personas(brackets, modifiers=partial)
    assert len(personas) == 100
    # Quants get custom modifier
    quants = [p for p in personas if p.bracket == BracketType.QUANTS]
    for p in quants:
        assert "custom quants modifier" in p.system_prompt
    # Sovereigns get static round-robin (no custom modifier)
    sovereigns = [p for p in personas if p.bracket == BracketType.SOVEREIGNS]
    assert BRACKET_MODIFIERS[BracketType.SOVEREIGNS][0] in sovereigns[0].system_prompt
