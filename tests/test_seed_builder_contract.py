"""build_seeded_cycle against an autospecced GraphStateManager (offline, no Neo4j)."""

from __future__ import annotations

from collections import Counter
from unittest.mock import create_autospec

import pytest

from alphaswarm.graph import GraphStateManager
from alphaswarm.types import BracketType, SignalType
from alphaswarm.write_buffer import compute_flip_type
from tests.support.seed_builder import (
    HUB_CITATIONS,
    PARSE_ERRORS_BY_ROUND,
    SEED_ENTITIES,
    SEED_RUMOR,
    SHOCK_ROUND,
    SHOCK_TEXT,
    SeededCycle,
    build_seeded_cycle,
)

CYCLE_ID = "00000000-0000-4000-8000-0000000000aa"


def _fake_graph() -> GraphStateManager:
    gm = create_autospec(GraphStateManager, instance=True)
    gm.create_cycle_with_seed_event.return_value = CYCLE_ID
    gm.read_cycle_entities.return_value = [e.name for e in SEED_ENTITIES]
    gm.write_decisions.side_effect = lambda decisions, cycle_id, round_num, **_: [
        f"d{round_num}-{i}" for i in range(len(decisions))
    ]
    gm.compute_influence_edges.return_value = {}
    gm.write_shock_event.return_value = "shock-1"
    return gm


async def _build(num_rounds: int = 3) -> tuple[SeededCycle, GraphStateManager]:
    gm = _fake_graph()
    return await build_seeded_cycle(gm, num_rounds=num_rounds), gm


def _flips(seeded: SeededCycle, round_num: int) -> list[str]:
    before = dict(seeded.decisions[round_num - 1])
    return [
        agent_id
        for agent_id, d in seeded.decisions[round_num]
        if compute_flip_type(before[agent_id].signal, d.signal).value != "none"
    ]


async def test_shape_matches_the_contract() -> None:
    seeded, _ = await _build()
    assert seeded.cycle_id == CYCLE_ID
    assert seeded.num_rounds == 3
    assert len(seeded.personas) == 100
    assert sorted(seeded.decisions) == [1, 2, 3]
    assert all(len(rows) == 100 for rows in seeded.decisions.values())
    assert [agent_id for agent_id, _ in seeded.decisions[1]] == [p.id for p in seeded.personas]
    assert (seeded.shock_text, seeded.shock_round) == (SHOCK_TEXT, SHOCK_ROUND)


async def test_parse_errors_are_at_least_three_per_round() -> None:
    seeded, _ = await _build()
    for round_num, rows in seeded.decisions.items():
        failed = {agent_id for agent_id, d in rows if d.signal is SignalType.PARSE_ERROR}
        assert failed == PARSE_ERRORS_BY_ROUND[round_num]
        assert len(failed) >= 3
    assert seeded.parse_error_agent_ids == frozenset().union(*PARSE_ERRORS_BY_ROUND.values())


async def test_every_bracket_flips_between_rounds_1_and_2() -> None:
    seeded, _ = await _build()
    bracket_of = {p.id: p.bracket for p in seeded.personas}
    assert {bracket_of[agent_id] for agent_id in _flips(seeded, 2)} == set(BracketType)


async def test_citations_cross_brackets_and_match_decisions() -> None:
    seeded, _ = await _build()
    bracket_of = {p.id: p.bracket for p in seeded.personas}
    assert seeded.cited_pairs[1] == frozenset()
    for round_num in (2, 3):
        from_decisions = frozenset(
            (agent_id, cited) for agent_id, d in seeded.decisions[round_num] for cited in d.cited_agents
        )
        assert from_decisions == seeded.cited_pairs[round_num]
        assert all(bracket_of[a] != bracket_of[b] for a, b in from_decisions)


async def test_rankings_have_no_ties() -> None:
    seeded, _ = await _build()
    for rows in seeded.decisions.values():
        confidences = [d.confidence for _, d in rows if d.signal is not SignalType.PARSE_ERROR]
        assert len(confidences) == len(set(confidences))
    for up_to in (2, 3):
        pairs = set().union(*(seeded.cited_pairs[r] for r in range(2, up_to + 1)))
        counts = list(Counter(target for _, target in pairs).values())
        assert len(counts) == len(set(counts)) == len(HUB_CITATIONS)
    bracket_of = {p.id: p.bracket for p in seeded.personas}
    for round_num in (2, 3):
        brackets = [bracket_of[agent_id] for agent_id in _flips(seeded, round_num)]
        assert len(brackets) == len(set(brackets))


async def test_build_is_deterministic() -> None:
    first, _ = await _build()
    second, _ = await _build()

    def dump(seeded: SeededCycle) -> dict[int, list[tuple[str, dict[str, object]]]]:
        return {r: [(a, d.model_dump()) for a, d in rows] for r, rows in seeded.decisions.items()}

    assert dump(first) == dump(second)
    assert first.cited_pairs == second.cited_pairs


async def test_writes_follow_the_simulation_order() -> None:
    _, gm = await _build()
    round_writes = ["write_decisions", "write_rationale_episodes", "write_narrative_edges"]
    assert [call[0] for call in gm.mock_calls] == [
        "create_cycle_with_seed_event",
        "read_cycle_entities",
        *round_writes,
        "write_shock_event",
        *round_writes,
        "compute_influence_edges",
        *round_writes,
        "compute_influence_edges",
        "write_cycle_metrics",
    ]
    assert gm.create_cycle_with_seed_event.await_args.args[0] == SEED_RUMOR
    assert gm.create_cycle_with_seed_event.await_args.kwargs == {"num_rounds": 3}
    gm.write_shock_event.assert_awaited_once_with(CYCLE_ID, SHOCK_TEXT, SHOCK_ROUND)
    assert [c.kwargs for c in gm.compute_influence_edges.await_args_list] == [
        {"up_to_round": 2, "total_agents": 96},
        {"up_to_round": 3, "total_agents": 94},
    ]
    metrics = gm.write_cycle_metrics.await_args.args[1]
    assert (metrics["num_rounds"], metrics["agent_count"], metrics["r3_parse_errors"]) == (
        3,
        100,
        6,
    )


async def test_two_round_build_and_invalid_round_counts() -> None:
    seeded, gm = await _build(num_rounds=2)
    assert sorted(seeded.decisions) == [1, 2]
    assert gm.compute_influence_edges.await_count == 1
    with pytest.raises(ValueError, match="num_rounds must be 2 or 3"):
        await build_seeded_cycle(_fake_graph(), num_rounds=4)
