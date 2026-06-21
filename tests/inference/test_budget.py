"""Tests for BudgetMeter, DEFAULT_PRICING, and estimate_run."""

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
    RunEstimate,
    estimate_run,
)


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
        assert err.spent_usd >= 3.0
        assert err.cap_usd == pytest.approx(2.0)


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
