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

from alphaswarm.errors import GovernorCrisisError
from alphaswarm.types import AgentDecision, SignalType
from alphaswarm.worker import agent_worker

if TYPE_CHECKING:
    from alphaswarm.config import GovernorSettings
    from alphaswarm.governor import ResourceGovernor
    from alphaswarm.inference.provider import InferenceProvider
    from alphaswarm.state import StateStore
    from alphaswarm.worker import WorkerPersonaConfig

log = structlog.get_logger(component="batch_dispatcher")


async def _safe_agent_inference(
    persona: WorkerPersonaConfig,
    governor: ResourceGovernor,
    provider: InferenceProvider,
    user_message: str,
    peer_context: str | None,
    market_context: str | None,
    jitter_min: float,
    jitter_max: float,
    state_store: StateStore | None = None,
    round_num: int = 0,
) -> AgentDecision:
    """Run a single agent inference with jitter and exception safety.

    Applies random jitter BEFORE acquiring the governor slot (D-14).
    Catches only Exception subclasses (excluding GovernorCrisisError).
    CancelledError and KeyboardInterrupt are NEVER caught -- they propagate
    to preserve TaskGroup cleanup and Ctrl+C handling (review concern #2).

    Streams the resolved AgentDecision to state_store.update_agent_state
    IMMEDIATELY upon successful inference so the WS broadcaster sees a
    progressively-filling agent_states dict during the 14-18min round
    dispatch (replaces the post-dispatch batch loop in simulation.py).
    Skips the streaming write for PARSE_ERROR results so the broadcaster
    keeps the prior round's signal (or "thinking" placeholder) instead of
    flipping a failed agent into a misleading state.

    Also (ITEM 4 of quick task 260512-jqn): after a successful inference,
    streams one RationaleEntry into state_store so the WS rationale feed
    populates progressively (1 → 100 over the round) instead of bulk-
    arriving at end-of-round. PARSE_ERROR decisions skip the rationale
    push as well so the feed stays clean.

    Returns:
        AgentDecision on success, or PARSE_ERROR AgentDecision on failure.

    Raises:
        asyncio.CancelledError: Always re-raised for TaskGroup cleanup.
        KeyboardInterrupt: Always re-raised for Ctrl+C handling.
        GovernorCrisisError: Always re-raised (crisis must propagate).
    """
    try:
        await asyncio.sleep(random.uniform(jitter_min, jitter_max))
        async with agent_worker(persona, governor, provider, state_store=state_store) as worker:
            decision = await worker.infer(
                user_message=user_message,
                peer_context=peer_context,
                market_context=market_context,
            )
    except (asyncio.CancelledError, KeyboardInterrupt, GovernorCrisisError):
        raise  # NEVER catch these -- preserves TaskGroup cleanup and Ctrl+C
    except Exception as e:
        log.warning("agent inference failed", agent_id=persona["agent_id"], error=str(e))
        return AgentDecision(
            signal=SignalType.PARSE_ERROR,
            confidence=0.0,
            sentiment=0.0,
            rationale=f"Inference failed for {persona['agent_id']}: {e}",
        )

    # Streaming writes (success path only): agent_state + rationale together
    # so the WS broadcaster sees a progressively-filling agent_states dict
    # AND rationale feed instead of a 0->100 jump at end-of-round.
    if state_store is not None and decision.signal is not SignalType.PARSE_ERROR:
        await state_store.update_agent_state(
            persona["agent_id"], decision.signal, decision.confidence,
        )
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
    governor: ResourceGovernor,
    provider: InferenceProvider,
    user_message: str,
    settings: GovernorSettings,
    *,
    peer_context: str | None = None,
    peer_contexts: list[str | None] | None = None,
    market_context: str | None = None,
    state_store: StateStore | None = None,
    round_num: int = 0,
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

    Returns:
        List of AgentDecision, one per persona. Failed agents have
        signal=PARSE_ERROR.

    Raises:
        ValueError: If peer_contexts length does not match personas length.
        GovernorCrisisError: If any agent hits a governor crisis.
        ExceptionGroup: If CancelledError or other unrecoverable errors
            propagate from TaskGroup.
    """
    if peer_contexts is not None:
        if len(peer_contexts) != len(personas):
            raise ValueError(
                f"peer_contexts length {len(peer_contexts)} != personas length {len(personas)}"
            )

    tasks: list[asyncio.Task[AgentDecision]] = []

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
                )
            )
            for i, p in enumerate(personas)
        ]

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
