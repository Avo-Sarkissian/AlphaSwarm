"""One implementation of a simulation round, shared by every round number.

run_round owns the shock-gate side effects, the peer context, the dispatch, the
round-abort check, persistence, influence edges, the round's metrics and the
on_round_complete callback; run_simulation owns seeding, phase transitions, the
worker and governor sessions and the cycle metrics (docs/DECISIONS.md#adr-round-runner).
"""

from __future__ import annotations

import dataclasses
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from typing import TYPE_CHECKING

import structlog

from alphaswarm.batch_dispatcher import dispatch_wave
from alphaswarm.episodes import EpisodeRecord, compute_flip_type, match_entities, new_decision_ids
from alphaswarm.errors import RoundAlignmentError, RoundFailedError
from alphaswarm.metrics import split_flips
from alphaswarm.peers import (
    PeerContextsResult,
    apply_holdout_and_priors,
    build_peer_contexts,
    compute_exposure_metrics,
    select_control_ids,
)
from alphaswarm.personas import persona_to_worker_config
from alphaswarm.state import BracketSummary
from alphaswarm.types import SignalType

if TYPE_CHECKING:
    from alphaswarm.episodes import EntityRef
    from alphaswarm.graph import GraphStateManager, PersistRoundResult
    from alphaswarm.inference.concurrency import ConcurrencyController
    from alphaswarm.inference.provider import InferenceProvider
    from alphaswarm.ingestion.providers import MarketDataProvider, NewsProvider
    from alphaswarm.ingestion.types import ContextPacket
    from alphaswarm.settings import AppSettings
    from alphaswarm.state import StateSink
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


def _with_shocks(rumor: str, shocks: Sequence[str]) -> str:
    """Rumor plus every applied shock, oldest first (one "[MARKET SHOCK]" line each)."""
    return rumor + "".join(f"\n\n[MARKET SHOCK]: {text}" for text in shocks)


@dataclasses.dataclass(frozen=True)
class SimulationDeps:
    """Everything a run needs from outside the engine (docs/DECISIONS.md#adr-round-runner).

    Providers are required and come from alphaswarm.inference.factory; the engine
    never builds or imports Ollama objects. ``state`` is None for headless runs.
    ``context_fixture`` replaces the live market and news fetch with a recorded
    packet for evaluation runs. Public path: alphaswarm.simulation.SimulationDeps.
    """

    settings: AppSettings
    graph: GraphStateManager
    controller: ConcurrencyController
    orchestrator: InferenceProvider
    worker: InferenceProvider
    state: StateSink | None = None
    market: MarketDataProvider | None = None
    news: NewsProvider | None = None
    context_fixture: ContextPacket | None = None


@dataclasses.dataclass(frozen=True)
class RoundOutcome:
    """What one round produced (docs/DECISIONS.md#p7-d-08)."""

    round_num: int
    decisions: tuple[tuple[str, AgentDecision], ...]
    decision_ids: tuple[str, ...]
    exposures: tuple[tuple[str, ...], ...]  # aligned with personas; () entries in round 1
    shift: ShiftMetrics | None  # None for round 1
    bracket_summaries: tuple[BracketSummary, ...]
    influence_weights: Mapping[str, float]  # {} when no edges were computed
    applied_shocks: tuple[str, ...]  # every shock active in this round, oldest first
    seconds: float
    metrics: Mapping[str, float | int | str | bool]  # this round's r{n}_* keys


@dataclasses.dataclass(frozen=True)
class RoundContext:
    """Per-run inputs every round shares."""

    deps: SimulationDeps
    cycle_id: str
    personas: tuple[AgentPersona, ...]
    brackets: tuple[BracketConfig, ...]
    rumor: str
    market_context: str | None  # fenced block for round 1 (docs/DECISIONS.md#adr-market-context)
    entities: tuple[EntityRef, ...]
    run_seed: str
    on_round_complete: OnRoundComplete = None


