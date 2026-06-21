"""Budget tracking, pricing table, and run estimator for cloud inference.

All monetary values are Python ``Decimal`` to avoid floating-point drift.
Prices in DEFAULT_PRICING are approximate public USD-per-1M-token values as of
mid-2025; they are best-effort and user-overridable via InferenceConfig.pricing_overrides.

Also provides ``BudgetTrackingProvider``: a thin InferenceProvider wrapper that
records every call's token cost in a shared BudgetMeter and enforces the USD cap
BEFORE dispatching.  Because it wraps the inner provider, ALL cloud calls
(worker waves, seed, advisory, report) are counted and capped uniformly —
even those that bypass the RateLimitController.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from alphaswarm.config import InferenceConfig, ModelPrice, ProviderType
from alphaswarm.errors import BudgetExceededError
from alphaswarm.inference.types import InferenceMessage, InferenceResult, ProviderRole

if TYPE_CHECKING:
    from alphaswarm.inference.provider import InferenceProvider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default pricing table
# ---------------------------------------------------------------------------

# Values are approximate USD per 1M tokens (input / output).
# Sources: public provider pricing pages, accurate as of mid-2025.
# User can override any entry via InferenceConfig.pricing_overrides.
DEFAULT_PRICING: dict[str, ModelPrice] = {
    # Anthropic
    "claude-opus-4-5": ModelPrice(
        input_per_mtok=Decimal("15.00"),
        output_per_mtok=Decimal("75.00"),
    ),
    "claude-sonnet-4-5": ModelPrice(
        input_per_mtok=Decimal("3.00"),
        output_per_mtok=Decimal("15.00"),
    ),
    "claude-haiku-4-5": ModelPrice(
        input_per_mtok=Decimal("0.80"),
        output_per_mtok=Decimal("4.00"),
    ),
    "claude-3-5-sonnet-20241022": ModelPrice(
        input_per_mtok=Decimal("3.00"),
        output_per_mtok=Decimal("15.00"),
    ),
    "claude-3-5-haiku-20241022": ModelPrice(
        input_per_mtok=Decimal("0.80"),
        output_per_mtok=Decimal("4.00"),
    ),
    # OpenAI
    "gpt-4o": ModelPrice(
        input_per_mtok=Decimal("2.50"),
        output_per_mtok=Decimal("10.00"),
    ),
    "gpt-4o-mini": ModelPrice(
        input_per_mtok=Decimal("0.15"),
        output_per_mtok=Decimal("0.60"),
    ),
    "o1": ModelPrice(
        input_per_mtok=Decimal("15.00"),
        output_per_mtok=Decimal("60.00"),
    ),
    "o3-mini": ModelPrice(
        input_per_mtok=Decimal("1.10"),
        output_per_mtok=Decimal("4.40"),
    ),
    # OpenRouter-style aliases (common community models)
    "meta-llama/llama-3.3-70b-instruct": ModelPrice(
        input_per_mtok=Decimal("0.12"),
        output_per_mtok=Decimal("0.30"),
    ),
    "mistralai/mistral-large-2411": ModelPrice(
        input_per_mtok=Decimal("2.00"),
        output_per_mtok=Decimal("6.00"),
    ),
    "google/gemini-2.0-flash-001": ModelPrice(
        input_per_mtok=Decimal("0.10"),
        output_per_mtok=Decimal("0.40"),
    ),
}

_CENTS = Decimal("0.01")
_MTOK = Decimal("1000000")

# ---------------------------------------------------------------------------
# RunEstimate
# ---------------------------------------------------------------------------


@dataclass
class RunEstimate:
    """Estimated cost for a full simulation run.

    Attributes
    ----------
    calls:
        Total LLM calls (agents * rounds + 3 orchestrator calls).
    low_usd:
        Lower bound of cost estimate (~0.7× point estimate), quantized to cents.
    high_usd:
        Upper bound of cost estimate (~1.3× point estimate), quantized to cents.
    """

    calls: int
    low_usd: Decimal
    high_usd: Decimal


# ---------------------------------------------------------------------------
# BudgetMeter
# ---------------------------------------------------------------------------


class BudgetMeter:
    """Tracks cumulative inference spend and enforces a hard USD cap.

    Parameters
    ----------
    cap_usd:
        Hard spend ceiling in USD.  ``None`` disables cap enforcement.
    pricing:
        Mapping of model id → ModelPrice.  Typically DEFAULT_PRICING merged
        with InferenceConfig.pricing_overrides.
    """

    def __init__(
        self,
        cap_usd: Decimal | None,
        pricing: dict[str, ModelPrice],
    ) -> None:
        self._cap = cap_usd
        self._pricing = pricing
        self._total: Decimal = Decimal(0)
        self._warned_unknown: set[str] = set()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cost_of(self, model: str, in_tokens: int, out_tokens: int) -> Decimal:
        price = self._pricing.get(model)
        if price is None:
            if model not in self._warned_unknown:
                logger.warning(
                    "BudgetMeter: unknown model %r — treating as free (price = $0). "
                    "Add an entry to DEFAULT_PRICING or InferenceConfig.pricing_overrides.",
                    model,
                )
                self._warned_unknown.add(model)
            return Decimal(0)
        return (
            Decimal(in_tokens) / _MTOK * price.input_per_mtok
            + Decimal(out_tokens) / _MTOK * price.output_per_mtok
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(
        self,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> Decimal:
        """Add cost for one inference call; return the new running total."""
        in_tok = input_tokens if input_tokens is not None else 0
        out_tok = output_tokens if output_tokens is not None else 0
        cost = self._cost_of(model, in_tok, out_tok)
        self._total += cost
        return self._total

    def spent(self) -> Decimal:
        """Return cumulative spend so far."""
        return self._total

    def would_exceed(self, model: str, est_in: int, est_out: int) -> bool:
        """Return True if adding this call's projected cost would exceed the cap."""
        if self._cap is None:
            return False
        projected = self._total + self._cost_of(model, est_in, est_out)
        return projected > self._cap

    def check(self) -> None:
        """Raise BudgetExceededError if cap is set and spent() >= cap."""
        if self._cap is not None and self._total >= self._cap:
            raise BudgetExceededError(self._total, self._cap)


