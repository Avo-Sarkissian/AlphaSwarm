"""Exact and golden assertions for the GraphStateManager read models on the seeded cycle.

Reads with a known bug get exact assertions on their correct fields only; the bug itself is
pinned with a strict xfail further down. The fixing change removes the xfail and records the
golden in the same commit.
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from collections.abc import Iterable
from typing import TYPE_CHECKING

import pytest

from alphaswarm.config import DEFAULT_BRACKETS
from alphaswarm.interview import _strip_json_instructions
from alphaswarm.types import SeedEvent, SignalType
from alphaswarm.write_buffer import compute_flip_type
from tests.support.golden import assert_golden
from tests.support.seed_builder import (
    HUB_CITATIONS,
    OVERALL_SENTIMENT,
    SEED_ENTITIES,
    SEED_RUMOR,
    SHOCK_ROUND,
    SHOCK_TEXT,
    SeededCycle,
)

if TYPE_CHECKING:
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.types import AgentDecision

pytestmark = pytest.mark.neo4j

_VALID = (SignalType.BUY, SignalType.SELL, SignalType.HOLD)


def _round(seeded: SeededCycle, round_num: int) -> dict[str, AgentDecision]:
    return dict(seeded.decisions[round_num])


def _bracket_of(seeded: SeededCycle) -> dict[str, str]:
    return {p.id: p.bracket.value for p in seeded.personas}


def _counts(decisions: Iterable[AgentDecision]) -> tuple[int, int, int]:
    tally = Counter(d.signal for d in decisions)
    return tally[SignalType.BUY], tally[SignalType.SELL], tally[SignalType.HOLD]


def _counts_by_bracket(seeded: SeededCycle, round_num: int) -> dict[str, tuple[int, int, int]]:
    """Valid-signal counts per bracket; brackets with no valid decision are left out."""
    bracket_of = _bracket_of(seeded)
    grouped: dict[str, list[AgentDecision]] = {}
    for agent_id, decision in seeded.decisions[round_num]:
        grouped.setdefault(bracket_of[agent_id], []).append(decision)
    counts = {bracket: _counts(ds) for bracket, ds in grouped.items()}
    return {bracket: c for bracket, c in counts.items() if sum(c)}


def _majority(buy: int, sell: int, hold: int) -> str:
    """Tie-break order used by the dissenter query: BUY, then SELL, then HOLD."""
    if buy >= sell and buy >= hold:
        return "BUY"
    if sell >= buy and sell >= hold:
        return "SELL"
    return "HOLD"


def _active(seeded: SeededCycle, round_num: int) -> int:
    return sum(1 for _, d in seeded.decisions[round_num] if d.signal in _VALID)


async def test_read_cycle_seed(graph_reader: GraphStateManager, seeded_cycle: SeededCycle) -> None:
    assert await graph_reader.read_cycle_seed(seeded_cycle.cycle_id) == SEED_RUMOR
    assert await graph_reader.read_cycle_seed("00000000-0000-4000-8000-00000000dead") is None


async def test_read_cycle_entities(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    names = await graph_reader.read_cycle_entities(seeded_cycle.cycle_id)
    assert sorted(names) == sorted(e.name for e in SEED_ENTITIES)


async def test_read_influence_edges(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    by_round: dict[str, list[dict[str, object]]] = {}
    for round_num in range(2, seeded_cycle.num_rounds + 1):
        rows = await graph_reader.read_influence_edges(seeded_cycle.cycle_id, round_num)
        rows = sorted(rows, key=lambda r: (r["source_id"], r["target_id"]))  # no ORDER BY
        cumulative: set[tuple[str, str]] = set().union(
            *(seeded_cycle.cited_pairs[r] for r in range(2, round_num + 1))
        )
        assert {(r["source_id"], r["target_id"]) for r in rows} == cumulative
        citers = Counter(target for _, target in cumulative)
        active = _active(seeded_cycle, round_num)
        for row in rows:
            assert row["weight"] == pytest.approx(citers[row["target_id"]] / active)
        by_round[f"round_{round_num}"] = rows
    assert await graph_reader.read_influence_edges(seeded_cycle.cycle_id, 1) == []
    assert_golden("reads/read_influence_edges.json", by_round)


async def test_read_agent_interview_context(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    personas = {p.id: p for p in seeded_cycle.personas}
    contexts: dict[str, dict[str, object]] = {}
    for agent_id in ("sell_side_01", "degens_07"):
        ctx = await graph_reader.read_agent_interview_context(agent_id, seeded_cycle.cycle_id)
        expected_prompt = _strip_json_instructions(personas[agent_id].system_prompt)
        assert ctx.interview_system_prompt == expected_prompt
        assert [(d.round_num, d.signal) for d in ctx.decisions] == [
            (r, _round(seeded_cycle, r)[agent_id].signal.value)
            for r in range(1, seeded_cycle.num_rounds + 1)
        ]
        # decision_narrative lives on the global Agent node, so other tests can change it.
        contexts[agent_id] = {
            **dataclasses.asdict(ctx),
            "interview_system_prompt": "<asserted above>",
            "decision_narrative": "<not pinned>",
        }
    assert_golden("reads/read_agent_interview_context.json", contexts)


async def test_read_consensus_summary_counts(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    row = await graph_reader.read_consensus_summary(seeded_cycle.cycle_id)
    final = _round(seeded_cycle, seeded_cycle.num_rounds).values()
    assert (row["buy_count"], row["sell_count"], row["hold_count"]) == _counts(final)
    assert_golden("reads/read_consensus_summary.json", row)


async def test_read_round_timeline_counts(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    rows = await graph_reader.read_round_timeline(seeded_cycle.cycle_id)
    assert [(r["round_num"], r["buy_count"], r["sell_count"], r["hold_count"]) for r in rows] == [
        (n, *_counts(_round(seeded_cycle, n).values()))
        for n in range(1, seeded_cycle.num_rounds + 1)
    ]
    assert_golden("reads/read_round_timeline.json", rows)


async def test_read_bracket_narratives_counts(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    rows = await graph_reader.read_bracket_narratives(seeded_cycle.cycle_id)
    expected = _counts_by_bracket(seeded_cycle, seeded_cycle.num_rounds)
    got = {
        r["bracket"]: (r["buy_count"], r["sell_count"], r["hold_count"])
        for r in rows
        if r["bracket"] in expected
    }
    assert got == expected
    assert [r["bracket"] for r in rows] == [b.bracket_type.value for b in DEFAULT_BRACKETS]
    assert_golden("reads/read_bracket_narratives.json", rows)


async def test_read_key_dissenters_valid_rows(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    rows = await graph_reader.read_key_dissenters(seeded_cycle.cycle_id)
    bracket_of = _bracket_of(seeded_cycle)
    final_round = seeded_cycle.num_rounds
    majorities = {
        b: _majority(*c) for b, c in _counts_by_bracket(seeded_cycle, final_round).items()
    }
    expected = sorted(
        (bracket_of[agent_id], agent_id, d.signal.value.upper(), majorities[bracket_of[agent_id]])
        for agent_id, d in seeded_cycle.decisions[final_round]
        if d.signal in _VALID and d.signal.value.upper() != majorities[bracket_of[agent_id]]
    )
    got = [
        (r["bracket"], r["agent_id"], r["signal"], r["bracket_majority"])
        for r in rows
        if r["signal"] != SignalType.PARSE_ERROR.value
    ]
    assert got == expected
    assert_golden("reads/read_key_dissenters.json", rows)


async def test_read_influence_leaders_rank_by_citations(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    rows = await graph_reader.read_influence_leaders(seeded_cycle.cycle_id)
    assert [(r["agent_id"], r["citation_count"]) for r in rows] == list(HUB_CITATIONS[:10])
    assert_golden("reads/read_influence_leaders.json", rows)


async def test_read_signal_flips(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    rows = await graph_reader.read_signal_flips(seeded_cycle.cycle_id)
    keys = [(r["round_num"], r["bracket"]) for r in rows]
    assert keys == sorted(keys), "documented order: re.round, a.bracket"
    assert len(keys) == len(set(keys)), "seeded cycle has at most one flip per bracket per round"
    expected = set()
    for n in range(2, seeded_cycle.num_rounds + 1):
        before, after = _round(seeded_cycle, n - 1), _round(seeded_cycle, n)
        for agent_id, d in after.items():
            flip = compute_flip_type(before[agent_id].signal, d.signal).value
            if flip != "none":
                expected.add((agent_id, n, flip, d.signal.value.upper()))
    got = {(r["agent_id"], r["round_num"], r["flip_type"], r["final_signal"]) for r in rows}
    assert got == expected
    assert_golden("reads/read_signal_flips.json", rows)


async def test_read_entity_impact_entities(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    rows = await graph_reader.read_entity_impact(seeded_cycle.cycle_id)
    assert {(r["entity_name"], r["entity_type"]) for r in rows} == {
        (e.name, e.type.value) for e in SEED_ENTITIES
    }
    counts = [r["mention_count"] for r in rows]
    assert counts == sorted(counts, reverse=True), "documented order: mention_count DESC"
    assert_golden("reads/read_entity_impact.json", rows)


async def test_read_latest_cycle_id_returns_newest(
    graph_manager_test: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    event = SeedEvent(
        raw_rumor=SEED_RUMOR, entities=list(SEED_ENTITIES), overall_sentiment=OVERALL_SENTIMENT
    )
    newest = await graph_manager_test.create_cycle_with_seed_event(
        SEED_RUMOR, event, num_rounds=3
    )
    assert newest != seeded_cycle.cycle_id
    assert await graph_manager_test.read_latest_cycle_id() == newest


async def test_read_shock_event(graph_reader: GraphStateManager, seeded_cycle: SeededCycle) -> None:
    row = await graph_reader.read_shock_event(seeded_cycle.cycle_id)
    assert row is not None
    assert (row["shock_text"], row["injected_before_round"]) == (SHOCK_TEXT, SHOCK_ROUND)
    assert_golden("reads/read_shock_event.json", row)


async def test_read_shock_impact_identity(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    result = await graph_reader.read_shock_impact(seeded_cycle.cycle_id)
    assert (result["shock_text"], result["injected_before_round"]) == (SHOCK_TEXT, SHOCK_ROUND)


async def test_read_full_cycle_signals(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    states = await graph_reader.read_full_cycle_signals(seeded_cycle.cycle_id)
    expected = {
        (agent_id, n): (d.signal, d.confidence)
        for n, decisions in seeded_cycle.decisions.items()
        for agent_id, d in decisions
    }
    assert {key: (s.signal, s.confidence) for key, s in states.items()} == expected
    flat = {
        f"{agent_id}|r{n}": {"signal": s.signal, "confidence": s.confidence}
        for (agent_id, n), s in sorted(states.items())
    }
    assert_golden("reads/read_full_cycle_signals.json", flat)


async def test_read_completed_cycles(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    rows = [
        r
        for r in await graph_reader.read_completed_cycles(limit=100)
        if r["cycle_id"] == seeded_cycle.cycle_id
    ]
    assert len(rows) == 1
    assert (rows[0]["seed_rumor"], rows[0]["round_count"]) == (SEED_RUMOR, seeded_cycle.num_rounds)
    assert_golden("reads/read_completed_cycles.json", rows)


@pytest.mark.parametrize("round_num", [1, 2, 3])
async def test_read_bracket_narratives_for_round_counts(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle, round_num: int
) -> None:
    rows = await graph_reader.read_bracket_narratives_for_round(seeded_cycle.cycle_id, round_num)
    expected = _counts_by_bracket(seeded_cycle, round_num)
    got = {
        r["bracket"]: (r["buy_count"], r["sell_count"], r["hold_count"])
        for r in rows
        if r["bracket"] in expected
    }
    assert got == expected


async def test_read_rationale_entries_for_round(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    by_round: dict[str, list[dict[str, object]]] = {}
    for n in range(1, seeded_cycle.num_rounds + 1):
        rows = await graph_reader.read_rationale_entries_for_round(seeded_cycle.cycle_id, n)
        top = sorted(
            (
                (d.confidence, agent_id)
                for agent_id, d in seeded_cycle.decisions[n]
                if d.signal in _VALID
            ),
            reverse=True,
        )[:10]
        assert [r["agent_id"] for r in rows] == [agent_id for _, agent_id in top]
        decisions = _round(seeded_cycle, n)
        for row in rows:
            assert row["rationale"] == decisions[row["agent_id"]].rationale
            assert row["round_num"] == n
        by_round[f"round_{n}"] = rows
    assert_golden("reads/read_rationale_entries_for_round.json", by_round)


# ---------------------------------------------------------------------------
# Known bugs, pinned. Remove the marker in the commit that fixes the bug.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True, reason="T2.2: shock bracket deltas never carry pre_dominant (fix: plan 06)"
)
async def test_shock_impact_bracket_deltas_carry_pre_dominant(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    result = await graph_reader.read_shock_impact(seeded_cycle.cycle_id)
    assert result["bracket_deltas"]
    assert all("pre_dominant" in delta for delta in result["bracket_deltas"])


@pytest.mark.xfail(
    strict=True, reason="T2.2: replay bracket rows have no total, so replay shows 0 (fix: plan 06)"
)
async def test_replay_bracket_rows_carry_total(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    rows = await graph_reader.read_bracket_narratives_for_round(seeded_cycle.cycle_id, 1)
    assert rows
    for row in rows:
        decided = row["buy_count"] + row["sell_count"] + row["hold_count"]
        assert row["total"] >= decided > 0


async def test_key_dissenters_exclude_parse_errors(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    rows = await graph_reader.read_key_dissenters(seeded_cycle.cycle_id)
    failed = [r["agent_id"] for r in rows if r["signal"].lower() == SignalType.PARSE_ERROR.value]
    assert failed == []


async def test_empty_bracket_has_no_majority(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    rows = {
        r["bracket"]: r for r in await graph_reader.read_bracket_narratives(seeded_cycle.cycle_id)
    }
    assert rows["allocators"]["majority"] is None


async def test_consensus_summary_counts_parse_errors(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    row = await graph_reader.read_consensus_summary(seeded_cycle.cycle_id)
    final = seeded_cycle.decisions[seeded_cycle.num_rounds]
    assert row["parse_error_count"] == sum(1 for _, d in final if d.signal not in _VALID)


async def test_round_timeline_counts_parse_errors(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    rows = await graph_reader.read_round_timeline(seeded_cycle.cycle_id)
    assert [r["parse_error_count"] for r in rows] == [
        sum(1 for _, d in seeded_cycle.decisions[n] if d.signal not in _VALID)
        for n in range(1, seeded_cycle.num_rounds + 1)
    ]


async def test_bracket_averages_exclude_parse_errors(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    rows = {
        r["bracket"]: r for r in await graph_reader.read_bracket_narratives(seeded_cycle.cycle_id)
    }
    bracket_of = _bracket_of(seeded_cycle)
    degens = [
        d.confidence
        for agent_id, d in seeded_cycle.decisions[seeded_cycle.num_rounds]
        if bracket_of[agent_id] == "degens" and d.signal in _VALID
    ]
    assert rows["degens"]["avg_confidence"] == pytest.approx(sum(degens) / len(degens))


@pytest.mark.xfail(
    strict=True, reason="T2.3: shock pivots count transitions to or from PARSE_ERROR (fix: plan 06)"
)
async def test_shock_pivots_exclude_parse_errors(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    result = await graph_reader.read_shock_impact(seeded_cycle.cycle_id)
    failed = SignalType.PARSE_ERROR.value
    assert [
        p for p in result["pivot_agents"] if failed in (p["pre_signal"], p["post_signal"])
    ] == []


async def test_influence_leaders_report_influence_share(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    rows = await graph_reader.read_influence_leaders(seeded_cycle.cycle_id)
    active = _active(seeded_cycle, seeded_cycle.num_rounds)
    assert [r["influence_share"] for r in rows] == pytest.approx(
        [count / active for _, count in HUB_CITATIONS[:10]]
    )


@pytest.mark.xfail(
    strict=True,
    reason="T2.4: READ_POST is never written, so post reach is empty (fix: plan 06 deletes it)",
)
async def test_social_post_reach_has_rows(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    assert await graph_reader.read_social_post_reach(seeded_cycle.cycle_id) != []


async def test_entity_impact_counts_final_round_only(
    graph_reader: GraphStateManager, seeded_cycle: SeededCycle
) -> None:
    rows = await graph_reader.read_entity_impact(seeded_cycle.cycle_id)
    final = seeded_cycle.decisions[seeded_cycle.num_rounds]
    expected = {
        e.name: sum(1 for _, d in final if e.name.lower() in d.rationale.lower())
        for e in SEED_ENTITIES
    }
    assert {r["entity_name"]: r["mention_count"] for r in rows} == expected
