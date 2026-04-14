"""Replay endpoints for AlphaSwarm web server."""

from __future__ import annotations

from datetime import datetime

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

log = structlog.get_logger(component="web.replay")

router = APIRouter()


# --- Response models ---


class CycleItem(BaseModel):
    """Single completed cycle in the replay listing."""

    cycle_id: str
    created_at: str  # ISO-8601 string (datetime serialized)
    seed_rumor: str
    round_count: int  # Always 3 for completed cycles


class ReplayCyclesResponse(BaseModel):
    """Response for GET /replay/cycles."""

    cycles: list[CycleItem]


class ReplayStartResponse(BaseModel):
    """Response for POST /replay/start/{cycle_id} (D-13 stub)."""

    status: str
    cycle_id: str
    round_num: int


class ReplayAdvanceResponse(BaseModel):
    """Response for POST /replay/advance (D-14 stub)."""

    status: str
    round_num: int


# --- Endpoints ---


@router.get("/replay/cycles", response_model=ReplayCyclesResponse)
async def replay_cycles(request: Request) -> ReplayCyclesResponse:
    """List completed simulation cycles eligible for replay (D-12).

    Returns 503 if Neo4j is not connected (same pattern as edges endpoint).

    NOTE on "completed cycles" definition (addresses review concern #5):
    The underlying graph_manager.read_completed_cycles() query already
    filters to cycles that have at least one Round 3 decision via:
        WHERE EXISTS {
            MATCH (:Agent)-[:MADE]->(d:Decision {cycle_id: c.cycle_id, round: 3})
        }
    This means in-progress cycles (no Round 3 data yet) are excluded.
    round_count is hard-coded to 3 because by definition, all returned
    cycles have completed all 3 rounds.
    """
    app_state = request.app.state.app_state
    graph_manager = app_state.graph_manager
    if graph_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "graph_unavailable", "message": "Neo4j is not connected"},
        )

    raw_cycles = await graph_manager.read_completed_cycles()
    cycles = [
        CycleItem(
            cycle_id=c["cycle_id"],
            created_at=c["created_at"].isoformat() if isinstance(c["created_at"], datetime) else str(c["created_at"]),
            seed_rumor=c.get("seed_rumor", ""),
            round_count=3,  # All completed cycles have exactly 3 rounds
        )
        for c in raw_cycles
    ]
    log.info("replay_cycles_listed", count=len(cycles))
    return ReplayCyclesResponse(cycles=cycles)


@router.post("/replay/start/{cycle_id}", response_model=ReplayStartResponse)
async def replay_start(cycle_id: str) -> ReplayStartResponse:
    """Start replay for a given cycle (D-13 contract stub).

    Phase 34 fills in the real replay state machine.
    Returns correct response schema so Phase 34 only adds logic.
    """
    log.info("replay_start_stub", cycle_id=cycle_id)
    return ReplayStartResponse(status="ok", cycle_id=cycle_id, round_num=1)


@router.post("/replay/advance", response_model=ReplayAdvanceResponse)
async def replay_advance() -> ReplayAdvanceResponse:
    """Advance replay to the next round (D-14 contract stub).

    Phase 34 fills in the real state progression.
    Returns correct response schema so Phase 34 only adds logic.
    """
    log.info("replay_advance_stub")
    return ReplayAdvanceResponse(status="ok", round_num=1)
