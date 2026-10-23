"""Interview endpoint for post-simulation agent Q&A.

Interviews target any complete cycle: the body may name ``cycle_id``; otherwise
the latest complete cycle is used. Sessions are keyed by ``(cycle_id, agent_id)``
(docs/DECISIONS.md#p35-d-06). Interviews are refused while a simulation runs
because they share the worker model.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, TypedDict

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from alphaswarm.config import load_inference_config
from alphaswarm.errors import AgentNotFoundError
from alphaswarm.inference.factory import build_providers
from alphaswarm.interview import InterviewEngine, ensure_decision_narrative
from alphaswarm.web.errors import ApiError
from alphaswarm.web.guards import require_complete_cycle, require_graph
from alphaswarm.web.params import CYCLE_ID_PATTERN

if TYPE_CHECKING:
    from alphaswarm.inference.provider import InferenceProvider

log = structlog.get_logger(component="web.interview")

router = APIRouter()


class InterviewSession(TypedDict, total=False):
    """One conversation; the shape of the app.state.interview_sessions values."""

    engine: InterviewEngine | None
    lock: asyncio.Lock
    provider: InferenceProvider


class InterviewRequest(BaseModel):
    """Body for POST /interview/{agent_id}; ``cycle_id`` defaults to the latest complete cycle."""

    message: str = Field(..., min_length=1, max_length=4000)
    cycle_id: str | None = Field(None, pattern=CYCLE_ID_PATTERN)


class InterviewResponse(BaseModel):
    response: str


@router.post("/interview/{agent_id}", response_model=InterviewResponse)
async def interview_agent(
    agent_id: str,
    body: InterviewRequest,
    request: Request,
) -> InterviewResponse:
    """Answer one interview turn in character.

    409 simulation_running during a run; 404 no_completed_cycle when no cycle is
    complete; 404 cycle_not_found / 422 cycle_not_ready for an explicit cycle;
    404 agent_not_found when the cycle has no context for the agent. The
    per-session lock serializes engine creation and ask() for one conversation.
    """
    app_state = request.app.state.app_state
    sim_manager = request.app.state.sim_manager
    graph = require_graph(app_state)
    if sim_manager.is_running:
        raise ApiError(
            409,
            "simulation_running",
            "Interviews are unavailable while a simulation is running",
        )
    if body.cycle_id is not None:
        await require_complete_cycle(app_state, sim_manager, body.cycle_id)
        cycle_id = body.cycle_id
    else:
        latest = await graph.read_completed_cycles(limit=1)
        if not latest:
            raise ApiError(404, "no_completed_cycle", "No completed simulation cycle found")
        cycle_id = latest[0]["cycle_id"]

    sessions: dict[tuple[str, str], InterviewSession] = request.app.state.interview_sessions
    key = (cycle_id, agent_id)
    # Insert the entry (with its lock) before any await so two concurrent first
    # messages share one lock instead of both building engines.
    entry = sessions.get(key)
    if entry is None:
        entry = {"engine": None, "lock": asyncio.Lock()}
        sessions[key] = entry

    async with entry["lock"]:
        engine = entry.get("engine")
        if engine is None:
            try:
                try:
                    context = await graph.read_agent_interview_context(agent_id, cycle_id)
                except AgentNotFoundError as exc:
                    raise ApiError(
                        404,
                        "agent_not_found",
                        f"No interview context for agent {agent_id}",
                    ) from exc
                cfg = await asyncio.to_thread(load_inference_config, app_state.settings)
                built = build_providers(
                    cfg,
                    ollama_client=app_state.ollama_client,
                    ollama_model_manager=app_state.model_manager,
                )
                # First interview of (cycle, agent) generates and stores the
                # narrative once (docs/DECISIONS.md#p11-d-11).
                context = await ensure_decision_narrative(graph, built.worker, context, cycle_id=cycle_id)
                engine = InterviewEngine(context=context, provider=built.worker)
                entry["engine"] = engine
                # Kept so the sim-start cleanup can aclose() cloud clients.
                entry["provider"] = built.worker
                log.info("interview_session_created", agent_id=agent_id, cycle_id=cycle_id)
            except BaseException:
                if sessions.get(key) is entry:
                    sessions.pop(key, None)
                raise
        response_text = await engine.ask(body.message)

    log.info("interview_turn", agent_id=agent_id, cycle_id=cycle_id, message_len=len(body.message))
    return InterviewResponse(response=response_text)
