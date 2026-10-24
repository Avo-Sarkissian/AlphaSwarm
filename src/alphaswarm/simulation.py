"""Simulation orchestration: seeding, the Round 1 market context, the round loop, metrics.

run_simulation seeds the cycle with the orchestrator, builds the fenced Round 1 market
context, then loops over settings.num_rounds through rounds.run_round inside one worker
session and one governor session, and finally writes the cycle metrics and status
(docs/DECISIONS.md#adr-round-runner). The engine never imports Ollama objects: providers
arrive in SimulationDeps, built by alphaswarm.inference.factory.
"""

from __future__ import annotations

import asyncio
import dataclasses
import re
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import structlog

from alphaswarm.context_formatter import format_market_context
from alphaswarm.errors import run_error_from_exception
from alphaswarm.ingestion.types import ContextPacket
from alphaswarm.manifest import (
    build_run_manifest,
    current_git_revision,
    derive_sim_seed,
    provenance_from_providers,
    sha256_text,
)
from alphaswarm.metrics import RoundInput, methodology_metrics
from alphaswarm.personas import compute_prompt_template_hash, generate_personas
from alphaswarm.prompts.decision import JSON_OUTPUT_INSTRUCTIONS
from alphaswarm.prompts.modifiers import MODIFIER_GENERATION_PROMPT
from alphaswarm.rounds import (
    OnRoundComplete,
    RoundContext,
    RoundOutcome,
    ShiftMetrics,
    SimulationDeps,
    run_round,
)
from alphaswarm.seed import generate_modifiers, inject_seed
from alphaswarm.telemetry import governor_metrics
from alphaswarm.types import SignalType, SimulationPhase

if TYPE_CHECKING:
    from alphaswarm.errors import RunErrorCode
    from alphaswarm.graph import CycleStatus, GraphStateManager
    from alphaswarm.inference.provider import InferenceProvider
    from alphaswarm.ingestion.providers import MarketDataProvider, NewsProvider
    from alphaswarm.settings import SimulationSettings
    from alphaswarm.state import BracketSummary, StateSink
    from alphaswarm.types import (
        AgentDecision,
        AgentPersona,
        BracketConfig,
        ParsedModifiersResult,
        ParsedSeedResult,
    )

__all__ = ["SimulationDeps", "SimulationResult", "assemble_market_context", "run_simulation"]

logger = structlog.get_logger(component="simulation")

_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")
"""Same pattern as alphaswarm.ingestion.rss_provider._TICKER_RE (Phase 38 T-38-01).
Defense-in-depth: re-applied here so non-ticker entities (company names like
'NVIDIA', 'Federal Reserve') never reach MarketDataProvider.get_prices. All
entities pass to NewsProvider.get_headlines (provider handles routing)."""


_PEER_SELECTION_VERSION: Final = 2
"""Stamped as ``peer_selection_version``: 2 = seeded stratified sampling with a
per-bracket cap and shuffle; 1 = the legacy deterministic top-weight fill."""

_PEER_SEED_SOURCE: Final = "sim_seed"
"""What run_simulation passes as ``run_seed`` to the peer builder: ``str(sim_seed)``
(docs/DECISIONS.md#adr-run-manifest). Cycles recorded before the run manifest say "cycle_id"."""


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


_EMPTY_SHIFT: Final = ShiftMetrics(signal_transitions=(), total_flips=0, bracket_confidence_delta=(), agents_shifted=0)
_LEGACY_ROUNDS: Final = (1, 2, 3)
"""Rounds whose seconds, parse-error and flip keys every cycle carries, 0 when the round
did not run (docs/DECISIONS.md#adr-cycle-metrics)."""


