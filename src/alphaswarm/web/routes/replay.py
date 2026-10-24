"""Replay endpoints for AlphaSwarm web server."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Query, Request
from fastapi import Path as PathParam
from pydantic import BaseModel

from alphaswarm.web.errors import ApiError
from alphaswarm.web.guards import require_graph
from alphaswarm.web.params import CycleId

log = structlog.get_logger(component="web.replay")

router = APIRouter()


# --- Response models ---


class CycleItem(BaseModel):
    """One complete cycle in the replay/history listing.

    Metric fields are None for cycles recorded before run metrics existed.
    """

    cycle_id: str
    created_at: str  # ISO-8601 with offset; also the paging cursor
    seed_rumor: str
    round_count: int  # the cycle's num_rounds, 2 or 3 (docs/DECISIONS.md#adr-num-rounds)
    status: str
    final_buy: int | None = None
    final_sell: int | None = None
    final_hold: int | None = None
    total_flips: int | None = None
    total_seconds: float | None = None
    agent_count: int | None = None


class ReplayCyclesResponse(BaseModel):
    """Response for GET /replay/cycles: one page plus the cursor for the next."""

    cycles: list[CycleItem]
    next_before: str | None = None


class ReplayStartResponse(BaseModel):
    """Response for POST /replay/start/{cycle_id} (docs/DECISIONS.md#p34-d-08)."""

    status: str
    cycle_id: str
    round_num: int


class ReplayAdvanceResponse(BaseModel):
    """Response for POST /replay/advance (docs/DECISIONS.md#p34-d-09)."""

    status: str
    round_num: int


class ReplayStopResponse(BaseModel):
    """Response for POST /replay/stop (docs/DECISIONS.md#p34-d-10)."""

    status: str


# --- Endpoints ---


@router.get("/replay/cycles", response_model=ReplayCyclesResponse)
async def replay_cycles(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    before: Annotated[datetime | None, Query()] = None,
) -> ReplayCyclesResponse:
    """List complete cycles, newest first, one page at a time (docs/DECISIONS.md#p32-d-12).

    `limit` caps the page (1-100, default 20). `before` is the `created_at`
    of the previous page's last row (URL-encoded; a naive value is read as
    UTC). `next_before` is the cursor for the next page, or null when this
    page is not full. Status-based: running, failed and cancelled cycles are
    excluded (docs/DECISIONS.md#adr-cycle-metrics). 503 `graph_unavailable`
    without Neo4j; 422 `validation_error` for a bad limit or cursor.
    """
    graph = require_graph(request.app.state.app_state)
    rows = await graph.read_completed_cycles(limit, before=before)
    cycles = [CycleItem.model_validate(row) for row in rows]
    next_before = cycles[-1].created_at if len(cycles) == limit else None
    log.info("replay_cycles_listed", count=len(cycles), limit=limit, paged=before is not None)
    return ReplayCyclesResponse(cycles=cycles, next_before=next_before)


@router.post("/replay/start/{cycle_id}", response_model=ReplayStartResponse)
async def replay_start(cycle_id: CycleId, request: Request) -> ReplayStartResponse:
    """Start replay for *cycle_id* (docs/DECISIONS.md#p34-d-08).

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
    await replay_manager.start(cycle_id, signals, graph)
    log.info("replay_started", cycle_id=cycle_id)
    return ReplayStartResponse(status="ok", cycle_id=cycle_id, round_num=1)


@router.post("/replay/advance", response_model=ReplayAdvanceResponse)
async def replay_advance(request: Request) -> ReplayAdvanceResponse:
    """Advance to the next round (docs/DECISIONS.md#p34-d-09); a concurrent stop surfaces as 409 no_replay_active."""
    replay_manager = request.app.state.replay_manager
    if not replay_manager.is_active:
        raise ApiError(409, "no_replay_active", "No replay session is active")
    graph = require_graph(request.app.state.app_state)
    new_round = await replay_manager.advance(graph)
    log.info("replay_advanced", round_num=new_round)
    return ReplayAdvanceResponse(status="ok", round_num=new_round)


@router.post("/replay/round/{round_num}", response_model=ReplayAdvanceResponse)
async def replay_seek(
    round_num: Annotated[int, PathParam(ge=1, le=3)],
    request: Request,
) -> ReplayAdvanceResponse:
    """Show round *round_num* of the active replay, clamped to the cycle's depth.

    Used by the round scrubber, rewind and "Play cascade"
    (docs/DECISIONS.md#adr-replaystore-separate). 409 no_replay_active without a
    replay, 422 validation_error outside 1..3, 503 graph_unavailable without
    Neo4j. The 5 Hz broadcaster shows the round on its next tick.
    """
    replay_manager = request.app.state.replay_manager
    if not replay_manager.is_active:
        raise ApiError(409, "no_replay_active", "No replay session is active")
    graph = require_graph(request.app.state.app_state)
    shown_round = await replay_manager.seek(graph, round_num)
    log.info("replay_seek_served", round_num=shown_round)
    return ReplayAdvanceResponse(status="ok", round_num=shown_round)


@router.post("/replay/stop", response_model=ReplayStopResponse)
async def replay_stop(request: Request) -> ReplayStopResponse:
    """Stop the active replay (docs/DECISIONS.md#p34-d-10); 409 when none is active."""
    replay_manager = request.app.state.replay_manager
    if not replay_manager.is_active:
        raise ApiError(409, "no_replay_active", "No replay session is active")
    await replay_manager.stop()
    log.info("replay_stopped")
    return ReplayStopResponse(status="ok")
