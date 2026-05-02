"""Health check endpoints for AlphaSwarm web server.

Exposes:
  - GET /health              — server-wide readiness probe (Phase 32 baseline)
  - GET /health/ollama       — orchestrator-model connection probe (NR-7)

The /health/ollama endpoint NEVER raises: it returns 200 with
``connected=False`` when the underlying Ollama client is missing or its ps()
call fails. This lets the frontend useOllamaHealth hook poll without needing
exception-handling at every tick.
"""

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


class OllamaHealthResponse(BaseModel):
    """Response model for GET /health/ollama (NR-7)."""

    connected: bool
    models_loaded: list[str]


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


@router.get("/health/ollama", response_model=OllamaHealthResponse)
async def health_ollama(request: Request) -> OllamaHealthResponse:
    """Return Ollama connection state + currently-loaded models (NR-7).

    Used by the frontend TaskBanner / useOllamaHealth hook to detect when the
    orchestrator model unloaded after macOS sleep, so the UI can surface a
    Retry CTA on the AdvisoryModal Error state.

    Method choice: ``raw_client.ps()`` (NOT ``.list()``) — we want the set of
    models CURRENTLY loaded into Ollama memory, not every model the daemon
    knows about. ps() is Ollama's "running models" probe.

    NEVER raises: returns 200 with ``connected=False`` on any failure so the
    frontend poll loop stays simple.
    """
    app_state = request.app.state.app_state
    ollama_client = getattr(app_state, "ollama_client", None)

    if ollama_client is None:
        return OllamaHealthResponse(connected=False, models_loaded=[])

    try:
        raw = ollama_client.raw_client
        ps_response = await raw.ps()
        # ollama AsyncClient.ps() returns a ProcessResponse with `.models` —
        # each entry exposes `.name` (alias) and `.model` (resolved tag).
        models_field = getattr(ps_response, "models", None)
        if models_field is None and isinstance(ps_response, dict):
            models_field = ps_response.get("models", [])
        names: list[str] = []
        for m in models_field or []:
            name = getattr(m, "name", None)
            if name is None and isinstance(m, dict):
                name = m.get("name")
            if name:
                names.append(str(name))
        return OllamaHealthResponse(connected=True, models_loaded=names)
    except Exception as exc:  # defensive — never propagate
        log.warning("health_ollama_query_failed", error=str(exc))
        return OllamaHealthResponse(connected=False, models_loaded=[])
