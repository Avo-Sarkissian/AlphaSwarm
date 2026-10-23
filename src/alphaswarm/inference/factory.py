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
    build_controller — select ResourceGovernor (local) or RateLimitController (cloud)
"""

from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass
from typing import Any, Literal, cast
from urllib.parse import urlsplit

from alphaswarm.inference.anthropic_provider import AnthropicProvider
from alphaswarm.inference.budget import DEFAULT_PRICING, BudgetMeter, BudgetTrackingProvider
from alphaswarm.inference.concurrency import ConcurrencyController
from alphaswarm.inference.config import InferenceConfig, ProviderLimits, ProviderType
from alphaswarm.inference.ollama_provider import OllamaProvider
from alphaswarm.inference.openai_provider import OpenAICompatProvider
from alphaswarm.inference.provider import InferenceProvider
from alphaswarm.inference.rate_limit import RateLimitController
from alphaswarm.inference.types import ProviderRole

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
    ollama_client: Any,
    ollama_model_manager: Any,
    meter: BudgetMeter,
    max_retries: int = 3,
) -> InferenceProvider:
    """Construct a single provider and optionally wrap it in a BudgetTrackingProvider.

    ``max_retries`` is forwarded to the OpenAI-compatible adapter so callers can
    raise the 429/5xx retry budget for rate-limited free tiers (defaults to 3,
    preserving prior behavior; the Anthropic path is unaffected).
    """
    if provider_type == ProviderType.OLLAMA:
        return OllamaProvider(role, model, ollama_client, ollama_model_manager)

    # Cloud path — validate credentials first for a clear error message
    _validate_cloud_role(provider_type, model, api_key, base_url)

    if provider_type == ProviderType.ANTHROPIC:
        # The Anthropic Messages API hard-caps output at max_tokens. The 1024
        # constructor default silently truncated long orchestrator output —
        # breaking seed JSON synthesis, the ReAct report loop, and advisory
        # synthesis (F-05). Give the orchestrator a generous ceiling; the worker
        # emits a single small decision JSON, so a tighter bound is fine.
        max_tokens_default = 8192 if role == ProviderRole.ORCHESTRATOR else 2048
        # _validate_cloud_role above raised for an empty key/base_url, so `or ""` never
        # changes the value; it only narrows `str | None` to `str` for mypy.
        inner: InferenceProvider = AnthropicProvider(
            role, model, api_key=api_key or "", max_tokens_default=max_tokens_default
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


# ---------------------------------------------------------------------------
# build_providers
# ---------------------------------------------------------------------------


def build_providers(
    cfg: InferenceConfig,
    *,
    ollama_client: Any,
    ollama_model_manager: Any,
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
        Shared ``OllamaClient`` instance.  Passed through to ``OllamaProvider``
        unchanged; not called during construction.
    ollama_model_manager:
        Shared ``OllamaModelManager`` instance.  Passed through to
        ``OllamaProvider``; not called during construction.

    Returns
    -------
    BuiltProviders
        Frozen dataclass with ``orchestrator``, ``worker``, and ``budget_meter``.

    Raises
    ------
    ValueError
        If a cloud role is missing ``api_key`` or (for OPENAI_COMPATIBLE)
        ``base_url``.  Raised before any provider is constructed so the error
        is unambiguous.
    """
    # Build ONE shared pricing table and meter for the whole run
    merged_pricing = {**DEFAULT_PRICING, **cfg.pricing_overrides}
    meter = BudgetMeter(cfg.spend_cap_usd, merged_pricing)

    # Resolve per-role retry budget from the provider's limits (falls back to the
    # ProviderLimits default of 3 when no limits are configured for that backend).
    orch_retries = cfg.limits.get(cfg.orchestrator.provider, ProviderLimits()).max_retries
    worker_retries = cfg.limits.get(cfg.worker.provider, ProviderLimits()).max_retries

    orchestrator = _build_single_provider(
        ProviderRole.ORCHESTRATOR,
        cfg.orchestrator.provider,
        cfg.orchestrator.model,
        cfg.orchestrator.api_key,
        cfg.orchestrator.base_url,
        ollama_client=ollama_client,
        ollama_model_manager=ollama_model_manager,
        meter=meter,
        max_retries=orch_retries,
    )

    worker = _build_single_provider(
        ProviderRole.WORKER,
        cfg.worker.provider,
        cfg.worker.model,
        cfg.worker.api_key,
        cfg.worker.base_url,
        ollama_client=ollama_client,
        ollama_model_manager=ollama_model_manager,
        meter=meter,
        max_retries=worker_retries,
    )

    return BuiltProviders(orchestrator=orchestrator, worker=worker, budget_meter=meter)


# ---------------------------------------------------------------------------
# build_controller
# ---------------------------------------------------------------------------


def build_controller(
    cfg: InferenceConfig,
    governor_settings: Any,
    *,
    state_store: Any = None,
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
        # Lazy import avoids circular dependency:
        # inference.__init__ → factory → governor → inference.concurrency → inference.__init__
        from alphaswarm.governor import ResourceGovernor  # noqa: PLC0415

        return ResourceGovernor(governor_settings, state_store=state_store)

    # Cloud path: look up limits for the worker's provider, fall back to defaults
    limits: ProviderLimits = cfg.limits.get(cfg.worker.provider, ProviderLimits())

    return RateLimitController(
        max_in_flight=limits.max_in_flight,
        requests_per_min=limits.requests_per_min,
        tokens_per_min=limits.tokens_per_min,
        state_store=state_store,
    )
