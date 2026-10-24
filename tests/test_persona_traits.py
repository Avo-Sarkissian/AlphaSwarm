"""Seeded persona traits break the prompt twins (docs/DECISIONS.md#adr-persona-traits)."""

from __future__ import annotations

import pytest

from alphaswarm.personas import (
    BRACKET_MODIFIERS,
    TRAIT_HORIZONS,
    assign_traits,
    generate_personas,
    load_bracket_configs,
    persona_body,
    prompt_twin_groups,
    render_traits,
    trait_for,
)
from alphaswarm.types import BracketType
from tests.inference.fakes import AGENT_HEADER_RE

BRACKETS = load_bracket_configs()


def test_trait_pools_cover_every_bracket() -> None:
    assert set(TRAIT_HORIZONS) == set(BracketType)


@pytest.mark.parametrize("seed", [101, 102, 103, 104])
def test_every_persona_body_is_unique_with_traits(seed: int) -> None:
    personas = generate_personas(BRACKETS, seed=seed)
    assert len({persona_body(p.system_prompt) for p in personas}) == len(personas) == 100


def test_traits_are_deterministic_and_seed_specific() -> None:
    assert assign_traits(BRACKETS, seed=101) == assign_traits(BRACKETS, seed=101)
    assert assign_traits(BRACKETS, seed=101) != assign_traits(BRACKETS, seed=102)


def test_prompt_twins_never_share_traits() -> None:
    traits = assign_traits(BRACKETS, seed=101)
    for group in prompt_twin_groups(generate_personas(BRACKETS)):
        combos = [traits[agent_id] for agent_id in group]
        assert len(set(combos)) == len(combos), group


def test_no_seed_means_the_previous_prompts() -> None:
    plain = generate_personas(BRACKETS)
    assert all("Your horizon:" not in p.system_prompt for p in plain)
    assert [p.system_prompt for p in plain] == [p.system_prompt for p in generate_personas(BRACKETS, seed=None)]


def test_traits_leave_the_shared_prefix_alone() -> None:
    plain = generate_personas(BRACKETS)
    seeded = generate_personas(BRACKETS, seed=101)
    for before, after in zip(plain, seeded, strict=True):
        assert after.shared_prompt_chars == before.shared_prompt_chars
        prefix = before.system_prompt[: before.shared_prompt_chars]
        assert after.system_prompt[: after.shared_prompt_chars] == prefix


def test_trait_line_sits_with_the_agent_modifier_and_the_header_still_matches() -> None:
    traits = assign_traits(BRACKETS, seed=101)
    for persona in generate_personas(BRACKETS, seed=101):
        assert render_traits(traits[persona.id]) in persona.system_prompt
        assert AGENT_HEADER_RE.search(persona.system_prompt) is not None
        modifier = next(m for m in BRACKET_MODIFIERS[persona.bracket] if f"You are a {m}." in persona.system_prompt)
        assert persona.system_prompt.index(modifier) < persona.system_prompt.index("Your horizon:")


def test_render_traits_is_one_line() -> None:
    line = render_traits(assign_traits(BRACKETS, seed=7)["quants_01"])
    assert line.startswith("Your horizon: ") and line.endswith(".\n") and line.count("\n") == 1


def test_a_large_bracket_keeps_each_modifier_group_distinct() -> None:
    big = next(b for b in BRACKETS if b.bracket_type is BracketType.QUANTS)
    big = big.model_copy(update={"count": 60})
    groups = len(BRACKET_MODIFIERS[BracketType.QUANTS])
    picks = [trait_for(big, i, seed=5) for i in range(1, 61)]
    for group in range(groups):
        members = picks[group::groups]
        assert len(set(members)) == len(members)
