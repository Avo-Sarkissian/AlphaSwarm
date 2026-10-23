"""Simulation pipeline for AlphaSwarm.

Composes inject_seed, dispatch_wave, and GraphStateManager.persist_round into:
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
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import structlog

from alphaswarm.batch_dispatcher import dispatch_wave
from alphaswarm.context_formatter import format_market_context
from alphaswarm.errors import run_error_from_exception
from alphaswarm.inference.ollama_provider import OllamaProvider
from alphaswarm.inference.types import ProviderRole
from alphaswarm.ingestion.types import ContextPacket
from alphaswarm.manifest import current_git_revision
from alphaswarm.metrics import split_flips
from alphaswarm.peers import build_peer_contexts, compute_exposure_metrics
from alphaswarm.personas import compute_prompt_template_hash, generate_personas, persona_to_worker_config
from alphaswarm.rounds import (
    OnRoundComplete,
    RoundCompleteEvent,
    ShiftMetrics,
    _persist_round_records,
    _raise_if_round_failed,
    _with_shocks,
    compute_bracket_summaries,
    compute_shifts,
)
from alphaswarm.security.sanitize import sanitize_rationale
from alphaswarm.seed import generate_modifiers, inject_seed
from alphaswarm.state import BracketSummary
from alphaswarm.types import SignalType, SimulationPhase

if TYPE_CHECKING:
    from alphaswarm.episodes import EntityRef
    from alphaswarm.errors import RunErrorCode
    from alphaswarm.graph import CycleStatus, GraphStateManager
    from alphaswarm.inference.concurrency import ConcurrencyController
    from alphaswarm.inference.provider import InferenceProvider
    from alphaswarm.ingestion.providers import MarketDataProvider, NewsProvider
    from alphaswarm.ollama_client import OllamaClient
    from alphaswarm.ollama_models import OllamaModelManager
    from alphaswarm.settings import AppSettings, SimulationSettings
    from alphaswarm.state import StateStore
    from alphaswarm.types import (
        AgentDecision,
        AgentPersona,
        BracketConfig,
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
    citations_dropped: int = 0  # CITED targets that matched no Agent (r1_citations_dropped)


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
    entities: Sequence[EntityRef] = (),
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
    8. persist_round with round_num=1 (one transaction)
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
        entities: The cycle's entities (read once by run_simulation), matched
            against rationales for REFERENCES edges.

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
            #    persist the round in one transaction
            _raise_if_round_failed(
                1,
                agent_decisions,
                settings.governor.round_abort_failure_percent,
            )
            persisted = await _persist_round_records(
                graph_manager,
                cycle_id,
                1,
                agent_decisions,
                personas=personas,
                peer_contexts=None,
                prev_decisions=None,
                entities=entities,
            )
            round1_decision_ids = list(persisted.decision_ids)
            round1_citations_dropped = persisted.citations_dropped
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
        citations_dropped=round1_citations_dropped,
    )


@dataclasses.dataclass
class _RunTracker:
    """What the run_simulation wrapper needs to know about a run in flight."""

    cycle_id: str | None = None


# A managed write keeps retrying an unreachable database for the driver's
# max_transaction_retry_time (30 s), and the failed/cancelled write runs before
# the exception reaches the caller, so it is bounded: Stop and a failed run
# return promptly while Neo4j is down (docs/DECISIONS.md#adr-cycle-metrics).
_TERMINAL_STATUS_TIMEOUT_S: Final = 5.0


async def _record_terminal_status(
    graph_manager: GraphStateManager,
    cycle_id: str | None,
    status: CycleStatus,
    error_code: RunErrorCode | None,
) -> None:
    """Best-effort terminal status write; never masks the error being raised.

    docs/DECISIONS.md#adr-cycle-metrics: failed/cancelled are written from
    the except path; a write that fails or outlasts
    ``_TERMINAL_STATUS_TIMEOUT_S`` is logged, the cycle stays ``running``,
    and the original exception keeps propagating.
    """
    if cycle_id is None:
        return  # the run failed before the Cycle existed
    try:
        async with asyncio.timeout(_TERMINAL_STATUS_TIMEOUT_S):
            await graph_manager.set_cycle_status(cycle_id, status, error_code=error_code)
    except Exception:
        logger.warning(
            "cycle_status_write_failed",
            cycle_id=cycle_id,
            status=status,
            exc_info=True,
        )


async def _run_simulation(
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
    consume_shock: Callable[[], str | None] | None = None,
    market_provider: MarketDataProvider | None = None,
    news_provider: NewsProvider | None = None,
    orchestrator_provider: InferenceProvider | None = None,
    worker_provider: InferenceProvider | None = None,
    context_fixture: ContextPacket | None = None,
    tracker: _RunTracker,
) -> SimulationResult:
    """Body of run_simulation; see the public wrapper below for the contract."""
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
        prompt_template_hash=compute_prompt_template_hash(brackets),
    )
    # run_simulation runs in its own task (SimulationManager) or as the CLI's main
    # coroutine, so this binding is task-local; agent tasks created later inherit it,
    # and every later log line of this run carries the cycle id
    # (docs/DECISIONS.md#adr-security-2026-08).
    structlog.contextvars.bind_contextvars(cycle_id=cycle_id)
    tracker.cycle_id = cycle_id
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

    # Entities are read once per cycle and matched against every round's
    # rationales inside persist_round (docs/DECISIONS.md#p11-d-09).
    entities = await graph_manager.read_cycle_entities(cycle_id)

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
        entities=entities,
    )
    r1_seconds = time.monotonic() - r1_start
    cycle_id = round1_result.cycle_id

    phase = SimulationPhase.ROUND_1
    logger.info("simulation_phase_transition", phase=phase.value, cycle_id=cycle_id)

    # Skip Round 1 influence-edge computation: Round 1 agents see only the
    # rumor (no peer context), so they can't populate `cited_agents`, so
    # `compute_influence_edges(up_to_round=1)` always returns {} and the
    # returned weights were never read anyway (Round 2 builds peer context
    # in memory via `build_peer_contexts`, not from these weights).
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
        _peers = build_peer_contexts(
            personas,
            round1_result.agent_decisions,
            source_round=1,
            sim=settings.simulation,
            run_seed=cycle_id,
        )
        round2_peer_contexts, round2_exposures = list(_peers.contexts), list(_peers.exposures)
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

            _raise_if_round_failed(
                2,
                round2_decisions,
                settings.governor.round_abort_failure_percent,
            )
            round2_persisted = await _persist_round_records(
                graph_manager,
                cycle_id,
                2,
                round2_decisions,
                personas=personas,
                peer_contexts=round2_peer_contexts,
                prev_decisions=round1_result.agent_decisions,
                entities=entities,
                control_ids=control_ids,
            )

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
            round2_shifts = compute_shifts(
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
            round3_citations_dropped = 0

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
                _peers = build_peer_contexts(
                    personas,
                    round2_decisions,
                    source_round=2,
                    sim=settings.simulation,
                    run_seed=cycle_id,
                    global_citation_weights=round2_weights,
                )
                round3_peer_contexts, round3_exposures = list(_peers.contexts), list(_peers.exposures)
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

                _raise_if_round_failed(
                    3,
                    round3_decisions,
                    settings.governor.round_abort_failure_percent,
                )
                round3_persisted = await _persist_round_records(
                    graph_manager,
                    cycle_id,
                    3,
                    round3_decisions,
                    personas=personas,
                    peer_contexts=round3_peer_contexts,
                    prev_decisions=round2_decisions,
                    entities=entities,
                    control_ids=control_ids,
                )
                round3_citations_dropped = round3_persisted.citations_dropped

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
                round3_shifts = compute_shifts(
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

            # FINALIZING: every round is persisted; the metrics and status write
            # follow, so the UI no longer sits on the last round's label
            # (docs/DECISIONS.md#p7-d-07).
            phase = SimulationPhase.FINALIZING
            logger.info("simulation_phase_transition", phase=phase.value, cycle_id=cycle_id)
            if state_store is not None:
                await state_store.set_phase(SimulationPhase.FINALIZING)

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
    citations_dropped = {
        1: round1_result.citations_dropped,
        2: round2_persisted.citations_dropped,
        3: round3_citations_dropped,
    }
    for n, decisions_n in rounds_run.items():
        cycle_metrics[f"r{n}_inference_errors"] = sum(1 for _, d in decisions_n if d.error_kind == "inference")
        cycle_metrics[f"r{n}_citations_dropped"] = citations_dropped[n]
    cycle_metrics["final_round"] = max(rounds_run)
    try:
        await graph_manager.write_cycle_metrics(cycle_id, cycle_metrics)
    except Exception:
        logger.warning("cycle_metrics_write_failed", cycle_id=cycle_id, exc_info=True)

    # Rounds are persisted and metrics were attempted: the cycle is complete
    # (docs/DECISIONS.md#adr-cycle-metrics). A failure here fails the run.
    await graph_manager.set_cycle_status(cycle_id, "complete")

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
    consume_shock: Callable[[], str | None] | None = None,
    market_provider: MarketDataProvider | None = None,
    news_provider: NewsProvider | None = None,
    orchestrator_provider: InferenceProvider | None = None,
    worker_provider: InferenceProvider | None = None,
    context_fixture: ContextPacket | None = None,
) -> SimulationResult:
    """Run the full multi-round simulation (docs/DECISIONS.md#p7-d-04).

    Phases (docs/DECISIONS.md#p7-d-07): IDLE -> SEEDING -> ROUND_1 .. ROUND_N -> FINALIZING -> COMPLETE,
    mirrored to ``state_store`` when one is given.

    Seeding parses the rumor and generates persona modifiers before the Cycle
    is created. Round 1 receives the fenced market context when both
    ``market_provider`` and ``news_provider`` are supplied
    (docs/DECISIONS.md#adr-market-context); a ``context_fixture`` (a
    point-in-time ContextPacket for evaluation runs,
    docs/DECISIONS.md#adr-eval-harness) takes precedence over both providers.
    Each later round builds per-reader peer contexts in memory from the
    previous round (docs/DECISIONS.md#adr-diverse-peer-context). After
    ``dispatch_wave`` a round is aborted with ``RoundFailedError`` when too
    many agents failed; otherwise it is persisted in one ``persist_round``
    transaction, influence edges are computed and ``on_round_complete`` fires.

    Cycle status (docs/DECISIONS.md#adr-cycle-metrics): the Cycle is created
    ``running``; ``complete`` is written after the last round and the metrics
    attempt; ``failed`` (+ error_code) on any exception and ``cancelled`` on
    cancellation are written here, best effort and within
    ``_TERMINAL_STATUS_TIMEOUT_S``, then the exception propagates unchanged.
    """
    tracker = _RunTracker()
    try:
        return await _run_simulation(
            rumor,
            settings,
            ollama_client,
            model_manager,
            graph_manager,
            governor,
            personas,
            brackets,
            on_round_complete=on_round_complete,
            state_store=state_store,
            consume_shock=consume_shock,
            market_provider=market_provider,
            news_provider=news_provider,
            orchestrator_provider=orchestrator_provider,
            worker_provider=worker_provider,
            context_fixture=context_fixture,
            tracker=tracker,
        )
    except asyncio.CancelledError:
        await _record_terminal_status(graph_manager, tracker.cycle_id, "cancelled", None)
        raise
    except Exception as exc:
        code = run_error_from_exception(exc, round_num=None).code
        await _record_terminal_status(graph_manager, tracker.cycle_id, "failed", code)
        raise