def _round_metrics(
    round_num: int,
    decisions: Sequence[tuple[str, AgentDecision]],
    *,
    citations_dropped: int,
    shift: ShiftMetrics | None,
    seconds: float,
) -> dict[str, float | int | str | bool]:
    """This round's r{n}_* cycle-metric keys (docs/DECISIONS.md#adr-cycle-metrics)."""
    metrics: dict[str, float | int | str | bool] = {
        f"r{round_num}_seconds": round(seconds, 1),
        f"r{round_num}_parse_errors": sum(1 for _, d in decisions if d.signal == SignalType.PARSE_ERROR),
        f"r{round_num}_inference_errors": sum(1 for _, d in decisions if d.error_kind == "inference"),
        f"r{round_num}_citations_dropped": citations_dropped,
    }
    if shift is not None:
        metrics[f"r{round_num}_flips"] = shift.total_flips
    return metrics


def parse_tier_metrics(
    round_num: int,
    decisions: Sequence[tuple[str, AgentDecision]],
) -> dict[str, int]:
    """Worker parse tiers for one round: ``r{n}_parse_tier1..3``.

    Decisions without a tier (the dispatcher's inference failures) are not
    counted; ``r{n}_parse_tier3`` equals the parse errors the parser produced
    (docs/DECISIONS.md#adr-structured-output).
    """
    counts: Counter[int | None] = Counter(decision.parse_tier for _, decision in decisions)
    return {f"r{round_num}_parse_tier{tier}": counts[tier] for tier in (1, 2, 3)}


