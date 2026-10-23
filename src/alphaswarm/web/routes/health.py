"""Health endpoints: GET /api/health (probes, cached 5 s) and GET /api/health/live.

`status` is "degraded" when any required component is not ok; the onboarding
screen uses `components` to show what is down and the command that fixes it.
The `inference_config` component reads the stored inference config on every
request (no cache, so a fixed file shows up on the next poll); an invalid file
is reported by key path and error type, never rewritten
(docs/DECISIONS.md#adr-local-first-inference).
When Neo4j comes back after a failed startup, the schema is applied once
(docs/DECISIONS.md#p4-d-05).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Final, Literal

import psutil
import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from alphaswarm import __version__
from alphaswarm.errors import InferenceConfigFileError
from alphaswarm.inference.config import InferenceConfig, ProviderType, load_inference_config
from alphaswarm.inference.factory import inference_mode
from alphaswarm.readiness import ComponentStatus, check_neo4j, check_ollama

if TYPE_CHECKING:
    from alphaswarm.settings import AppSettings

log = structlog.get_logger(component="web.health")

router = APIRouter()

COMPONENT_CACHE_TTL_S: Final = 5.0
# Indirection so tests can move the cache clock without patching time.monotonic globally.
_clock: Callable[[], float] = time.monotonic

INFERENCE_CONFIG_FIX: Final = (
    "Fix or move aside the file named by ALPHASWARM_INFERENCE_CONFIG_PATH "
    "(default .secrets/inference.json); Settings then opens and can save again"
)


class ComponentOut(BaseModel):
    ok: bool
    required: bool
    detail: str | None = None
    fix: str | None = None
    missing: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """Response model for GET /health."""

    status: Literal["ok", "degraded"]
    simulation_phase: str
    memory_percent: float
    is_simulation_running: bool
    inference_mode: Literal["local", "cloud", "mixed"]
    spent_usd: float | None
    version: str  # importlib.metadata.version("alphaswarm"); never a hard-coded string
    components: dict[str, ComponentOut]


class LiveResponse(BaseModel):
    status: Literal["ok"]


@router.get("/health/live", response_model=LiveResponse)
async def health_live() -> LiveResponse:
    """Liveness only: the process answers; no probes."""
    return LiveResponse(status="ok")


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Readiness: phase, memory, inference mode, spend and per-component status."""
    app_state = request.app.state.app_state
    snap = app_state.state_store.snapshot()
    cfg, config_status = await asyncio.to_thread(_read_inference_config, app_state.settings)
    mode: Literal["local", "cloud", "mixed"] = "local"
    try:
        if cfg is not None:
            mode = inference_mode(cfg)
    except Exception:
        log.debug("health_check_inference_mode_fallback")
    spent: float | None = None
    try:
        meter = getattr(app_state, "budget_meter", None)
        if meter is not None:
            spent = float(meter.spent())
    except Exception:
        log.debug("health_check_spent_usd_fallback")

    components = {**await _components(request, cfg), "inference_config": config_status}
    degraded = any(c.required and not c.ok for c in components.values())
    return HealthResponse(
        status="degraded" if degraded else "ok",
        simulation_phase=snap.phase.value,
        memory_percent=psutil.virtual_memory().percent,
        is_simulation_running=request.app.state.sim_manager.is_running,
        inference_mode=mode,
        spent_usd=spent,
        version=__version__,
        components={
            name: ComponentOut(
                ok=c.ok,
                required=c.required,
                detail=c.detail,
                fix=c.fix,
                missing=list(c.missing),
            )
            for name, c in components.items()
        },
    )


def _read_inference_config(settings: AppSettings) -> tuple[InferenceConfig | None, ComponentStatus]:
    """Blocking: load the stored inference config and describe it as a component.

    The file is only read. The detail names key paths and error types, never a
    value (the file holds API keys) or the file path.
    """
    path = settings.resolve_path(settings.inference_config_path)
    try:
        cfg = load_inference_config(settings, path)
    except InferenceConfigFileError as exc:
        return None, _inference_config_invalid(f"rejected: {exc.problems}")
    except Exception as exc:
        log.debug("health_check_inference_config_unreadable", error_type=type(exc).__name__)
        return None, _inference_config_invalid(f"unreadable ({type(exc).__name__})")
    detail = "stored file" if path.exists() else "no file: local defaults"
    return cfg, ComponentStatus("inference_config", ok=True, required=True, detail=detail)


def _inference_config_invalid(detail: str) -> ComponentStatus:
    return ComponentStatus(
        "inference_config",
        ok=False,
        required=True,
        detail=detail,
        fix=INFERENCE_CONFIG_FIX,
    )


def _local_models(cfg: InferenceConfig | None, request: Request) -> tuple[str, ...]:
    """Model names the Ollama-backed roles call (empty when both roles are cloud)."""
    if cfg is None:
        ollama = request.app.state.app_state.settings.ollama
        return (ollama.orchestrator_model_alias, ollama.worker_model_alias)
    roles = (cfg.orchestrator, cfg.worker)
    return tuple(dict.fromkeys(r.model for r in roles if r.provider == ProviderType.OLLAMA))


async def _components(request: Request, cfg: InferenceConfig | None) -> dict[str, ComponentStatus]:
    state = request.app.state
    cached: tuple[float, dict[str, ComponentStatus]] | None = getattr(state, "health_components", None)
    now = _clock()
    if cached is not None and now - cached[0] < COMPONENT_CACHE_TTL_S:
        return cached[1]
    app_state = state.app_state
    models = _local_models(cfg, request)
    async with asyncio.TaskGroup() as tg:
        neo4j_task = tg.create_task(check_neo4j(app_state.graph_manager))
        ollama_task = tg.create_task(
            check_ollama(app_state.ollama_client, models, required=bool(models)),
        )
    neo4j = await _apply_schema_after_recovery(request, neo4j_task.result())
    ollama, aliases = ollama_task.result()
    result = {"neo4j": neo4j, "ollama": ollama, "aliases": aliases}
    state.health_components = (now, result)
    return result


async def _apply_schema_after_recovery(request: Request, neo4j: ComponentStatus) -> ComponentStatus:
    state = request.app.state
    graph = state.app_state.graph_manager
    if not neo4j.ok or graph is None or getattr(state, "neo4j_ready", True):
        return neo4j
    try:
        await graph.ensure_schema()
    except Exception as exc:
        log.warning("neo4j_schema_apply_failed", exc_type=exc.__class__.__name__)
        return ComponentStatus(
            "neo4j",
            ok=False,
            required=True,
            detail="reachable, but applying the schema failed",
            fix="Check the server log for neo4j_schema_apply_failed",
        )
    state.neo4j_ready = True
    log.info("neo4j_schema_applied_after_recovery")
    return neo4j
