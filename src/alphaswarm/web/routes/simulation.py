"""Simulation control endpoints for AlphaSwarm web server."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from alphaswarm.web.simulation_manager import (
    NoSimulationRunningError,
    ShockAlreadyQueuedError,
    SimulationAlreadyRunningError,
)

log = structlog.get_logger(component="web.simulation")

router = APIRouter()


class SimulateStartRequest(BaseModel):
    """Request body for POST /simulate/start."""

    seed: str


class SimulateStartResponse(BaseModel):
    """Response body for successful POST /simulate/start."""

    status: str
    message: str


class SimulateStopResponse(BaseModel):
    """Response body for successful POST /simulate/stop."""

    status: str


class SimulateShockRequest(BaseModel):
    """Request body for POST /simulate/shock."""

    shock_text: str


class SimulateShockResponse(BaseModel):
    """Response body for successful POST /simulate/shock."""

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


@router.post("/simulate/stop", response_model=SimulateStopResponse)
async def simulate_stop(request: Request) -> SimulateStopResponse:
    """Stop a running simulation.

    Returns 200 when the simulation is cancelled.
    Returns 409 Conflict when no simulation is running.
    """
    sim_manager = request.app.state.sim_manager
    try:
        sim_manager.stop()
    except NoSimulationRunningError as exc:
        log.warning("simulate_stop_rejected", reason="not_running")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "no_simulation_running", "message": str(exc)},
        ) from exc
    log.info("simulate_stop_accepted")
    return SimulateStopResponse(status="stopped")


@router.post(
    "/simulate/shock",
    response_model=SimulateShockResponse,
)
async def simulate_shock(body: SimulateShockRequest, request: Request) -> SimulateShockResponse:
    """Queue a shock for the next simulation round.

    Returns 200 when the shock is queued.
    Returns 409 Conflict when no simulation is running or shock already queued.
    """
    sim_manager = request.app.state.sim_manager
    try:
        sim_manager.inject_shock(body.shock_text)
    except NoSimulationRunningError as exc:
        log.warning("simulate_shock_rejected", reason="not_running")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "no_simulation_running", "message": str(exc)},
        ) from exc
    except ShockAlreadyQueuedError as exc:
        log.warning("simulate_shock_rejected", reason="already_queued")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "shock_already_queued", "message": str(exc)},
        ) from exc
    log.info("simulate_shock_accepted", shock_length=len(body.shock_text))
    return SimulateShockResponse(status="queued", message="Shock queued for next round")
