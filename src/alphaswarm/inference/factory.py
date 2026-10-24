"""Provider + controller factory for AlphaSwarm inference.

Turns an ``InferenceConfig`` into role-bound ``InferenceProvider`` instances and
the right ``ConcurrencyController`` for swarm execution.

Public surface:
    inference_mode  — classify cfg as "local" | "cloud" | "mixed"
    advisory_allowed — may the advisory send portfolio data to the orchestrator?
    advisory_block_reason — which check refuses the advisory (None when allowed)
    is_local_ollama — does an Ollama model + host keep data on this machine?
    is_cloud_ollama_model — is this an Ollama cloud model name?
    is_loopback_url — does this Ollama host name this machine?
    effective_ollama_host — the host ollama.AsyncClient resolves for a base_url
    BuiltProviders  — frozen dataclass holding the two providers + shared meter
    build_providers — construct providers from cfg, wrapping cloud ones in budget guard
    build_role_provider — construct one role's provider only (e.g. the interview worker)
    build_controller — select ResourceGovernor (local) or RateLimitController (cloud)
"""

from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast
from urllib.parse import urlsplit

from alphaswarm.governor import ResourceGovernor
from alphaswarm.inference.anthropic_provider import AnthropicProvider
from alphaswarm.inference.budget import DEFAULT_PRICING, BudgetMeter, BudgetTrackingProvider
from alphaswarm.inference.caps import (
    ANTHROPIC_ORCHESTRATOR_DEFAULT_MAX_TOKENS,
    ANTHROPIC_WORKER_DEFAULT_MAX_TOKENS,
)
from alphaswarm.inference.concurrency import ConcurrencyController
from alphaswarm.inference.config import InferenceConfig, ProviderLimits, ProviderType
from alphaswarm.inference.ollama_provider import OllamaProvider
from alphaswarm.inference.openai_provider import OpenAICompatProvider
from alphaswarm.inference.provider import InferenceProvider
from alphaswarm.inference.rate_limit import RateLimitController
from alphaswarm.inference.types import ProviderRole

if TYPE_CHECKING:
    from alphaswarm.ollama_client import OllamaClient
    from alphaswarm.ollama_models import OllamaModelManager
    from alphaswarm.settings import GovernorSettings
    from alphaswarm.state import StateStore

# ---------------------------------------------------------------------------
# inference_mode
# ---------------------------------------------------------------------------


def inference_mode(cfg: InferenceConfig) -> Literal["local", "cloud", "mixed"]:
    """Classify an InferenceConfig by provider combination.

    Returns
    -------
    "local"
        Both orchestrator and worker use OLLAMA.
    "cloud"
        Both orchestrator and worker use a non-OLLAMA provider.
    "mixed"
        One role is OLLAMA and the other is a cloud provider.
    """
    orch_local = cfg.orchestrator.provider == ProviderType.OLLAMA
    worker_local = cfg.worker.provider == ProviderType.OLLAMA

    if orch_local and worker_local:
        return "local"
    if not orch_local and not worker_local:
        return "cloud"
    return "mixed"


# ---------------------------------------------------------------------------
# Local vs. off-machine Ollama (docs/DECISIONS.md#adr-advisory-pipeline)
# ---------------------------------------------------------------------------

# Where ollama.AsyncClient connects when given no host and OLLAMA_HOST is unset.
_OLLAMA_DEFAULT_HOST = "http://127.0.0.1:11434"


def is_cloud_ollama_model(model: str) -> bool:
    """True for an Ollama cloud model, which Ollama runs on ollama.com.

    Ollama names its cloud models with a ``-cloud`` tag suffix
    (``gpt-oss:120b-cloud``) or a bare ``cloud`` tag (``glm-4.6:cloud``). To
    fail closed on other spellings, any dash- or colon-separated part of the
    name or tag that is exactly ``cloud`` counts: ``my-model-cloud``,
    ``my-model-cloud:latest`` and ``qwen3:cloud-preview`` do, ``cloudy-model``
    does not. An alias built from a Modelfile whose ``FROM`` is a cloud model
    cannot be detected from its name; the advisory job asks the server
    (``OllamaClient.is_remote_model``).
    """
    name = model.strip().lower().rsplit("/", 1)[-1].split("@", 1)[0]
    return "cloud" in re.split(r"[-:]", name)