@dataclasses.dataclass(frozen=True)
class SimulationResult:
    """Immutable result of one run: one RoundOutcome per round that ran
    (docs/DECISIONS.md#p7-d-08).

    The roundN_* properties keep the earlier shape for the CLI and tests; a round that
    did not run reads as an empty tuple or a zero ShiftMetrics.
    """

    cycle_id: str
    parsed_result: ParsedSeedResult
    rounds: tuple[RoundOutcome, ...]

    def outcome(self, round_num: int) -> RoundOutcome | None:
        """The outcome of ``round_num``, or None when that round did not run."""
        return next((o for o in self.rounds if o.round_num == round_num), None)

    def _decisions(self, round_num: int) -> tuple[tuple[str, AgentDecision], ...]:
        found = self.outcome(round_num)
        return found.decisions if found is not None else ()

    def _summaries(self, round_num: int) -> tuple[BracketSummary, ...]:
        found = self.outcome(round_num)
        return found.bracket_summaries if found is not None else ()

    def _shift(self, round_num: int) -> ShiftMetrics:
        found = self.outcome(round_num)
        return found.shift if found is not None and found.shift is not None else _EMPTY_SHIFT

    @property
    def round1_decisions(self) -> tuple[tuple[str, AgentDecision], ...]:
        return self._decisions(1)

    @property
    def round2_decisions(self) -> tuple[tuple[str, AgentDecision], ...]:
        return self._decisions(2)

    @property
    def round3_decisions(self) -> tuple[tuple[str, AgentDecision], ...]:
        return self._decisions(3)

    @property
    def round2_shifts(self) -> ShiftMetrics:
        return self._shift(2)

    @property
    def round3_shifts(self) -> ShiftMetrics:
        return self._shift(3)

    @property
    def round1_summaries(self) -> tuple[BracketSummary, ...]:
        return self._summaries(1)

    @property
    def round2_summaries(self) -> tuple[BracketSummary, ...]:
        return self._summaries(2)

    @property
    def round3_summaries(self) -> tuple[BracketSummary, ...]:
        return self._summaries(3)


async def assemble_market_context(
    cycle_id: str,
    parsed_result: ParsedSeedResult,
    market: MarketDataProvider | None,
    news: NewsProvider | None,
) -> str | None:
    """Build the fenced Round 1 market-context block (docs/DECISIONS.md#adr-market-context).

    Ticker-shaped entity names go to the market provider and every entity goes to the
    news provider; providers never raise (docs/DECISIONS.md#adr-provider-never-raise).
    Returns None when a provider is missing or nothing renderable came back.
    """
    if market is None or news is None:
        logger.warning("context_assembly_skipped", reason="no_providers_configured", cycle_id=cycle_id)
        return None
    entity_names = [e.name for e in parsed_result.seed_event.entities]
    tickers = [name for name in entity_names if _TICKER_RE.match(name)]
    market_slices, news_slices = await asyncio.gather(market.get_prices(tickers), news.get_headlines(entity_names))
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
    return format_market_context(packet)


async def _round_1_market_context(deps: SimulationDeps, cycle_id: str, parsed_result: ParsedSeedResult) -> str | None:
    """The Round 1 block: the recorded fixture when one is set, else the live fetch.

    A point-in-time run replaces the live market and news fetch with
    ``deps.context_fixture`` (docs/DECISIONS.md#adr-eval-harness).
    """
    fixture = deps.context_fixture
    if fixture is None:
        return await assemble_market_context(cycle_id, parsed_result, deps.market, deps.news)
    block = format_market_context(fixture)
    logger.info(
        "context_fixture_used",
        cycle_id=cycle_id,
        as_of=fixture.as_of.isoformat(),
        entity_count=len(fixture.entities),
        rendered=block is not None,
    )
    return block


async def _enter_phase(state: StateSink | None, phase: SimulationPhase, *, cycle_id: str | None = None) -> None:
    """Log and publish a phase transition (docs/DECISIONS.md#p7-d-07)."""
    logger.info("simulation_phase_transition", phase=phase.value, cycle_id=cycle_id)
    if state is not None:
        await state.set_phase(phase)


async def _enter_round(state: StateSink | None, round_num: int, cycle_id: str) -> None:
    """Start round ``round_num``: phase ROUND_n first, then the round number."""
    await _enter_phase(state, SimulationPhase(f"round_{round_num}"), cycle_id=cycle_id)
    if state is not None:
        await state.set_round(round_num)


