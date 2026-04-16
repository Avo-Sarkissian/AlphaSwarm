"""Interview endpoint for post-simulation agent Q&A."""

from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from alphaswarm.interview import InterviewEngine
from alphaswarm.types import SimulationPhase

log = structlog.get_logger(component="web.interview")

router = APIRouter()


class InterviewRequest(BaseModel):
    """Request body for POST /interview/{agent_id}.

    message: user question to the interviewed agent. Must be non-empty and
    at most 4000 characters (addresses review HIGH: request validation).
    """

    message: str = Field(..., min_length=1, max_length=4000)


class InterviewResponse(BaseModel):
    response: str


@router.post("/interview/{agent_id}", response_model=InterviewResponse)
async def interview_agent(
    agent_id: str, body: InterviewRequest, request: Request,
) -> InterviewResponse:
    """Send a message to an agent and receive their in-character response (per D-08).

    Flow:
    1. Guard: services must be connected (503 otherwise).
    2. Guard: phase must be COMPLETE (409 otherwise — prevents contention with live simulation).
    3. On first call for an agent_id:
       a. Resolve cycle_id from the most recent completed cycle (404 if none).
          NOTE: Always uses the most recent completed cycle. If the user is in
          Replay Mode viewing an older cycle, the interview still targets the
          most recent cycle, not the replayed one. This is documented behavior
          per review consensus.
       b. Reconstruct InterviewContext from Neo4j (404 if context is None or empty).
       c. Create InterviewEngine with worker model; store (engine, asyncio.Lock()) in sessions.
    4. Subsequent calls reuse the existing engine (per D-06).
    5. Wrap engine.ask() in the per-agent lock to prevent concurrent history mutation.
    """
    app_state = request.app.state.app_state
    graph_manager = app_state.graph_manager
    ollama_client = app_state.ollama_client

    # 503: Guard on required services (mirrors replay.py pattern)
    if graph_manager is None or ollama_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "services_unavailable", "message": "Neo4j or Ollama is not connected"},
        )

    # 409: Phase guard — addresses Codex HIGH. Only allow interviews after simulation completes.
    snap = app_state.state_store.snapshot()
    if snap.phase != SimulationPhase.COMPLETE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "interview_unavailable",
                "message": "Interviews are only available after a simulation completes",
                "current_phase": snap.phase.value,
            },
        )

    # sessions stores {agent_id: {"engine": InterviewEngine, "lock": asyncio.Lock}}
    sessions: dict = request.app.state.interview_sessions

    if agent_id not in sessions:
        cycles = await graph_manager.read_completed_cycles(limit=1)
        if not cycles:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "no_completed_cycle", "message": "No completed simulation cycle found"},
            )
        cycle_id = cycles[0]["cycle_id"]

        context = await graph_manager.read_agent_interview_context(agent_id, cycle_id)

        # 404 if context is missing or has no agent data (addresses Gemini/Codex agent validation concern)
        if context is None or not getattr(context, "agent_name", None):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "agent_not_found", "message": f"No interview context for agent {agent_id}"},
            )

        engine = InterviewEngine(
            context=context,
            ollama_client=ollama_client,
            model=app_state.settings.ollama.worker_model_alias,
        )
        sessions[agent_id] = {"engine": engine, "lock": asyncio.Lock()}
        log.info("interview_session_created", agent_id=agent_id, cycle_id=cycle_id)

    entry = sessions[agent_id]
    engine = entry["engine"]
    lock: asyncio.Lock = entry["lock"]

    # Per-agent lock — addresses Codex HIGH: concurrent _history mutation
    async with lock:
        response_text = await engine.ask(body.message)

    log.info("interview_turn", agent_id=agent_id, message_len=len(body.message))
    return InterviewResponse(response=response_text)