# ---------------------------------------------------------------------------
# estimate_run
# ---------------------------------------------------------------------------


def estimate_run(
    cfg: InferenceConfig,
    *,
    agents: int,
    rounds: int,
    avg_in: int,
    avg_out: int,
    narrative_calls: int = 0,
    pricing: dict[str, ModelPrice] | None = None,
) -> RunEstimate:
    """Estimate cost of a full AlphaSwarm simulation run.

    Call breakdown
    --------------
    - ``agents * rounds`` worker inference calls.
    - ``narrative_calls`` additional worker calls for post-sim narrative generation
      (typically ``agents`` when narratives are enabled, which is the default).
    - 3 orchestrator calls (seed synthesis, advisory, report).

    Pricing resolution
    ------------------
    Uses *pricing* if provided, else DEFAULT_PRICING merged with
    ``cfg.pricing_overrides`` (overrides win).  Local (OLLAMA) models always
    cost Decimal(0).

    Returns
    -------
    RunEstimate with calls count and a ±30% USD band, quantized to cents.
    """
    # Merge pricing table: DEFAULT → cfg.pricing_overrides → caller-supplied
    resolved: dict[str, ModelPrice] = dict(DEFAULT_PRICING)
    resolved.update(cfg.pricing_overrides)
    if pricing is not None:
        resolved.update(pricing)

    worker_calls = agents * rounds
    orch_calls = 3
    total_calls = worker_calls + narrative_calls + orch_calls

    worker_provider = cfg.worker.provider
    orch_provider = cfg.orchestrator.provider

    def _call_cost(model: str, provider: ProviderType, n: int) -> Decimal:
        if provider == ProviderType.OLLAMA:
            return Decimal(0)
        mp = resolved.get(model)
        if mp is None:
            logger.warning(
                "estimate_run: no pricing for model %r — treating as $0.",
                model,
            )
            return Decimal(0)
        per_call = (
            Decimal(avg_in) / _MTOK * mp.input_per_mtok
            + Decimal(avg_out) / _MTOK * mp.output_per_mtok
        )
        return per_call * n

    point = (
        _call_cost(cfg.worker.model, worker_provider, worker_calls)
        + _call_cost(cfg.worker.model, worker_provider, narrative_calls)
        + _call_cost(cfg.orchestrator.model, orch_provider, orch_calls)
    )

    low = (point * Decimal("0.7")).quantize(_CENTS)
    high = (point * Decimal("1.3")).quantize(_CENTS)

    return RunEstimate(calls=total_calls, low_usd=low, high_usd=high)


# ---------------------------------------------------------------------------
# BudgetTrackingProvider
# ---------------------------------------------------------------------------


class BudgetTrackingProvider:
    """Provider wrapper that enforces a USD budget cap on every inference call.

    Wraps any ``InferenceProvider`` and a shared ``BudgetMeter``.  On every
    ``chat`` call it:

    1. Calls ``meter.check()`` before dispatching — raises ``BudgetExceededError``
       immediately if the cap is already met or exceeded.
    2. Awaits the inner provider's ``chat``.
    3. Records the actual token cost with ``meter.record``.

    Because this wraps the provider (not the concurrency controller), ALL calls —
    worker waves, seed synthesis, advisory, report — are counted and capped,
    regardless of whether they went through ``RateLimitController``.

    Parameters
    ----------
    inner:
        The actual inference backend to delegate to.
    meter:
        Shared ``BudgetMeter`` instance (typically one per simulation run).

    Notes
    -----
    ``role``, ``model``, and ``is_local()`` are forwarded to the inner provider.
    Lifecycle methods (``prepare``, ``teardown``, ``aclose``) are also delegated.
    """

    def __init__(self, inner: InferenceProvider, meter: BudgetMeter) -> None:
        self._inner = inner
        self._meter = meter

    # ------------------------------------------------------------------
    # InferenceProvider protocol — delegated attributes
    # ------------------------------------------------------------------

    @property
    def role(self) -> ProviderRole:
        return self._inner.role

    @property
    def model(self) -> str:
        return self._inner.model

    def is_local(self) -> bool:
        return self._inner.is_local()

    async def prepare(self) -> None:
        await self._inner.prepare()

    async def teardown(self) -> None:
        await self._inner.teardown()

    async def aclose(self) -> None:
        await self._inner.aclose()

    # ------------------------------------------------------------------
    # Core: budget-guarded chat
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[InferenceMessage],
        *,
        response_schema: dict[str, Any] | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> InferenceResult:
        """Run a guarded inference call.

        Note: the spend cap is a hard ceiling enforced on the NEXT call, so
        concurrent in-flight calls can overshoot by at most ``max_in_flight``
        calls' cost — this is bounded and intentional.

        Raises
        ------
        BudgetExceededError
            If the meter's cumulative spend is already >= the configured cap
            before the call is dispatched.  This is a hard pre-call guard;
            the inner provider is never called.
        """
        # Pre-call guard — raises BudgetExceededError if already at/over cap
        self._meter.check()

        result = await self._inner.chat(
            messages,
            response_schema=response_schema,
            json_mode=json_mode,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        self._meter.record(result.model, result.input_tokens, result.output_tokens)
        return result
