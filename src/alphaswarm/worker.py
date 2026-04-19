"""Agent worker types and context manager for LLM inference dispatch.

Every LLM call that goes through a worker MUST be wrapped in agent_worker().
No raw OllamaClient.chat() calls outside this context manager.

Pattern (per CONTEXT.md locked decision):
    async with agent_worker(persona, governor, ollama_client) as worker:
        decision = await worker.infer(user_message="What is your reaction?")
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, TypedDict

import structlog

from alphaswarm.parsing import parse_agent_decision
from alphaswarm.types import AgentDecision

if TYPE_CHECKING:
    from alphaswarm.governor import ResourceGovernor
    from alphaswarm.ollama_client import OllamaClient
    from alphaswarm.state import StateStore

logger = structlog.get_logger(component="worker")


class WorkerPersonaConfig(TypedDict):
    """Lightweight runtime persona config for hot-path agent inference.

    Derived from the frozen Pydantic AgentPersona at dispatch time via
    config.persona_to_worker_config(). Uses TypedDict (not Pydantic BaseModel)
    for minimal overhead on the inference hot path per user locked decision.
    """

    agent_id: str
    bracket: str  # BracketType.value string
    influence_weight: float
    temperature: float
    system_prompt: str
    risk_profile: str


class AgentWorker:
    """Typed worker interface for agent inference.

    Created by agent_worker() context manager. Do NOT instantiate directly --
    the context manager ensures semaphore acquisition before any inference.

    Usage:
        async with agent_worker(persona, governor, client) as worker:
            decision = await worker.infer(user_message="...")
    """

    def __init__(
        self,
        persona: WorkerPersonaConfig,
        ollama_client: OllamaClient,
        model: str,
        state_store: StateStore | None = None,
    ) -> None:
        self._persona = persona
        self._client = ollama_client
        self._model = model
        self._state_store = state_store

    async def infer(
        self,
        user_message: str,
        peer_context: str | None = None,
        market_context: str | None = None,
    ) -> AgentDecision:
        """Run inference for this agent and return a parsed AgentDecision.

        Constructs the message list from persona system_prompt + user message,
        calls OllamaClient.chat() with format="json" and think=False,
        then pipes the response through parse_agent_decision().

        Args:
            user_message: The prompt content (seed rumor + optional context).
            peer_context: Optional peer decision context for Rounds 2-3.
            market_context: Optional grounded market data block (Round 1 only).
                Injected as a system message before peer_context per Phase 40 D-04.

        Returns:
            AgentDecision -- always returns, never raises (parse fallback).
        """
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self._persona["system_prompt"]},
        ]
        if market_context:
            messages.append({"role": "system", "content": f"Market context:\n{market_context}"})
        if peer_context:
            messages.append({"role": "system", "content": f"Peer context:\n{peer_context}"})
        messages.append({"role": "user", "content": user_message})

        response = await self._client.chat(
            model=self._model,
            messages=messages,
            format="json",
            think=False,  # Disable thinking for structured output reliability
            keep_alive="5m",
        )

        # Extract TPS data from response metadata (Phase 10: TUI-04, D-05)
        if self._state_store is not None:
            eval_count = response.eval_count
            eval_duration = response.eval_duration
            if eval_count is not None and eval_duration is not None and eval_duration > 0:
                self._state_store.update_tps(eval_count, eval_duration)

        raw_content = response.message.content or ""
        decision = parse_agent_decision(raw_content)

        logger.debug(
            "agent inference complete",
            agent_id=self._persona["agent_id"],
            bracket=self._persona["bracket"],
            signal=decision.signal.value,
            confidence=decision.confidence,
        )

        return decision


@asynccontextmanager
async def agent_worker(
    persona: WorkerPersonaConfig,
    governor: ResourceGovernor,
    ollama_client: OllamaClient,
    model: str | None = None,
    state_store: StateStore | None = None,
) -> AsyncGenerator[AgentWorker, None]:
    """Async context manager for agent inference with semaphore guarding.

    Acquires a governor concurrency slot before yielding the worker.
    Releases the slot on exit (even on exception). Per CONTEXT.md locked
    decision: implemented as asynccontextmanager, not class with __aenter__.

    Args:
        persona: Runtime persona config (WorkerPersonaConfig TypedDict).
        governor: ResourceGovernor for concurrency slot management.
        ollama_client: OllamaClient wrapper for Ollama calls.
        model: Ollama model tag. If None, defaults to "alphaswarm-worker".
               In production, use settings.ollama.worker_model_alias.
        state_store: Optional StateStore for TPS metric collection (Phase 10, TUI-04).

    Yields:
        AgentWorker -- call worker.infer() to run inference.
    """
    effective_model = model or "alphaswarm-worker"
    await governor.acquire()
    _success = True
    try:
        yield AgentWorker(persona, ollama_client, effective_model, state_store=state_store)
    except Exception:
        _success = False
        raise
    finally:
        governor.release(success=_success)