def _cycle_metrics(
    outcomes: Sequence[RoundOutcome], *, num_rounds: int, agent_count: int, total_seconds: float
) -> dict[str, float | int | str | bool]:
    """Flat per-cycle metrics (docs/DECISIONS.md#adr-cycle-metrics).

    The baseline r1..r3 seconds, parse-error and flip keys are always present (0 for a
    round that did not run); every other per-round key comes from that round's
    RoundOutcome.metrics, so it exists only for rounds that ran.
    """
    final = outcomes[-1]
    counts = {"buy": 0, "sell": 0, "hold": 0}
    for _, decision in final.decisions:
        if decision.signal != SignalType.PARSE_ERROR:
            counts[decision.signal.value] += 1
    metrics: dict[str, float | int | str | bool] = {
        "metrics_version": 3,
        "num_rounds": num_rounds,
        "total_seconds": round(total_seconds, 1),
        "final_buy": counts["buy"],
        "final_sell": counts["sell"],
        "final_hold": counts["hold"],
        "agent_count": agent_count,
        "final_round": final.round_num,
    }
    for n in _LEGACY_ROUNDS:
        metrics[f"r{n}_seconds"] = 0.0
        metrics[f"r{n}_parse_errors"] = 0
        if n >= 2:
            metrics[f"r{n}_flips"] = 0
    for outcome in outcomes:
        metrics.update(outcome.metrics)
    return metrics


async def _record_cycle_metrics(
    deps: SimulationDeps,
    cycle_id: str,
    outcomes: Sequence[RoundOutcome],
    *,
    roster: Sequence[AgentPersona],
    run_seed: str,
    total_seconds: float,
    git_sha: str | None,
    git_dirty: bool | None,
    extra: Mapping[str, float] | None = None,
) -> None:
    """Write the cycle metrics; a failed write is logged and never fails the run."""
    metrics = _cycle_metrics(
        outcomes,
        num_rounds=deps.settings.num_rounds,
        agent_count=len(roster),
        total_seconds=total_seconds,
    )
    metrics.update(_derived_cycle_metrics(outcomes, roster, run_seed=run_seed, cycle_id=cycle_id))
    metrics.update(
        _peer_and_provenance_metrics(
            deps.settings.simulation,
            deps.orchestrator,
            deps.worker,
            git_sha=git_sha,
            git_dirty=git_dirty,
        )
    )
    if extra:
        metrics.update(extra)
    try:
        await deps.graph.write_cycle_metrics(cycle_id, metrics)
    except Exception:
        logger.warning("cycle_metrics_write_failed", cycle_id=cycle_id, exc_info=True)


def _derived_cycle_metrics(
    outcomes: Sequence[RoundOutcome],
    roster: Sequence[AgentPersona],
    *,
    run_seed: str,
    cycle_id: str,
) -> dict[str, float | int | str | bool]:
    """Consensus, dispersion and cross-round estimators for the cycle metrics
    (metrics_version 3, docs/DECISIONS.md#adr-consensus-estimators).

    Derived numbers only: a bug here is logged with its traceback and the run
    still completes with its other metrics (docs/DECISIONS.md#adr-cycle-metrics).
    """
    metrics: dict[str, float | int | str | bool] = {}
    try:
        metrics.update(
            methodology_metrics(
                [RoundInput(o.round_num, o.decisions, o.exposures) for o in outcomes],
                roster,
                run_seed=run_seed,
            )
        )
    except Exception:
        logger.warning("methodology_metrics_failed", cycle_id=cycle_id, exc_info=True)
    return metrics


def _collect_prompt_hashes(brackets: Sequence[BracketConfig]) -> dict[str, str]:
    """sha256 of every static prompt text a run depends on (docs/DECISIONS.md#adr-run-manifest).

    ``persona_template`` covers templates, static modifiers and the JSON
    instructions together (the value also stored as Cycle.prompt_template_hash);
    the per-piece hashes show which part changed between two manifests.
    """
    hashes = {
        "persona_template": compute_prompt_template_hash(brackets),
        "json_output_instructions": sha256_text(JSON_OUTPUT_INSTRUCTIONS),
        "modifier_prompt": sha256_text(MODIFIER_GENERATION_PROMPT),
    }
    for bracket in brackets:
        hashes[f"bracket:{bracket.bracket_type.value}"] = sha256_text(bracket.system_prompt_template)
    return hashes


