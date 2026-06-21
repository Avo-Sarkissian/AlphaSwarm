"""Tests for BudgetMeter, BudgetTrackingProvider, DEFAULT_PRICING, and estimate_run."""

from decimal import Decimal

import pytest

from alphaswarm.config import (
    InferenceConfig,
    ModelPrice,
    ProviderLimits,
    ProviderType,
    RoleConfig,
)
from alphaswarm.errors import BudgetExceededError
from alphaswarm.inference.budget import (
    DEFAULT_PRICING,
    BudgetMeter,
    BudgetTrackingProvider,
    RunEstimate,
    estimate_run,
)
from alphaswarm.inference.provider import InferenceProvider
from alphaswarm.inference.types import InferenceResult, ProviderRole
from tests.inference.fakes import FakeInferenceProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _meter(cap: Decimal | None = None, pricing: dict[str, ModelPrice] | None = None) -> BudgetMeter:
    if pricing is None:
        pricing = {
            "test-model": ModelPrice(
                input_per_mtok=Decimal("1.00"),
                output_per_mtok=Decimal("2.00"),
            )
        }
    return BudgetMeter(cap_usd=cap, pricing=pricing)


def _cloud_cfg(worker_model: str = "test-model", orch_model: str = "test-model") -> InferenceConfig:
    return InferenceConfig(
        orchestrator=RoleConfig(provider=ProviderType.ANTHROPIC, model=orch_model),
        worker=RoleConfig(provider=ProviderType.OPENAI_COMPATIBLE, model=worker_model),
        pricing_overrides={
            worker_model: ModelPrice(
                input_per_mtok=Decimal("1.00"),
                output_per_mtok=Decimal("2.00"),
            ),
            orch_model: ModelPrice(
                input_per_mtok=Decimal("1.00"),
                output_per_mtok=Decimal("2.00"),
            ),
        },
    )


def _local_cfg() -> InferenceConfig:
    return InferenceConfig(
        orchestrator=RoleConfig(provider=ProviderType.OLLAMA, model="local-orch"),
        worker=RoleConfig(provider=ProviderType.OLLAMA, model="local-worker"),
    )


# ---------------------------------------------------------------------------
# BudgetMeter.record — exact Decimal cost math
# ---------------------------------------------------------------------------


class TestBudgetMeterRecord:
    def test_exact_cost_1m_in_1m_out(self) -> None:
        meter = _meter()
        # 1M input @ $1.00/MTok + 1M output @ $2.00/MTok = $3.00
        total = meter.record("test-model", 1_000_000, 1_000_000)
        assert total == Decimal("3.00")

    def test_spent_accumulates(self) -> None:
        meter = _meter()
        meter.record("test-model", 1_000_000, 0)
        meter.record("test-model", 1_000_000, 0)
        assert meter.spent() == Decimal("2.00")

    def test_unknown_model_costs_zero(self) -> None:
        meter = _meter()
        total = meter.record("unknown-model-xyz", 1_000_000, 1_000_000)
        assert total == Decimal("0")

    def test_none_tokens_treated_as_zero(self) -> None:
        meter = _meter()
        total = meter.record("test-model", None, None)
        assert total == Decimal("0")

    def test_none_input_tokens(self) -> None:
        meter = _meter()
        # None input → 0 input cost; 1M output @ $2.00 = $2.00
        total = meter.record("test-model", None, 1_000_000)
        assert total == Decimal("2.00")

    def test_none_output_tokens(self) -> None:
        meter = _meter()
        # 1M input @ $1.00, None output = $1.00
        total = meter.record("test-model", 1_000_000, None)
        assert total == Decimal("1.00")

    def test_zero_tokens(self) -> None:
        meter = _meter()
        total = meter.record("test-model", 0, 0)
        assert total == Decimal("0")

    def test_spent_initial_zero(self) -> None:
        meter = _meter()
        assert meter.spent() == Decimal("0")


# ---------------------------------------------------------------------------
# would_exceed
# ---------------------------------------------------------------------------


