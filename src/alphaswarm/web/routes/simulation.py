"""Simulation control endpoints for AlphaSwarm web server."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from alphaswarm.web.simulation_manager import SimulationAlreadyRunningError

log = structlog.get_logger(component="web.simulation")

router = APIRouter()


class SimulateStartRequest(BaseModel):
    """Request body for POST /simulate/start."""

    seed: str


class SimulateStartResponse(BaseModel):
    """Response body for successful POST /simulate/start."""

    status: str
    message: str


@router.post(
    "/simulate/start",
    response_model=SimulateStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def simulate_start(body: SimulateStartRequest, request: Request) -> SimulateStartResponse:
    """Start a simulation run.

    Returns 202 Accepted when the simulation is queued.
    Returns 409 Conflict when a simulation is already running.
    """
    sim_manager = request.app.state.sim_manager

    try:
        await sim_manager.start(body.seed)
    except SimulationAlreadyRunningError as exc:
        log.warning("simulate_start_rejected", reason="already_running")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "simulation_already_running", "message": str(exc)},
        ) from exc

    log.info("simulate_start_accepted", seed_length=len(body.seed))
    return SimulateStartResponse(
        status="accepted",
        message="Simulation started",
    )
