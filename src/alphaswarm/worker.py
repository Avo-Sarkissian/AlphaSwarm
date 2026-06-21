"""Agent worker types and context manager for LLM inference dispatch.

Every LLM call that goes through a worker MUST be wrapped in agent_worker().
No raw OllamaClient.chat() calls outside this context manager.

Pattern (per CONTEXT.md locked decision):
    async with agent_worker(persona, governor, provider) as worker:
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
    from alphaswarm.inference.provider import InferenceProvider
    from alphaswarm.state import StateStore

logger = structlog.get_logger(component="worker")

# Ollama structured-outputs schema for agent decisions. Constraining the
# decode to this schema (vs bare format="json") nearly eliminates tier-2/3
# parse fallbacks and malformed-signal outputs from the 8B worker.
# parse_agent_decision stays as the validation/fallback layer.
DECISION_JSON_SCHEMA: dict = {  # type: ignore[type-arg]
    "type": "object",
    "properties": {
        "signal": {"type": "string", "enum": ["buy", "sell", "hold"]},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "sentiment": {"type": "number", "minimum": -1.0, "maximum": 1.0},
        "rationale": {"type": "string"},
        "cited_agents": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["signal", "confidence", "sentiment", "rationale", "cited_agents"],
}


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
        async with agent_worker(persona, governor, provider) as worker:
            decision = await worker.infer(user_message="...")
    """

    def __init__(
        self,
        persona: WorkerPersonaConfig,
        provider: InferenceProvider,
        state_store: StateStore | None = None,
    ) -> None:
        self._persona = persona
        self._provider = provider
        self._state_store = state_store

    async def infer(
        self,
        user_message: str,
        peer_context: str | None = None,
        market_context: str | None = None,
    ) -> AgentDecision:
        """Run inference for this agent and return a parsed AgentDecision.

        Constructs the message list from persona system_prompt + user message,
        calls InferenceProvider.chat() with response_schema=DECISION_JSON_SCHEMA
        and temperature from persona config, then pipes the response through
        parse_agent_decision().

        Args:
            user_message: The prompt content (seed rumor + optional context).
            peer_context: Optional peer decision context for Rounds 2-3.
            market_context: Optional grounded market data block (Round 1 only).
                Injected as a system message before peer_context per Phase 40 D-04.

        Returns:
            AgentDecision -- always returns, never raises (parse fallback).
        """
        from alphaswarm.inference.types import InferenceMessage

        messages: list[InferenceMessage] = [
            {"role": "system", "content": self._persona["system_prompt"]},
        ]
        if market_context:
            messages.append({"role": "system", "content": f"Market context:\n{market_context}"})
        if peer_context:
            messages.append({"role": "system", "content": f"Peer context:\n{peer_context}"})
        messages.append({"role": "user", "content": user_message})

        result = await self._provider.chat(
            messages,
            response_schema=DECISION_JSON_SCHEMA,  # structured outputs: schema-constrained decode
            temperature=self._persona["temperature"],
            # Per-bracket sampling temperature (Degens 1.1 ... Algos 0.15).
            # Without this, every agent ran at the Modelfile's temperature
            # and the bracket temperature design was dead config.
        )

        # Extract TPS data from result metadata (Phase 10: TUI-04, D-05)
        if self._state_store is not None:
            eval_count = result.eval_count
            eval_duration_ns = result.eval_duration_ns
            if eval_count is not None and eval_duration_ns is not None and eval_duration_ns > 0:
                self._state_store.update_tps(eval_count, eval_duration_ns)

        decision = parse_agent_decision(result.content)

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
    provider: InferenceProvider,
    state_store: StateStore | None = None,
) -> AsyncGenerator[AgentWorker, None]:
    """Async context manager for agent inference with semaphore guarding.

    Acquires a governor concurrency slot before yielding the worker.
    Releases the slot on exit (even on exception). Per CONTEXT.md locked
    decision: implemented as asynccontextmanager, not class with __aenter__.

    Args:
        persona: Runtime persona config (WorkerPersonaConfig TypedDict).
        governor: ResourceGovernor for concurrency slot management.
        provider: InferenceProvider for LLM calls (local or cloud).
        state_store: Optional StateStore for TPS metric collection (Phase 10, TUI-04).

    Yields:
        AgentWorker -- call worker.infer() to run inference.
    """
    await governor.acquire()
    _success = True
    try:
        yield AgentWorker(persona, provider, state_store=state_store)
    except Exception:
        _success = False
        raise
    finally:
        governor.release(success=_success)