async def _record_run_manifest(
    deps: SimulationDeps,
    cycle_id: str,
    brackets: Sequence[BracketConfig],
    modifier_result: ParsedModifiersResult | None,
    market_context: str | None,
    *,
    git: tuple[str | None, bool | None],
) -> int:
    """Fix the run seed and stamp the run manifest on the Cycle; return the seed.

    Runs after seeding and before Round 1, so a run that fails later is still
    described. ``sim_seed`` is the configured value or, when unset, a blake2b
    derivation of the cycle id. A failed write fails the run: an undescribed
    cycle must not look like a valid experiment (docs/DECISIONS.md#adr-run-manifest).
    """
    sim = deps.settings.simulation
    sim_seed = sim.sim_seed if sim.sim_seed is not None else derive_sim_seed(cycle_id)
    manifest = build_run_manifest(
        cycle_id=cycle_id,
        settings=deps.settings,
        brackets=brackets,
        provenance=deps.provenance or provenance_from_providers(deps.orchestrator, deps.worker),
        prompt_hashes=_collect_prompt_hashes(brackets),
        modifiers=modifier_result.modifiers if modifier_result is not None else None,
        modifier_parse_tier=modifier_result.parse_tier if modifier_result is not None else None,
        market_context=market_context,
        sim_seed=sim_seed,
        git_sha=git[0],
        git_dirty=git[1],
    )
    await deps.graph.write_run_manifest(cycle_id, manifest)
    return sim_seed


async def _run_simulation(
    rumor: str,
    deps: SimulationDeps,
    personas: Sequence[AgentPersona],
    brackets: Sequence[BracketConfig],
    *,
    on_round_complete: OnRoundComplete,
    consume_shock: Callable[[], str | None] | None,
    tracker: _RunTracker,
) -> SimulationResult:
    """Body of run_simulation; see the public wrapper below for the contract."""
    # One run clock from the first instruction: total_seconds now includes
    # seeding, and seed_seconds isolates it (docs/DECISIONS.md#adr-cycle-metrics).
    sim_start = time.monotonic()
    settings, graph, state = deps.settings, deps.graph, deps.state
    await _enter_phase(state, SimulationPhase.IDLE)
    if state is not None:
        state.set_num_rounds(settings.num_rounds)
    # Provenance for the cycle metrics; git runs as a subprocess, off the event loop.
    git_sha, git_dirty = await asyncio.to_thread(current_git_revision)

    await _enter_phase(state, SimulationPhase.SEEDING)
    if state is not None:
        await state.begin_run([p.id for p in personas])
    cycle_id, parsed_result, modifier_result = await inject_seed(
        rumor,
        settings,
        deps.orchestrator,
        graph,
        modifier_generator=generate_modifiers,
        prompt_template_hash=compute_prompt_template_hash(brackets),
    )
    tracker.cycle_id = cycle_id
    # Task-local: every later log line of this run carries the cycle id
    # (docs/DECISIONS.md#adr-security-2026-08).
    structlog.contextvars.bind_contextvars(cycle_id=cycle_id)
    if state is not None:
        await state.set_cycle(cycle_id)
    roster = list(personas)
    if modifier_result is not None:
        roster = generate_personas(list(brackets), modifiers=modifier_result.modifiers)
        logger.info("personas_regenerated_with_modifiers", parse_tier=modifier_result.parse_tier)
    market_context = await _round_1_market_context(deps, cycle_id, parsed_result)
    sim_seed = await _record_run_manifest(
        deps, cycle_id, brackets, modifier_result, market_context, git=(git_sha, git_dirty)
    )

    ctx = RoundContext(
        deps=deps,
        cycle_id=cycle_id,
        personas=tuple(roster),
        brackets=tuple(brackets),
        rumor=rumor,
        market_context=market_context,
        entities=tuple(await graph.read_cycle_entities(cycle_id)),
        run_seed=str(sim_seed),  # docs/DECISIONS.md#adr-run-manifest
        on_round_complete=on_round_complete,
        sim_seed=sim_seed,
    )
    outcomes: list[RoundOutcome] = []
    shocks: list[str] = []
    # One governor session and one worker load for every round; inject_seed already
    # tore the orchestrator down (docs/DECISIONS.md#adr-round-runner).
    await deps.controller.start_monitoring()
    try:
        await deps.worker.prepare()
        seed_seconds = time.monotonic() - sim_start
        try:
            for round_num in range(1, settings.num_rounds + 1):
                await _enter_round(state, round_num, cycle_id)
                # Consumed after the round started, so the shock window is already
                # closed when the last round consumes (docs/DECISIONS.md#b1).
                if round_num >= 2 and consume_shock is not None:
                    text = consume_shock()
                    if text:
                        shocks.append(text)
                prev = outcomes[-1] if outcomes else None
                outcomes.append(await run_round(ctx, round_num, prev, tuple(shocks)))
            await _enter_phase(state, SimulationPhase.FINALIZING, cycle_id=cycle_id)
        finally:
            await deps.worker.teardown()
    finally:
        await deps.controller.stop_monitoring()

    await _record_cycle_metrics(
        deps,
        cycle_id,
        outcomes,
        roster=roster,
        run_seed=ctx.run_seed,
        total_seconds=time.monotonic() - sim_start,
        git_sha=git_sha,
        git_dirty=git_dirty,
        extra={"seed_seconds": round(seed_seconds, 1), **governor_metrics(deps.controller)},
    )
    # Every round is persisted and metrics were attempted (docs/DECISIONS.md#adr-cycle-metrics).
    await graph.set_cycle_status(cycle_id, "complete")
    await _enter_phase(state, SimulationPhase.COMPLETE, cycle_id=cycle_id)
    logger.info("simulation_complete", cycle_id=cycle_id, rounds_run=len(outcomes))
    return SimulationResult(cycle_id=cycle_id, parsed_result=parsed_result, rounds=tuple(outcomes))


