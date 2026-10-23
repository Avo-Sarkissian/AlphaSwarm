"""Simulation pipeline for AlphaSwarm.

Composes inject_seed, dispatch_wave, and write_decisions into:
- run_round1(): Round 1 dispatch for a cycle run_simulation already seeded
- run_simulation(): Full 3-round consensus cascade (Phase 7)

run_simulation() calls run_round1() for Round 1, then orchestrates
Rounds 2-3 with per-agent peer context injection. Fires on_round_complete
callback after each round for progressive CLI output.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import math
import random
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import structlog

from alphaswarm.batch_dispatcher import HARD_STOP_ERRORS, dispatch_wave
from alphaswarm.config import generate_modifiers, generate_personas, persona_to_worker_config
from alphaswarm.context_formatter import format_market_context
from alphaswarm.episodes import EpisodeRecord, compute_flip_type
from alphaswarm.errors import RoundFailedError
from alphaswarm.inference.ollama_provider import OllamaProvider
from alphaswarm.inference.types import ProviderRole
from alphaswarm.ingestion.types import ContextPacket
from alphaswarm.manifest import current_git_revision
from alphaswarm.metrics import split_flips
from alphaswarm.seed import inject_seed
from alphaswarm.state import BracketSummary
from alphaswarm.types import SignalType, SimulationPhase
from alphaswarm.utils import sanitize_rationale
from alphaswarm.write_buffer import WriteBuffer

if TYPE_CHECKING:
    from alphaswarm.config import AppSettings, BracketConfig, SimulationSettings
    from alphaswarm.graph import GraphStateManager, RankedPost
    from alphaswarm.inference.concurrency import ConcurrencyController
    from alphaswarm.inference.provider import InferenceProvider
    from alphaswarm.ingestion.providers import MarketDataProvider, NewsProvider
    from alphaswarm.ollama_client import OllamaClient
    from alphaswarm.ollama_models import OllamaModelManager
    from alphaswarm.state import StateStore
    from alphaswarm.types import (
        AgentDecision,
        AgentPersona,
        ParsedModifiersResult,
        ParsedSeedResult,
    )

logger = structlog.get_logger(component="simulation")

_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")
"""Same pattern as alphaswarm.ingestion.rss_provider._TICKER_RE (Phase 38 T-38-01).
Defense-in-depth: re-applied here so non-ticker entities (company names like
'NVIDIA', 'Federal Reserve') never reach MarketDataProvider.get_prices. All
entities pass to NewsProvider.get_headlines (provider handles routing)."""


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


def peer_rng(run_seed: str, reader_id: str, round_num: int) -> random.Random:
    """Per-(run, reader, round) RNG for peer sampling (docs/DECISIONS.md#adr-diverse-peer-context).

    Seeded from blake2b, never the process-salted builtin ``hash()``, so the
    same run seed reproduces the same peer draws in any process.
    ``round_num`` is the round being dispatched (2 for peers drawn from Round 1).
    """
    digest = hashlib.blake2b(f"{run_seed}:{reader_id}:{round_num}".encode(), digest_size=8).digest()
    return random.Random(int.from_bytes(digest, "big"))


CONTROL_SALT: Final = "control"
_OWN_PRIOR_TRANSLATION: Final = str.maketrans({"<": None, ">": None, "[": "(", "]": ")", '"': "'"})


def subset_size(count: int, fraction: float) -> int:
    """Round-half-up share of a bracket; a bracket of two or more keeps one agent outside."""
    if count < 2 or fraction <= 0.0:
        return 0
    return min(count - 1, math.floor(count * fraction + 0.5))


def seeded_bracket_subset(
    personas: Sequence[AgentPersona], *, fraction: float, run_seed: str, salt: str
) -> frozenset[str]:
    """A seeded sample of ``subset_size(count, fraction)`` agents from every bracket.

    The draw depends only on ``(run_seed, salt, bracket)`` and the bracket's ids
    (sorted), so it is the same in every round, every process and any roster
    order (docs/DECISIONS.md#adr-diverse-peer-context).
    """
    by_bracket: dict[str, list[str]] = {}
    for persona in personas:
        by_bracket.setdefault(persona.bracket.value, []).append(persona.id)
    chosen: set[str] = set()
    for bracket, ids in by_bracket.items():
        k = subset_size(len(ids), fraction)
        if k == 0:
            continue
        digest = hashlib.blake2b(f"{run_seed}:{salt}:{bracket}".encode(), digest_size=8).digest()
        chosen.update(random.Random(int.from_bytes(digest, "big")).sample(sorted(ids), k))
    return frozenset(chosen)


def select_control_ids(personas: Sequence[AgentPersona], *, fraction: float, run_seed: str) -> frozenset[str]:
    """Readers held out from peer context for the whole run (``d.control``)."""
    return seeded_bracket_subset(personas, fraction=fraction, run_seed=run_seed, salt=CONTROL_SALT)


def own_prior_line(decision: AgentDecision | None, source_round: int) -> str | None:
    """The reader's own previous decision as one sanitized line, or None.

    None for a missing or PARSE_ERROR decision, so a failure never appears as a
    position. The rationale is model output: control characters go, whitespace
    collapses into one line and the text is cut at 300 characters ("..." marks a
    cut). Then "<"/">" are dropped and "[" "]" become "(" ")", so no fence tag or
    [agent_id] token can be forged, and double quotes become single quotes, so a
    quoted field stays unambiguous (docs/DECISIONS.md#adr-diverse-peer-context).
    """
    if decision is None or decision.signal == SignalType.PARSE_ERROR:
        return None
    head = f"Your Round {source_round} position: {decision.signal.value.upper()} (conf {decision.confidence:.2f})"
    rationale = sanitize_rationale(decision.rationale, max_len=300).translate(_OWN_PRIOR_TRANSLATION).strip()
    return f"{head}: {rationale}" if rationale else head


def apply_holdout_and_priors(
    personas: Sequence[AgentPersona],
    contexts: Sequence[str | None],
    exposures: Sequence[tuple[str, ...]],
    prev_decisions: Sequence[tuple[str, AgentDecision]],
    source_round: int,
    *,
    sim: SimulationSettings,
    control_ids: frozenset[str],
) -> tuple[list[str | None], list[tuple[str, ...]], list[str | None]]:
    """Blank the holdout's peer contexts and exposures, and build own-prior lines.

    Control readers get no peers but keep their own prior, so their flips
    measure everything except peer influence (docs/DECISIONS.md#adr-diverse-peer-context).
    """
    prev_by_id = dict(prev_decisions)
    blanked = [None if p.id in control_ids else context for p, context in zip(personas, contexts, strict=True)]
    shown = [() if p.id in control_ids else exposure for p, exposure in zip(personas, exposures, strict=True)]
    priors = [own_prior_line(prev_by_id.get(p.id), source_round) if sim.own_prior_memory else None for p in personas]
    return blanked, shown, priors


def _reach(weight: float) -> float:
    """Sampling weight: ``weight`` when finite and positive, else 0.0 (no reach)."""
    return weight if math.isfinite(weight) and weight > 0.0 else 0.0


def _sampling_key(rng: random.Random, weight: float) -> tuple[bool, float]:
    """Efraimidis–Spirakis key; larger wins.

    The float is ``log(u) / w``, the log of ``u ** (1/w)``: sorting by it,
    descending, is weighted sampling without replacement, and the log form
    avoids underflow for small weights. The flag is False for a weight without
    reach (non-finite or not positive), whose float then draws as weight 1:
    such keys sort behind every positive weight, whatever ``u`` is, and stay in
    random order among themselves. One ``u`` is drawn either way.
    """
    u = rng.random()
    while u == 0.0:  # random() is in [0, 1); log(0) is undefined
        u = rng.random()
    if math.isfinite(weight) and weight > 0.0:
        return True, math.log(u) / weight
    return False, math.log(u)


def select_diverse_peers(
    agent_id: str,
    influence_weights: Mapping[str, float],
    personas: Sequence[AgentPersona],
    prev_decisions: Mapping[str, AgentDecision] | None = None,
    *,
    rng: random.Random,
    limit: int = 10,
    min_brackets: int = 4,
    bracket_cap: int = 3,
) -> list[str]:
    """Sample up to ``limit`` peers for one reader (docs/DECISIONS.md#adr-diverse-peer-context).

    Weighted sampling without replacement with Efraimidis–Spirakis keys:

    1. Candidates are every persona except the reader and agents whose
       previous-round decision is PARSE_ERROR.
    2. Phase 1 samples ``min(min_brackets, limit)`` brackets, each weighted by
       the summed weight of its candidates, and takes one peer from each by
       key. A guaranteed slot is therefore a weighted draw over agents that
       skips brackets already chosen, so a small bracket's members do not gain
       per agent merely because the bracket is small.
    3. Phase 2 fills the remaining slots by key, skipping any bracket that
       already holds ``bracket_cap`` peers. The cap is hard: with few eligible
       brackets the result is shorter than ``limit``.
    4. The result is shuffled, so display position carries no authority.

    Production passes ``rng=peer_rng(run_seed, agent_id, round_num)``; the same
    rng state always yields the same list. Non-finite or non-positive weights
    have no reach: such candidates, and brackets with no positive weight, sort
    behind every positive weight (in random order among themselves) and
    nothing raises.

    Raises:
        ValueError: if ``bracket_cap`` is below 1.
    """
    if bracket_cap < 1:
        raise ValueError(f"bracket_cap must be >= 1, got {bracket_cap}")
    parse_error_ids: set[str] = set()
    if prev_decisions is not None:
        parse_error_ids = {aid for aid, dec in prev_decisions.items() if dec.signal == SignalType.PARSE_ERROR}
    candidates = [p for p in personas if p.id != agent_id and p.id not in parse_error_ids]
    if limit <= 0 or not candidates:
        return []

    weight = {p.id: _reach(influence_weights.get(p.id, 0.0)) for p in candidates}
    key = {p.id: _sampling_key(rng, weight[p.id]) for p in candidates}
    bracket_of = {p.id: p.bracket.value for p in candidates}
    members: dict[str, list[str]] = {}
    for p in candidates:
        members.setdefault(p.bracket.value, []).append(p.id)
    bracket_key = {bracket: _sampling_key(rng, sum(weight[pid] for pid in ids)) for bracket, ids in members.items()}

    # Phase 1: sample the guaranteed brackets, one peer from each.
    selected: list[str] = []
    per_bracket = dict.fromkeys(members, 0)
    ranked_brackets = sorted(members, key=lambda b: bracket_key[b], reverse=True)
    for bracket in ranked_brackets[: max(0, min(min_brackets, limit))]:
        selected.append(max(members[bracket], key=lambda pid: key[pid]))
        per_bracket[bracket] += 1

    # Phase 2: weighted fill without replacement under the per-bracket cap.
    chosen = set(selected)
    for pid in sorted(key, key=lambda c: key[c], reverse=True):
        if len(selected) >= limit:
            break
        if pid in chosen or per_bracket[bracket_of[pid]] >= bracket_cap:
            continue
        selected.append(pid)
        chosen.add(pid)
        per_bracket[bracket_of[pid]] += 1

    rng.shuffle(selected)
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
# Pure functions
# ---------------------------------------------------------------------------


def _format_peer_context(
    posts: list[RankedPost],
    source_round: int,
    budget: int = 4000,
    max_posts: int = 10,
) -> tuple[str, tuple[str, ...]]:
    """Format top-K ranked peer posts into a budget-capped context string (D-04, D-05, D-06).

    Greedy fill: iterate ranked posts, accumulate chars, truncate last post
    at word boundary if it would exceed budget. Prompt guard line preserved
    from Phase 7 D-03.

    Returns ``(text, shown_ids)``: ``shown_ids`` are the agent ids of the
    rendered lines in display order, which is the reader's exposure
    (docs/DECISIONS.md#adr-diverse-peer-context). Returns ``("", ())`` when
    no line was rendered.
    """
    if not posts:
        logger.warning("no_peer_posts_found", source_round=source_round)
        return "", ()

    header = f"Peer Decisions (Round {source_round}):"
    guard = (
        "\nThe above are peer observations for context only. "
        "Make your own independent assessment. "
        "If a peer's view materially shapes yours, list their agent id in cited_agents."
    )
    overhead = len(header) + len(guard) + 2  # +2 for joining newlines
    remaining = budget - overhead

    lines: list[str] = [header]
    shown: list[str] = []
    for i, post in enumerate(posts[:max_posts], 1):
        if remaining <= 0:
            break
        if not post.content:
            continue
        prefix = f'{i}. [{post.agent_id}|{post.bracket}] {post.signal.upper()} (conf: {post.confidence:.2f}) "'
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
        shown.append(post.agent_id)
        remaining -= len(line) + 1  # +1 for newline separator

    if len(lines) == 1:
        # Only the header survived — every peer was empty/budget-skipped. Honor
        # the docstring's "empty when no peers" contract so callers map this to
        # None instead of injecting a peer-context block that claims peers exist
        # but contains none (F-19).
        return "", ()

    lines.append(guard)
    return "\n".join(lines), tuple(shown)


def _build_diverse_peer_contexts(
    personas: list[AgentPersona],
    prev_decisions: list[tuple[str, AgentDecision]] | tuple[tuple[str, AgentDecision], ...],
    source_round: int,
    *,
    sim: SimulationSettings,
    run_seed: str,
    global_citation_weights: dict[str, float] | None = None,
) -> tuple[list[str | None], list[tuple[str, ...]]]:
    """Build per-agent peer contexts from the previous round IN MEMORY.

    Replaces the `read_ranked_posts` path (docs/DECISIONS.md#sweep-3-3 fix),
    which showed all 100 agents the same authority top-10 and cost 100
    sequential Neo4j reads per round. This builder:

    1. Computes a PER-READER weight for each candidate author:
       base reach (influence_weight_base)
       + global citation share (citations/total_agents, when available)
       + ``sim.personal_boost`` when the READER cited the author last round.
    2. Feeds those weights through `select_diverse_peers` with the knobs in
       ``sim`` and a per-reader ``peer_rng(run_seed, reader, source_round + 1)``
       (docs/DECISIONS.md#adr-diverse-peer-context).

    Returns ``(contexts, exposures)`` aligned by persona index: the context
    string (None when no peer line was rendered) and the ids of the peers whose
    lines were rendered, in display order (``()`` when none). Peers cut by the
    character budget are not exposure.
    """
    from alphaswarm.graph import RankedPost

    persona_lookup = {p.id: p for p in personas}
    prev_dict: dict[str, AgentDecision] = {aid: dec for aid, dec in prev_decisions}
    base_weights = {p.id: p.influence_weight_base for p in personas}
    global_w = global_citation_weights or {}

    contexts: list[str | None] = []
    exposures: list[tuple[str, ...]] = []
    for persona in personas:
        reader_prev = prev_dict.get(persona.id)
        cited_by_reader: set[str] = set(reader_prev.cited_agents) if reader_prev is not None else set()
        weights = {
            pid: base_weights[pid] + global_w.get(pid, 0.0) + (sim.personal_boost if pid in cited_by_reader else 0.0)
            for pid in base_weights
        }
        peer_ids = select_diverse_peers(
            persona.id,
            weights,
            personas,
            prev_decisions=prev_dict,
            rng=peer_rng(run_seed, persona.id, source_round + 1),
            limit=sim.peer_limit,
            min_brackets=sim.min_brackets,
            bracket_cap=sim.bracket_cap,
        )
        ranked_posts = [
            RankedPost(
                post_id="",
                agent_id=pid,
                bracket=persona_lookup[pid].bracket.value,
                signal=prev_dict[pid].signal.value,
                confidence=prev_dict[pid].confidence,
                content=prev_dict[pid].rationale,
                influence_weight=weights.get(pid, 0.0),
                round_num=source_round,
            )
            for pid in peer_ids
            if pid in prev_dict and pid in persona_lookup
        ]
        ctx, shown = _format_peer_context(
            ranked_posts,
            source_round,
            budget=sim.peer_budget_chars,
            max_posts=sim.peer_limit,
        )
        contexts.append(ctx if ctx else None)
        exposures.append(shown)
    return contexts, exposures


def compute_exposure_metrics(
    exposures: Sequence[tuple[str, ...]],
    personas: Sequence[AgentPersona],
    round_num: int,
) -> dict[str, int]:
    """Summarize one round's peer exposure as flat cycle-metric keys.

    ``exposures[i]`` holds the peer ids rendered into reader i's prompt (``()``
    when the reader saw no peers). Produces, for every bracket in roster
    order, ``r{n}_exposure_<bracket>`` (peer slots that bracket filled) and
    ``r{n}_readers_seeing_<bracket>`` (readers shown at least one peer from
    it), plus ``r{n}_distinct_peers_shown``. Unseen brackets report 0; ids
    outside the roster are ignored (docs/DECISIONS.md#adr-diverse-peer-context).
    """
    bracket_of = {p.id: p.bracket.value for p in personas}
    brackets = list(dict.fromkeys(p.bracket.value for p in personas))
    slots = dict.fromkeys(brackets, 0)
    readers = dict.fromkeys(brackets, 0)
    distinct: set[str] = set()
    for shown in exposures:
        seen_here: set[str] = set()
        for peer_id in shown:
            bracket = bracket_of.get(peer_id)
            if bracket is None:
                continue
            slots[bracket] += 1
            seen_here.add(bracket)
            distinct.add(peer_id)
        for bracket in seen_here:
            readers[bracket] += 1

    metrics: dict[str, int] = {}
    for bracket in brackets:
        metrics[f"r{round_num}_exposure_{bracket}"] = slots[bracket]
        metrics[f"r{round_num}_readers_seeing_{bracket}"] = readers[bracket]
    metrics[f"r{round_num}_distinct_peers_shown"] = len(distinct)
    return metrics


_PEER_SELECTION_VERSION: Final = 2
"""Stamped as ``peer_selection_version``: 2 = seeded stratified sampling with a
per-bracket cap and shuffle; 1 = the legacy deterministic top-weight fill."""

_PEER_SEED_SOURCE: Final = "cycle_id"
"""What run_simulation passes as ``run_seed`` to the peer builder."""


def _provider_label(provider: InferenceProvider) -> str:
    """Provider kind for the cycle metrics (docs/DECISIONS.md#adr-cycle-metrics).

    The InferenceProvider protocol exposes only ``is_local()``. Ollama is the
    only local provider type, so local providers report its ProviderType value
    "ollama"; cloud providers report "cloud" and are told apart by model id.
    """
    return "ollama" if provider.is_local() else "cloud"


def _mode_from_providers(orchestrator: InferenceProvider, worker: InferenceProvider) -> str:
    """Return "local", "cloud" or "mixed": the classification inference_mode(cfg) uses."""
    orchestrator_local = orchestrator.is_local()
    worker_local = worker.is_local()
    if orchestrator_local and worker_local:
        return "local"
    if not orchestrator_local and not worker_local:
        return "cloud"
    return "mixed"


def _peer_and_provenance_metrics(
    sim: SimulationSettings,
    orchestrator: InferenceProvider,
    worker: InferenceProvider,
    *,
    git_sha: str | None,
    git_dirty: bool | None,
) -> dict[str, float | int | str | bool]:
    """Effective peer parameters, experiment knobs and run provenance as flat cycle-metric keys.

    ``git_sha`` is "" when unknown. ``git_dirty`` is omitted when unknown,
    because a Neo4j property cannot hold null (docs/DECISIONS.md#adr-cycle-metrics).
    """
    metrics: dict[str, float | int | str | bool] = {
        "peer_selection_version": _PEER_SELECTION_VERSION,
        "peer_limit": sim.peer_limit,
        "peer_min_brackets": sim.min_brackets,
        "peer_bracket_cap": sim.bracket_cap,
        "peer_budget_chars": sim.peer_budget_chars,
        "peer_personal_boost": sim.personal_boost,
        "peer_seed_source": _PEER_SEED_SOURCE,
        "own_prior_memory": sim.own_prior_memory,
        "control_fraction": sim.control_fraction,
        "orchestrator_provider": _provider_label(orchestrator),
        "orchestrator_model": orchestrator.model,
        "worker_provider": _provider_label(worker),
        "worker_model": worker.model,
        "inference_mode": _mode_from_providers(orchestrator, worker),
        "git_sha": git_sha or "",
    }
    if git_dirty is not None:
        metrics["git_dirty"] = git_dirty
    return metrics


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


# ---------------------------------------------------------------------------
# Round 1 pipeline (Phase 6)
# ---------------------------------------------------------------------------


async def run_round1(
    rumor: str,
    settings: AppSettings,
    ollama_client: OllamaClient,
    model_manager: OllamaModelManager,
    graph_manager: GraphStateManager,
    governor: ConcurrencyController,
    personas: list[AgentPersona],
    *,
    pre_injected: tuple[str, ParsedSeedResult],
    state_store: StateStore | None = None,
    market_context: str | None = None,
    worker_provider: InferenceProvider | None = None,
) -> Round1Result:
    """Execute the Round 1 simulation pipeline.

    Pipeline steps:
    1. Unpack the (cycle_id, parsed_result) that run_simulation's inject_seed produced
    2. ensure_clean_state (defensive cleanup after orchestrator)
    3. start_monitoring (governor RAM monitoring)
    4. load worker model (or prepare injected worker_provider)
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
        pre_injected: (cycle_id, parsed_result) from the caller's inject_seed
            call. Required: run_simulation seeds the cycle and generates the
            persona modifiers before Round 1, so run_round1 never seeds.
        market_context: Optional grounded market data block injected into Round 1
            agent prompts per Phase 40 D-04, D-06. Forwarded to dispatch_wave.
            F3: it is third-party text, so AgentWorker.infer fences it inside the
            user message rather than trusting it as a system message. When None,
            behavior is identical to pre-Phase-40 (rumor-only prompts).
        worker_provider: Optional pre-configured InferenceProvider for worker
            inference. When supplied, provider.prepare()/teardown() replace
            model_manager.load_model/unload_model and the provider is forwarded
            to dispatch_wave. When None (default), preserves existing local
            OllamaProvider + model_manager load/unload behavior exactly.

    Returns:
        Round1Result with cycle_id, parsed_result, and agent_decisions.
    """
    logger.info("round1_start", agent_count=len(personas))

    cycle_id, parsed_result = pre_injected

    # StateStore: mark ROUND_1 phase after seed injection
    if state_store is not None:
        await state_store.set_phase(SimulationPhase.ROUND_1)
        await state_store.set_round(1)

    # 2. Defensive model cleanup (review concern #4)
    await model_manager.ensure_clean_state()

    worker_alias = settings.ollama.worker_model_alias

    # Resolve the effective worker provider for Round 1.
    # When worker_provider is injected (cloud path), use it directly.
    # When None (default/local path), build the local OllamaProvider and manage
    # the model lifecycle via model_manager.load_model/unload_model exactly as
    # before — preserving the existing local behavior byte-for-byte.
    _use_injected_worker = worker_provider is not None
    _r1_worker_provider: InferenceProvider
    if _use_injected_worker:
        assert worker_provider is not None  # narrowing for mypy
        _r1_worker_provider = worker_provider
    else:
        _r1_worker_provider = OllamaProvider(ProviderRole.WORKER, worker_alias, ollama_client, model_manager)

    # 3. Start governor monitoring (review concern #1 -- must happen before dispatch)
    await governor.start_monitoring()
    try:
        # 4. Load worker model (local: model_manager.load_model; cloud: provider.prepare no-op)
        if _use_injected_worker:
            await _r1_worker_provider.prepare()
        else:
            await model_manager.load_model(worker_alias)
        try:
            # 5. Convert personas and dispatch
            worker_configs = [persona_to_worker_config(p) for p in personas]
            decisions = await dispatch_wave(
                personas=worker_configs,
                governor=governor,
                provider=_r1_worker_provider,
                user_message=rumor,
                settings=settings.governor,
                peer_context=None,
                market_context=market_context,
                state_store=state_store,
                round_num=1,
            )

            # 6. Positional alignment assertion (review concern #3)
            assert len(decisions) == len(worker_configs), (
                f"dispatch_wave returned {len(decisions)} results for {len(worker_configs)} personas"
            )

            # 7. Pair agent IDs with decisions
            agent_decisions: list[tuple[str, AgentDecision]] = [
                (wc["agent_id"], dec) for wc, dec in zip(worker_configs, decisions, strict=False)
            ]

            # Per-agent StateStore writes now happen INSIDE
            # batch_dispatcher._safe_agent_inference the moment each inference
            # resolves (streaming). The previous post-dispatch for-loop here
            # caused the WS broadcaster to see an empty agent_states dict for
            # the entire 14-18min round window — see debug session
            # ws-agent-states-not-emitted-mid-sim.

            # 8. Abort before persisting when too many agents failed, then
            #    persist (Phase 11: capture returned decision_ids)
            _raise_if_round_failed(
                1,
                agent_decisions,
                settings.governor.round_abort_failure_percent,
            )
            round1_decision_ids = await graph_manager.write_decisions(
                agent_decisions,
                cycle_id,
                round_num=1,
            )
        finally:
            # 9a. Always unload worker model (inner finally)
            if _use_injected_worker:
                await _r1_worker_provider.teardown()
            else:
                await model_manager.unload_model(worker_alias)
    finally:
        # 9b. Always stop governor monitoring (outer finally)
        await governor.stop_monitoring()

    # 10. Log completion and return
    error_count = sum(1 for _, d in agent_decisions if d.signal == SignalType.PARSE_ERROR)
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
# Full 3-round simulation orchestrator (Phase 7)
# ---------------------------------------------------------------------------


def _with_shocks(rumor: str, shocks: Sequence[str]) -> str:
    """Rumor plus every applied shock, oldest first (one "[MARKET SHOCK]" line each)."""
    return rumor + "".join(f"\n\n[MARKET SHOCK]: {text}" for text in shocks)


async def run_simulation(
    rumor: str,
    settings: AppSettings,
    ollama_client: OllamaClient,
    model_manager: OllamaModelManager,
    graph_manager: GraphStateManager,
    governor: ConcurrencyController,
    personas: list[AgentPersona],
    brackets: list[BracketConfig],
    *,
    on_round_complete: OnRoundComplete = None,
    state_store: StateStore | None = None,
    generate_narratives: bool = True,
    consume_shock: Callable[[], str | None] | None = None,
    market_provider: MarketDataProvider | None = None,
    news_provider: NewsProvider | None = None,
    orchestrator_provider: InferenceProvider | None = None,
    worker_provider: InferenceProvider | None = None,
    context_fixture: ContextPacket | None = None,
) -> SimulationResult:
    """Execute the full 3-round simulation pipeline (D-04).

    Phase transitions (docs/DECISIONS.md#p7-d-07):
    IDLE -> SEEDING -> ROUND_1 .. ROUND_N -> FINALIZING -> COMPLETE
    Each transition is logged and, when state_store is given, set on it with
    StateStore.set_phase, which drives the UI.

    Progressive output (addresses Gemini/Codex review): fires on_round_complete
    callback after each round finishes, enabling CLI to print reports in real time.

    Phase 40 context assembly (D-01, D-02, D-03, D-06):
    When both market_provider and news_provider are supplied, run_simulation
    assembles a ContextPacket AFTER inject_seed and BEFORE run_round1, formats
    it via `format_market_context`, and forwards the result to run_round1 as
    `market_context=...`. If either provider is None, a structlog warning
    (`context_assembly_skipped`) is emitted and run_round1 receives
    `market_context=None` (backward compatible). Rounds 2-3 are NOT affected
    (D-06 keeps market context Round 1 only).

    A context_fixture (a point-in-time ContextPacket for evaluation runs,
    docs/DECISIONS.md#adr-eval-harness) takes precedence over both providers:
    it is formatted directly, the providers are never called, and
    `context_fixture_used` is logged instead.

    Lifecycle:
    1. SEEDING: inject_seed parses the rumor and generates the persona modifiers
       (docs/DECISIONS.md#p13-d-06). run_simulation always seeds; run_round1 never does
    2. Phase 40 context assembly: asyncio.gather(get_prices + get_headlines)
       -> format_market_context -> forward to run_round1 (docs/DECISIONS.md#p40-d-01)
    3. run_round1() runs ROUND_1 on the seeded cycle and owns its own governor session
       (docs/DECISIONS.md#p7-d-06). No influence edges after Round 1: its agents see no
       peers, so they cite none (docs/DECISIONS.md#sweep-b-5)
    4. Compute Round 1 bracket summaries (D-08)
    5. Fire on_round_complete for Round 1 (shift=None, no prior round to compare)
    6. ensure_clean_state + reload worker (D-05: one cold load for modularity)
    7. Fresh governor monitoring session for Rounds 2-3 block (D-06)
    8. Round 2: dispatch_wave with per-reader peer contexts built in memory from
       Round 1 decisions -> write -> callback
    9. Compute influence edges after Round 2 (D-04: cumulative, up_to_round=2)
    10. Round 3: dispatch_wave with peer contexts from Round 2 -> write -> callback
    11. Return SimulationResult with all bracket summaries (D-08)
    """
    phase = SimulationPhase.IDLE
    logger.info("simulation_start", phase=phase.value)
    if state_store is not None:
        await state_store.set_phase(SimulationPhase.IDLE)

    # Compute effective providers: use injected providers when supplied, else build local defaults.
    # DEFAULT PATH INVARIANT: when both are None (all existing callers), builds the same
    # OllamaProvider instances as before — byte-for-byte equivalent behavior.
    orch = orchestrator_provider or OllamaProvider(
        ProviderRole.ORCHESTRATOR,
        settings.ollama.orchestrator_model_alias,
        ollama_client,
        model_manager,
    )
    worker = worker_provider or OllamaProvider(
        ProviderRole.WORKER,
        settings.ollama.worker_model_alias,
        ollama_client,
        model_manager,
    )
    # Provenance stamped into the cycle metrics (docs/DECISIONS.md#adr-cycle-metrics).
    # git runs as a subprocess: cached per process and kept off the event loop.
    git_sha, git_dirty = await asyncio.to_thread(current_git_revision)

    # Phase 13: Seed injection with modifier generation (D-06: same orchestrator session)
    phase = SimulationPhase.SEEDING
    logger.info("simulation_phase_transition", phase=phase.value)
    if state_store is not None:
        state_store.set_num_rounds(settings.num_rounds)
        await state_store.set_phase(SimulationPhase.SEEDING)
        # Canonical roster for this run, in config order and all pending, so
        # every frame from SEEDING on carries the same agents in the same order
        # (docs/DECISIONS.md#adr-streaming-state).
        await state_store.begin_run([p.id for p in personas])

    cycle_id, parsed_result, modifier_result = await inject_seed(
        rumor,
        settings,
        orch,
        graph_manager,
        modifier_generator=generate_modifiers,
    )
    if state_store is not None:
        # The frame's cycle id: the canvas fetches this cycle's edges, never the
        # previous run's (docs/DECISIONS.md#adr-ws-broadcaster).
        await state_store.set_cycle(cycle_id)

    # Phase 13: Regenerate personas with entity-aware modifiers (D-01, D-02)
    if modifier_result is not None:
        personas = generate_personas(brackets, modifiers=modifier_result.modifiers)
        logger.info("personas_regenerated_with_modifiers", parse_tier=modifier_result.parse_tier)

    # Phase 40 context assembly (D-01, D-02, D-03).
    # Happens AFTER inject_seed so we have entity names, BEFORE run_round1 so
    # the market_context string reaches Round 1 prompts. D-06: Rounds 2-3 not
    # affected. KNOWN LIMITATION: orchestrator emits human-readable entity
    # names (e.g. "NVIDIA") per seed.py:24 prompt. `_TICKER_RE` filter means
    # non-ticker entities do NOT reach the market provider — they receive
    # news-only context. See context_formatter.py module docstring for
    # full rationale.
    market_context_str: str | None = None
    if context_fixture is not None:
        # Point-in-time run: the fixture replaces the live fetch
        # (docs/DECISIONS.md#adr-eval-harness).
        market_context_str = format_market_context(context_fixture)
        logger.info(
            "context_fixture_used",
            cycle_id=cycle_id,
            as_of=context_fixture.as_of.isoformat(),
            entity_count=len(context_fixture.entities),
            rendered=market_context_str is not None,
        )
    elif market_provider is None or news_provider is None:
        logger.warning(
            "context_assembly_skipped",
            reason="no_providers_configured",
            cycle_id=cycle_id,
        )
    else:
        entity_names = [e.name for e in parsed_result.seed_event.entities]
        tickers = [e for e in entity_names if _TICKER_RE.match(e)]
        market_slices, news_slices = await asyncio.gather(
            market_provider.get_prices(tickers),
            news_provider.get_headlines(entity_names),
        )
        packet = ContextPacket(
            cycle_id=cycle_id,
            as_of=datetime.now(UTC),
            entities=tuple(entity_names),
            market=tuple(market_slices.values()),
            news=tuple(news_slices.values()),
        )
        logger.info(
            "context_packet_assembled",
            cycle_id=cycle_id,
            entity_count=len(entity_names),
            ticker_count=len(tickers),
            market_success=sum(1 for s in packet.market if s.staleness != "fetch_failed"),
            news_success=sum(1 for s in packet.news if s.staleness != "fetch_failed"),
            total_headlines=sum(len(s.headlines) for s in packet.news if s.staleness != "fetch_failed"),
        )
        market_context_str = format_market_context(packet)

    # Measurement infra: wall-clock per phase, persisted to the Cycle node at
    # the end so A/B experiments read metrics with one Cypher query.
    sim_start = time.monotonic()

    # Round 1 dispatch (skip inject_seed since we already did it)
    r1_start = time.monotonic()
    round1_result = await run_round1(
        rumor,
        settings,
        ollama_client,
        model_manager,
        graph_manager,
        governor,
        personas,
        state_store=state_store,
        pre_injected=(cycle_id, parsed_result),
        market_context=market_context_str,
        worker_provider=worker,
    )
    r1_seconds = time.monotonic() - r1_start
    cycle_id = round1_result.cycle_id

    phase = SimulationPhase.ROUND_1
    logger.info("simulation_phase_transition", phase=phase.value, cycle_id=cycle_id)

    # Phase 11: Initialize WriteBuffer and load entity names cache once (D-01, D-09)
    write_buffer = WriteBuffer(maxsize=200)
    entity_names = await graph_manager.read_cycle_entities(cycle_id)

    # Phase 11: Push Round 1 episodes to WriteBuffer
    # (retroactive -- run_round1 already wrote decisions)
    for did, (agent_id, decision) in zip(round1_result.decision_ids, round1_result.agent_decisions, strict=False):
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

    # Skip Round 1 influence-edge computation: Round 1 agents see only the
    # rumor (no peer context), so they can't populate `cited_agents`, so
    # `compute_influence_edges(up_to_round=1)` always returns {} and the
    # returned weights were never read anyway (Round 2 builds peer context
    # in memory via `_build_diverse_peer_contexts`, not from these weights).
    # One fewer Neo4j round-trip per cycle. See docs/DECISIONS.md#sweep-b-5.

    # Compute Round 1 bracket summaries (D-08)
    round1_summaries = compute_bracket_summaries(
        round1_result.agent_decisions,
        personas,
        brackets,
    )

    # Push bracket summaries to StateStore for the live UI (docs/DECISIONS.md#p10-d-08).
    # Rationale entries stream per agent from batch_dispatcher._safe_agent_inference,
    # so there is no end-of-round rationale push (docs/DECISIONS.md#p10-d-02).
    if state_store is not None:
        await state_store.set_bracket_summaries(round1_summaries)

    # Fire callback for Round 1 (progressive output)
    round1_decisions_tuple = tuple(round1_result.agent_decisions)
    if on_round_complete is not None:
        await on_round_complete(
            RoundCompleteEvent(
                round_num=1,
                cycle_id=cycle_id,
                agent_decisions=round1_decisions_tuple,
                shift=None,
                bracket_summaries=round1_summaries,
            )
        )

    # Reload worker for Rounds 2-3 (D-05)
    await model_manager.ensure_clean_state()

    # Fresh governor monitoring for Rounds 2-3 block (D-06)
    await governor.start_monitoring()
    try:
        # Round 2 (D-09: peer context from Round 1)
        # Build peer contexts BEFORE loading model to minimize idle keep_alive drain.
        phase = SimulationPhase.ROUND_2
        r2_start = time.monotonic()
        logger.info("simulation_phase_transition", phase=phase.value, cycle_id=cycle_id)
        if state_store is not None:
            await state_store.set_phase(SimulationPhase.ROUND_2)
            await state_store.set_round(2)

        # Shock gate (docs/DECISIONS.md#b1): consume a pending shock before Round 2.
        # Every applied shock stays in all later rounds' user message, oldest first.
        active_shocks: list[str] = []
        if consume_shock is not None:
            shock_text_r2 = consume_shock()
            if shock_text_r2:
                active_shocks.append(shock_text_r2)
                await graph_manager.write_shock_event(
                    cycle_id,
                    shock_text_r2,
                    injected_before_round=2,
                )
                if state_store is not None:
                    state_store.record_applied_shock(shock_text_r2, 2)
                logger.info(
                    "shock_injected",
                    cycle_id=cycle_id,
                    round_num=2,
                    shock_length=len(shock_text_r2),
                )
        effective_rumor_r2 = _with_shocks(rumor, active_shocks)

        # Seeded no-peer holdout for the whole run (docs/DECISIONS.md#adr-diverse-peer-context).
        control_ids = select_control_ids(personas, fraction=settings.simulation.control_fraction, run_seed=cycle_id)

        # Build bracket-diverse peer contexts from Round 1 decisions in memory
        # (docs/DECISIONS.md#sweep-3-3: replaces the global-authority read_ranked_posts
        # path that showed every agent the same top-10). READ_POST edge writes
        # removed with it: ~10k edges/round recording "everyone read
        # everything" carried no analytical value.
        round2_peer_contexts, round2_exposures = _build_diverse_peer_contexts(
            personas,
            round1_result.agent_decisions,
            source_round=1,
            sim=settings.simulation,
            run_seed=cycle_id,
        )
        round2_peer_contexts, round2_exposures, round2_own_priors = apply_holdout_and_priors(
            personas,
            round2_peer_contexts,
            round2_exposures,
            round1_result.agent_decisions,
            1,
            sim=settings.simulation,
            control_ids=control_ids,
        )
        exposure_metrics: dict[str, int] = compute_exposure_metrics(
            round2_exposures,
            personas,
            round_num=2,
        )
        _ = round1_post_ids  # Posts still written for report/interview reads

        logger.info(
            "round_dispatch_start",
            round_num=2,
            agent_count=len(personas),
            peers_found=sum(1 for c in round2_peer_contexts if c),
            distinct_peers_shown=exposure_metrics["r2_distinct_peers_shown"],
            peer_selection="seeded_stratified",
        )

        # Prepare worker (load model for local OllamaProvider; no-op for cloud providers)
        # immediately before dispatch — no idle gap.
        await worker.prepare()
        try:
            # Dispatch Round 2 with the pre-built per-reader peer contexts
            worker_configs = [persona_to_worker_config(p) for p in personas]
            round2_wave_decisions = await dispatch_wave(
                personas=worker_configs,
                governor=governor,
                provider=worker,
                user_message=effective_rumor_r2,
                settings=settings.governor,
                peer_contexts=round2_peer_contexts,
                state_store=state_store,
                round_num=2,
                own_priors=round2_own_priors,
            )
            round2_decisions: list[tuple[str, AgentDecision]] = [
                (wc["agent_id"], dec) for wc, dec in zip(worker_configs, round2_wave_decisions, strict=False)
            ]
            # Per-agent StateStore writes are now streamed from inside
            # batch_dispatcher._safe_agent_inference. See debug session
            # ws-agent-states-not-emitted-mid-sim.

            # Normalize peer contexts for episode storage
            round2_peer_contexts_normalized: list[str] = [
                ctx if ctx is not None else "" for ctx in round2_peer_contexts
            ]

            _raise_if_round_failed(
                2,
                round2_decisions,
                settings.governor.round_abort_failure_percent,
            )
            round2_ids = await graph_manager.write_decisions(
                round2_decisions, cycle_id, round_num=2, control_ids=control_ids
            )

            # Phase 12: Write Round 2 Post nodes (D-12 step 2)
            round2_post_ids = await graph_manager.write_posts(
                round2_decisions,
                round2_ids,
                cycle_id,
                round_num=2,
            )

            # Phase 11: Push Round 2 episodes to WriteBuffer
            round1_map = {aid: dec for aid, dec in round1_result.agent_decisions}
            for did, (agent_id, decision) in zip(round2_ids, round2_decisions, strict=False):
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

            # Compute influence edges after Round 2 (D-04: cumulative, up_to_round=2).
            # total_agents is the ACTIVE (non-PARSE_ERROR) decision count per the
            # compute_influence_edges contract — counting failed agents in the
            # denominator deflates every peer's influence weight (F-20).
            round2_active = sum(1 for _, d in round2_decisions if d.signal != SignalType.PARSE_ERROR)
            round2_weights: dict[str, float] = {}
            if round2_active > 0:
                round2_weights = await graph_manager.compute_influence_edges(
                    cycle_id,
                    up_to_round=2,
                    total_agents=round2_active,
                )
            else:
                logger.warning("influence_edges_skipped", cycle_id=cycle_id, round_num=2)
            if state_store is not None:
                state_store.bump_edges_version()  # round-2 edges are now readable

            # Compute Round 2 bracket summaries (D-08)
            round2_summaries = compute_bracket_summaries(round2_decisions, personas, brackets)

            # Rationale entries stream per agent (docs/DECISIONS.md#p10-d-02).
            if state_store is not None:
                await state_store.set_bracket_summaries(round2_summaries)

            # Compute Round 2 shifts in-memory (D-13)
            round2_shifts = _compute_shifts(
                round1_result.agent_decisions,
                round2_decisions,
                personas,
            )
            r2_control_flips, r2_treated_flips = split_flips(
                round1_result.agent_decisions, round2_decisions, control_ids
            )
            exposure_metrics.update(
                {
                    "r2_control_agents": len(control_ids),
                    "r2_flips_control": r2_control_flips,
                    "r2_flips_treated": r2_treated_flips,
                }
            )

            # Fire callback for Round 2 (progressive output)
            round2_decisions_tuple = tuple((aid, dec) for aid, dec in round2_decisions)
            if on_round_complete is not None:
                await on_round_complete(
                    RoundCompleteEvent(
                        round_num=2,
                        cycle_id=cycle_id,
                        agent_decisions=round2_decisions_tuple,
                        shift=round2_shifts,
                        bracket_summaries=round2_summaries,
                    )
                )

            r2_seconds = time.monotonic() - r2_start

            # Defaults for the 2-round configuration (ALPHASWARM_NUM_ROUNDS=2):
            # round3 fields stay empty, FINAL state is Round 2's.
            round3_decisions: list[tuple[str, AgentDecision]] = []
            round3_decisions_tuple: tuple[tuple[str, AgentDecision], ...] = ()
            round3_shifts = ShiftMetrics(
                signal_transitions=(),
                total_flips=0,
                bracket_confidence_delta=(),
                agents_shifted=0,
            )
            round3_summaries: tuple[BracketSummary, ...] = ()
            r3_seconds = 0.0

            if settings.num_rounds >= 3:
                # Round 3 (D-09: peer context from Round 2)
                phase = SimulationPhase.ROUND_3
                r3_start = time.monotonic()
                logger.info("simulation_phase_transition", phase=phase.value, cycle_id=cycle_id)
                if state_store is not None:
                    await state_store.set_phase(SimulationPhase.ROUND_3)
                    await state_store.set_round(3)

                # Shock gate before Round 3; earlier shocks are carried forward.
                if consume_shock is not None:
                    shock_text_r3 = consume_shock()
                    if shock_text_r3:
                        active_shocks.append(shock_text_r3)
                        await graph_manager.write_shock_event(
                            cycle_id,
                            shock_text_r3,
                            injected_before_round=3,
                        )
                        if state_store is not None:
                            state_store.record_applied_shock(shock_text_r3, 3)
                        logger.info(
                            "shock_injected",
                            cycle_id=cycle_id,
                            round_num=3,
                            shock_length=len(shock_text_r3),
                        )
                effective_rumor_r3 = _with_shocks(rumor, active_shocks)

                # Bracket-diverse peer contexts from Round 2 decisions in memory.
                # R3 weights are PER-READER: base + global citation share
                # (round2_weights) + settings.simulation.personal_boost for authors
                # this reader cited in R2. READ_POST writes dropped (no analytical value).
                round3_peer_contexts, round3_exposures = _build_diverse_peer_contexts(
                    personas,
                    round2_decisions,
                    source_round=2,
                    sim=settings.simulation,
                    run_seed=cycle_id,
                    global_citation_weights=round2_weights,
                )
                (
                    round3_peer_contexts,
                    round3_exposures,
                    round3_own_priors,
                ) = apply_holdout_and_priors(
                    personas,
                    round3_peer_contexts,
                    round3_exposures,
                    round2_decisions,
                    2,
                    sim=settings.simulation,
                    control_ids=control_ids,
                )
                exposure_metrics.update(compute_exposure_metrics(round3_exposures, personas, round_num=3))
                _ = round2_post_ids  # Posts still written for report/interview reads

                logger.info(
                    "round_dispatch_start",
                    round_num=3,
                    agent_count=len(personas),
                    peers_found=sum(1 for c in round3_peer_contexts if c),
                    distinct_peers_shown=exposure_metrics["r3_distinct_peers_shown"],
                    peer_selection="seeded_stratified",
                )

                # Dispatch Round 3 with pre-built peer contexts
                round3_wave_decisions = await dispatch_wave(
                    personas=worker_configs,
                    governor=governor,
                    provider=worker,
                    user_message=effective_rumor_r3,
                    settings=settings.governor,
                    peer_contexts=round3_peer_contexts,
                    state_store=state_store,
                    round_num=3,
                    own_priors=round3_own_priors,
                )
                round3_decisions: list[tuple[str, AgentDecision]] = [
                    (wc["agent_id"], dec) for wc, dec in zip(worker_configs, round3_wave_decisions, strict=False)
                ]
                # Per-agent StateStore writes are now streamed from inside
                # batch_dispatcher._safe_agent_inference. See debug session
                # ws-agent-states-not-emitted-mid-sim.

                round3_peer_contexts_normalized: list[str] = [
                    ctx if ctx is not None else "" for ctx in round3_peer_contexts
                ]

                _raise_if_round_failed(
                    3,
                    round3_decisions,
                    settings.governor.round_abort_failure_percent,
                )
                round3_ids = await graph_manager.write_decisions(
                    round3_decisions, cycle_id, round_num=3, control_ids=control_ids
                )

                # Phase 12: Write Round 3 Post nodes
                await graph_manager.write_posts(
                    round3_decisions,
                    round3_ids,
                    cycle_id,
                    round_num=3,
                )

                # Phase 11: Push Round 3 episodes to WriteBuffer
                round2_map = {aid: dec for aid, dec in round2_decisions}
                for did, (agent_id, decision) in zip(round3_ids, round3_decisions, strict=False):
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

                # Compute influence edges after Round 3 so /api/edges/{cycle}?round=3
                # returns a non-empty array (ITEM 2 of quick task 260512-jqn).
                # Without this call, simulation.py only materializes INFLUENCED_BY
                # relationships for round=1 and round=2 — the frontend "FINAL" tab
                # then renders an empty influence graph despite 100 R3 decisions
                # being written. up_to_round=3 is cumulative per D-04, but the
                # write tx fixes round=3 on every new edge so the /api/edges
                # round-filtered read picks them up.
                round3_active = sum(1 for _, d in round3_decisions if d.signal != SignalType.PARSE_ERROR)
                round3_weights: dict[str, float] = {}
                if round3_active > 0:
                    round3_weights = await graph_manager.compute_influence_edges(
                        cycle_id,
                        up_to_round=3,
                        total_agents=round3_active,
                    )
                else:
                    logger.warning("influence_edges_skipped", cycle_id=cycle_id, round_num=3)
                if state_store is not None:
                    state_store.bump_edges_version()  # round-3 edges are now readable

                # Compute Round 3 bracket summaries (D-08)
                round3_summaries = compute_bracket_summaries(round3_decisions, personas, brackets)

                # Rationale entries stream per agent (docs/DECISIONS.md#p10-d-02).
                # round3_weights is still computed above for the influence write
                # (R3 INFLUENCED_BY edges — ITEM 2 of 260512-jqn).
                if state_store is not None:
                    await state_store.set_bracket_summaries(round3_summaries)
                    _ = round3_weights  # retained for future use / explicit no-op marker

                # Compute Round 3 shifts in-memory (D-13)
                round3_shifts = _compute_shifts(
                    round2_decisions,
                    round3_decisions,
                    personas,
                )
                r3_control_flips, r3_treated_flips = split_flips(round2_decisions, round3_decisions, control_ids)
                exposure_metrics.update(
                    {
                        "r3_control_agents": len(control_ids),
                        "r3_flips_control": r3_control_flips,
                        "r3_flips_treated": r3_treated_flips,
                    }
                )

                # Fire callback for Round 3 (progressive output)
                round3_decisions_tuple = tuple((aid, dec) for aid, dec in round3_decisions)
                if on_round_complete is not None:
                    await on_round_complete(
                        RoundCompleteEvent(
                            round_num=3,
                            cycle_id=cycle_id,
                            agent_decisions=round3_decisions_tuple,
                            shift=round3_shifts,
                            bracket_summaries=round3_summaries,
                        )
                    )

                r3_seconds = time.monotonic() - r3_start

            # FINALIZING: every round is persisted; narratives (while still
            # eager) and metrics follow, so the UI no longer sits on the last
            # round's label (docs/DECISIONS.md#p7-d-07).
            phase = SimulationPhase.FINALIZING
            logger.info("simulation_phase_transition", phase=phase.value, cycle_id=cycle_id)
            if state_store is not None:
                await state_store.set_phase(SimulationPhase.FINALIZING)

            # Phase 11: Post-simulation narrative generation (D-10, D-11)
            # Worker model is still loaded here -- generate before unload
            narratives_start = time.monotonic()
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
                    provider=worker,
                )
                logger.info("narrative_generation_complete", count=len(narratives))
            narratives_seconds = time.monotonic() - narratives_start

        finally:
            # Teardown worker (unload model for local OllamaProvider; no-op for cloud providers)
            await worker.teardown()
    finally:
        # Always stop governor monitoring (outer finally)
        await governor.stop_monitoring()

    # Persist run metrics onto the Cycle node (measurement infra). Failure is
    # logged but never fails a completed simulation.
    def _parse_errors(
        decisions: list[tuple[str, AgentDecision]] | tuple[tuple[str, AgentDecision], ...],
    ) -> int:
        return sum(1 for _, d in decisions if d.signal == SignalType.PARSE_ERROR)

    final_round_decisions = round3_decisions if settings.num_rounds >= 3 else round2_decisions
    final_counts = {"buy": 0, "sell": 0, "hold": 0}
    for _, dec in final_round_decisions:
        if dec.signal != SignalType.PARSE_ERROR:
            final_counts[dec.signal.value] += 1

    cycle_metrics: dict[str, float | int | str | bool] = {
        "metrics_version": 1,
        "num_rounds": settings.num_rounds,
        "r1_seconds": round(r1_seconds, 1),
        "r2_seconds": round(r2_seconds, 1),
        "r3_seconds": round(r3_seconds, 1),
        "narratives_seconds": round(narratives_seconds, 1),
        "total_seconds": round(time.monotonic() - sim_start, 1),
        "r2_flips": round2_shifts.total_flips,
        "r3_flips": round3_shifts.total_flips,
        "r1_parse_errors": _parse_errors(round1_result.agent_decisions),
        "r2_parse_errors": _parse_errors(round2_decisions),
        "r3_parse_errors": _parse_errors(round3_decisions),
        "final_buy": final_counts["buy"],
        "final_sell": final_counts["sell"],
        "final_hold": final_counts["hold"],
        "agent_count": len(personas),
    }
    cycle_metrics.update(exposure_metrics)
    cycle_metrics.update(
        _peer_and_provenance_metrics(settings.simulation, orch, worker, git_sha=git_sha, git_dirty=git_dirty)
    )
    # Inference failures separately from all PARSE_ERRORs, for every round
    # actually run (docs/DECISIONS.md#adr-cycle-metrics).
    rounds_run: dict[int, Sequence[tuple[str, AgentDecision]]] = {
        1: round1_result.agent_decisions,
        2: round2_decisions,
    }
    if settings.num_rounds >= 3:
        rounds_run[3] = round3_decisions
    for n, decisions_n in rounds_run.items():
        cycle_metrics[f"r{n}_inference_errors"] = sum(1 for _, d in decisions_n if d.error_kind == "inference")
    cycle_metrics["final_round"] = max(rounds_run)
    try:
        await graph_manager.write_cycle_metrics(cycle_id, cycle_metrics)
    except Exception:
        logger.warning("cycle_metrics_write_failed", cycle_id=cycle_id, exc_info=True)

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
    governor: ConcurrencyController,
    provider: InferenceProvider,
) -> list[dict]:
    """Generate natural-language decision narrative for each agent (D-10, D-11).

    Uses the worker provider through governor for memory safety.
    Skip-and-log on per-agent failures (Pitfall 5 from research); hard stops
    (HARD_STOP_ERRORS) propagate bare, the first one if several fail.

    Args:
        personas: Agent personas to generate narratives for.
        all_decisions: Mapping of round_num -> list of (agent_id, AgentDecision).
        graph_manager: Neo4j graph state manager for persisting narratives.
        governor: Concurrency controller for throttling inference.
        provider: Worker InferenceProvider to route narrative inference through.
            For local path this is the OllamaProvider; for cloud path it is the
            configured cloud provider. Behavior is identical for local (same
            model, same prompt) — only the call site changes from client.generate
            to provider.chat with equivalent messages.

    Returns list of {"agent_id": str, "narrative": str} dicts that were written.
    """
    import asyncio as _asyncio

    from alphaswarm.inference.types import InferenceMessage

    # Build per-agent decision summaries
    agent_decisions_by_id: dict[str, dict[int, AgentDecision]] = {}
    for round_num, decisions in all_decisions.items():
        for agent_id, decision in decisions:
            if agent_id not in agent_decisions_by_id:
                agent_decisions_by_id[agent_id] = {}
            agent_decisions_by_id[agent_id][round_num] = decision

    persona_map = {p.id: p for p in personas}
    narratives: list[dict[str, str]] = []
    failed = 0

    async def _generate_one(agent_id: str) -> dict[str, str] | None:
        persona = persona_map.get(agent_id)
        if not persona:
            return None
        rounds = agent_decisions_by_id.get(agent_id, {})
        if not rounds:
            return None

        # Build a prompt summarizing the arc over the rounds that ran
        # (docs/DECISIONS.md#adr-num-rounds)
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
            f"Summarize this agent's {len(rounds)}-round decision arc in 2-3 sentences. "
            "Note any signal changes and key influences. Be concise.\n\n" + "\n".join(lines)
        )

        messages: list[InferenceMessage] = [
            {
                "role": "system",
                "content": (
                    "You are a concise financial analyst narrator. Summarize agent decision arcs in 2-3 sentences."
                ),
            },
            {"role": "user", "content": prompt},
        ]

        nonlocal failed
        try:
            async with governor:
                result = await provider.chat(messages)
                narrative_text = result.content.strip()
                if narrative_text:
                    return {"agent_id": agent_id, "narrative": narrative_text}
                return None
        except HARD_STOP_ERRORS:
            raise  # budget/auth/crisis stop the run (docs/DECISIONS.md#adr-taskgroup-dispatch)
        except Exception:
            failed += 1
            logger.warning("narrative_generation_failed", agent_id=agent_id, exc_info=True)
            return None

    # Fan out through a TaskGroup (the governor throttles); hard stops leave bare.
    tasks: list[_asyncio.Task[dict[str, str] | None]] = []
    try:
        async with _asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(_generate_one(agent_id)) for agent_id in agent_decisions_by_id]
    except* HARD_STOP_ERRORS as eg:
        raise eg.exceptions[0] from eg

    for task in tasks:
        outcome = task.result()
        if outcome is not None:
            narratives.append(outcome)

    if failed:
        logger.warning("narrative_generation_partial_failures", error_count=failed)

    # Batch-write all successful narratives to Agent nodes
    if narratives:
        await graph_manager.write_decision_narratives(narratives)

    return narratives
