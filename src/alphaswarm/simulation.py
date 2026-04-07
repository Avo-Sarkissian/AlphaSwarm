"""Simulation pipeline for AlphaSwarm.

Composes inject_seed, dispatch_wave, and write_decisions into:
- run_round1(): Single-round standalone pipeline (Phase 6)
- run_simulation(): Full 3-round consensus cascade (Phase 7)

run_simulation() calls run_round1() for Round 1, then orchestrates
Rounds 2-3 with per-agent peer context injection. Fires on_round_complete
callback after each round for progressive CLI output.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Awaitable, Callable

import structlog

from alphaswarm.batch_dispatcher import dispatch_wave
from alphaswarm.config import generate_modifiers, generate_personas, persona_to_worker_config
from alphaswarm.market_data import fetch_market_data
from alphaswarm.seed import inject_seed
from alphaswarm.state import BracketSummary
from alphaswarm.types import SignalType, SimulationPhase
from alphaswarm.utils import sanitize_rationale
from alphaswarm.write_buffer import EpisodeRecord, WriteBuffer, compute_flip_type

if TYPE_CHECKING:
    from alphaswarm.config import AppSettings, BracketConfig, GovernorSettings
    from alphaswarm.governor import ResourceGovernor
    from alphaswarm.graph import GraphStateManager, PeerDecision, RankedPost
    from alphaswarm.ollama_client import OllamaClient
    from alphaswarm.ollama_models import OllamaModelManager
    from alphaswarm.state import StateStore
    from alphaswarm.types import AgentDecision, AgentPersona, MarketDataSnapshot, ParsedModifiersResult, ParsedSeedResult

logger = structlog.get_logger(component="simulation")


@dataclasses.dataclass(frozen=True)
class Round1Result:
    """Immutable result container for the Round 1 pipeline.

    agent_decisions is the single canonical collection. Use it
    to derive decisions list when needed (no redundant field).
    """

    cycle_id: str
    parsed_result: ParsedSeedResult
    agent_decisions: list[tuple[str, AgentDecision]]
    decision_ids: list[str] = dataclasses.field(default_factory=list)
    modifier_result: ParsedModifiersResult | None = None


@dataclasses.dataclass(frozen=True)
class RoundDispatchResult:
    """Result from _dispatch_round including peer contexts for episode storage (Phase 11).

    peer_contexts is aligned by persona index, empty string for no context.
    """

    agent_decisions: list[tuple[str, AgentDecision]]
    peer_contexts: list[str]  # Aligned by persona index, "" for no context


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
    agent_decisions: list[tuple[str, AgentDecision]] | tuple[tuple[str, AgentDecision], ...],
    personas: list[AgentPersona],
    brackets: list[BracketConfig],
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
        bv = agent_bracket.get(agent_id)
        if bv is None or bv not in counts:
            continue
        signal_key = decision.signal.value  # "buy", "sell", "hold"
        counts[bv][signal_key] = counts[bv].get(signal_key, 0) + 1
        conf_sums[bv] += decision.confidence
        sent_sums[bv] += decision.sentiment
        totals[bv] += 1

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


def select_diverse_peers(
    agent_id: str,
    influence_weights: dict[str, float],
    personas: list[AgentPersona],
    prev_decisions: dict[str, AgentDecision] | None = None,
    limit: int = 5,
    min_brackets: int = 3,
) -> list[str]:
    """Select top-N peers with bracket diversity guarantee (D-06).

    Algorithm:
    1. Exclude self from candidates.
    2. Exclude agents with PARSE_ERROR decisions if prev_decisions provided.
    3. Group by bracket, sort each group by dynamic weight descending.
    4. Sort brackets by their top agent's weight.
    5. Phase 1: Pick top-1 from top-min_brackets brackets.
    6. Phase 2: Fill remaining slots by pure weight (any bracket).

    If fewer than min_brackets have candidates, fills from available brackets
    (best effort, always returns up to `limit` peers).

    Args:
        agent_id: The requesting agent's ID (excluded from results).
        influence_weights: {agent_id: weight} from compute_influence_edges().
        personas: All agent personas for bracket lookup.
        prev_decisions: Optional {agent_id: AgentDecision} from previous round.
            Used to exclude PARSE_ERROR agents from peer candidates.
        limit: Maximum peers to return (default 5).
        min_brackets: Minimum distinct brackets to ensure (default 3, best effort).

    Returns:
        list[str]: Ordered list of up to `limit` peer agent IDs.
    """
    from collections import defaultdict

    # Explicit self-exclusion + PARSE_ERROR exclusion
    parse_error_ids: set[str] = set()
    if prev_decisions is not None:
        parse_error_ids = {
            aid for aid, dec in prev_decisions.items()
            if dec.signal == SignalType.PARSE_ERROR
        }

    candidates = [
        p for p in personas
        if p.id != agent_id and p.id not in parse_error_ids
    ]

    bracket_groups: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for p in candidates:
        w = influence_weights.get(p.id, 0.0)
        bracket_groups[p.bracket.value].append((p.id, w))

    for bracket in bracket_groups:
        bracket_groups[bracket].sort(key=lambda x: x[1], reverse=True)

    sorted_brackets = sorted(
        bracket_groups.keys(),
        key=lambda b: bracket_groups[b][0][1] if bracket_groups[b] else 0.0,
        reverse=True,
    )

    selected: list[str] = []

    # Phase 1: top-1 from top-min_brackets brackets
    for bracket in sorted_brackets:
        if len(selected) >= min_brackets:
            break
        if bracket_groups[bracket]:
            agent, _ = bracket_groups[bracket].pop(0)
            selected.append(agent)

    # Phase 2: fill remaining by pure weight
    remaining: list[tuple[str, float]] = []
    for bracket in bracket_groups:
        remaining.extend(bracket_groups[bracket])
    remaining.sort(key=lambda x: x[1], reverse=True)

    for agent, _ in remaining:
        if len(selected) >= limit:
            break
        if agent not in selected:
            selected.append(agent)

    return selected


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


@dataclasses.dataclass(frozen=True)
class SimulationResult:
    """Immutable result for the full 3-round simulation (per D-08).

    Uses tuples for true immutability (Codex review concern).
    """

    cycle_id: str
    parsed_result: ParsedSeedResult
    round1_decisions: tuple[tuple[str, AgentDecision], ...]
    round2_decisions: tuple[tuple[str, AgentDecision], ...]
    round3_decisions: tuple[tuple[str, AgentDecision], ...]
    round2_shifts: ShiftMetrics
    round3_shifts: ShiftMetrics
    round1_summaries: tuple[BracketSummary, ...]  # NEW: per D-08
    round2_summaries: tuple[BracketSummary, ...]  # NEW: per D-08
    round3_summaries: tuple[BracketSummary, ...]  # NEW: per D-08


OnRoundComplete = Callable[[RoundCompleteEvent], Awaitable[None]] | None


# ---------------------------------------------------------------------------
# TUI data helpers (Phase 10: TUI-03, TUI-04, TUI-05)
# ---------------------------------------------------------------------------


async def _push_top_rationales(
    agent_decisions: list[tuple[str, AgentDecision]] | tuple[tuple[str, AgentDecision], ...],
    round_num: int,
    state_store: StateStore,
    influence_weights: dict[str, float] | None = None,
    limit: int = 10,
) -> None:
    """Push top-influence agent rationales to StateStore queue (D-02, TUI-03).

    Selects agents by influence weight (if available) or by confidence (fallback).
    Skips PARSE_ERROR agents. Truncates rationale to 50 characters per D-03.

    Args:
        agent_decisions: All agent decisions for this round.
        round_num: Round number (1, 2, or 3).
        state_store: StateStore to push RationaleEntry objects to.
        influence_weights: Optional {agent_id: weight} from compute_influence_edges().
            When provided and non-empty, sorts by influence weight descending.
            Fallback: sorts by confidence descending.
        limit: Maximum entries to push (default 10).
    """
    from alphaswarm.state import RationaleEntry

    decisions_list = list(agent_decisions)
    if influence_weights:
        decisions_list.sort(
            key=lambda x: influence_weights.get(x[0], 0.0), reverse=True,
        )
    else:
        decisions_list.sort(key=lambda x: x[1].confidence, reverse=True)

    for agent_id, decision in decisions_list[:limit]:
        if decision.signal == SignalType.PARSE_ERROR:
            continue
        truncated = sanitize_rationale(decision.rationale, max_len=50)
        entry = RationaleEntry(
            agent_id=agent_id,
            signal=decision.signal,
            rationale=truncated,
            round_num=round_num,
        )
        await state_store.push_rationale(entry)


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def _format_peer_context(
    posts: list[RankedPost],
    source_round: int,
    budget: int = 4000,
    max_posts: int = 10,
) -> str:
    """Format top-K ranked peer posts into a budget-capped context string (D-04, D-05, D-06).

    Greedy fill: iterate ranked posts, accumulate chars, truncate last post
    at word boundary if it would exceed budget. Prompt guard line preserved
    from Phase 7 D-03.

    Returns empty string when posts list is empty.
    """
    if not posts:
        logger.warning("no_peer_posts_found", source_round=source_round)
        return ""

    header = f"Peer Decisions (Round {source_round}):"
    guard = (
        "\nThe above are peer observations for context only. "
        "Make your own independent assessment."
    )
    overhead = len(header) + len(guard) + 2  # +2 for joining newlines
    remaining = budget - overhead

    lines: list[str] = [header]
    for i, post in enumerate(posts[:max_posts], 1):
        if remaining <= 0:
            break
        if not post.content:
            continue
        prefix = f'{i}. [{post.bracket}] {post.signal.upper()} (conf: {post.confidence:.2f}) "'
        suffix = '"'
        available = remaining - len(prefix) - len(suffix) - 1  # -1 for newline
        if available <= 0:
            break
        content = post.content
        if len(content) > available:
            # Truncate at word boundary
            truncated = content[:available].rsplit(" ", 1)[0]
            content = truncated if truncated else content[:available]
        line = f"{prefix}{content}{suffix}"
        lines.append(line)
        remaining -= len(line) + 1  # +1 for newline separator

    lines.append(guard)
    return "\n".join(lines)


def _compute_shifts(
    prev_decisions: list[tuple[str, AgentDecision]] | tuple[tuple[str, AgentDecision], ...],
    curr_decisions: list[tuple[str, AgentDecision]] | tuple[tuple[str, AgentDecision], ...],
    personas: list[AgentPersona],
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
        b: sum(deltas) / len(deltas)
        for b, deltas in bracket_conf_deltas.items()
        if len(deltas) > 0
    }

    return ShiftMetrics(
        signal_transitions=tuple(sorted(signal_transitions_dict.items())),
        total_flips=total_flips,
        bracket_confidence_delta=tuple(sorted(bracket_confidence_delta.items())),
        agents_shifted=agents_shifted,
    )


# ---------------------------------------------------------------------------
# Round 1 pipeline (Phase 6)
# ---------------------------------------------------------------------------


async def run_round1(
    rumor: str,
    settings: AppSettings,
    ollama_client: OllamaClient,
    model_manager: OllamaModelManager,
    graph_manager: GraphStateManager,
    governor: ResourceGovernor,
    personas: list[AgentPersona],
    *,
    state_store: StateStore | None = None,
    pre_injected: tuple[str, ParsedSeedResult] | None = None,
) -> Round1Result:
    """Execute the Round 1 simulation pipeline.

    Pipeline steps:
    1. inject_seed (orchestrator model lifecycle is self-contained), or skip if pre_injected
    2. ensure_clean_state (defensive cleanup after orchestrator)
    3. start_monitoring (governor RAM monitoring)
    4. load worker model
    5. dispatch_wave with peer_context=None (Round 1 = no peer influence)
    6. Positional assertion (dispatch results must match persona count)
    7. Pair agent IDs with decisions
    8. write_decisions with round_num=1
    9. Cleanup: unload worker (inner finally), stop monitoring (outer finally)

    Args:
        rumor: Raw seed rumor text.
        settings: Application settings.
        ollama_client: OllamaClient for inference.
        model_manager: Model lifecycle manager.
        graph_manager: Neo4j graph state manager.
        governor: ResourceGovernor for concurrency control.
        personas: List of AgentPersona to dispatch.
        pre_injected: Optional (cycle_id, parsed_result) when seed injection
            was already performed by the caller (e.g., run_simulation for Phase 13
            modifier generation). Skips inject_seed when provided.

    Returns:
        Round1Result with cycle_id, parsed_result, and agent_decisions.
    """
    logger.info("round1_start", agent_count=len(personas))

    if pre_injected is not None:
        cycle_id, parsed_result = pre_injected
    else:
        # StateStore: mark SEEDING phase
        if state_store is not None:
            await state_store.set_phase(SimulationPhase.SEEDING)

        # 1. Inject seed (orchestrator model lifecycle is self-contained)
        cycle_id, parsed_result, _modifier_result = await inject_seed(
            rumor, settings, ollama_client, model_manager, graph_manager,
        )

    # StateStore: mark ROUND_1 phase after seed injection
    if state_store is not None:
        await state_store.set_phase(SimulationPhase.ROUND_1)
        await state_store.set_round(1)

    # 2. Defensive model cleanup (review concern #4)
    await model_manager.ensure_clean_state()

    worker_alias = settings.ollama.worker_model_alias

    # 3. Start governor monitoring (review concern #1 -- must happen before dispatch)
    await governor.start_monitoring()
    try:
        # 4. Load worker model
        await model_manager.load_model(worker_alias)
        try:
            # 5. Convert personas and dispatch
            worker_configs = [persona_to_worker_config(p) for p in personas]
            decisions = await dispatch_wave(
                personas=worker_configs,
                governor=governor,
                client=ollama_client,
                model=worker_alias,
                user_message=rumor,
                settings=settings.governor,
                peer_context=None,
                state_store=state_store,
            )

            # 6. Positional alignment assertion (review concern #3)
            assert len(decisions) == len(worker_configs), (
                f"dispatch_wave returned {len(decisions)} results "
                f"for {len(worker_configs)} personas"
            )

            # 7. Pair agent IDs with decisions
            agent_decisions: list[tuple[str, AgentDecision]] = [
                (wc["agent_id"], dec)
                for wc, dec in zip(worker_configs, decisions)
            ]

            # Per-agent StateStore writes (D-02: immediate per-agent, not batch)
            if state_store is not None:
                for agent_id, dec in agent_decisions:
                    await state_store.update_agent_state(agent_id, dec.signal, dec.confidence)

            # 8. Persist to Neo4j (Phase 11: capture returned decision_ids)
            round1_decision_ids = await graph_manager.write_decisions(
                agent_decisions, cycle_id, round_num=1,
            )
        finally:
            # 9a. Always unload worker model (inner finally)
            await model_manager.unload_model(worker_alias)
    finally:
        # 9b. Always stop governor monitoring (outer finally)
        await governor.stop_monitoring()

    # 10. Log completion and return
    error_count = sum(
        1 for _, d in agent_decisions if d.signal == SignalType.PARSE_ERROR
    )
    logger.info(
        "round1_complete",
        cycle_id=cycle_id,
        decision_count=len(agent_decisions),
        parse_error_count=error_count,
    )

    return Round1Result(
        cycle_id=cycle_id,
        parsed_result=parsed_result,
        agent_decisions=agent_decisions,
        decision_ids=round1_decision_ids,
    )


# ---------------------------------------------------------------------------
# Rounds 2-3 dispatch helper (Phase 7)
# ---------------------------------------------------------------------------


async def _dispatch_round(
    personas: list[AgentPersona],
    cycle_id: str,
    source_round: int,
    graph_manager: GraphStateManager,
    governor: ResourceGovernor,
    client: OllamaClient,
    model: str,
    rumor: str,
    settings: GovernorSettings,
    *,
    influence_weights: dict[str, float] | None = None,
    prev_decisions: list[tuple[str, AgentDecision]] | tuple[tuple[str, AgentDecision], ...] | None = None,
    state_store: StateStore | None = None,
) -> RoundDispatchResult:
    """Dispatch a round with per-agent peer context (D-09, D-10).

    When influence_weights is provided AND non-empty (and prev_decisions available):
    - Uses select_diverse_peers for bracket-diverse dynamic peer selection (D-06).
    - Builds PeerDecision objects from in-memory prev_decisions data.

    When influence_weights is None OR empty dict (zero-citation fallback, D-05):
    - Falls back to static influence_weight_base ordering via read_peer_decisions (Neo4j).
    - This path is expected for Round 2 when Round 1 has no citations (cold-start per Pitfall 1).

    Uses ValueError for runtime contract checks (Codex review: assert disappears under -O).
    """
    from alphaswarm.graph import PeerDecision, RankedPost

    worker_configs = [persona_to_worker_config(p) for p in personas]

    # Determine whether to use dynamic or static peer selection
    use_dynamic = (
        influence_weights is not None
        and len(influence_weights) > 0
        and prev_decisions is not None
    )

    peer_contexts: list[str | None] = []

    def _peer_to_ranked(peer: PeerDecision, weight: float = 0.0) -> RankedPost:
        """Convert a PeerDecision to RankedPost for _format_peer_context compatibility."""
        return RankedPost(
            post_id="",  # No post_id in legacy PeerDecision path
            agent_id=peer.agent_id,
            bracket=peer.bracket,
            signal=peer.signal,
            confidence=peer.confidence,
            content=peer.rationale,
            influence_weight=weight,
            round_num=source_round,
        )

    if use_dynamic:
        # Dynamic path: bracket-diverse peer selection using influence weights (D-06)
        assert influence_weights is not None  # narrowing for type checker
        assert prev_decisions is not None     # narrowing for type checker
        persona_lookup = {p.id: p for p in personas}
        prev_dict: dict[str, AgentDecision] = {aid: dec for aid, dec in prev_decisions}

        for persona in personas:
            peer_ids = select_diverse_peers(
                persona.id,
                influence_weights,
                personas,
                prev_decisions=prev_dict,
            )
            ranked_posts = [
                RankedPost(
                    post_id="",
                    agent_id=pid,
                    bracket=persona_lookup[pid].bracket.value,
                    signal=prev_dict[pid].signal.value,
                    confidence=prev_dict[pid].confidence,
                    content=prev_dict[pid].rationale,
                    influence_weight=influence_weights.get(pid, 0.0),
                    round_num=source_round,
                )
                for pid in peer_ids
                if pid in prev_dict and pid in persona_lookup
            ]
            ctx = _format_peer_context(ranked_posts, source_round)
            peer_contexts.append(ctx if ctx else None)

        logger.info(
            "round_dispatch_start",
            round_num=source_round + 1,
            agent_count=len(personas),
            peers_found=sum(1 for c in peer_contexts if c),
            peer_selection="dynamic",
        )
    else:
        # Static path (zero-citation fallback): sequential Neo4j reads per D-05
        logger.info(
            "dynamic_peer_fallback_to_static",
            reason="empty_weights_or_no_prev_decisions",
            round_num=source_round,
        )
        # Sequential peer reads (D-10: reads happen BEFORE dispatch)
        # Sequential avoids Neo4j connection pool exhaustion (Pitfall 3)
        for persona in personas:
            peers = await graph_manager.read_peer_decisions(
                persona.id, cycle_id, source_round, limit=5,
            )
            ranked_posts = [_peer_to_ranked(p) for p in peers]
            ctx = _format_peer_context(ranked_posts, source_round)
            # Empty string from _format_peer_context means no peers found -> pass None
            peer_contexts.append(ctx if ctx else None)

        logger.info(
            "round_dispatch_start",
            round_num=source_round + 1,
            agent_count=len(personas),
            peers_found=sum(1 for c in peer_contexts if c),
            peer_selection="static",
        )

    decisions = await dispatch_wave(
        personas=worker_configs,
        governor=governor,
        client=client,
        model=model,
        user_message=rumor,
        settings=settings,
        peer_contexts=peer_contexts,
        state_store=state_store,
    )

    if len(decisions) != len(worker_configs):
        raise ValueError(
            f"dispatch_wave returned {len(decisions)} results "
            f"for {len(worker_configs)} personas"
        )

    agent_decisions: list[tuple[str, AgentDecision]] = [
        (wc["agent_id"], dec)
        for wc, dec in zip(worker_configs, decisions)
    ]

    # Per-agent StateStore writes (D-02)
    if state_store is not None:
        for agent_id, dec in agent_decisions:
            await state_store.update_agent_state(agent_id, dec.signal, dec.confidence)

    # Phase 11: normalize peer_contexts (None -> "") and return with decisions
    normalized_peer_contexts: list[str] = [
        ctx if ctx is not None else "" for ctx in peer_contexts
    ]
    return RoundDispatchResult(
        agent_decisions=agent_decisions,
        peer_contexts=normalized_peer_contexts,
    )


# ---------------------------------------------------------------------------
# Full 3-round simulation orchestrator (Phase 7)
# ---------------------------------------------------------------------------


async def run_simulation(
    rumor: str,
    settings: AppSettings,
    ollama_client: OllamaClient,
    model_manager: OllamaModelManager,
    graph_manager: GraphStateManager,
    governor: ResourceGovernor,
    personas: list[AgentPersona],
    brackets: list[BracketConfig],
    *,
    on_round_complete: OnRoundComplete = None,
    state_store: StateStore | None = None,
    generate_narratives: bool = True,
) -> SimulationResult:
    """Execute the full 3-round simulation pipeline (D-04).

    Phase transitions (D-07): IDLE -> SEEDING -> ROUND_1 -> ROUND_2 -> ROUND_3 -> COMPLETE
    Logged via structlog, not persisted to StateStore.

    Progressive output (addresses Gemini/Codex review): fires on_round_complete
    callback after each round finishes, enabling CLI to print reports in real time.

    Lifecycle:
    1. run_round1() handles SEEDING + ROUND_1 (owns its own governor session per D-06)
    2. Compute influence edges after Round 1 (D-02: shapes Round 2 peer selection)
    3. Compute Round 1 bracket summaries (D-08)
    4. Fire on_round_complete for Round 1 (shift=None, no prior round to compare)
    5. ensure_clean_state + reload worker (D-05: one cold load for modularity)
    6. Fresh governor monitoring session for Rounds 2-3 block (D-06)
    7. Round 2: _dispatch_round with dynamic weights if available (fallback to static) -> write -> callback
    8. Compute influence edges after Round 2 (D-04: cumulative, up_to_round=2)
    9. Round 3: _dispatch_round with Round 2 weights -> write -> callback
    10. Return SimulationResult with all bracket summaries (D-08)
    """
    phase = SimulationPhase.IDLE
    logger.info("simulation_start", phase=phase.value)
    if state_store is not None:
        await state_store.set_phase(SimulationPhase.IDLE)

    # Phase 13: Seed injection with modifier generation (D-06: same orchestrator session)
    phase = SimulationPhase.SEEDING
    logger.info("simulation_phase_transition", phase=phase.value)
    if state_store is not None:
        await state_store.set_phase(SimulationPhase.SEEDING)

    cycle_id, parsed_result, modifier_result = await inject_seed(
        rumor, settings, ollama_client, model_manager, graph_manager,
        modifier_generator=generate_modifiers,
    )

    # Phase 13: Regenerate personas with entity-aware modifiers (D-01, D-02)
    if modifier_result is not None:
        personas = generate_personas(brackets, modifiers=modifier_result.modifiers)
        logger.info("personas_regenerated_with_modifiers", parse_tier=modifier_result.parse_tier)

    # Phase 17: Fetch market data for extracted tickers (D-07)
    # Must complete before Round 1 per DATA-01 / ENRICH-01
    market_snapshots: dict[str, MarketDataSnapshot] = {}
    if parsed_result.seed_event.tickers:
        logger.info(
            "market_data_fetch_start",
            ticker_count=len(parsed_result.seed_event.tickers),
            tickers=[t.symbol for t in parsed_result.seed_event.tickers],
        )
        market_snapshots = await fetch_market_data(
            parsed_result.seed_event.tickers,
            av_key=settings.alpha_vantage_api_key,
        )
        # Persist to Neo4j (D-12, D-13)
        await graph_manager.create_ticker_with_market_data(cycle_id, market_snapshots)
        logger.info(
            "market_data_fetch_complete",
            fetched=len(market_snapshots),
            degraded=[s for s, snap in market_snapshots.items() if snap.is_degraded],
        )

    # Round 1 dispatch (skip inject_seed since we already did it)
    round1_result = await run_round1(
        rumor, settings, ollama_client, model_manager,
        graph_manager, governor, personas,
        state_store=state_store,
        pre_injected=(cycle_id, parsed_result),
    )
    cycle_id = round1_result.cycle_id

    phase = SimulationPhase.ROUND_1
    logger.info("simulation_phase_transition", phase=phase.value, cycle_id=cycle_id)

    # Phase 11: Initialize WriteBuffer and load entity names cache once (D-01, D-09)
    write_buffer = WriteBuffer(maxsize=200)
    entity_names = await graph_manager.read_cycle_entities(cycle_id)

    # Phase 11: Push Round 1 episodes to WriteBuffer (retroactive -- run_round1 already wrote decisions)
    for did, (agent_id, decision) in zip(round1_result.decision_ids, round1_result.agent_decisions):
        record = EpisodeRecord(
            decision_id=did,
            agent_id=agent_id,
            rationale=decision.rationale,
            peer_context_received="",  # Round 1 has no peer context (Pitfall 3)
            flip_type=compute_flip_type(None, decision.signal).value,
            round_num=1,
            cycle_id=cycle_id,
        )
        await write_buffer.push(record)
    round1_flushed = await write_buffer.flush(graph_manager, entity_names)
    logger.info("write_buffer_flushed", round_num=1, flushed=round1_flushed)

    # Phase 12: Write Round 1 Post nodes from Decision rationale (D-13)
    round1_post_ids = await graph_manager.write_posts(
        round1_result.agent_decisions,
        round1_result.decision_ids,
        cycle_id,
        round_num=1,
    )

    # Compute influence edges after Round 1 (D-02: shapes Round 2 peer selection)
    # Pass len(round1_result.agent_decisions) as total_agents (active agents, not global 100)
    round1_weights = await graph_manager.compute_influence_edges(
        cycle_id, up_to_round=1, total_agents=len(round1_result.agent_decisions),
    )

    # Compute Round 1 bracket summaries (D-08)
    round1_summaries = compute_bracket_summaries(
        round1_result.agent_decisions, personas, brackets,
    )

    # Push bracket summaries and rationale entries to StateStore (Phase 10: TUI-05, TUI-03)
    if state_store is not None:
        await state_store.set_bracket_summaries(round1_summaries)
        await _push_top_rationales(
            round1_result.agent_decisions, 1, state_store, influence_weights=round1_weights,
        )

    # Fire callback for Round 1 (progressive output)
    round1_decisions_tuple = tuple(round1_result.agent_decisions)
    if on_round_complete is not None:
        await on_round_complete(RoundCompleteEvent(
            round_num=1,
            cycle_id=cycle_id,
            agent_decisions=round1_decisions_tuple,
            shift=None,
            bracket_summaries=round1_summaries,
        ))

    # Reload worker for Rounds 2-3 (D-05)
    await model_manager.ensure_clean_state()
    worker_alias = settings.ollama.worker_model_alias

    # Fresh governor monitoring for Rounds 2-3 block (D-06)
    await governor.start_monitoring()
    try:
        # Round 2 (D-09: peer context from Round 1)
        # Build peer contexts BEFORE loading model to minimize idle keep_alive drain.
        phase = SimulationPhase.ROUND_2
        logger.info("simulation_phase_transition", phase=phase.value, cycle_id=cycle_id)
        if state_store is not None:
            await state_store.set_phase(SimulationPhase.ROUND_2)
            await state_store.set_round(2)

        # Phase 12: Build peer contexts from Round 1 posts (D-12 ordering)
        round2_peer_contexts: list[str | None] = []
        all_round1_post_ids = round1_post_ids  # For READ_POST edges
        for persona in personas:
            ranked_posts = await graph_manager.read_ranked_posts(
                persona.id, cycle_id, source_round=1, limit=10,
            )
            ctx = _format_peer_context(ranked_posts, source_round=1)
            round2_peer_contexts.append(ctx if ctx else None)

        # Phase 12: Write READ_POST edges for Round 2 (D-09, D-10, D-11)
        agent_ids = [p.id for p in personas]
        if all_round1_post_ids:
            await graph_manager.write_read_post_edges(
                agent_ids, all_round1_post_ids, round_num=2, cycle_id=cycle_id,
            )

        logger.info(
            "round_dispatch_start",
            round_num=2,
            agent_count=len(personas),
            peers_found=sum(1 for c in round2_peer_contexts if c),
            peer_selection="ranked_posts",
        )

        # Load worker model immediately before dispatch — no idle gap
        await model_manager.load_model(worker_alias)
        try:
            # Dispatch Round 2 with pre-built peer contexts (bypass _dispatch_round)
            worker_configs = [persona_to_worker_config(p) for p in personas]
            round2_wave_decisions = await dispatch_wave(
                personas=worker_configs,
                governor=governor,
                client=ollama_client,
                model=worker_alias,
                user_message=rumor,
                settings=settings.governor,
                peer_contexts=round2_peer_contexts,
                state_store=state_store,
            )
            round2_decisions: list[tuple[str, AgentDecision]] = [
                (wc["agent_id"], dec) for wc, dec in zip(worker_configs, round2_wave_decisions)
            ]
            # Per-agent StateStore writes
            if state_store is not None:
                for agent_id, dec in round2_decisions:
                    await state_store.update_agent_state(agent_id, dec.signal, dec.confidence)

            # Normalize peer contexts for episode storage
            round2_peer_contexts_normalized: list[str] = [
                ctx if ctx is not None else "" for ctx in round2_peer_contexts
            ]

            round2_ids = await graph_manager.write_decisions(round2_decisions, cycle_id, round_num=2)

            # Phase 12: Write Round 2 Post nodes (D-12 step 2)
            round2_post_ids = await graph_manager.write_posts(
                round2_decisions, round2_ids, cycle_id, round_num=2,
            )

            # Phase 11: Push Round 2 episodes to WriteBuffer
            round1_map = {aid: dec for aid, dec in round1_result.agent_decisions}
            for did, (agent_id, decision) in zip(round2_ids, round2_decisions):
                prev_signal = round1_map.get(agent_id)
                prev_sig = prev_signal.signal if prev_signal else None
                persona_idx = next((i for i, p in enumerate(personas) if p.id == agent_id), None)
                peer_ctx = (
                    round2_peer_contexts_normalized[persona_idx]
                    if persona_idx is not None and persona_idx < len(round2_peer_contexts_normalized)
                    else ""
                )
                record = EpisodeRecord(
                    decision_id=did,
                    agent_id=agent_id,
                    rationale=decision.rationale,
                    peer_context_received=peer_ctx,
                    flip_type=compute_flip_type(prev_sig, decision.signal).value,
                    round_num=2,
                    cycle_id=cycle_id,
                )
                await write_buffer.push(record)
            round2_flushed = await write_buffer.flush(graph_manager, entity_names)
            logger.info("write_buffer_flushed", round_num=2, flushed=round2_flushed)

            # Compute influence edges after Round 2 (D-04: cumulative, up_to_round=2)
            round2_weights = await graph_manager.compute_influence_edges(
                cycle_id, up_to_round=2, total_agents=len(round2_decisions),
            )

            # Compute Round 2 bracket summaries (D-08)
            round2_summaries = compute_bracket_summaries(round2_decisions, personas, brackets)

            # Push bracket summaries and rationale entries to StateStore (Phase 10: TUI-05, TUI-03)
            if state_store is not None:
                await state_store.set_bracket_summaries(round2_summaries)
                await _push_top_rationales(
                    round2_decisions, 2, state_store, influence_weights=round2_weights,
                )

            # Compute Round 2 shifts in-memory (D-13)
            round2_shifts = _compute_shifts(
                round1_result.agent_decisions, round2_decisions, personas,
            )

            # Fire callback for Round 2 (progressive output)
            round2_decisions_tuple = tuple(
                (aid, dec) for aid, dec in round2_decisions
            )
            if on_round_complete is not None:
                await on_round_complete(RoundCompleteEvent(
                    round_num=2,
                    cycle_id=cycle_id,
                    agent_decisions=round2_decisions_tuple,
                    shift=round2_shifts,
                    bracket_summaries=round2_summaries,
                ))

            # Round 3 (D-09: peer context from Round 2)
            phase = SimulationPhase.ROUND_3
            logger.info("simulation_phase_transition", phase=phase.value, cycle_id=cycle_id)
            if state_store is not None:
                await state_store.set_phase(SimulationPhase.ROUND_3)
                await state_store.set_round(3)

            # Phase 12: Build peer contexts from Round 2 posts (D-12 ordering)
            round3_peer_contexts: list[str | None] = []
            for persona in personas:
                ranked_posts = await graph_manager.read_ranked_posts(
                    persona.id, cycle_id, source_round=2, limit=10,
                )
                ctx = _format_peer_context(ranked_posts, source_round=2)
                round3_peer_contexts.append(ctx if ctx else None)

            # Phase 12: Write READ_POST edges for Round 3
            if round2_post_ids:
                await graph_manager.write_read_post_edges(
                    agent_ids, round2_post_ids, round_num=3, cycle_id=cycle_id,
                )

            logger.info(
                "round_dispatch_start",
                round_num=3,
                agent_count=len(personas),
                peers_found=sum(1 for c in round3_peer_contexts if c),
                peer_selection="ranked_posts",
            )

            # Dispatch Round 3 with pre-built peer contexts
            round3_wave_decisions = await dispatch_wave(
                personas=worker_configs,
                governor=governor,
                client=ollama_client,
                model=worker_alias,
                user_message=rumor,
                settings=settings.governor,
                peer_contexts=round3_peer_contexts,
                state_store=state_store,
            )
            round3_decisions: list[tuple[str, AgentDecision]] = [
                (wc["agent_id"], dec) for wc, dec in zip(worker_configs, round3_wave_decisions)
            ]
            if state_store is not None:
                for agent_id, dec in round3_decisions:
                    await state_store.update_agent_state(agent_id, dec.signal, dec.confidence)

            round3_peer_contexts_normalized: list[str] = [
                ctx if ctx is not None else "" for ctx in round3_peer_contexts
            ]

            round3_ids = await graph_manager.write_decisions(round3_decisions, cycle_id, round_num=3)

            # Phase 12: Write Round 3 Post nodes
            round3_post_ids = await graph_manager.write_posts(
                round3_decisions, round3_ids, cycle_id, round_num=3,
            )

            # Phase 11: Push Round 3 episodes to WriteBuffer
            round2_map = {aid: dec for aid, dec in round2_decisions}
            for did, (agent_id, decision) in zip(round3_ids, round3_decisions):
                prev_signal = round2_map.get(agent_id)
                prev_sig = prev_signal.signal if prev_signal else None
                persona_idx = next((i for i, p in enumerate(personas) if p.id == agent_id), None)
                peer_ctx = (
                    round3_peer_contexts_normalized[persona_idx]
                    if persona_idx is not None and persona_idx < len(round3_peer_contexts_normalized)
                    else ""
                )
                record = EpisodeRecord(
                    decision_id=did,
                    agent_id=agent_id,
                    rationale=decision.rationale,
                    peer_context_received=peer_ctx,
                    flip_type=compute_flip_type(prev_sig, decision.signal).value,
                    round_num=3,
                    cycle_id=cycle_id,
                )
                await write_buffer.push(record)
            round3_flushed = await write_buffer.flush(graph_manager, entity_names)
            logger.info("write_buffer_flushed", round_num=3, flushed=round3_flushed)

            # Compute Round 3 bracket summaries (D-08)
            round3_summaries = compute_bracket_summaries(round3_decisions, personas, brackets)

            # Push bracket summaries and rationale entries to StateStore (Phase 10: TUI-05, TUI-03)
            if state_store is not None:
                await state_store.set_bracket_summaries(round3_summaries)
                await _push_top_rationales(round3_decisions, 3, state_store)

            # Compute Round 3 shifts in-memory (D-13)
            round3_shifts = _compute_shifts(
                round2_decisions, round3_decisions, personas,
            )

            # Fire callback for Round 3 (progressive output)
            round3_decisions_tuple = tuple(
                (aid, dec) for aid, dec in round3_decisions
            )
            if on_round_complete is not None:
                await on_round_complete(RoundCompleteEvent(
                    round_num=3,
                    cycle_id=cycle_id,
                    agent_decisions=round3_decisions_tuple,
                    shift=round3_shifts,
                    bracket_summaries=round3_summaries,
                ))

            # Phase 11: Post-simulation narrative generation (D-10, D-11)
            # Worker model is still loaded here -- generate before unload
            if generate_narratives:
                logger.info("narrative_generation_start", agent_count=len(personas))
                narratives = await _generate_decision_narratives(
                    personas=personas,
                    all_decisions={
                        1: round1_result.agent_decisions,
                        2: round2_decisions,
                        3: round3_decisions,
                    },
                    graph_manager=graph_manager,
                    governor=governor,
                    client=ollama_client,
                    model=worker_alias,
                )
                logger.info("narrative_generation_complete", count=len(narratives))

        finally:
            # Always unload worker (inner finally)
            await model_manager.unload_model(worker_alias)
    finally:
        # Always stop governor monitoring (outer finally)
        await governor.stop_monitoring()

    phase = SimulationPhase.COMPLETE
    if state_store is not None:
        await state_store.set_phase(SimulationPhase.COMPLETE)
    logger.info(
        "simulation_complete",
        phase=phase.value,
        cycle_id=cycle_id,
        round2_flips=round2_shifts.total_flips,
        round3_flips=round3_shifts.total_flips,
    )

    return SimulationResult(
        cycle_id=cycle_id,
        parsed_result=round1_result.parsed_result,
        round1_decisions=round1_decisions_tuple,
        round2_decisions=round2_decisions_tuple,
        round3_decisions=round3_decisions_tuple,
        round2_shifts=round2_shifts,
        round3_shifts=round3_shifts,
        round1_summaries=round1_summaries,
        round2_summaries=round2_summaries,
        round3_summaries=round3_summaries,
    )


# ---------------------------------------------------------------------------
# Post-simulation narrative generation helper (Phase 11, D-10, D-11)
# ---------------------------------------------------------------------------


async def _generate_decision_narratives(
    personas: list[AgentPersona],
    all_decisions: dict[int, list[tuple[str, AgentDecision]] | tuple[tuple[str, AgentDecision], ...]],
    graph_manager: GraphStateManager,
    governor: ResourceGovernor,
    client: OllamaClient,
    model: str,
) -> list[dict]:
    """Generate natural-language decision narrative for each agent (D-10, D-11).

    Uses worker model (already loaded) through governor for memory safety.
    Skip-and-log on per-agent failures (Pitfall 5 from research).

    Returns list of {"agent_id": str, "narrative": str} dicts that were written.
    """
    import asyncio as _asyncio

    # Build per-agent decision summaries
    agent_decisions_by_id: dict[str, dict[int, AgentDecision]] = {}
    for round_num, decisions in all_decisions.items():
        for agent_id, decision in decisions:
            if agent_id not in agent_decisions_by_id:
                agent_decisions_by_id[agent_id] = {}
            agent_decisions_by_id[agent_id][round_num] = decision

    persona_map = {p.id: p for p in personas}
    narratives: list[dict] = []
    errors: list[str] = []

    async def _generate_one(agent_id: str) -> dict | None:
        persona = persona_map.get(agent_id)
        if not persona:
            return None
        rounds = agent_decisions_by_id.get(agent_id, {})
        if not rounds:
            return None

        # Build prompt summarizing 3-round arc
        lines = [
            f"Agent: {persona.name} ({persona.bracket.value})",
            f"Risk profile: {persona.risk_profile}",
            "",
        ]
        for rn in sorted(rounds.keys()):
            dec = rounds[rn]
            flip_label = "none"
            if rn > 1:
                prev = rounds.get(rn - 1)
                if prev:
                    flip_label = compute_flip_type(prev.signal, dec.signal).value
            lines.append(
                f"Round {rn}: {dec.signal.value.upper()} "
                f"(confidence: {dec.confidence:.2f}, sentiment: {dec.sentiment:.2f}) "
                f"flip: {flip_label}"
            )
            if dec.cited_agents:
                lines.append(f"  Cited: {', '.join(dec.cited_agents)}")

        prompt = (
            "Summarize this agent's 3-round decision arc in 2-3 sentences. "
            "Note any signal changes and key influences. Be concise.\n\n"
            + "\n".join(lines)
        )

        try:
            async with governor:
                response = await client.generate(
                    model=model,
                    prompt=prompt,
                    system="You are a concise financial analyst narrator. Summarize agent decision arcs in 2-3 sentences.",
                )
                narrative_text = response.get("response", "").strip()
                if narrative_text:
                    return {"agent_id": agent_id, "narrative": narrative_text}
                return None
        except Exception:
            logger.warning("narrative_generation_failed", agent_id=agent_id, exc_info=True)
            return None

    # Dispatch all agents concurrently through governor (governor provides throttling)
    tasks = [_generate_one(agent_id) for agent_id in agent_decisions_by_id]
    results = await _asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, dict):
            narratives.append(result)
        elif isinstance(result, Exception):
            errors.append(str(result))

    if errors:
        logger.warning("narrative_generation_partial_failures", error_count=len(errors))

    # Batch-write all successful narratives to Agent nodes
    if narratives:
        await graph_manager.write_decision_narratives(narratives)

    return narratives