async def run_simulation(
    rumor: str,
    deps: SimulationDeps,
    personas: Sequence[AgentPersona],
    brackets: Sequence[BracketConfig],
    *,
    on_round_complete: OnRoundComplete = None,
    consume_shock: Callable[[], str | None] | None = None,
) -> SimulationResult:
    """Run the full multi-round simulation (docs/DECISIONS.md#adr-round-runner).

    Phases (docs/DECISIONS.md#p7-d-07): IDLE -> SEEDING -> ROUND_1 .. ROUND_N ->
    FINALIZING -> COMPLETE, mirrored to ``deps.state`` when one is given.

    Seeding parses the rumor and generates persona modifiers before the Cycle is
    created. Round 1 receives the fenced market context when both the market and the
    news provider are supplied (docs/DECISIONS.md#adr-market-context); a
    ``deps.context_fixture`` (a point-in-time ContextPacket for evaluation runs,
    docs/DECISIONS.md#adr-eval-harness) takes precedence over both providers. The
    worker is prepared once before Round 1 and torn down once after the last round,
    inside one governor monitoring session. Each round runs through
    ``rounds.run_round``; a pending shock is consumed after its round has started and
    carried into every later round (docs/DECISIONS.md#b1).

    Cycle status (docs/DECISIONS.md#adr-cycle-metrics): the Cycle is created
    ``running``; ``complete`` is written after the last round and the metrics attempt;
    ``failed`` (+ error_code) on any exception and ``cancelled`` on cancellation are
    written here, best effort and within ``_TERMINAL_STATUS_TIMEOUT_S``, then the
    exception propagates unchanged.
    """
    tracker = _RunTracker()
    try:
        return await _run_simulation(
            rumor,
            deps,
            personas,
            brackets,
            on_round_complete=on_round_complete,
            consume_shock=consume_shock,
            tracker=tracker,
        )
    except asyncio.CancelledError:
        await _record_terminal_status(deps.graph, tracker.cycle_id, "cancelled", None)
        raise
    except Exception as exc:
        code = run_error_from_exception(exc, round_num=None).code
        await _record_terminal_status(deps.graph, tracker.cycle_id, "failed", code)
        raise
