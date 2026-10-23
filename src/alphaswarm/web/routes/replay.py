"""Replay endpoints for AlphaSwarm web server."""

from __future__ import annotations

from datetime import datetime

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel

from alphaswarm.web.errors import ApiError
from alphaswarm.web.guards import require_graph
from alphaswarm.web.params import CycleId

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
    """Response for POST /replay/start/{cycle_id} (D-08)."""

    status: str
    cycle_id: str
    round_num: int


class ReplayAdvanceResponse(BaseModel):
    """Response for POST /replay/advance (D-09)."""

    status: str
    round_num: int


class ReplayStopResponse(BaseModel):
    """Response for POST /replay/stop (D-10)."""

    status: str


# --- Endpoints ---


@router.get("/replay/cycles", response_model=ReplayCyclesResponse)
async def replay_cycles(request: Request) -> ReplayCyclesResponse:
    """List completed cycles eligible for replay (D-12); 503 without Neo4j.

    Completed means the cycle stamped its metrics at simulation end, or (for
    cycles predating the stamp) has a round-3 decision; cycles still running
    are excluded (docs/DECISIONS.md#adr-cycle-metrics).
    """
    graph = require_graph(request.app.state.app_state)
    raw_cycles = await graph.read_completed_cycles()
    cycles = [
        CycleItem(
            cycle_id=c["cycle_id"],
            created_at=(c["created_at"].isoformat() if isinstance(c["created_at"], datetime) else str(c["created_at"])),
            seed_rumor=c.get("seed_rumor", ""),
            # Actual cascade depth (2 under ALPHASWARM_NUM_ROUNDS=2);
            # cycles predating metrics stamping default to 3.
            round_count=c.get("round_count", 3),
        )
        for c in raw_cycles
    ]
    log.info("replay_cycles_listed", count=len(cycles))
    return ReplayCyclesResponse(cycles=cycles)


@router.post("/replay/start/{cycle_id}", response_model=ReplayStartResponse)
async def replay_start(cycle_id: CycleId, request: Request) -> ReplayStartResponse:
    """Start replay for *cycle_id* (D-08).

    422 malformed id; 409 simulation_in_progress / replay_already_active; 404
    cycle_not_found when the cycle has no signals; 503 graph_unavailable. The
    TOCTOU errors raised inside ReplayManager.start map to the same 409 codes
    in web/errors.py.
    """
    replay_manager = request.app.state.replay_manager
    if request.app.state.sim_manager.is_running:
        raise ApiError(
            409,
            "simulation_in_progress",
            "Cannot start replay while a simulation is running",
        )
    graph = require_graph(request.app.state.app_state)
    if replay_manager.is_active:
        raise ApiError(409, "replay_already_active", "A replay session is already active")
    signals = await graph.read_full_cycle_signals(cycle_id)
    if not signals:
        raise ApiError(404, "cycle_not_found", f"No signals found for cycle {cycle_id}")
    await replay_manager.start(cycle_id, signals, request.app.state.connection_manager, graph)
    log.info("replay_started", cycle_id=cycle_id)
    return ReplayStartResponse(status="ok", cycle_id=cycle_id, round_num=1)


@router.post("/replay/advance", response_model=ReplayAdvanceResponse)
async def replay_advance(request: Request) -> ReplayAdvanceResponse:
    """Advance to the next round (D-09); a concurrent stop surfaces as 409 no_replay_active."""
    replay_manager = request.app.state.replay_manager
    if not replay_manager.is_active:
        raise ApiError(409, "no_replay_active", "No replay session is active")
    graph = require_graph(request.app.state.app_state)
    new_round = await replay_manager.advance(request.app.state.connection_manager, graph)
    log.info("replay_advanced", round_num=new_round)
    return ReplayAdvanceResponse(status="ok", round_num=new_round)


@router.post("/replay/stop", response_model=ReplayStopResponse)
async def replay_stop(request: Request) -> ReplayStopResponse:
    """Stop the active replay (D-10); 409 when none is active."""
    replay_manager = request.app.state.replay_manager
    if not replay_manager.is_active:
        raise ApiError(409, "no_replay_active", "No replay session is active")
    await replay_manager.stop()
    log.info("replay_stopped")
    return ReplayStopResponse(status="ok")
