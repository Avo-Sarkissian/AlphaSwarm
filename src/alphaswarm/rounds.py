"""One implementation of a simulation round, shared by every round number.

run_round owns the shock-gate side effects, the peer context, the dispatch, the
round-abort check, persistence, influence edges, the round's metrics and the
on_round_complete callback; run_simulation owns seeding, phase transitions, the
worker and governor sessions and the cycle metrics (docs/DECISIONS.md#adr-round-runner).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Awaitable, Callable, Collection, Sequence
from typing import TYPE_CHECKING

import structlog

from alphaswarm.episodes import EpisodeRecord, compute_flip_type, match_entities, new_decision_ids
from alphaswarm.errors import RoundFailedError
from alphaswarm.state import BracketSummary
from alphaswarm.types import SignalType

if TYPE_CHECKING:
    from alphaswarm.episodes import EntityRef
    from alphaswarm.graph import GraphStateManager, PersistRoundResult
    from alphaswarm.types import AgentDecision, AgentPersona, BracketConfig

logger = structlog.get_logger(component="rounds")


@dataclasses.dataclass(frozen=True)
class ShiftMetrics:
    """Opinion shift metrics between two consecutive rounds.

    Uses tuple and tuple-of-pairs for true immutability in frozen dataclass
    (addresses Codex review concern about mutable list/dict fields).
    """

    signal_transitions: tuple[tuple[str, int], ...]  # (("BUY->SELL", 2), ("SELL->HOLD", 1))
    total_flips: int
    bracket_confidence_delta: tuple[tuple[str, float], ...]  # (("quants", +0.05), ...)
    agents_shifted: int


def compute_bracket_summaries(
    agent_decisions: Sequence[tuple[str, AgentDecision]],
    personas: Sequence[AgentPersona],
    brackets: Sequence[BracketConfig],
) -> tuple[BracketSummary, ...]:
    """Compute per-bracket summaries from a round's decisions (D-07, D-08).

    Promoted from cli.py:_aggregate_brackets() pattern. Excludes PARSE_ERROR agents.
    Returns tuple of BracketSummary for each bracket (preserves bracket config order).
    """
    agent_bracket: dict[str, str] = {p.id: p.bracket.value for p in personas}
    display_lookup: dict[str, str] = {b.bracket_type.value: b.display_name for b in brackets}

    # Accumulators per bracket
    counts: dict[str, dict[str, int]] = {}
    conf_sums: dict[str, float] = {}
    sent_sums: dict[str, float] = {}
    totals: dict[str, int] = {}
    for b in brackets:
        bv = b.bracket_type.value
        counts[bv] = {"buy": 0, "sell": 0, "hold": 0}
        conf_sums[bv] = 0.0
        sent_sums[bv] = 0.0
        totals[bv] = 0

    for agent_id, decision in agent_decisions:
        if decision.signal == SignalType.PARSE_ERROR:
            continue
        agent_bv = agent_bracket.get(agent_id)
        if agent_bv is None or agent_bv not in counts:
            continue
        signal_key = decision.signal.value  # "buy", "sell", "hold"
        counts[agent_bv][signal_key] = counts[agent_bv].get(signal_key, 0) + 1
        conf_sums[agent_bv] += decision.confidence
        sent_sums[agent_bv] += decision.sentiment
        totals[agent_bv] += 1

    result: list[BracketSummary] = []
    for b in brackets:
        bv = b.bracket_type.value
        t = totals[bv]
        result.append(
            BracketSummary(
                bracket=bv,
                display_name=display_lookup.get(bv, bv),
                buy_count=counts[bv]["buy"],
                sell_count=counts[bv]["sell"],
                hold_count=counts[bv]["hold"],
                total=t,
                avg_confidence=conf_sums[bv] / t if t > 0 else 0.0,
                avg_sentiment=sent_sums[bv] / t if t > 0 else 0.0,
            )
        )
    return tuple(result)


@dataclasses.dataclass(frozen=True)
class RoundCompleteEvent:
    """Payload fired via on_round_complete callback after each round finishes.

    Enables progressive CLI output without run_simulation() knowing about print().
    Addresses Gemini MEDIUM / Codex HIGH review concern: reports must print as
    rounds complete, not after run_simulation() returns.
    """

    round_num: int
    cycle_id: str
    agent_decisions: tuple[tuple[str, AgentDecision], ...]
    shift: ShiftMetrics | None  # None for Round 1 (no prior round to compare)
    bracket_summaries: tuple[BracketSummary, ...]  # NEW: per D-08


OnRoundComplete = Callable[[RoundCompleteEvent], Awaitable[None]] | None


def compute_shifts(
    prev_decisions: Sequence[tuple[str, AgentDecision]],
    curr_decisions: Sequence[tuple[str, AgentDecision]],
    personas: Sequence[AgentPersona],
) -> ShiftMetrics:
    """Compute opinion shift metrics between two rounds (D-11, D-12, D-13).

    In-memory comparison, no Neo4j queries needed (per D-13).
    Excludes PARSE_ERROR agents from signal flip counts and confidence deltas.
    """
    prev_map = {aid: dec for aid, dec in prev_decisions}
    curr_map = {aid: dec for aid, dec in curr_decisions}
    persona_bracket = {p.id: p.bracket.value for p in personas}

    signal_transitions_dict: dict[str, int] = {}
    agents_shifted = 0
    bracket_conf_deltas: dict[str, list[float]] = {}

    for agent_id in prev_map:
        prev_dec = prev_map[agent_id]
        curr_dec = curr_map.get(agent_id)
        if curr_dec is None:
            continue
        # Skip PARSE_ERROR agents
        if prev_dec.signal == SignalType.PARSE_ERROR or curr_dec.signal == SignalType.PARSE_ERROR:
            continue

        # Signal flip tracking (D-11)
        if prev_dec.signal != curr_dec.signal:
            key = f"{prev_dec.signal.value.upper()}->{curr_dec.signal.value.upper()}"
            signal_transitions_dict[key] = signal_transitions_dict.get(key, 0) + 1
            agents_shifted += 1

        # Per-bracket confidence delta (D-12)
        bracket = persona_bracket.get(agent_id, "unknown")
        delta = curr_dec.confidence - prev_dec.confidence
        if bracket not in bracket_conf_deltas:
            bracket_conf_deltas[bracket] = []
        bracket_conf_deltas[bracket].append(delta)

    total_flips = sum(signal_transitions_dict.values())
    bracket_confidence_delta = {
        b: sum(deltas) / len(deltas) for b, deltas in bracket_conf_deltas.items() if len(deltas) > 0
    }

    return ShiftMetrics(
        signal_transitions=tuple(sorted(signal_transitions_dict.items())),
        total_flips=total_flips,
        bracket_confidence_delta=tuple(sorted(bracket_confidence_delta.items())),
        agents_shifted=agents_shifted,
    )


def _raise_if_round_failed(
    round_num: int,
    decisions: Sequence[tuple[str, AgentDecision]],
    threshold_percent: float,
) -> None:
    """Abort a round before it is persisted when too many agents failed.

    "Failed" means a PARSE_ERROR decision of any error_kind. The rule is
    ``failed * 100 > threshold_percent * total`` (exactly the threshold
    passes), and an empty round always fails
    (docs/DECISIONS.md#adr-taskgroup-dispatch). Failed agents are not
    re-dispatched.
    """
    total = len(decisions)
    failed = sum(1 for _, d in decisions if d.signal == SignalType.PARSE_ERROR)
    if total == 0 or failed * 100 > threshold_percent * total:
        logger.error(
            "round_failed",
            round_num=round_num,
            failed=failed,
            total=total,
            threshold_percent=threshold_percent,
        )
        raise RoundFailedError(round_num, failed, total, threshold_percent)


async def _persist_round_records(
    graph_manager: GraphStateManager,
    cycle_id: str,
    round_num: int,
    decisions: Sequence[tuple[str, AgentDecision]],
    *,
    personas: Sequence[AgentPersona],
    peer_contexts: Sequence[str | None] | None,
    prev_decisions: Sequence[tuple[str, AgentDecision]] | None,
    entities: Sequence[EntityRef],
    control_ids: Collection[str] = (),
) -> PersistRoundResult:
    """Persist one round atomically through GraphStateManager.persist_round.

    Builds the round's EpisodeRecords (peer context aligned with
    ``personas``, flip type from ``prev_decisions``) and entity matches, then
    writes Decisions, CITED, episodes and REFERENCES in one transaction
    (docs/DECISIONS.md#p4-d-08). ``control_ids`` marks the seeded no-peer
    holdout on its Decisions (docs/DECISIONS.md#adr-diverse-peer-context).
    """
    decision_ids = new_decision_ids(len(decisions))
    peer_by_agent: dict[str, str] = {}
    if peer_contexts is not None:
        peer_by_agent = {p.id: (ctx or "") for p, ctx in zip(personas, peer_contexts, strict=True)}
    prev_signal = {aid: d.signal for aid, d in prev_decisions} if prev_decisions else {}
    episodes = [
        EpisodeRecord(
            decision_id=did,
            agent_id=agent_id,
            rationale=decision.rationale,
            peer_context_received=peer_by_agent.get(agent_id, ""),
            flip_type=compute_flip_type(prev_signal.get(agent_id), decision.signal).value,
            round_num=round_num,
            cycle_id=cycle_id,
        )
        for did, (agent_id, decision) in zip(decision_ids, decisions, strict=True)
    ]
    return await graph_manager.persist_round(
        cycle_id,
        round_num,
        decisions,
        decision_ids=decision_ids,
        episodes=episodes,
        entity_matches=match_entities(episodes, entities),
        control_ids=control_ids,
    )


# ---------------------------------------------------------------------------
# Full 3-round simulation orchestrator (Phase 7)
# ---------------------------------------------------------------------------


def _with_shocks(rumor: str, shocks: Sequence[str]) -> str:
    """Rumor plus every applied shock, oldest first (one "[MARKET SHOCK]" line each)."""
    return rumor + "".join(f"\n\n[MARKET SHOCK]: {text}" for text in shocks)
