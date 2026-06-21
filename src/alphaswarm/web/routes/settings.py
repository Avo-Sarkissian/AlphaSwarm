"""Settings endpoints for AlphaSwarm inference configuration.

Exposes GET/PUT for the runtime InferenceConfig (provider selection, API keys,
model overrides), a POST connection-test, and a GET cost estimate.

Keys are NEVER returned raw; masked_config() replaces them with
{"set": bool, "last4": str|None}.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ValidationError

from alphaswarm.config import (
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

router = APIRouter()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Representative average token counts for a single agent inference call.
# These are deliberately rough; the real distribution varies by model+prompt.
_AVG_IN_TOKENS: int = 1500   # typical prompt (persona + rumor + context)
_AVG_OUT_TOKENS: int = 250   # typical structured-JSON completion

# Non-authoritative convenience list of well-known cloud model IDs for the
# settings UI dropdown. Users can type any id — these are illustrative only.
# Keys from DEFAULT_PRICING are always included; this adds a few extras.
_EXTRA_KNOWN_API_MODELS: list[str] = [
    "claude-opus-4-5",
    "claude-sonnet-4-5",
    "gpt-4o",
    "openrouter/meta-llama/llama-3.3-70b-instruct",
]

# Deduplicated ordered list: DEFAULT_PRICING keys first, then any extras
_KNOWN_API_MODELS: list[str] = list(
    dict.fromkeys(list(DEFAULT_PRICING.keys()) + _EXTRA_KNOWN_API_MODELS)
)

# ---------------------------------------------------------------------------
# Provider presets
# ---------------------------------------------------------------------------

# One-click provider configurations for the settings UI.
#
# IMPORTANT: model IDs listed here are EXAMPLES only — provider catalogs
# change frequently.  Users can type any model ID that the provider supports;
# these lists are illustrative starting points, not authoritative catalogs.
#
# Each entry:
#   label    — human-readable name shown in the UI dropdown
#   provider — must be a valid ProviderType value
#   base_url — API root URL (None for providers that don't need one, e.g. Anthropic)
#   models   — representative model IDs for that provider


class ProviderPreset(BaseModel):
    """A single provider preset for the settings UI."""

    label: str
    provider: str  # ProviderType value string
    base_url: str | None
    models: list[str]


PROVIDER_PRESETS: list[ProviderPreset] = [
    ProviderPreset(
        label="OpenRouter",
        provider=ProviderType.OPENAI_COMPATIBLE,
        base_url="https://openrouter.ai/api/v1",
        models=[
            "google/gemini-2.5-flash",
            "google/gemini-2.5-pro",
            "nvidia/llama-3.1-nemotron-70b-instruct",
            "anthropic/claude-3.5-sonnet",
            "meta-llama/llama-3.3-70b-instruct",
        ],
    ),
    ProviderPreset(
        label="Google Gemini",
        provider=ProviderType.OPENAI_COMPATIBLE,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        models=[
            "gemini-2.0-flash",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
        ],
    ),
    ProviderPreset(
        label="NVIDIA NIM",
        provider=ProviderType.OPENAI_COMPATIBLE,
        base_url="https://integrate.api.nvidia.com/v1",
        models=[
            "nvidia/llama-3.1-nemotron-70b-instruct",
        ],
    ),
    ProviderPreset(
        label="Groq",
        provider=ProviderType.OPENAI_COMPATIBLE,
        base_url="https://api.groq.com/openai/v1",
        models=[
            "llama-3.3-70b-versatile",
        ],
    ),
    ProviderPreset(
        label="Together AI",
        provider=ProviderType.OPENAI_COMPATIBLE,
        base_url="https://api.together.xyz/v1",
        models=[
            "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        ],
    ),
    ProviderPreset(
        label="OpenAI",
        provider=ProviderType.OPENAI_COMPATIBLE,
        base_url="https://api.openai.com/v1",
        models=[
            "gpt-4o",
            "gpt-4o-mini",
        ],
    ),
    ProviderPreset(
        label="Anthropic",
        provider=ProviderType.ANTHROPIC,
        base_url=None,
        models=[
            "claude-3-5-sonnet-latest",
            "claude-3-5-haiku-latest",
        ],
    ),
    ProviderPreset(
        label="Local (Ollama)",
        provider=ProviderType.OLLAMA,
        base_url="http://localhost:11434",
        models=[],
    ),
]


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class SettingsResponse(BaseModel):
    """Response body for GET /api/settings."""

    config: dict[str, Any]
    mode: Literal["local", "cloud", "mixed"]
    available_local_models: list[str]
    known_api_models: list[str]
    provider_presets: list[ProviderPreset]


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

    The returned RoleConfig is fully validated (provider coerced to ProviderType
    enum) so downstream model_dump() calls never trigger pydantic serialization
    warnings.
    """
    api_key_in = incoming.get("api_key")
    effective_key: str | None
    # Strip before the empty check so whitespace-only ("   ") is treated as absent
    stripped = api_key_in.strip() if isinstance(api_key_in, str) else api_key_in

    effective_provider = incoming.get("provider", stored_role.provider)
    effective_base_url = incoming.get("base_url", stored_role.base_url)

    # Only inherit the stored key when the destination vendor is UNCHANGED.
    # Applying a provider preset (sends provider+base_url, no api_key) or
    # otherwise switching vendor must NOT carry the prior vendor's secret onto
    # the new endpoint — that both misconfigures auth and transmits a key to an
    # unintended third party (F-13). Compare both provider and base_url so
    # switching between two openai_compatible endpoints also drops the old key.
    vendor_changed = (
        str(effective_provider) != str(stored_role.provider)
        or effective_base_url != stored_role.base_url
    )
    if stripped:
        effective_key = stripped
    elif vendor_changed:
        effective_key = None
    else:
        effective_key = stored_role.api_key

    raw = stored_role.model_dump()
    raw.update(
        {
            "provider": effective_provider,
            "model": incoming.get("model", stored_role.model),
            "base_url": effective_base_url,
            "api_key": effective_key,
        }
    )
    # model_validate coerces provider string → ProviderType enum via StrEnum
    return RoleConfig.model_validate(raw)


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
        provider_presets=PROVIDER_PRESETS,
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
            detail={
                "error": "simulation_running",
                "message": "Cannot update settings while a simulation is running.",
            },
        )

    try:
        stored: InferenceConfig = await asyncio.to_thread(load_inference_config, app_state.settings)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"stored inference config is invalid: {exc}",
        ) from exc

    # Merge role configs, preserving stored keys when incoming omits them.
    # ValidationError from _merge_role (invalid provider enum, etc.) is caught
    # here together with InferenceConfig validation so both yield 400.
    incoming_orch: dict[str, Any] = body.get("orchestrator", {})
    incoming_worker: dict[str, Any] = body.get("worker", {})

    try:
        merged_orch = _merge_role(stored.orchestrator, incoming_orch)
        merged_worker = _merge_role(stored.worker, incoming_worker)

        # Build the full merged config dict, letting pydantic validate it
        merged_dict: dict[str, Any] = {
            "orchestrator": merged_orch.model_dump(),
            "worker": merged_worker.model_dump(),
            "limits": body.get(
                "limits",
                {role.value: lim.model_dump() for role, lim in stored.limits.items()},
            ),
            "spend_cap_usd": body.get("spend_cap_usd", stored.spend_cap_usd),
            "pricing_overrides": body.get(
                "pricing_overrides",
                {k: v.model_dump() for k, v in stored.pricing_overrides.items()},
            ),
        }

        merged_cfg = InferenceConfig.model_validate(merged_dict)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "validation_error", "message": str(exc)},
        ) from exc

    try:
        await asyncio.to_thread(save_inference_config, merged_cfg)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed to persist settings: {exc}",
        ) from exc

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
        provider_role = (
            ProviderRole.ORCHESTRATOR if body.role == "orchestrator" else ProviderRole.WORKER
        )
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
