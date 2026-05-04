"""Health check endpoint for AlphaSwarm web server."""

from __future__ import annotations

import psutil
import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel

log = structlog.get_logger(component="web.health")

router = APIRouter()


class HealthResponse(BaseModel):
    """Response model for GET /health."""

    status: str
    simulation_phase: str
    memory_percent: float
    is_simulation_running: bool


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Return server health status with simulation phase and memory info."""
    app_state = request.app.state.app_state
    sim_manager = request.app.state.sim_manager

    snap = app_state.state_store.snapshot()

    log.debug("health_check", phase=snap.phase.value)

    return HealthResponse(
        status="ok",
        simulation_phase=snap.phase.value,
        memory_percent=psutil.virtual_memory().percent,
        is_simulation_running=sim_manager.is_running,
    )