def is_loopback_url(url: str) -> bool:
    """True when *url* names this machine: localhost, 127.0.0.0/8 or ::1.

    Parsed like ollama's ``_parse_host``: the scheme is optional and an empty
    host means 127.0.0.1. Anything unparseable, any other name or address
    (including the 0.0.0.0 bind address) is treated as remote.
    """
    text = url.strip()
    if "://" not in text:
        text = f"http://{text}"
    try:
        parts = urlsplit(text)
        _ = parts.port  # raises ValueError on a malformed port
    except ValueError:
        return False
    host = (parts.hostname or "").rstrip(".")
    if not host:
        return True
    if host == "localhost":
        return True
    try:
        addr = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped.is_loopback
    return addr.is_loopback


def effective_ollama_host(base_url: str | None) -> str:
    """The host ``ollama.AsyncClient(host=base_url)`` really connects to.

    The client uses ``host or OLLAMA_HOST`` and falls back to 127.0.0.1:11434.
    """
    return base_url or os.environ.get("OLLAMA_HOST") or _OLLAMA_DEFAULT_HOST


def is_local_ollama(model: str, base_url: str | None) -> bool:
    """True when *model* on the Ollama server at *base_url* keeps data on this machine."""
    return not is_cloud_ollama_model(model) and is_loopback_url(effective_ollama_host(base_url))


AdvisoryBlockReason = Literal["cloud_provider", "role_base_url_remote", "cloud_model", "remote_host"]


def advisory_block_reason(cfg: InferenceConfig, *, ollama_base_url: str | None) -> AdvisoryBlockReason | None:
    """Which check refuses the advisory, or None when it may run.

    Without the explicit ``allow_cloud_advisory`` opt-in, only a local Ollama
    orchestrator is allowed: provider Ollama, not an Ollama cloud model, and a
    loopback server (docs/DECISIONS.md#adr-advisory-pipeline).

    ``ollama_base_url`` is the host of the shared OllamaClient that
    OllamaProvider sends through (``OllamaClient.base_url``). The role's own
    ``base_url`` is checked as well, so a remote one fails closed even though
    the provider does not use it today. The reason is for logs, so the user can
    tell which setting to fix.
    """
    if cfg.allow_cloud_advisory:
        return None
    orchestrator = cfg.orchestrator
    if orchestrator.provider != ProviderType.OLLAMA:
        return "cloud_provider"
    if orchestrator.base_url and not is_loopback_url(orchestrator.base_url):
        return "role_base_url_remote"
    if is_cloud_ollama_model(orchestrator.model):
        return "cloud_model"
    if not is_loopback_url(effective_ollama_host(ollama_base_url)):
        return "remote_host"
    return None


def advisory_allowed(cfg: InferenceConfig, *, ollama_base_url: str | None) -> bool:
    """True when the advisory may send portfolio data to the orchestrator.

    See ``advisory_block_reason`` for the rule.
    """
    return advisory_block_reason(cfg, ollama_base_url=ollama_base_url) is None


# ---------------------------------------------------------------------------
# BuiltProviders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BuiltProviders:
    """Constructed provider pair + shared budget meter for a simulation run.

    Attributes
    ----------
    orchestrator:
        Provider for the orchestrator role (synthesis, advisory, report).
    worker:
        Provider for the worker role (individual agent inference).
    budget_meter:
        Shared ``BudgetMeter`` instance.  Cloud providers hold a reference to
        this same object; Ollama providers are not budget-wrapped (local = free).
    """

    orchestrator: InferenceProvider
    worker: InferenceProvider
    budget_meter: BudgetMeter


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_cloud_role(provider: ProviderType, model: str, api_key: str | None, base_url: str | None) -> None:
    """Raise ValueError with a clear message if cloud credentials are missing."""
    if not api_key:
        raise ValueError(
            f"InferenceConfig: role with provider={provider.value!r} model={model!r} "
            f"requires a non-empty api_key — set it in your inference config "
            f"(a missing key would produce a confusing 401 at runtime)."
        )
    if provider == ProviderType.OPENAI_COMPATIBLE and not base_url:
        raise ValueError(
            f"InferenceConfig: role with provider={provider.value!r} model={model!r} "
            f"requires a non-empty base_url (e.g. 'https://api.openai.com/v1')."
        )