class TestWouldExceed:
    def test_false_when_no_cap(self) -> None:
        meter = _meter(cap=None)
        assert meter.would_exceed("test-model", 10_000_000, 10_000_000) is False

    def test_false_when_under_cap(self) -> None:
        meter = _meter(cap=Decimal("10.00"))
        # 1M in + 1M out = $3; cap = $10
        assert meter.would_exceed("test-model", 1_000_000, 1_000_000) is False

    def test_true_when_over_cap(self) -> None:
        meter = _meter(cap=Decimal("2.00"))
        # spent=0, projected $3 > cap $2
        assert meter.would_exceed("test-model", 1_000_000, 1_000_000) is True

    def test_accumulated_spent_counts(self) -> None:
        meter = _meter(cap=Decimal("4.00"))
        meter.record("test-model", 1_000_000, 1_000_000)  # spent = $3
        # next call would add $3 → total $6 > cap $4
        assert meter.would_exceed("test-model", 1_000_000, 1_000_000) is True

    def test_exactly_at_cap_does_not_exceed(self) -> None:
        # would_exceed is strictly > cap
        meter = _meter(cap=Decimal("3.00"))
        # spent=0, projected $3 → total $3 == cap $3 → not exceeding
        assert meter.would_exceed("test-model", 1_000_000, 1_000_000) is False


# ---------------------------------------------------------------------------
# check()
# ---------------------------------------------------------------------------


class TestCheck:
    def test_no_raise_when_under_cap(self) -> None:
        meter = _meter(cap=Decimal("10.00"))
        meter.record("test-model", 1_000_000, 0)  # $1
        meter.check()  # should not raise

    def test_no_raise_when_no_cap(self) -> None:
        meter = _meter(cap=None)
        meter.record("test-model", 10_000_000, 10_000_000)
        meter.check()  # should not raise

    def test_raises_at_cap(self) -> None:
        meter = _meter(cap=Decimal("3.00"))
        meter.record("test-model", 1_000_000, 1_000_000)  # $3 == cap
        with pytest.raises(BudgetExceededError):
            meter.check()

    def test_raises_over_cap(self) -> None:
        meter = _meter(cap=Decimal("1.00"))
        meter.record("test-model", 1_000_000, 1_000_000)  # $3 > cap $1
        with pytest.raises(BudgetExceededError):
            meter.check()

    def test_raises_with_correct_values(self) -> None:
        meter = _meter(cap=Decimal("2.00"))
        meter.record("test-model", 1_000_000, 1_000_000)  # $3
        with pytest.raises(BudgetExceededError) as exc_info:
            meter.check()
        err = exc_info.value
        # M4: attributes must be Decimal, not float
        assert isinstance(err.spent_usd, Decimal)
        assert isinstance(err.cap_usd, Decimal)
        assert err.spent_usd >= Decimal("3.00")
        assert err.cap_usd == Decimal("2.00")


# ---------------------------------------------------------------------------
# estimate_run
# ---------------------------------------------------------------------------


