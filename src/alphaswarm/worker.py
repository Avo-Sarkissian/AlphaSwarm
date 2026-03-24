"""Agent worker types and context manager for LLM inference dispatch.

Phase 2 Plan 01: TypedDict definition only.
Phase 2 Plan 03: agent_worker context manager and AgentWorker class.
"""

from __future__ import annotations

from typing import TypedDict


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