def _build_single_provider(
    role: ProviderRole,
    provider_type: ProviderType,
    model: str,
    api_key: str | None,
    base_url: str | None,
    *,
    ollama_client: OllamaClient | None,
    ollama_model_manager: OllamaModelManager | None,
    meter: BudgetMeter,
    max_retries: int = 3,
) -> InferenceProvider:
    """Construct a single provider and optionally wrap it in a BudgetTrackingProvider.

    ``max_retries`` is forwarded to both cloud adapters so callers can raise the
    429/5xx retry budget for rate-limited free tiers (defaults to 3; the Anthropic
    path receives the same budget, docs/DECISIONS.md#adr-cloud-retry).
    """
    if provider_type == ProviderType.OLLAMA:
        if ollama_client is None:
            raise ValueError(
                f"InferenceConfig: role {role.value!r} with provider='ollama' model={model!r} "
                "requires a running Ollama client, but this process was started without one."
            )
        return OllamaProvider(
            role,
            model,
            ollama_client,
            ollama_model_manager,
            clean_state_on_prepare=role == ProviderRole.WORKER,
        )

    # Cloud path — validate credentials first for a clear error message
    _validate_cloud_role(provider_type, model, api_key, base_url)

    if provider_type == ProviderType.ANTHROPIC:
        # Anthropic requires max_tokens on every request. Call sites pass their own
        # cap; these defaults only cover a caller that passes none
        # (docs/DECISIONS.md#adr-output-caps; docs/DECISIONS.md#f-05 for the
        # orchestrator value).
        max_tokens_default = (
            ANTHROPIC_ORCHESTRATOR_DEFAULT_MAX_TOKENS
            if role == ProviderRole.ORCHESTRATOR
            else ANTHROPIC_WORKER_DEFAULT_MAX_TOKENS
        )
        # _validate_cloud_role above raised for an empty key/base_url, so `or ""` never
        # changes the value; it only narrows `str | None` to `str` for mypy.
        inner: InferenceProvider = AnthropicProvider(
            role, model, api_key=api_key or "", max_tokens_default=max_tokens_default, max_retries=max_retries
        )
    elif provider_type == ProviderType.OPENAI_COMPATIBLE:
        inner = OpenAICompatProvider(
            role, model, base_url=base_url or "", api_key=api_key or "", max_retries=max_retries
        )
    else:
        raise ValueError(f"Unsupported provider type: {provider_type!r}")

    # cast: BudgetTrackingProvider exposes role/model as read-only @property, but the
    # Protocol declares them as plain attributes (settable).  At runtime they satisfy
    # the protocol; cast tells mypy to trust us here.
    return cast(InferenceProvider, BudgetTrackingProvider(inner, meter))


def build_role_provider(
    cfg: InferenceConfig,
    role: ProviderRole,
    *,
    ollama_client: OllamaClient | None,
    ollama_model_manager: OllamaModelManager | None,
    meter: BudgetMeter | None = None,
) -> InferenceProvider:
    """Build the provider for one role only (interviews and connection tests need a single role).

    ``meter=None`` creates a fresh meter with the config's spend cap and merged
    pricing. The role's retry budget comes from its provider's limits (the
    ProviderLimits default of 3 when none are configured). Raises ValueError for
    a cloud role missing its key or base URL.
    """
    role_cfg = cfg.orchestrator if role == ProviderRole.ORCHESTRATOR else cfg.worker
    if meter is None:
        meter = BudgetMeter(cfg.spend_cap_usd, {**DEFAULT_PRICING, **cfg.pricing_overrides})
    return _build_single_provider(
        role,
        role_cfg.provider,
        role_cfg.model,
        role_cfg.api_key,
        role_cfg.base_url,
        ollama_client=ollama_client,
        ollama_model_manager=ollama_model_manager,
        meter=meter,
        max_retries=cfg.limits.get(role_cfg.provider, ProviderLimits()).max_retries,
    )


