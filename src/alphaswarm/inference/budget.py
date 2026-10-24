"""Budget tracking, pricing table, and run estimator for cloud inference.

All monetary values are Python ``Decimal`` to avoid floating-point drift.
Prices in DEFAULT_PRICING are vendor list prices checked on PRICING_VERIFIED_AT
(a test fails once that check is older than PRICING_MAX_AGE_DAYS); any entry is
user-overridable via InferenceConfig.pricing_overrides.

Also provides ``BudgetTrackingProvider``: a thin InferenceProvider wrapper that
records every call's token cost in a shared BudgetMeter and enforces the USD cap
BEFORE dispatching.  Because it wraps the inner provider, ALL cloud calls
(worker waves, seed, advisory, report) are counted and capped uniformly —
even those that bypass the RateLimitController.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

import structlog

from alphaswarm.errors import BudgetExceededError
from alphaswarm.inference.config import InferenceConfig, ModelPrice, ProviderType
from alphaswarm.inference.types import InferenceMessage, InferenceResult, ProviderRole

if TYPE_CHECKING:
    from alphaswarm.inference.provider import InferenceProvider

log = structlog.get_logger(component="inference.budget")

# ---------------------------------------------------------------------------
# Default pricing table
# ---------------------------------------------------------------------------


def _price(input_per_mtok: str, output_per_mtok: str) -> ModelPrice:
    return ModelPrice(input_per_mtok=Decimal(input_per_mtok), output_per_mtok=Decimal(output_per_mtok))


# Standard list prices in USD per 1M tokens (input, output): non-batch, uncached,
# prompts up to 200K tokens. Keys are normalized ids (no date suffix);
# resolve_price() maps dated and versioned ids onto them. Premium "-pro" variants
# are not listed: add a pricing_overrides entry before using one
# (docs/DECISIONS.md#adr-cloud-retry).
PRICING_VERIFIED_AT: Final[date] = date(2026, 10, 8)
PRICING_MAX_AGE_DAYS: Final = 180

DEFAULT_PRICING: dict[str, ModelPrice] = {
    # Anthropic (anthropic.com/pricing)
    "claude-opus-4-5": _price("5.00", "25.00"),
    "claude-opus-4-1": _price("15.00", "75.00"),
    "claude-opus-4": _price("15.00", "75.00"),
    "claude-sonnet-4-5": _price("3.00", "15.00"),
    "claude-sonnet-4": _price("3.00", "15.00"),
    "claude-haiku-4-5": _price("1.00", "5.00"),
    "claude-3-5-haiku": _price("0.80", "4.00"),
    "claude-3-5-sonnet": _price("3.00", "15.00"),
    # OpenAI (openai.com/api/pricing)
    "gpt-5": _price("1.25", "10.00"),
    "gpt-5-mini": _price("0.25", "2.00"),
    "gpt-5-nano": _price("0.05", "0.40"),
    "gpt-4.1": _price("2.00", "8.00"),
    "gpt-4.1-mini": _price("0.40", "1.60"),
    "gpt-4.1-nano": _price("0.10", "0.40"),
    "gpt-4o": _price("2.50", "10.00"),
    "gpt-4o-mini": _price("0.15", "0.60"),
    "o1": _price("15.00", "60.00"),
    "o3": _price("2.00", "8.00"),
    "o3-mini": _price("1.10", "4.40"),
    "o4-mini": _price("1.10", "4.40"),
    # OpenRouter-style ids (openrouter.ai/models; the listed price for the id)
    "meta-llama/llama-3.3-70b-instruct": _price("0.13", "0.40"),
    "mistralai/mistral-large-2411": _price("2.00", "6.00"),
    "google/gemini-2.0-flash-001": _price("0.10", "0.40"),
    "google/gemini-2.5-flash": _price("0.30", "2.50"),
    "google/gemini-2.5-pro": _price("1.25", "10.00"),
}

# A dated snapshot suffix: -20251001 (Anthropic) or -2024-07-18 (OpenAI).
_DATE_SUFFIX: Final = re.compile(r"-(?:\d{8}|\d{4}-\d{2}-\d{2})$")
# What may follow a table key for the key's price to apply: a version number
# ("-6", "-4.1") or a tag (":free", "@2025"), never another word ("-pro", "-mini").
_VERSION_SUFFIX: Final = re.compile(r"(?:-\d[\w.-]*|[:@][\w.-]+)")


def normalize_model_id(model: str) -> str:
    """Strip a dated snapshot suffix: claude-haiku-4-5-20251001 -> claude-haiku-4-5."""
    return _DATE_SUFFIX.sub("", model.strip())


def resolve_price(pricing: Mapping[str, ModelPrice], model: str) -> tuple[str, ModelPrice] | None:
    """(matched key, price) for ``model``, or None when it is unpriced.

    Order: the exact id (so a dated override wins), the normalized id, then the
    longest key that the normalized id extends only by a version suffix.
    """
    if model in pricing:
        return model, pricing[model]
    normalized = normalize_model_id(model)
    if normalized in pricing:
        return normalized, pricing[normalized]
    best: str | None = None
    for key in pricing:
        if (
            normalized.startswith(key)
            and _VERSION_SUFFIX.fullmatch(normalized[len(key) :]) is not None
            and (best is None or len(key) > len(best))
        ):
            best = key
    return (best, pricing[best]) if best is not None else None


_CENTS = Decimal("0.01")
_MTOK = Decimal("1000000")

# Conservative ceiling used for an unpriced model WHEN A CAP IS SET, so an
# unknown/aliased model id can never silently make the spend cap unenforceable
# (F-18). Matches the most expensive tier in DEFAULT_PRICING; only used as a
# floor if the merged pricing table is somehow empty.
_FALLBACK_UNKNOWN_PRICE = ModelPrice(
    input_per_mtok=Decimal("15.00"),
    output_per_mtok=Decimal("75.00"),
)

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
    warn_unpriced:
        False for estimates, which run on every Settings request.
    """

    def __init__(
        self,
        cap_usd: Decimal | None,
        pricing: dict[str, ModelPrice],
        *,
        warn_unpriced: bool = True,
    ) -> None:
        self._cap = cap_usd
        self._pricing = pricing
        self._total: Decimal = Decimal(0)
        self._warned_unknown: set[str] = set()
        self._warn_unpriced = warn_unpriced
        # Conservative ceiling for an unpriced model under a cap (F-18). The
        # table is immutable, so compute once. Floored at the opus-tier fallback
        # so the ceiling is never *below* a realistic price even if the table is
        # sparse/cheap (which would otherwise under-enforce the cap).
        # Floor each rate list with the fallback so max() always has a non-empty
        # iterable even when the pricing table is empty.
        _in_rates = [_FALLBACK_UNKNOWN_PRICE.input_per_mtok]
        _in_rates += [p.input_per_mtok for p in pricing.values()]
        _out_rates = [_FALLBACK_UNKNOWN_PRICE.output_per_mtok]
        _out_rates += [p.output_per_mtok for p in pricing.values()]
        self._unknown_price: ModelPrice = ModelPrice(
            input_per_mtok=max(_in_rates),
            output_per_mtok=max(_out_rates),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cost_of(self, model: str, in_tokens: int, out_tokens: int) -> Decimal:
        match = resolve_price(self._pricing, model)
        if match is None:
            # Unknown model: $0 is only safe for uncapped runs. With a cap set,
            # treating it as free would make the cap silently unenforceable, so
            # price it at a conservative ceiling instead (docs/DECISIONS.md#adr-cloud-retry).
            if self._warn_unpriced and model not in self._warned_unknown:
                # Add an entry to DEFAULT_PRICING or InferenceConfig.pricing_overrides.
                log.warning(
                    "budget_model_unpriced",
                    model=model,
                    policy="ceiling" if self._cap is not None else "free",
                )
                self._warned_unknown.add(model)
            if self._cap is None:
                return Decimal(0)
            price = self._unknown_price
        else:
            key, price = match
            inferred = key not in (model, normalize_model_id(model))
            if inferred and self._warn_unpriced and model not in self._warned_unknown:
                log.info("budget_model_price_inferred", model=model, priced_as=key)
                self._warned_unknown.add(model)
        return Decimal(in_tokens) / _MTOK * price.input_per_mtok + Decimal(out_tokens) / _MTOK * price.output_per_mtok

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
    - ``narrative_calls`` additional worker calls, priced at the worker rate. A
      run makes none (default 0): decision narratives are generated on an
      agent's first interview (docs/DECISIONS.md#p11-d-11).
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
        match = resolve_price(resolved, model)
        if match is None:
            log.warning("estimate_model_unpriced", model=model)
            return Decimal(0)
        mp = match[1]
        per_call = Decimal(avg_in) / _MTOK * mp.input_per_mtok + Decimal(avg_out) / _MTOK * mp.output_per_mtok
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

    @property
    def inner(self) -> InferenceProvider:
        """The wrapped provider (the factory attaches the retry gate to it)."""
        return self._inner

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
