"""Settings endpoints for AlphaSwarm inference configuration.

Exposes GET/PUT for the runtime InferenceConfig (provider selection, API keys,
model overrides), a POST connection-test, and a GET cost estimate.

Keys are NEVER returned raw; masked_config() replaces them with
{"set": bool, "last4": str|None}.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ValidationError

from alphaswarm.config import (
    INFERENCE_CONFIG_PATH,
    InferenceConfig,
    ProviderType,
    RoleConfig,
    load_inference_config,
    masked_config,
    save_inference_config,
)
from alphaswarm.errors import AuthError, InferenceError
from alphaswarm.inference.budget import DEFAULT_PRICING, BudgetMeter, RunEstimate, estimate_run
from alphaswarm.inference.factory import _build_single_provider, inference_mode
from alphaswarm.inference.types import ProviderRole

log = structlog.get_logger(component="web.settings")
logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Representative average token counts for a single agent inference call.
# These are deliberately rough; the real distribution varies by model+prompt.
_AVG_IN_TOKENS: int = 1500   # typical prompt (persona + rumor + context)
_AVG_OUT_TOKENS: int = 250   # typical structured-JSON completion

# Curated list of well-known cloud model IDs surfaced to the settings UI.
# Keys from DEFAULT_PRICING are always included; this constant adds a few
# additional aliases (e.g., "latest" variants) for discoverability.
_EXTRA_KNOWN_API_MODELS: list[str] = [
    # Anthropic additional aliases
    "claude-opus-4-5",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
    "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-20241022",
    # OpenAI
    "gpt-4o",
    "gpt-4o-mini",
    "o1",
    "o3-mini",
    # OpenRouter community models
    "meta-llama/llama-3.3-70b-instruct",
    "mistralai/mistral-large-2411",
    "google/gemini-2.0-flash-001",
]

# Deduplicated ordered list: DEFAULT_PRICING keys first, then any extras
_KNOWN_API_MODELS: list[str] = list(
    dict.fromkeys(list(DEFAULT_PRICING.keys()) + _EXTRA_KNOWN_API_MODELS)
)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class SettingsResponse(BaseModel):
    """Response body for GET /api/settings."""

    config: dict[str, Any]
    mode: Literal["local", "cloud", "mixed"]
    available_local_models: list[str]
    known_api_models: list[str]


class SettingsUpdateResponse(BaseModel):
    """Response body for PUT /api/settings."""

    config: dict[str, Any]
    mode: Literal["local", "cloud", "mixed"]


class TestConnectionRequest(BaseModel):
    """Request body for POST /api/settings/test."""

    role: Literal["orchestrator", "worker"]


class TestConnectionResponse(BaseModel):
    """Response body for POST /api/settings/test."""

    ok: bool
    error: str | None = None


class EstimateResponse(BaseModel):
    """Response body for GET /api/settings/estimate."""

    calls: int
    low_usd: str   # Decimal serialized as string for JSON safety
    high_usd: str
    mode: Literal["local", "cloud", "mixed"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _local_model_names(ollama_client: Any) -> list[str]:
    """Return available Ollama model names; returns [] on any failure."""
    try:
        raw_client = ollama_client.raw_client
        result = await raw_client.list()
        # result is an ollama.ListResponse; models is a list of ModelResponse
        models = getattr(result, "models", None) or []
        names: list[str] = []
        for m in models:
            name = getattr(m, "model", None) or getattr(m, "name", None)
            if name:
                names.append(str(name))
        return names
    except Exception:
        log.debug("ollama_list_failed", exc_info=True)
        return []


def _merge_role(
    stored_role: RoleConfig,
    incoming: dict[str, Any],
) -> RoleConfig:
    """Merge incoming role dict onto stored_role, preserving the stored API key
    if the incoming api_key field is missing, None, or empty string.
    """
    api_key_in = incoming.get("api_key")
    effective_key: str | None
    if api_key_in is None or api_key_in == "":
        effective_key = stored_role.api_key  # keep current stored value
    else:
        effective_key = api_key_in

    merged = stored_role.model_copy(
        update={
            "provider": incoming.get("provider", stored_role.provider),
            "model": incoming.get("model", stored_role.model),
            "base_url": incoming.get("base_url", stored_role.base_url),
            "api_key": effective_key,
        }
    )
    return merged


# ---------------------------------------------------------------------------
# GET /api/settings
# ---------------------------------------------------------------------------


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(request: Request) -> SettingsResponse:
    """Return current inference config (keys masked) + available model lists."""
    app_state = request.app.state.app_state

    cfg: InferenceConfig = await asyncio.to_thread(load_inference_config, app_state.settings)

    available: list[str] = []
    if app_state.ollama_client is not None:
        available = await _local_model_names(app_state.ollama_client)

    return SettingsResponse(
        config=masked_config(cfg),
        mode=inference_mode(cfg),
        available_local_models=available,
        known_api_models=_KNOWN_API_MODELS,
    )


# ---------------------------------------------------------------------------
# PUT /api/settings
# ---------------------------------------------------------------------------


@router.put("/settings", response_model=SettingsUpdateResponse)
async def put_settings(
    body: dict[str, Any],
    request: Request,
) -> SettingsUpdateResponse:
    """Update and persist the inference config.

    Returns 409 if a simulation is currently running.
    Returns 400 on validation errors.
    Preserves currently-stored API keys when the incoming payload omits them.
    """
    sim_manager = request.app.state.sim_manager
    app_state = request.app.state.app_state

    if sim_manager.is_running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "simulation_running", "message": "Cannot update settings while a simulation is running."},
        )

    stored: InferenceConfig = await asyncio.to_thread(load_inference_config, app_state.settings)

    # Merge role configs, preserving stored keys when incoming omits them
    incoming_orch: dict[str, Any] = body.get("orchestrator", {})
    incoming_worker: dict[str, Any] = body.get("worker", {})

    merged_orch = _merge_role(stored.orchestrator, incoming_orch)
    merged_worker = _merge_role(stored.worker, incoming_worker)

    # Build the full merged config dict, letting pydantic validate it
    merged_dict: dict[str, Any] = {
        "orchestrator": merged_orch.model_dump(),
        "worker": merged_worker.model_dump(),
        "limits": body.get("limits", {role.value: lim.model_dump() for role, lim in stored.limits.items()}),
        "spend_cap_usd": body.get("spend_cap_usd", stored.spend_cap_usd),
        "pricing_overrides": body.get("pricing_overrides", {k: v.model_dump() for k, v in stored.pricing_overrides.items()}),
    }

    try:
        merged_cfg = InferenceConfig.model_validate(merged_dict)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "validation_error", "message": str(exc)},
        ) from exc

    await asyncio.to_thread(save_inference_config, merged_cfg)

    log.info("settings_updated", mode=inference_mode(merged_cfg))

    return SettingsUpdateResponse(
        config=masked_config(merged_cfg),
        mode=inference_mode(merged_cfg),
    )


# ---------------------------------------------------------------------------
# POST /api/settings/test
# ---------------------------------------------------------------------------


@router.post("/settings/test", response_model=TestConnectionResponse)
async def test_connection(
    body: TestConnectionRequest,
    request: Request,
) -> TestConnectionResponse:
    """Test connectivity for the stored config of a single role.

    Builds a transient provider, issues a 1-token ping, then closes it.
    NEVER persists anything. Returns {ok: false, error: ...} on any failure;
    never raises a 500.
    """
    app_state = request.app.state.app_state

    try:
        cfg: InferenceConfig = await asyncio.to_thread(load_inference_config, app_state.settings)

        role_cfg: RoleConfig = cfg.orchestrator if body.role == "orchestrator" else cfg.worker

        # Build a single provider for the requested role
        provider_role = ProviderRole.ORCHESTRATOR if body.role == "orchestrator" else ProviderRole.WORKER
        meter = BudgetMeter(cap_usd=None, pricing=dict(DEFAULT_PRICING))

        provider = _build_single_provider(
            provider_role,
            role_cfg.provider,
            role_cfg.model,
            role_cfg.api_key,
            role_cfg.base_url,
            ollama_client=app_state.ollama_client,
            ollama_model_manager=app_state.model_manager,
            meter=meter,
        )

        try:
            await provider.chat(
                [{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
        finally:
            await provider.aclose()

        log.info("settings_test_ok", role=body.role, model=role_cfg.model)
        return TestConnectionResponse(ok=True)

    except (AuthError, InferenceError) as exc:
        log.info("settings_test_failed", role=body.role, error=str(exc))
        return TestConnectionResponse(ok=False, error=str(exc))
    except Exception as exc:  # broad catch — never 500 this endpoint
        log.warning("settings_test_error", role=body.role, exc=repr(exc))
        return TestConnectionResponse(ok=False, error=str(exc))


# ---------------------------------------------------------------------------
# GET /api/settings/estimate
# ---------------------------------------------------------------------------


@router.get("/settings/estimate", response_model=EstimateResponse)
async def get_estimate(request: Request) -> EstimateResponse:
    """Return a cost estimate for the current config and run parameters."""
    app_state = request.app.state.app_state

    cfg: InferenceConfig = await asyncio.to_thread(load_inference_config, app_state.settings)

    agents = len(app_state.personas)
    rounds = app_state.settings.num_rounds
    # narrative_calls = 1 worker call per agent (post-sim narrative generation, on by default)
    narrative_calls = agents

    result: RunEstimate = estimate_run(
        cfg,
        agents=agents,
        rounds=rounds,
        avg_in=_AVG_IN_TOKENS,
        avg_out=_AVG_OUT_TOKENS,
        narrative_calls=narrative_calls,
    )

    return EstimateResponse(
        calls=result.calls,
        low_usd=str(result.low_usd),
        high_usd=str(result.high_usd),
        mode=inference_mode(cfg),
    )
