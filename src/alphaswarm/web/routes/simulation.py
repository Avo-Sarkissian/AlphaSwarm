"""Simulation control endpoints: start, stop, shock.

Manager conflicts (already running, replay active, post-run jobs, no run, shock
window closed, shock already queued) are mapped to 409 in web/errors.py; inputs
are validated by the types in web/params.py (docs/DECISIONS.md#adr-background-tasks).
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request, status
from pydantic import BaseModel

from alphaswarm.web.params import SeedText, ShockText

log = structlog.get_logger(component="web.simulation")

router = APIRouter()


class SimulateStartRequest(BaseModel):
    """Request body for POST /simulate/start (10-2000 characters after stripping)."""

    seed: SeedText


class SimulateStartResponse(BaseModel):
    """Response body for successful POST /simulate/start."""

    status: str
    message: str


class SimulateStopResponse(BaseModel):
    """Response body for successful POST /simulate/stop."""

    status: str


class SimulateShockRequest(BaseModel):
    """Request body for POST /simulate/shock (10-1000 characters after stripping)."""

    shock_text: ShockText


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
    """202 when queued; 409 when a run, a replay or post-run jobs are active; 422 bad seed."""
    await request.app.state.sim_manager.start(body.seed)
    log.info("simulate_start_accepted", seed_length=len(body.seed))
    return SimulateStartResponse(status="accepted", message="Simulation started")


@router.post("/simulate/stop", response_model=SimulateStopResponse)
async def simulate_stop(request: Request) -> SimulateStopResponse:
    """200 when the run is cancelled; 409 no_simulation_running otherwise."""
    request.app.state.sim_manager.stop()
    log.info("simulate_stop_accepted")
    return SimulateStopResponse(status="stopped")


@router.post("/simulate/shock", response_model=SimulateShockResponse)
async def simulate_shock(body: SimulateShockRequest, request: Request) -> SimulateShockResponse:
    """Queue a shock for the next simulation round.

    200 when queued; 409 when no run is active, the shock window is closed, or a
    shock is already queued; 422 bad length.
    """
    request.app.state.sim_manager.inject_shock(body.shock_text)
    log.info("simulate_shock_accepted", shock_length=len(body.shock_text))
    return SimulateShockResponse(status="queued", message="Shock queued for next round")
