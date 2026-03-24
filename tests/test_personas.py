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