class TestEstimateRun:
    def test_call_count(self) -> None:
        cfg = _cloud_cfg()
        result = estimate_run(cfg, agents=10, rounds=3, avg_in=500, avg_out=200)
        assert result.calls == 10 * 3 + 3  # 33

    def test_call_count_large(self) -> None:
        cfg = _cloud_cfg()
        result = estimate_run(cfg, agents=100, rounds=3, avg_in=500, avg_out=200)
        assert result.calls == 100 * 3 + 3  # 303

    def test_cost_math_cloud(self) -> None:
        """Check the band arithmetic for a simple case."""
        cfg = _cloud_cfg()
        # worker model: $1/MTok in, $2/MTok out
        # orch model:   $1/MTok in, $2/MTok out
        agents, rounds, avg_in, avg_out = 10, 1, 1_000_000, 1_000_000
        # worker calls: 10*1 = 10, each: $1 + $2 = $3 → $30
        # orch calls: 3, each: $3 → $9
        # total point: $39
        result = estimate_run(cfg, agents=agents, rounds=rounds, avg_in=avg_in, avg_out=avg_out)
        expected_low = (Decimal("39.00") * Decimal("0.7")).quantize(Decimal("0.01"))
        expected_high = (Decimal("39.00") * Decimal("1.3")).quantize(Decimal("0.01"))
        assert result.low_usd == expected_low
        assert result.high_usd == expected_high

    def test_local_config_zero_cost(self) -> None:
        cfg = _local_cfg()
        result = estimate_run(cfg, agents=100, rounds=3, avg_in=500, avg_out=200)
        assert result.low_usd == Decimal("0.00")
        assert result.high_usd == Decimal("0.00")

    def test_run_estimate_is_dataclass(self) -> None:
        cfg = _cloud_cfg()
        result = estimate_run(cfg, agents=5, rounds=2, avg_in=100, avg_out=100)
        assert isinstance(result, RunEstimate)
        assert hasattr(result, "calls")
        assert hasattr(result, "low_usd")
        assert hasattr(result, "high_usd")

    def test_low_less_than_high_for_nonzero(self) -> None:
        cfg = _cloud_cfg()
        result = estimate_run(cfg, agents=10, rounds=3, avg_in=500_000, avg_out=200_000)
        if result.low_usd > Decimal("0"):
            assert result.low_usd < result.high_usd

    def test_narrative_calls_total_count(self) -> None:
        """(a) total calls == agents*rounds + narrative_calls + 3."""
        cfg = _cloud_cfg()
        result = estimate_run(cfg, agents=10, rounds=3, avg_in=500, avg_out=200, narrative_calls=10)
        assert result.calls == 10 * 3 + 10 + 3  # 43

    def test_narrative_calls_priced_at_worker_rate(self) -> None:
        """(b) narrative_calls are priced at the WORKER model rate, not orchestrator rate."""
        # Use distinguishable prices so we can tell which model was charged.
        # Worker: $10/MTok in — deliberately expensive.
        # Orchestrator: $1/MTok in — deliberately cheap.
        worker_model = "worker-model"
        orch_model = "orch-model"
        cfg = InferenceConfig(
            orchestrator=RoleConfig(provider=ProviderType.ANTHROPIC, model=orch_model),
            worker=RoleConfig(provider=ProviderType.OPENAI_COMPATIBLE, model=worker_model),
            pricing_overrides={
                worker_model: ModelPrice(
                    input_per_mtok=Decimal("10.00"),
                    output_per_mtok=Decimal("0.00"),
                ),
                orch_model: ModelPrice(
                    input_per_mtok=Decimal("1.00"),
                    output_per_mtok=Decimal("0.00"),
                ),
            },
        )
        # 0 regular worker rounds, 1 narrative call, 0 orch calls (override via pricing=custom)
        # We want to isolate the narrative cost; set agents=0 rounds=0 and check narrative_calls=1
        # But orch_calls is always 3 — use large avg_in=0 to zero orch cost via avg_out:
        # To isolate: set avg_in=1_000_000, avg_out=0; orch cost = 3 * $1 = $3
        # narrative cost (1 call, worker) = 1 * $10 = $10; total point = $13
        result = estimate_run(
            cfg,
            agents=0,
            rounds=0,
            avg_in=1_000_000,
            avg_out=0,
            narrative_calls=1,
        )
        # total point = orch(3 * $1) + narrative_worker(1 * $10) = $13
        expected_low = (Decimal("13.00") * Decimal("0.7")).quantize(Decimal("0.01"))
        expected_high = (Decimal("13.00") * Decimal("1.3")).quantize(Decimal("0.01"))
        assert result.low_usd == expected_low, (
            "narrative_calls must be priced at worker rate ($10), not orch rate ($1)"
        )
        assert result.high_usd == expected_high

    def test_narrative_calls_default_zero_regression(self) -> None:
        """(c) narrative_calls=0 (default) reproduces the prior cost — regression guard."""
        cfg = _cloud_cfg()
        # Explicit zero and omitted should produce identical results
        result_explicit = estimate_run(cfg, agents=10, rounds=3, avg_in=500, avg_out=200, narrative_calls=0)
        result_default = estimate_run(cfg, agents=10, rounds=3, avg_in=500, avg_out=200)
        assert result_explicit.calls == result_default.calls
        assert result_explicit.low_usd == result_default.low_usd
        assert result_explicit.high_usd == result_default.high_usd

    def test_custom_pricing_passed_in(self) -> None:
        cfg = _cloud_cfg()
        custom = {
            "test-model": ModelPrice(
                input_per_mtok=Decimal("0.00"),
                output_per_mtok=Decimal("0.00"),
            )
        }
        result = estimate_run(cfg, agents=10, rounds=3, avg_in=1_000_000, avg_out=1_000_000, pricing=custom)
        assert result.low_usd == Decimal("0.00")
        assert result.high_usd == Decimal("0.00")


# ---------------------------------------------------------------------------
# DEFAULT_PRICING sanity
# ---------------------------------------------------------------------------


class TestDefaultPricing:
    def test_has_entries(self) -> None:
        assert len(DEFAULT_PRICING) > 0

    def test_all_values_are_model_price(self) -> None:
        for k, v in DEFAULT_PRICING.items():
            assert isinstance(v, ModelPrice), f"Bad entry for {k}"

    def test_values_are_decimal(self) -> None:
        for k, v in DEFAULT_PRICING.items():
            assert isinstance(v.input_per_mtok, Decimal)
            assert isinstance(v.output_per_mtok, Decimal)


# ---------------------------------------------------------------------------
# BudgetTrackingProvider tests
# ---------------------------------------------------------------------------

