"""Deterministic 100-agent cycle written through the public GraphStateManager write API.

The seeded cycle is the fixture behind the read-model and report golden tests. Every value
comes from fixed tables or ``random.Random(SEED)``, so two builds produce identical
decisions, citations and rationales (only generated ids differ). Fictional data only.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from alphaswarm.config import DEFAULT_BRACKETS, generate_personas
from alphaswarm.types import (
    AgentDecision,
    AgentPersona,
    EntityType,
    SeedEntity,
    SeedEvent,
    SignalType,
)
from alphaswarm.write_buffer import EpisodeRecord, compute_flip_type

if TYPE_CHECKING:
    from alphaswarm.graph import GraphStateManager

SEED: Final = 20261003
SEED_RUMOR: Final = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."
SHOCK_TEXT: Final = "ZZZT Holdings says the QQQX Robotics talks ended without a deal."
SHOCK_ROUND: Final = 2
OVERALL_SENTIMENT: Final = 0.45
SEED_ENTITIES: Final[tuple[SeedEntity, ...]] = (
    SeedEntity(name="ZZZT Holdings", type=EntityType.COMPANY, relevance=0.95, sentiment=0.6),
    SeedEntity(name="QQQX Robotics", type=EntityType.COMPANY, relevance=0.9, sentiment=0.4),
    SeedEntity(name="Industrial Automation", type=EntityType.SECTOR, relevance=0.6, sentiment=0.2),
)
# Agents whose decision is a PARSE_ERROR, per round. Round 3 fails the whole Allocators
# bracket (an "empty bracket" for final-round analytics) plus one Degen.
PARSE_ERRORS_BY_ROUND: Final[Mapping[int, frozenset[str]]] = {
    1: frozenset({"quants_05", "degens_07", "algos_03"}),
    2: frozenset({"institutions_09", "degens_07", "shorts_02", "event_driven_04"}),
    3: frozenset(
        {
            "allocators_01",
            "allocators_02",
            "allocators_03",
            "allocators_04",
            "allocators_05",
            "degens_11",
        }
    ),
}
# Cited agents and their distinct-citer totals. The first half of each hub's citers cite in
# round 2 and the rest in round 3, so per-round and cumulative counts are all distinct
# (no ties at any LIMIT cut-off in the influence queries).
HUB_CITATIONS: Final[tuple[tuple[str, int], ...]] = (
    ("sell_side_01", 24),
    ("narrators_01", 22),
    ("institutions_01", 20),
    ("macro_01", 18),
    ("quants_01", 16),
    ("event_driven_01", 14),
    ("degens_01", 12),
    ("algos_01", 10),
    ("shorts_01", 8),
    ("allocators_03", 6),
    ("sell_side_02", 4),
    ("narrators_02", 2),
)
PARSE_FAILED_RATIONALE: Final = "Parse failed: seeded failure"
PEER_CONTEXT_TEXT: Final = "seeded peer context"
_SIGNAL_CYCLE: Final = (SignalType.BUY, SignalType.SELL, SignalType.HOLD)
_ROUND_SECONDS: Final = 10.0


@dataclass(frozen=True)
class SeededCycle:
    cycle_id: str
    num_rounds: int
    personas: tuple[AgentPersona, ...]
    decisions: Mapping[int, tuple[tuple[str, AgentDecision], ...]]
    shock_text: str | None
    shock_round: int | None
    parse_error_agent_ids: frozenset[str]
    cited_pairs: Mapping[int, frozenset[tuple[str, str]]]


def _agent_index(agent_id: str) -> int:
    """1-based index inside the bracket: ``sell_side_03`` -> 3."""
    return int(agent_id.rsplit("_", 1)[1])


def _intended_signals(personas: tuple[AgentPersona, ...], num_rounds: int) -> dict[int, dict[str, SignalType]]:
    """Signal each agent would give if it did not fail.

    Round 1 alternates BUY/SELL/HOLD inside every bracket. In round 2 agent 1 of each
    bracket flips to the next signal; in round 3 agent 2 does. Everyone else holds.
    """
    bracket_order = [b.bracket_type for b in DEFAULT_BRACKETS]
    rounds: dict[int, dict[str, SignalType]] = {1: {}}
    for persona in personas:
        position = _agent_index(persona.id) + bracket_order.index(persona.bracket)
        rounds[1][persona.id] = _SIGNAL_CYCLE[position % 3]
    for round_num in range(2, num_rounds + 1):
        flipper = round_num - 1
        previous = rounds[round_num - 1]
        current: dict[str, SignalType] = {}
        for persona in personas:
            signal = previous[persona.id]
            if _agent_index(persona.id) == flipper:
                signal = _SIGNAL_CYCLE[(_SIGNAL_CYCLE.index(signal) + 1) % 3]
            current[persona.id] = signal
        rounds[round_num] = current
    return rounds


def _citations(
    rng: random.Random, personas: tuple[AgentPersona, ...], num_rounds: int
) -> dict[int, dict[str, list[str]]]:
    """Round -> citing agent -> cited hub ids (HUB_CITATIONS order)."""
    bracket_of = {p.id: p.bracket for p in personas}
    failing = PARSE_ERRORS_BY_ROUND[2] | PARSE_ERRORS_BY_ROUND[3]
    cites: dict[int, dict[str, list[str]]] = {r: {} for r in range(1, num_rounds + 1)}
    for hub_id, total in HUB_CITATIONS:
        candidates = sorted(p.id for p in personas if p.bracket != bracket_of[hub_id] and p.id not in failing)
        citers = rng.sample(candidates, total)
        split = total // 2
        for round_num, group in ((2, citers[:split]), (3, citers[split:])):
            if round_num > num_rounds:
                continue
            for citer in group:
                cites[round_num].setdefault(citer, []).append(hub_id)
    return cites


def _rationale(persona: AgentPersona, index: int, round_num: int, signal: SignalType) -> str:
    """Deterministic rationale; some mention the seeded entities (case varies on purpose)."""
    parts = [f"{persona.name} round {round_num}: {signal.value.upper()}"]
    if (index + round_num) % 3 == 0:
        parts.append("ZZZT Holdings looks stretched at this price")
    if (index + round_num) % 5 == 0:
        parts.append("QQQX Robotics holders would get a premium")
    if (index + round_num) % 7 == 0:
        parts.append("industrial automation peers should rerate")
    if len(parts) == 1:
        parts.append("the tape on this rumor is still thin")
    return "; ".join(parts) + "."


def _sentiment(rng: random.Random, signal: SignalType) -> float:
    if signal is SignalType.BUY:
        return round(rng.uniform(0.15, 0.85), 2)
    if signal is SignalType.SELL:
        return round(-rng.uniform(0.15, 0.85), 2)
    return round(rng.uniform(-0.1, 0.1), 2)


def _round_decisions(
    rng: random.Random,
    personas: tuple[AgentPersona, ...],
    round_num: int,
    intended: Mapping[str, SignalType],
    cites: Mapping[str, list[str]],
) -> tuple[tuple[str, AgentDecision], ...]:
    pool = [round(0.30 + 0.0065 * k, 4) for k in range(len(personas))]
    rng.shuffle(pool)  # distinct confidences inside a round: no ties in ORDER BY confidence
    failing = PARSE_ERRORS_BY_ROUND[round_num]
    out: list[tuple[str, AgentDecision]] = []
    for index, persona in enumerate(personas):
        signal = intended[persona.id]
        sentiment = _sentiment(rng, signal)  # drawn for every agent: stable rng sequence
        if persona.id in failing:
            decision = AgentDecision(
                signal=SignalType.PARSE_ERROR,
                confidence=0.0,
                sentiment=0.0,
                rationale=PARSE_FAILED_RATIONALE,
                cited_agents=[],
            )
        else:
            decision = AgentDecision(
                signal=signal,
                confidence=pool[index],
                sentiment=sentiment,
                rationale=_rationale(persona, index, round_num, signal),
                cited_agents=list(cites.get(persona.id, [])),
            )
        out.append((persona.id, decision))
    return tuple(out)


async def build_seeded_cycle(gm: GraphStateManager, *, num_rounds: int = 3) -> SeededCycle:
    """Write the seeded cycle through the same public calls ``run_simulation`` makes.

    Order per round: write_decisions -> write_rationale_episodes -> write_narrative_edges
    -> compute_influence_edges (rounds >= 2, active-agent denominator). The shock is written
    after round 1, metrics after the last round. Post nodes are not written: no read model
    uses them.
    """
    if num_rounds not in (2, 3):
        raise ValueError(f"num_rounds must be 2 or 3, got {num_rounds}")
    rng = random.Random(SEED)
    personas = tuple(generate_personas(list(DEFAULT_BRACKETS)))
    intended = _intended_signals(personas, num_rounds)
    cites = _citations(rng, personas, num_rounds)

    seed_event = SeedEvent(raw_rumor=SEED_RUMOR, entities=list(SEED_ENTITIES), overall_sentiment=OVERALL_SENTIMENT)
    cycle_id = await gm.create_cycle_with_seed_event(SEED_RUMOR, seed_event, num_rounds=num_rounds)
    entity_names = await gm.read_cycle_entities(cycle_id)

    decisions: dict[int, tuple[tuple[str, AgentDecision], ...]] = {}
    previous: dict[str, SignalType] = {}
    for round_num in range(1, num_rounds + 1):
        if round_num == SHOCK_ROUND:
            await gm.write_shock_event(cycle_id, SHOCK_TEXT, SHOCK_ROUND)
        rows = _round_decisions(rng, personas, round_num, intended[round_num], cites[round_num])
        decision_ids = await gm.write_decisions(list(rows), cycle_id, round_num)
        records = [
            EpisodeRecord(
                decision_id=decision_id,
                agent_id=agent_id,
                rationale=decision.rationale,
                peer_context_received="" if round_num == 1 else PEER_CONTEXT_TEXT,
                flip_type=compute_flip_type(previous.get(agent_id), decision.signal).value,
                round_num=round_num,
                cycle_id=cycle_id,
            )
            for decision_id, (agent_id, decision) in zip(decision_ids, rows, strict=True)
        ]
        await gm.write_rationale_episodes(records)
        await gm.write_narrative_edges(records, entity_names)
        if round_num >= 2:
            active = sum(1 for _, d in rows if d.signal is not SignalType.PARSE_ERROR)
            await gm.compute_influence_edges(cycle_id, up_to_round=round_num, total_agents=active)
        decisions[round_num] = rows
        previous = {agent_id: d.signal for agent_id, d in rows}

    await gm.write_cycle_metrics(cycle_id, _metrics(decisions, num_rounds))
    return SeededCycle(
        cycle_id=cycle_id,
        num_rounds=num_rounds,
        personas=personas,
        decisions=decisions,
        shock_text=SHOCK_TEXT,
        shock_round=SHOCK_ROUND,
        parse_error_agent_ids=frozenset().union(*(PARSE_ERRORS_BY_ROUND[r] for r in range(1, num_rounds + 1))),
        cited_pairs={
            r: frozenset((citer, hub) for citer, hubs in cites[r].items() for hub in hubs)
            for r in range(1, num_rounds + 1)
        },
    )


def _metrics(decisions: Mapping[int, tuple[tuple[str, AgentDecision], ...]], num_rounds: int) -> dict[str, float | int]:
    """Baseline (metrics_version 1) keys with fixed timings."""
    metrics: dict[str, float | int] = {"metrics_version": 1, "num_rounds": num_rounds}
    for round_num in range(1, num_rounds + 1):
        metrics[f"r{round_num}_seconds"] = _ROUND_SECONDS * round_num
        metrics[f"r{round_num}_parse_errors"] = sum(
            1 for _, d in decisions[round_num] if d.signal is SignalType.PARSE_ERROR
        )
        if round_num >= 2:
            before = dict(decisions[round_num - 1])
            metrics[f"r{round_num}_flips"] = sum(
                1
                for agent_id, d in decisions[round_num]
                if compute_flip_type(before[agent_id].signal, d.signal).value != "none"
            )
    metrics["total_seconds"] = sum(_ROUND_SECONDS * r for r in range(1, num_rounds + 1))
    final = decisions[num_rounds]
    metrics["final_buy"] = sum(1 for _, d in final if d.signal is SignalType.BUY)
    metrics["final_sell"] = sum(1 for _, d in final if d.signal is SignalType.SELL)
    metrics["final_hold"] = sum(1 for _, d in final if d.signal is SignalType.HOLD)
    metrics["agent_count"] = len(final)
    return metrics
