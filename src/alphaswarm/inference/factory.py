"""Provider + controller factory for AlphaSwarm inference.

Turns an ``InferenceConfig`` into role-bound ``InferenceProvider`` instances and
the right ``ConcurrencyController`` for swarm execution.

Public surface:
    inference_mode  — classify cfg as "local" | "cloud" | "mixed"
    BuiltProviders  — frozen dataclass holding the two providers + shared meter
    build_providers — construct providers from cfg, wrapping cloud ones in budget guard
    build_controller — select ResourceGovernor (local) or RateLimitController (cloud)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

from alphaswarm.config import InferenceConfig, ProviderLimits, ProviderType
from alphaswarm.inference.anthropic_provider import AnthropicProvider
from alphaswarm.inference.budget import DEFAULT_PRICING, BudgetMeter, BudgetTrackingProvider
from alphaswarm.inference.concurrency import ConcurrencyController
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


def _validate_cloud_role(
    provider: ProviderType, model: str, api_key: str | None, base_url: str | None
) -> None:
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
) -> InferenceProvider:
    """Construct a single provider and optionally wrap it in a BudgetTrackingProvider."""
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
        inner: InferenceProvider = AnthropicProvider(
            role, model, api_key=api_key, max_tokens_default=max_tokens_default,  # type: ignore[arg-type]
        )
    elif provider_type == ProviderType.OPENAI_COMPATIBLE:
        inner = OpenAICompatProvider(role, model, base_url=base_url, api_key=api_key)  # type: ignore[arg-type]
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

    orchestrator = _build_single_provider(
        ProviderRole.ORCHESTRATOR,
        cfg.orchestrator.provider,
        cfg.orchestrator.model,
        cfg.orchestrator.api_key,
        cfg.orchestrator.base_url,
        ollama_client=ollama_client,
        ollama_model_manager=ollama_model_manager,
        meter=meter,
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