_PRICING = {
    "test-model": ModelPrice(
        input_per_mtok=Decimal("1.00"),
        output_per_mtok=Decimal("2.00"),
    )
}

_RESULT = InferenceResult(
    content="hello",
    model="test-model",
    input_tokens=1_000_000,
    output_tokens=1_000_000,
)  # cost = $3.00


def _make_wrapped(
    cap: Decimal | None = None,
    scripted: list[InferenceResult] | None = None,
) -> tuple[BudgetTrackingProvider, BudgetMeter, FakeInferenceProvider]:
    meter = BudgetMeter(cap_usd=cap, pricing=_PRICING)
    inner = FakeInferenceProvider(
        role=ProviderRole.WORKER,
        model="test-model",
        scripted=scripted or [_RESULT],
        is_local=False,
    )
    wrapper = BudgetTrackingProvider(inner=inner, meter=meter)
    return wrapper, meter, inner


class TestBudgetTrackingProviderDelegation:
    def test_role_delegated(self) -> None:
        wrapper, _, _ = _make_wrapped()
        assert wrapper.role == ProviderRole.WORKER

    def test_model_delegated(self) -> None:
        wrapper, _, _ = _make_wrapped()
        assert wrapper.model == "test-model"

    def test_is_local_delegated(self) -> None:
        wrapper, _, _ = _make_wrapped()
        assert wrapper.is_local() is False

    @pytest.mark.asyncio
    async def test_prepare_delegated(self) -> None:
        wrapper, _, inner = _make_wrapped()
        await wrapper.prepare()  # should not raise

    @pytest.mark.asyncio
    async def test_teardown_delegated(self) -> None:
        wrapper, _, inner = _make_wrapped()
        await wrapper.teardown()  # should not raise

    @pytest.mark.asyncio
    async def test_aclose_delegated(self) -> None:
        wrapper, _, inner = _make_wrapped()
        await wrapper.aclose()  # should not raise

    def test_satisfies_inference_provider_protocol(self) -> None:
        wrapper, _, _ = _make_wrapped()
        assert isinstance(wrapper, InferenceProvider)


class TestBudgetTrackingProviderChat:
    @pytest.mark.asyncio
    async def test_chat_records_cost(self) -> None:
        wrapper, meter, _ = _make_wrapped()
        assert meter.spent() == Decimal("0")
        result = await wrapper.chat([{"role": "user", "content": "hi"}])
        assert result.content == "hello"
        # 1M input @ $1/MTok + 1M output @ $2/MTok = $3
        assert meter.spent() == Decimal("3.00")

    @pytest.mark.asyncio
    async def test_chat_delegates_to_inner(self) -> None:
        wrapper, _, inner = _make_wrapped()
        await wrapper.chat([{"role": "user", "content": "test"}])
        assert len(inner.calls) == 1
        assert inner.calls[0]["messages"] == [{"role": "user", "content": "test"}]

    @pytest.mark.asyncio
    async def test_check_raises_before_second_call_when_at_cap(self) -> None:
        # Cap = $3, first call costs $3, second should raise before dispatch
        wrapper, meter, inner = _make_wrapped(
            cap=Decimal("3.00"),
            scripted=[_RESULT, _RESULT],
        )
        await wrapper.chat([{"role": "user", "content": "first"}])
        # spent == $3 == cap → next check() raises
        with pytest.raises(BudgetExceededError):
            await wrapper.chat([{"role": "user", "content": "second"}])
        # Inner should only have been called once
        assert len(inner.calls) == 1

    @pytest.mark.asyncio
    async def test_check_raises_when_over_cap_from_start(self) -> None:
        # Meter already over cap before any chat
        meter = BudgetMeter(cap_usd=Decimal("1.00"), pricing=_PRICING)
        meter.record("test-model", 1_000_000, 1_000_000)  # $3 > $1
        inner = FakeInferenceProvider(
            role=ProviderRole.WORKER,
            model="test-model",
            scripted=[_RESULT],
            is_local=False,
        )
        wrapper = BudgetTrackingProvider(inner=inner, meter=meter)
        with pytest.raises(BudgetExceededError):
            await wrapper.chat([{"role": "user", "content": "blocked"}])
        assert len(inner.calls) == 0  # inner never called

    @pytest.mark.asyncio
    async def test_no_cap_never_raises(self) -> None:
        wrapper, meter, _ = _make_wrapped(
            cap=None,
            scripted=[_RESULT, _RESULT, _RESULT],
        )
        for _ in range(3):
            await wrapper.chat([{"role": "user", "content": "x"}])
        assert meter.spent() == Decimal("9.00")
