"""Replay endpoints for AlphaSwarm web server."""

from __future__ import annotations

from datetime import datetime

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from alphaswarm.web.replay_manager import ReplayAlreadyActiveError

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
async def replay_start(cycle_id: str, request: Request) -> ReplayStartResponse:
    """Start replay for a given cycle (D-08).

    Loads all signals from Neo4j via graph_manager, constructs ReplayStore,
    sets round 1, and broadcasts the round-1 snapshot over WebSocket.

    Returns 503 if Neo4j is not connected.
    Returns 409 if a live simulation is currently running (B4 route-side).
    Returns 409 if a replay session is already active.
    Returns 404 if the cycle has no signals in Neo4j.
    """
    app_state = request.app.state.app_state
    replay_manager = request.app.state.replay_manager
    connection_manager = request.app.state.connection_manager
    graph_manager = app_state.graph_manager
    sim_manager = request.app.state.sim_manager

    # B4 route-side: block replay while a live simulation is running. Runs
    # BEFORE graph/replay-active checks so the most-specific conflict wins.
    if sim_manager.is_running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "simulation_in_progress",
                "message": "Cannot start replay while a simulation is running",
            },
        )

    if graph_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "graph_unavailable", "message": "Neo4j is not connected"},
        )

    if replay_manager.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "replay_already_active", "message": "A replay session is already active"},
        )

    signals = await graph_manager.read_full_cycle_signals(cycle_id)
    if not signals:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "cycle_not_found", "message": f"No signals found for cycle {cycle_id}"},
        )

    try:
        await replay_manager.start(cycle_id, signals, connection_manager, graph_manager)
    except ReplayAlreadyActiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "replay_already_active", "message": str(exc)},
        ) from exc

    log.info("replay_started", cycle_id=cycle_id)
    return ReplayStartResponse(status="ok", cycle_id=cycle_id, round_num=1)


@router.post("/replay/advance", response_model=ReplayAdvanceResponse)
async def replay_advance(request: Request) -> ReplayAdvanceResponse:
    """Advance replay to the next round (D-09).

    Increments round_num on ReplayManager (max 3), loads bracket summaries
    and rationale entries for the new round, and broadcasts the snapshot.

    Returns 409 if no replay session is active.
    Returns 503 if Neo4j is not connected.
    """
    replay_manager = request.app.state.replay_manager
    connection_manager = request.app.state.connection_manager
    graph_manager = request.app.state.app_state.graph_manager

    if not replay_manager.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "no_replay_active", "message": "No replay session is active"},
        )

    if graph_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "graph_unavailable", "message": "Neo4j is not connected"},
        )

    new_round = await replay_manager.advance(connection_manager, graph_manager)
    log.info("replay_advanced", round_num=new_round)
    return ReplayAdvanceResponse(status="ok", round_num=new_round)


@router.post("/replay/stop", response_model=ReplayStopResponse)
async def replay_stop(request: Request) -> ReplayStopResponse:
    """Stop the active replay session (D-10).

    Resets ReplayManager to idle, clears store, resets phase to IDLE.
    Returns 409 if no replay session is active.
    """
    replay_manager = request.app.state.replay_manager
    if not replay_manager.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "no_replay_active", "message": "No replay session is active"},
        )
    await replay_manager.stop()
    log.info("replay_stopped")
    return ReplayStopResponse(status="ok")