# ---------------------------------------------------------------------------
# build_providers
# ---------------------------------------------------------------------------


def build_providers(
    cfg: InferenceConfig,
    *,
    ollama_client: OllamaClient | None,
    ollama_model_manager: OllamaModelManager | None,
) -> BuiltProviders:
    """Construct role-bound providers from an InferenceConfig.

    One shared ``BudgetMeter`` is created for the run; cloud providers are
    wrapped in ``BudgetTrackingProvider`` referencing that meter.  Ollama
    providers are NOT wrapped (local inference is free).

    Parameters
    ----------
    cfg:
        Fully-validated ``InferenceConfig`` (pydantic model).
    ollama_client:
        Shared ``OllamaClient``, or ``None`` when this process runs without Ollama
        (allowed only when both roles are cloud). Not called during construction.
    ollama_model_manager:
        Shared ``OllamaModelManager``, or ``None``.

    Returns
    -------
    BuiltProviders
        Frozen dataclass with ``orchestrator``, ``worker``, and ``budget_meter``.

    Raises
    ------
    ValueError
        If a cloud role is missing ``api_key`` or (for OPENAI_COMPATIBLE)
        ``base_url``, or a local role has no ``ollama_client``.  Raised before any provider is constructed so the error
        is unambiguous.
    """
    # Build ONE shared pricing table and meter for the whole run
    merged_pricing = {**DEFAULT_PRICING, **cfg.pricing_overrides}
    meter = BudgetMeter(cfg.spend_cap_usd, merged_pricing)
    orchestrator = build_role_provider(
        cfg,
        ProviderRole.ORCHESTRATOR,
        ollama_client=ollama_client,
        ollama_model_manager=ollama_model_manager,
        meter=meter,
    )
    worker = build_role_provider(
        cfg,
        ProviderRole.WORKER,
        ollama_client=ollama_client,
        ollama_model_manager=ollama_model_manager,
        meter=meter,
    )
    return BuiltProviders(orchestrator=orchestrator, worker=worker, budget_meter=meter)


# ---------------------------------------------------------------------------
# build_controller
# ---------------------------------------------------------------------------


def build_controller(
    cfg: InferenceConfig,
    governor_settings: GovernorSettings,
    *,
    state_store: StateStore | None = None,
) -> ConcurrencyController:
    """Select and construct the right ConcurrencyController for the worker role.

    The WORKER role drives swarm concurrency: all 100 agents call the worker
    provider, so the worker's provider type determines which controller to use.

    Parameters
    ----------
    cfg:
        Inference configuration with provider details and optional limits.
    governor_settings:
        ``GovernorSettings`` pydantic model passed directly to
        ``ResourceGovernor`` for the local path.  Not used for the cloud path.
    state_store:
        Optional state store for metrics emission.  Passed through to both
        controller types.

    Returns
    -------
    ConcurrencyController
        ``ResourceGovernor`` for local (OLLAMA) workers;
        ``RateLimitController`` for cloud workers.
    """
    if cfg.worker.provider == ProviderType.OLLAMA:
        return ResourceGovernor(governor_settings, state_store=state_store)

    # Cloud path: look up limits for the worker's provider, fall back to defaults
    limits: ProviderLimits = cfg.limits.get(cfg.worker.provider, ProviderLimits())

    return RateLimitController(
        max_in_flight=limits.max_in_flight,
        requests_per_min=limits.requests_per_min,
        tokens_per_min=limits.tokens_per_min,
        state_store=state_store,
    )
