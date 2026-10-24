"""Seeded per-bracket subsets: control holdout and shock arm (docs/DECISIONS.md#adr-run-manifest)."""

from __future__ import annotations

import random
from collections import Counter

import pytest
from hypothesis import given
from hypothesis import strategies as st

from alphaswarm.peers import (
    seeded_bracket_subset,
    select_control_ids,
    select_shock_treated_ids,
    subset_size,
)
from alphaswarm.personas import DEFAULT_BRACKETS, generate_personas
from alphaswarm.types import AgentPersona, BracketType

PERSONAS = generate_personas(DEFAULT_BRACKETS)
BRACKET_OF = {p.id: p.bracket.value for p in PERSONAS}


def _roster(counts: dict[BracketType, int]) -> list[AgentPersona]:
    return [
        AgentPersona(
            id=f"{bracket.value}_{i:02d}",
            name=f"{bracket.value} {i}",
            bracket=bracket,
            risk_profile=0.5,
            temperature=0.5,
            system_prompt="fictional",
            influence_weight_base=0.5,
        )
        for bracket, count in counts.items()
        for i in range(1, count + 1)
    ]


@pytest.mark.parametrize(
    ("count", "fraction", "expected"),
    [
        (18, 0.2, 4),
        (10, 0.2, 2),
        (12, 0.2, 2),
        (15, 0.2, 3),
        (8, 0.2, 2),
        (7, 0.2, 1),
        (5, 0.2, 1),
        (1, 0.5, 0),
        (2, 0.5, 1),
        (7, 0.5, 4),
        (15, 0.5, 8),
        (18, 0.0, 0),
        (3, 0.5, 2),
    ],
)
def test_subset_size_rounds_half_up_and_keeps_one_outside(count: int, fraction: float, expected: int) -> None:
    assert subset_size(count, fraction) == expected


def test_twenty_percent_holdout_on_the_default_swarm() -> None:
    control = select_control_ids(PERSONAS, fraction=0.2, run_seed="4242")

    assert len(control) == 20
    assert Counter(BRACKET_OF[a] for a in control) == {
        "institutions": 4,
        "sell_side": 2,
        "event_driven": 2,
        "quants": 2,
        "degens": 3,
        "narrators": 2,
        "algos": 2,
        "macro": 1,
        "shorts": 1,
        "allocators": 1,
    }


def test_same_seed_same_set_in_any_roster_order() -> None:
    shuffled = list(PERSONAS)
    random.Random(7).shuffle(shuffled)

    first = select_control_ids(PERSONAS, fraction=0.2, run_seed="4242")

    assert select_control_ids(shuffled, fraction=0.2, run_seed="4242") == first


def test_different_seeds_draw_different_sets() -> None:
    sets = {select_control_ids(PERSONAS, fraction=0.2, run_seed=str(s)) for s in range(1, 6)}

    assert len(sets) > 1


def test_zero_fraction_selects_nobody() -> None:
    assert select_control_ids(PERSONAS, fraction=0.0, run_seed="4242") == frozenset()


def test_shock_arm_is_half_of_each_bracket_and_independent_of_control() -> None:
    arm = select_shock_treated_ids(PERSONAS, run_seed="4242")
    control = select_control_ids(PERSONAS, fraction=0.5, run_seed="4242")

    assert len(arm) == 52
    assert arm != control


@given(
    counts=st.dictionaries(st.sampled_from(list(BracketType)), st.integers(1, 20), min_size=1),
    fraction=st.floats(0.0, 0.5),
    seed=st.text(min_size=1, max_size=12),
)
def test_subset_properties(counts: dict[BracketType, int], fraction: float, seed: str) -> None:
    roster = _roster(counts)
    chosen = seeded_bracket_subset(roster, fraction=fraction, run_seed=seed, salt="control")

    assert chosen <= {p.id for p in roster}
    for bracket, count in counts.items():
        members = {p.id for p in roster if p.bracket is bracket}
        picked = chosen & members
        assert len(picked) == subset_size(count, fraction)
        if count >= 2:
            assert members - picked  # at least one agent stays outside
        else:
            assert not picked
