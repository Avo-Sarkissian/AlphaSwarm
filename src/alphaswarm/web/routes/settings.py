"""Settings endpoints for AlphaSwarm inference configuration.

Exposes GET/PUT for the runtime InferenceConfig (provider selection, API keys,
model overrides), a POST connection-test, and a GET cost estimate.

Keys are NEVER returned raw; masked_config() replaces them with
{"set": bool, "last4": str|None}.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel, StrictBool, ValidationError, field_validator

from alphaswarm.errors import AuthError, InferenceError
from alphaswarm.inference.budget import DEFAULT_PRICING, BudgetMeter, RunEstimate, estimate_run
from alphaswarm.inference.config import (
    InferenceConfig,
    ModelPrice,
    ProviderLimits,
    ProviderType,
    RoleConfig,
    load_inference_config,
    masked_config,
    save_inference_config,
)
from alphaswarm.inference.factory import build_role_provider, inference_mode
from alphaswarm.inference.types import ProviderRole
from alphaswarm.web.errors import ApiError, validation_fields
from alphaswarm.web.guards import STORED_CONFIG_INVALID_MESSAGE, load_inference_config_or_422

log = structlog.get_logger(component="web.settings")

router = APIRouter()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Representative average token counts for a single agent inference call.
# These are deliberately rough; the real distribution varies by model+prompt.
_AVG_IN_TOKENS: int = 1500  # typical prompt (persona + rumor + context)
_AVG_OUT_TOKENS: int = 250  # typical structured-JSON completion

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
_KNOWN_API_MODELS: list[str] = list(dict.fromkeys(list(DEFAULT_PRICING.keys()) + _EXTRA_KNOWN_API_MODELS))

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


class RoleUpdate(BaseModel, extra="forbid"):
    """Role fields a PUT may change; omitted fields keep the stored value."""

    provider: ProviderType | None = None
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None


class SettingsUpdateRequest(BaseModel, extra="forbid"):
    """Typed PUT /api/settings body.

    Unknown keys (typos) are rejected at every level, inside a role, a limits
    entry or a price included, never ignored (the stored-config models
    ProviderLimits and ModelPrice are strict themselves).
    """

    orchestrator: RoleUpdate | None = None
    worker: RoleUpdate | None = None
    limits: dict[ProviderType, ProviderLimits] | None = None
    spend_cap_usd: Decimal | None = None
    pricing_overrides: dict[str, ModelPrice] | None = None
    # Cloud-advisory opt-in (docs/DECISIONS.md#adr-advisory-pipeline). Omitted or
    # null keeps the stored value; only a JSON boolean changes it ("yes" is a 422).
    allow_cloud_advisory: StrictBool | None = None

    @field_validator("orchestrator", "worker", mode="before")
    @classmethod
    def _reject_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("must be an object; omit the key to keep the stored value")
        return value


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
    low_usd: str  # Decimal serialized as string for JSON safety
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
    # unintended third party (F-13). A base_url change only counts when the
    # incoming payload supplies a NON-None base_url that differs — so a
    # same-provider edit that omits or nulls base_url (e.g. a model-only change)
    # does not falsely drop a still-valid key, while a real endpoint switch
    # (openai_compatible A → B) still does.
    incoming_base_url = incoming.get("base_url")
    base_url_changed = incoming_base_url is not None and incoming_base_url != stored_role.base_url
    vendor_changed = str(effective_provider) != str(stored_role.provider) or base_url_changed
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


def _settings_validation_error(exc: ValidationError, *loc: str) -> ApiError:
    """422 validation_error for a merged role or config, located from the request body.

    The merge validates RoleConfig/InferenceConfig, whose error locations start at
    that model ("model"); the *loc* prefix ("body", "worker") says which part of
    the request failed, as the body check's own errors do. Input values are never
    included.
    """
    errors = [{**err, "loc": (*loc, *err["loc"])} for err in exc.errors(include_input=False)]
    return ApiError(
        422,
        "validation_error",
        "Settings validation failed",
        extra={"fields": validation_fields(errors)},
    )


# ---------------------------------------------------------------------------
# GET /api/settings
# ---------------------------------------------------------------------------


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(request: Request) -> SettingsResponse:
    """Return current inference config (keys masked) + available model lists."""
    app_state = request.app.state.app_state

    cfg = await load_inference_config_or_422(app_state)

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
async def put_settings(body: SettingsUpdateRequest, request: Request) -> SettingsUpdateResponse:
    """Update and persist the inference config.

    409 simulation_running during a run; 422 validation_error for an invalid body
    or merged config (field locations from the body, such as ["body", "worker",
    "model"], never input values); 422
    inference_config_invalid when the stored file cannot be read; 500
    settings_save_failed when writing fails. Omitted keys keep their stored values;
    stored API keys are kept unless replaced (see _merge_role).
    """
    app_state = request.app.state.app_state
    if request.app.state.sim_manager.is_running:
        raise ApiError(
            409,
            "simulation_running",
            "Cannot update settings while a simulation is running.",
        )
    stored = await load_inference_config_or_422(app_state)
    merged: dict[str, Any] = stored.model_dump()
    roles = (
        ("orchestrator", stored.orchestrator, body.orchestrator),
        ("worker", stored.worker, body.worker),
    )
    for name, stored_role, update in roles:
        if update is None:
            continue
        try:
            merged[name] = _merge_role(
                stored_role,
                update.model_dump(exclude_unset=True, mode="json"),
            ).model_dump()
        except ValidationError as exc:
            raise _settings_validation_error(exc, "body", name) from exc
    if body.limits is not None:
        merged["limits"] = {role: lim.model_dump() for role, lim in body.limits.items()}
    if "spend_cap_usd" in body.model_fields_set:
        merged["spend_cap_usd"] = body.spend_cap_usd
    if body.pricing_overrides is not None:
        merged["pricing_overrides"] = {model: price.model_dump() for model, price in body.pricing_overrides.items()}
    if body.allow_cloud_advisory is not None:
        merged["allow_cloud_advisory"] = body.allow_cloud_advisory
    try:
        merged_cfg = InferenceConfig.model_validate(merged)
    except ValidationError as exc:
        raise _settings_validation_error(exc, "body") from exc
    try:
        await asyncio.to_thread(save_inference_config, merged_cfg, settings=app_state.settings)
    except OSError as exc:
        log.error("settings_save_failed", exc_type=exc.__class__.__name__)
        raise ApiError(500, "settings_save_failed", "Failed to persist settings") from exc
    log.info(
        "settings_updated",
        mode=inference_mode(merged_cfg),
        allow_cloud_advisory=merged_cfg.allow_cloud_advisory,
    )
    return SettingsUpdateResponse(config=masked_config(merged_cfg), mode=inference_mode(merged_cfg))


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
    never raises a 500. Returns 409 simulation_running while a run is in
    progress (a test could load a second large model mid-run). A stored file
    that cannot be loaded gets the fixed Settings message: the load error's
    text names the file path (docs/DECISIONS.md#adr-local-first-inference).
    """
    if request.app.state.sim_manager.is_running:
        raise ApiError(
            409,
            "simulation_running",
            "Cannot test a connection while a simulation is running",
        )
    app_state = request.app.state.app_state

    try:
        cfg: InferenceConfig = await asyncio.to_thread(load_inference_config, app_state.settings)
    except (ValueError, OSError) as exc:
        log.info("settings_test_failed", role=body.role, error_type=type(exc).__name__)
        return TestConnectionResponse(ok=False, error=STORED_CONFIG_INVALID_MESSAGE)

    try:
        role_cfg: RoleConfig = cfg.orchestrator if body.role == "orchestrator" else cfg.worker

        # Build a single provider for the requested role
        provider_role = ProviderRole.ORCHESTRATOR if body.role == "orchestrator" else ProviderRole.WORKER
        meter = BudgetMeter(cap_usd=None, pricing=dict(DEFAULT_PRICING))

        provider = build_role_provider(
            cfg,
            provider_role,
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

    cfg = await load_inference_config_or_422(app_state)

    agents = len(app_state.personas)
    rounds = app_state.settings.num_rounds

    # No narrative calls: a run makes none; an agent's narrative is generated on
    # its first interview (docs/DECISIONS.md#p11-d-11).
    result: RunEstimate = estimate_run(
        cfg,
        agents=agents,
        rounds=rounds,
        avg_in=_AVG_IN_TOKENS,
        avg_out=_AVG_OUT_TOKENS,
    )

    return EstimateResponse(
        calls=result.calls,
        low_usd=str(result.low_usd),
        high_usd=str(result.high_usd),
        mode=inference_mode(cfg),
    )
