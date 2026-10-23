"""Invariant: round-2 peer feeds must not be monopolised by one bracket."""

from __future__ import annotations

from collections import Counter

from alphaswarm.types import AgentPersona
from tests.engine.scenario import RunScenario, round_calls
from tests.inference.fakes import ScriptedProvider

MAX_BRACKET_SLOT_SHARE = 0.35
MIN_READER_VISIBILITY = 0.15


async def test_round_2_peer_exposure_is_spread_across_brackets(
    run_scenario: RunScenario,
    scripted_worker: ScriptedProvider,
    all_personas: list[AgentPersona],
) -> None:
    await run_scenario(num_rounds=2)
    bracket_of = {p.id: p.bracket.value for p in all_personas}
    calls = round_calls(scripted_worker, 2)
    slots = Counter(bracket_of[pid] for c in calls for pid in c.shown_peer_ids)
    readers = Counter(b for c in calls for b in {bracket_of[pid] for pid in c.shown_peer_ids})
    total = sum(slots.values())
    assert total > 0
    worst = max(slots.values()) / total
    assert worst <= MAX_BRACKET_SLOT_SHARE, f"one bracket holds {worst:.0%}: {dict(slots)}"
    starved = {
        b: readers.get(b, 0) / len(calls)
        for b in sorted({p.bracket.value for p in all_personas})
        if readers.get(b, 0) / len(calls) < MIN_READER_VISIBILITY
    }
    assert not starved, f"brackets visible to < 15% of readers: {starved}"
