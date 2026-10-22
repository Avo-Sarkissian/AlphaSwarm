"""Batch agent dispatch via asyncio.TaskGroup with jitter and failure tracking.

All batch agent processing MUST use dispatch_wave() -- no bare create_task
calls anywhere in the codebase (INFRA-07).

Pattern:
    results = await dispatch_wave(
        personas=worker_configs,
        governor=governor,
        provider=ollama_provider,
        user_message="Seed rumor text",
        settings=governor_settings,
    )
"""

from __future__ import annotations

import asyncio
import random
from typing import TYPE_CHECKING

import structlog

from alphaswarm.errors import AuthError, BudgetExceededError, GovernorCrisisError
from alphaswarm.types import AgentDecision, SignalType
from alphaswarm.worker import agent_worker

if TYPE_CHECKING:
    from collections.abc import Sequence

    from alphaswarm.config import GovernorSettings
    from alphaswarm.inference.concurrency import ConcurrencyController
    from alphaswarm.inference.provider import InferenceProvider
    from alphaswarm.state import StateStore
    from alphaswarm.worker import WorkerPersonaConfig

log = structlog.get_logger(component="batch_dispatcher")

# Errors that must stop a run instead of becoming PARSE_ERROR decisions
# (docs/DECISIONS.md#adr-taskgroup-dispatch).
HARD_STOP_ERRORS: tuple[type[BaseException], ...] = (
    BudgetExceededError,
    AuthError,
    GovernorCrisisError,
)
_NEVER_CATCH: tuple[type[BaseException], ...] = (
    asyncio.CancelledError,
    KeyboardInterrupt,
    *HARD_STOP_ERRORS,
)


async def _safe_agent_inference(
    persona: WorkerPersonaConfig,
    governor: ConcurrencyController,
    provider: InferenceProvider,
    user_message: str,
    peer_context: str | None,
    market_context: str | None,
    jitter_min: float,
    jitter_max: float,
    state_store: StateStore | None = None,
    round_num: int = 0,
    own_prior: str | None = None,
) -> AgentDecision:
    """Run a single agent inference with jitter and exception safety.

    Applies random jitter BEFORE acquiring the governor slot (D-14).
    Catches only Exception subclasses (excluding GovernorCrisisError,
    BudgetExceededError, and AuthError).
    CancelledError and KeyboardInterrupt are NEVER caught -- they propagate
    to preserve TaskGroup cleanup and Ctrl+C handling (review concern #2).
    BudgetExceededError is NEVER caught -- when the spend cap trips, the wave
    must halt cleanly (completed rounds already persisted) rather than
    silently converting agents into PARSE_ERRORs.
    AuthError is NEVER caught -- a 401/403 is a deterministic config error
    (bad API key), not a transient per-agent failure.  Propagating it halts
    the wave immediately so all 100 agents do not silently become PARSE_ERRORs
    burning 3 waves of failed calls before the operator notices.

    Streams every resolved AgentDecision, PARSE_ERROR included, to
    state_store.update_agent_state the moment the agent finishes, so the WS
    broadcaster sees a progressively-filling agent_states dict and a failed
    agent stops showing "thinking" (docs/DECISIONS.md#adr-streaming-state).

    Also (ITEM 4 of quick task 260512-jqn): after a successful inference,
    streams one RationaleEntry into state_store so the WS rationale feed
    populates progressively (1 → 100 over the round) instead of bulk-
    arriving at end-of-round. PARSE_ERROR decisions skip only the rationale
    push, so the feed carries reasoning, not error text.

    Returns:
        AgentDecision on success, or PARSE_ERROR AgentDecision on failure.

    Raises:
        asyncio.CancelledError: Always re-raised for TaskGroup cleanup.
        KeyboardInterrupt: Always re-raised for Ctrl+C handling.
        GovernorCrisisError: Always re-raised (crisis must propagate).
        BudgetExceededError: Always re-raised (spend cap must halt the wave).
        AuthError: Always re-raised (bad API key is a config error, not transient).
    """
    try:
        await asyncio.sleep(random.uniform(jitter_min, jitter_max))
        async with agent_worker(persona, governor, provider, state_store=state_store) as worker:
            decision = await worker.infer(
                user_message=user_message,
                peer_context=peer_context,
                market_context=market_context,
                own_prior=own_prior,
            )
    except _NEVER_CATCH:
        raise  # NEVER catch these -- preserves TaskGroup cleanup and Ctrl+C
    except Exception as e:
        log.warning("agent inference failed", agent_id=persona["agent_id"], error=str(e))
        decision = AgentDecision(
            signal=SignalType.PARSE_ERROR,
            confidence=0.0,
            sentiment=0.0,
            rationale=f"Inference failed for {persona['agent_id']}: {e}",
            error_kind="inference",
        )

    if state_store is None:
        return decision

    # Every resolved agent streams its state at once, failures included: a
    # PARSE_ERROR agent must stop showing "thinking" and must not keep last
    # round's signal (docs/DECISIONS.md#adr-streaming-state).
    await state_store.update_agent_state(
        persona["agent_id"], decision.signal, decision.confidence,
    )
    # The rationale feed carries reasoning only; a failure's text is an error
    # message, so PARSE_ERROR decisions skip it.
    if decision.signal is SignalType.PARSE_ERROR:
        return decision

    # ITEM 4 — streaming rationale push. Lazy imports keep batch_dispatcher
    # import-time minimal.
    from alphaswarm.state import RationaleEntry
    from alphaswarm.utils import sanitize_rationale

    try:
        await state_store.push_rationale(
            RationaleEntry(
                agent_id=persona["agent_id"],
                signal=decision.signal,
                rationale=sanitize_rationale(decision.rationale, max_len=50),
                round_num=round_num,
            )
        )
    except Exception as push_err:  # noqa: BLE001 - never fail dispatch on telemetry error
        log.warning(
            "rationale push failed (non-fatal)",
            agent_id=persona["agent_id"],
            error=str(push_err),
        )

    return decision


