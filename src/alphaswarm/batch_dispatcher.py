"""Batch agent dispatch via asyncio.TaskGroup with jitter and failure tracking.

All batch agent processing MUST use dispatch_wave() -- no bare create_task
calls anywhere in the codebase (INFRA-07).

Pattern:
    results = await dispatch_wave(
        personas=worker_configs,
        governor=governor,
        client=ollama_client,
        model="alphaswarm-worker",
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
    from alphaswarm.ollama_client import OllamaClient
    from alphaswarm.state import StateStore
    from alphaswarm.worker import WorkerPersonaConfig

log = structlog.get_logger(component="batch_dispatcher")


async def _safe_agent_inference(
    persona: WorkerPersonaConfig,
    governor: ResourceGovernor,
    client: OllamaClient,
    model: str,
    user_message: str,
    peer_context: str | None,
    jitter_min: float,
    jitter_max: float,
    state_store: StateStore | None = None,
) -> AgentDecision:
    """Run a single agent inference with jitter and exception safety.

    Applies random jitter BEFORE acquiring the governor slot (D-14).
    Catches only Exception subclasses (excluding GovernorCrisisError).
    CancelledError and KeyboardInterrupt are NEVER caught -- they propagate
    to preserve TaskGroup cleanup and Ctrl+C handling (review concern #2).

    Returns:
        AgentDecision on success, or PARSE_ERROR AgentDecision on failure.

    Raises:
        asyncio.CancelledError: Always re-raised for TaskGroup cleanup.
        KeyboardInterrupt: Always re-raised for Ctrl+C handling.
        GovernorCrisisError: Always re-raised (crisis must propagate).
    """
    try:
        await asyncio.sleep(random.uniform(jitter_min, jitter_max))
        async with agent_worker(persona, governor, client, model, state_store=state_store) as worker:
            return await worker.infer(user_message=user_message, peer_context=peer_context)
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


async def dispatch_wave(
    personas: list[WorkerPersonaConfig],
    governor: ResourceGovernor,
    client: OllamaClient,
    model: str,
    user_message: str,
    settings: GovernorSettings,
    *,
    peer_context: str | None = None,
    peer_contexts: list[str | None] | None = None,
    state_store: StateStore | None = None,
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
        client: OllamaClient for inference calls.
        model: Ollama model tag.
        user_message: The seed rumor or prompt.
        settings: GovernorSettings with jitter and threshold config.
        peer_context: Optional peer decision context for Rounds 2-3.
        peer_contexts: Optional per-agent peer context list. When provided, must have
            same length as personas. Overrides peer_context scalar. Raises ValueError
            on length mismatch.
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
                    client,
                    model,
                    user_message,
                    peer_contexts[i] if peer_contexts is not None else peer_context,
                    settings.jitter_min_seconds,
                    settings.jitter_max_seconds,
                    state_store=state_store,
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