async def run_round(
    ctx: RoundContext,
    round_num: int,
    prev: RoundOutcome | None,
    shocks: Sequence[str],
) -> RoundOutcome:
    """Run one round: shock gate, peers, dispatch, abort check, persist, edges, callback.

    The caller has already set the round's phase and number on the state sink.
    ``shocks`` are every shock active for this round, oldest first; those not already
    active in ``prev`` were consumed for this round and are persisted and recorded
    here (docs/DECISIONS.md#b1). Round 1 gets the fenced market context and no peers;
    later rounds get per-reader peer contexts built from ``prev``, minus the seeded
    no-peer holdout, plus each reader's own prior (docs/DECISIONS.md#adr-diverse-peer-context).
    """
    deps = ctx.deps
    started = time.monotonic()
    personas = list(ctx.personas)
    already_active = len(prev.applied_shocks) if prev is not None else 0
    for text in shocks[already_active:]:
        await deps.graph.write_shock_event(ctx.cycle_id, text, injected_before_round=round_num)
        if deps.state is not None:
            deps.state.record_applied_shock(text, round_num)
        logger.info("shock_injected", cycle_id=ctx.cycle_id, round_num=round_num, shock_length=len(text))

    peers: PeerContextsResult | None = None
    control_ids: frozenset[str] | None = None
    own_priors: list[str | None] | None = None
    metrics: dict[str, float | int | str | bool] = {}
    if prev is not None:
        peers = build_peer_contexts(
            personas,
            prev.decisions,
            round_num - 1,
            sim=deps.settings.simulation,
            run_seed=ctx.run_seed,
            global_citation_weights=prev.influence_weights,
        )
        # Seeded no-peer holdout and own priors, before the exposure counts
        # (docs/DECISIONS.md#adr-diverse-peer-context).
        control_ids = select_control_ids(
            personas, fraction=deps.settings.simulation.control_fraction, run_seed=ctx.run_seed
        )
        contexts, exposures, own_priors = apply_holdout_and_priors(
            personas,
            list(peers.contexts),
            list(peers.exposures),
            prev.decisions,
            round_num - 1,
            sim=deps.settings.simulation,
            control_ids=control_ids,
        )
        peers = PeerContextsResult(contexts=tuple(contexts), exposures=tuple(exposures))
        metrics.update(compute_exposure_metrics(peers.exposures, personas, round_num=round_num))
    logger.info(
        "round_dispatch_start",
        cycle_id=ctx.cycle_id,
        round_num=round_num,
        agent_count=len(personas),
        peers_found=sum(1 for c in peers.contexts if c) if peers is not None else 0,
    )

    worker_configs = [persona_to_worker_config(p) for p in personas]
    raw = await dispatch_wave(
        personas=worker_configs,
        governor=deps.controller,
        provider=deps.worker,
        user_message=_with_shocks(ctx.rumor, shocks),
        settings=deps.settings.governor,
        peer_contexts=list(peers.contexts) if peers is not None else None,
        market_context=ctx.market_context if round_num == 1 else None,
        state_store=deps.state,
        round_num=round_num,
        own_priors=own_priors,
    )
    if len(raw) != len(worker_configs):
        raise RoundAlignmentError(round_num, expected=len(worker_configs), actual=len(raw))
    decisions = tuple((config["agent_id"], decision) for config, decision in zip(worker_configs, raw, strict=True))
    _raise_if_round_failed(round_num, decisions, deps.settings.governor.round_abort_failure_percent)
    persisted = await _persist_round_records(
        deps.graph,
        ctx.cycle_id,
        round_num,
        decisions,
        personas=personas,
        peer_contexts=peers.contexts if peers is not None else None,
        prev_decisions=prev.decisions if prev is not None else None,
        entities=ctx.entities,
        control_ids=control_ids or (),
    )

    weights: dict[str, float] = {}
    if prev is not None:
        # Denominator = active agents (docs/DECISIONS.md#f-20); none active -> no edges.
        active = sum(1 for _, d in decisions if d.signal != SignalType.PARSE_ERROR)
        if active > 0:
            weights = await deps.graph.compute_influence_edges(ctx.cycle_id, up_to_round=round_num, total_agents=active)
        else:
            logger.warning("influence_edges_skipped", cycle_id=ctx.cycle_id, round_num=round_num)
        if deps.state is not None:
            # The round's edge step is finished even when it was skipped: its edge set is
            # known (empty), so the frame may fetch it (docs/DECISIONS.md#adr-ws-broadcaster).
            deps.state.bump_edges_version()

    summaries = compute_bracket_summaries(decisions, personas, ctx.brackets)
    if deps.state is not None:
        await deps.state.set_bracket_summaries(summaries)
    shift = compute_shifts(prev.decisions, decisions, personas) if prev is not None else None
    if prev is not None and control_ids is not None:
        flips_control, flips_treated = split_flips(prev.decisions, decisions, control_ids)
        metrics.update(
            {
                f"r{round_num}_control_agents": len(control_ids),
                f"r{round_num}_flips_control": flips_control,
                f"r{round_num}_flips_treated": flips_treated,
            }
        )
    if ctx.on_round_complete is not None:
        await ctx.on_round_complete(
            RoundCompleteEvent(
                round_num=round_num,
                cycle_id=ctx.cycle_id,
                agent_decisions=decisions,
                shift=shift,
                bracket_summaries=summaries,
            )
        )
    seconds = time.monotonic() - started
    metrics.update(
        _round_metrics(
            round_num,
            decisions,
            citations_dropped=persisted.citations_dropped,
            shift=shift,
            seconds=seconds,
        )
    )
    metrics.update(parse_tier_metrics(round_num, decisions))
    logger.info(
        "round_complete",
        cycle_id=ctx.cycle_id,
        round_num=round_num,
        parse_errors=metrics[f"r{round_num}_parse_errors"],
    )
    return RoundOutcome(
        round_num=round_num,
        decisions=decisions,
        decision_ids=tuple(persisted.decision_ids),
        exposures=peers.exposures if peers is not None else tuple(() for _ in personas),
        shift=shift,
        bracket_summaries=summaries,
        influence_weights=weights,
        applied_shocks=tuple(shocks),
        seconds=seconds,
        metrics=metrics,
    )