async def dispatch_wave(
    personas: list[WorkerPersonaConfig],
    governor: ConcurrencyController,
    provider: InferenceProvider,
    user_message: str,
    settings: GovernorSettings,
    *,
    peer_context: str | None = None,
    peer_contexts: list[str | None] | None = None,
    market_context: str | None = None,
    state_store: StateStore | None = None,
    round_num: int = 0,
    own_priors: Sequence[str | None] | None = None,
) -> list[AgentDecision]:
    """Dispatch a wave of agent inferences using asyncio.TaskGroup.

    Creates one task per persona inside a TaskGroup (INFRA-07: no bare
    create_task). Each task applies random jitter before acquiring a
    governor slot and running inference.

    After the wave completes, counts failures and reports to the governor
    if any occurred (the governor internally decides whether to shrink
    based on batch_failure_threshold_percent).

    Args:
        personas: List of agent persona configs to dispatch.
        governor: ResourceGovernor for concurrency slot management.
        provider: InferenceProvider for LLM calls (local or cloud).
        user_message: The seed rumor or prompt.
        settings: GovernorSettings with jitter and threshold config.
        peer_context: Optional peer decision context for Rounds 2-3.
        peer_contexts: Optional per-agent peer context list. When provided, must have
            same length as personas. Overrides peer_context scalar. Raises ValueError
            on length mismatch.
        market_context: Optional grounded market context block. Applied to every
            agent identically per Phase 40 D-07 (scalar, same block for all 100
            agents). Round 1 only -- _dispatch_round does not accept this param.
        state_store: Optional StateStore for TPS metric collection (Phase 10, TUI-04).
            Threaded through to AgentWorker.infer() via agent_worker context manager.
        own_priors: Optional per-agent own-prior lines (same length as personas).

    Returns:
        List of AgentDecision, one per persona. Failed agents have
        signal=PARSE_ERROR.

    Raises:
        ValueError: If peer_contexts or own_priors length does not match personas length.
        GovernorCrisisError: If any agent hits a governor crisis.
        BudgetExceededError: If the spend cap is exceeded; halts the wave so
            completed rounds remain persisted and no further spend occurs.
        AuthError: If the API key is invalid (401/403); deterministic config
            error that halts the wave immediately.
        Hard stops (HARD_STOP_ERRORS) are raised bare -- the first one, chained
        ``from`` the TaskGroup's ExceptionGroup -- never as an ExceptionGroup.
    """
    if peer_contexts is not None and len(peer_contexts) != len(personas):
        raise ValueError(
            f"peer_contexts length {len(peer_contexts)} != personas length {len(personas)}"
        )
    if own_priors is not None and len(own_priors) != len(personas):
        raise ValueError(f"own_priors length {len(own_priors)} != personas length {len(personas)}")

    tasks: list[asyncio.Task[AgentDecision]] = []

    try:
        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(
                    _safe_agent_inference(
                        p,
                        governor,
                        provider,
                        user_message,
                        peer_contexts[i] if peer_contexts is not None else peer_context,
                        market_context,
                        settings.jitter_min_seconds,
                        settings.jitter_max_seconds,
                        state_store=state_store,
                        round_num=round_num,
                        own_prior=own_priors[i] if own_priors is not None else None,
                    )
                )
                for i, p in enumerate(personas)
            ]
    except* HARD_STOP_ERRORS as eg:
        # Unwrap so callers and the UI see the real error instead of
        # "unhandled errors in a TaskGroup" (docs/DECISIONS.md#adr-taskgroup-dispatch).
        raise eg.exceptions[0] from eg

    results = [t.result() for t in tasks]

    failure_count = sum(1 for r in results if r.signal == SignalType.PARSE_ERROR)
    success_count = len(results) - failure_count

    if failure_count > 0:
        governor.report_wave_failures(success_count, failure_count)

    log.info(
        "wave complete",
        wave_size=len(personas),
        success_count=success_count,
        failure_count=failure_count,
    )

    return results
