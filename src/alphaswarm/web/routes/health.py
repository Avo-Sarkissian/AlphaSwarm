"""Health check endpoint for AlphaSwarm web server."""

from __future__ import annotations

import asyncio

import psutil
import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel

from alphaswarm.config import load_inference_config
from alphaswarm.inference.factory import inference_mode

log = structlog.get_logger(component="web.health")

router = APIRouter()


class HealthResponse(BaseModel):
    """Response model for GET /health."""

    status: str
    simulation_phase: str
    memory_percent: float
    is_simulation_running: bool
    inference_mode: str
    spent_usd: float | None


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Return server health status with simulation phase and memory info."""
    app_state = request.app.state.app_state
    sim_manager = request.app.state.sim_manager

    snap = app_state.state_store.snapshot()

    log.debug("health_check", phase=snap.phase.value)

    # Resolve inference_mode from saved config; degrade to "local" on any error.
    mode: str = "local"
    try:
        cfg = await asyncio.to_thread(load_inference_config, app_state.settings)
        mode = inference_mode(cfg)
    except Exception:
        log.debug("health_check_inference_mode_fallback")

    # Resolve spent_usd from budget_meter if present; None when no run has started.
    spent: float | None = None
    try:
        meter = getattr(app_state, "budget_meter", None)
        if meter is not None:
            spent = float(meter.spent())
    except Exception:
        log.debug("health_check_spent_usd_fallback")

    return HealthResponse(
        status="ok",
        simulation_phase=snap.phase.value,
        memory_percent=psutil.virtual_memory().percent,
        is_simulation_running=sim_manager.is_running,
        inference_mode=mode,
        spent_usd=spent,
    )
