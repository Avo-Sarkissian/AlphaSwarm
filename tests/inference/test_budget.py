"""Tests for BudgetMeter, BudgetTrackingProvider, DEFAULT_PRICING, and estimate_run."""

from datetime import date
from decimal import Decimal

import pytest

from alphaswarm.errors import BudgetExceededError
from alphaswarm.inference.budget import (
    DEFAULT_CALL_PROFILE,
    DEFAULT_PRICING,
    PRICING_MAX_AGE_DAYS,
    PRICING_VERIFIED_AT,
    BudgetMeter,
    BudgetTrackingProvider,
    CallProfile,
    estimate_run,
    normalize_model_id,
    resolve_price,
)
from alphaswarm.inference.config import InferenceConfig, ModelPrice, ProviderType, RoleConfig
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

    def test_unknown_model_not_free_when_capped(self) -> None:
        """F-18: with a cap set, an unpriced model must accrue cost (conservative
        ceiling) — never $0, which would make the cap silently unenforceable."""
        meter = _meter(cap=Decimal("100.00"))
        total = meter.record("unknown-model-xyz", 1_000_000, 1_000_000)
        assert total > Decimal("0")

    def test_unknown_model_capped_would_exceed(self) -> None:
        """F-18: an unpriced model under a tiny cap must trip would_exceed/check."""
        meter = _meter(cap=Decimal("0.01"))
        assert meter.would_exceed("unknown-model-xyz", 1_000_000, 1_000_000) is True

    def test_empty_pricing_table_constructs_and_prices_unknown(self) -> None:
        """An empty pricing table must construct (no max()-of-single-Decimal crash)
        and, under a cap, price an unknown model at the opus-tier fallback."""
        meter = BudgetMeter(cap_usd=Decimal("100.00"), pricing={})
        total = meter.record("anything", 1_000_000, 1_000_000)
        # Floored at _FALLBACK_UNKNOWN_PRICE: $15 in + $75 out = $90 for 1M/1M.
        assert total == Decimal("90.00")
        # Uncapped + empty table still free.
        uncapped = BudgetMeter(cap_usd=None, pricing={})
        assert uncapped.record("anything", 1_000_000, 0) == Decimal("0")

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
    """estimate_run prices through the meter (docs/DECISIONS.md#adr-cloud-retry)."""

    PROFILE = CallProfile(
        worker_in=1_000_000,
        worker_out=0,
        orchestrator_calls=2,
        orchestrator_in=0,
        orchestrator_out=1_000_000,
    )

    def test_call_count_is_agents_times_rounds_plus_orchestrator_calls(self) -> None:
        result = estimate_run(_cloud_cfg(), agents=100, rounds=3)
        assert result.calls == 100 * 3 + DEFAULT_CALL_PROFILE.orchestrator_calls

    def test_default_profile_counts_seed_modifiers_report_and_advisory(self) -> None:
        # Narratives are generated at interview time; interviews are not part of a run.
        assert DEFAULT_CALL_PROFILE.orchestrator_calls == 4

    def test_cost_math_uses_each_roles_tokens(self) -> None:
        # worker: 10 calls x 1M in x $1 = $10; orchestrator: 2 calls x 1M out x $2 = $4; point $14
        result = estimate_run(_cloud_cfg(), agents=10, rounds=1, profile=self.PROFILE)
        assert (result.low_usd, result.high_usd) == (Decimal("9.80"), Decimal("18.20"))

    def test_local_config_costs_nothing(self) -> None:
        result = estimate_run(_local_cfg(), agents=100, rounds=3)
        assert (result.low_usd, result.high_usd, result.unpriced_models) == (Decimal("0.00"), Decimal("0.00"), ())

    def test_unknown_model_with_a_cap_is_priced_like_the_meter(self) -> None:
        cfg = InferenceConfig(
            orchestrator=RoleConfig(provider=ProviderType.OLLAMA, model="local-orch"),
            worker=RoleConfig(provider=ProviderType.OPENAI_COMPATIBLE, model="typo-model"),
            spend_cap_usd=Decimal("5.00"),
        )
        result = estimate_run(cfg, agents=1, rounds=1, profile=self.PROFILE)
        point = BudgetMeter(Decimal("5.00"), dict(DEFAULT_PRICING)).record("typo-model", 1_000_000, 0)
        assert result.high_usd == (point * Decimal("1.3")).quantize(Decimal("0.01"))
        assert result.high_usd > Decimal("0.00")
        assert result.unpriced_models == ("typo-model",)

    def test_unknown_model_without_a_cap_is_free_but_listed(self) -> None:
        role = RoleConfig(provider=ProviderType.OPENAI_COMPATIBLE, model="typo-model")
        result = estimate_run(InferenceConfig(orchestrator=role, worker=role), agents=10, rounds=3)
        assert result.high_usd == Decimal("0.00")
        assert result.unpriced_models == ("typo-model",)

    def test_dated_ids_are_priced(self) -> None:
        role = RoleConfig(provider=ProviderType.ANTHROPIC, model="claude-haiku-4-5-20251001")
        result = estimate_run(InferenceConfig(orchestrator=role, worker=role), agents=100, rounds=3)
        assert result.high_usd > Decimal("0.00")
        assert result.unpriced_models == ()

    def test_custom_pricing_passed_in(self) -> None:
        free = {"test-model": ModelPrice(input_per_mtok=Decimal("0"), output_per_mtok=Decimal("0"))}
        result = estimate_run(_cloud_cfg(), agents=10, rounds=3, pricing=free)
        assert result.high_usd == Decimal("0.00")

    def test_run_estimate_is_frozen(self) -> None:
        import dataclasses

        result = estimate_run(_cloud_cfg(), agents=5, rounds=2)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.calls = 0  # type: ignore[misc]

    def test_the_estimate_does_not_log_per_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import structlog
        from structlog.testing import capture_logs

        import alphaswarm.inference.budget as budget_module

        monkeypatch.setattr(budget_module, "log", structlog.get_logger(component="inference.budget"))
        role = RoleConfig(provider=ProviderType.OPENAI_COMPATIBLE, model="typo-model")
        with capture_logs() as logs:
            estimate_run(InferenceConfig(orchestrator=role, worker=role), agents=1, rounds=1)
        assert not [e for e in logs if e["event"] == "budget_model_unpriced"]


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
        for _k, v in DEFAULT_PRICING.items():
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

    async def test_prepare_delegated(self) -> None:
        wrapper, _, inner = _make_wrapped()
        await wrapper.prepare()  # should not raise

    async def test_teardown_delegated(self) -> None:
        wrapper, _, inner = _make_wrapped()
        await wrapper.teardown()  # should not raise

    async def test_aclose_delegated(self) -> None:
        wrapper, _, inner = _make_wrapped()
        await wrapper.aclose()  # should not raise

    def test_satisfies_inference_provider_protocol(self) -> None:
        wrapper, _, _ = _make_wrapped()
        assert isinstance(wrapper, InferenceProvider)


class TestBudgetTrackingProviderChat:
    async def test_chat_records_cost(self) -> None:
        wrapper, meter, _ = _make_wrapped()
        assert meter.spent() == Decimal("0")
        result = await wrapper.chat([{"role": "user", "content": "hi"}])
        assert result.content == "hello"
        # 1M input @ $1/MTok + 1M output @ $2/MTok = $3
        assert meter.spent() == Decimal("3.00")

    async def test_chat_delegates_to_inner(self) -> None:
        wrapper, _, inner = _make_wrapped()
        await wrapper.chat([{"role": "user", "content": "test"}])
        assert len(inner.calls) == 1
        assert inner.calls[0]["messages"] == [{"role": "user", "content": "test"}]

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

    async def test_no_cap_never_raises(self) -> None:
        wrapper, meter, _ = _make_wrapped(
            cap=None,
            scripted=[_RESULT, _RESULT, _RESULT],
        )
        for _ in range(3):
            await wrapper.chat([{"role": "user", "content": "x"}])
        assert meter.spent() == Decimal("9.00")


# ---------------------------------------------------------------------------
# Model id normalization and the pricing table (docs/DECISIONS.md#adr-cloud-retry)
# ---------------------------------------------------------------------------


def _mp(input_per_mtok: str, output_per_mtok: str) -> ModelPrice:
    return ModelPrice(input_per_mtok=Decimal(input_per_mtok), output_per_mtok=Decimal(output_per_mtok))


class TestModelIdNormalization:
    @pytest.mark.parametrize(
        ("raw", "normalized"),
        [
            ("claude-haiku-4-5-20251001", "claude-haiku-4-5"),
            ("claude-3-5-haiku-20241022", "claude-3-5-haiku"),
            ("gpt-4o-mini-2024-07-18", "gpt-4o-mini"),
            ("gpt-4o", "gpt-4o"),
            ("meta/llama-3.1-8b-instruct", "meta/llama-3.1-8b-instruct"),
        ],
    )
    def test_dated_suffixes_are_stripped(self, raw: str, normalized: str) -> None:
        assert normalize_model_id(raw) == normalized

    def test_dated_ids_resolve_to_the_base_price(self) -> None:
        match = resolve_price(DEFAULT_PRICING, "claude-haiku-4-5-20251001")
        assert match == ("claude-haiku-4-5", DEFAULT_PRICING["claude-haiku-4-5"])

    def test_longest_prefix_wins_for_version_suffixes(self) -> None:
        pricing = {"claude-opus-4": _mp("15", "75"), "claude-opus-4-5": _mp("5", "25")}
        assert resolve_price(pricing, "claude-opus-4-5-20251101") == ("claude-opus-4-5", pricing["claude-opus-4-5"])
        assert resolve_price(pricing, "claude-opus-4-7") == ("claude-opus-4", pricing["claude-opus-4"])

    def test_a_different_product_is_not_a_version(self) -> None:
        """o1-pro costs 10x o1: a bare prefix match would under-price it under a cap."""
        assert resolve_price({"o1": _mp("15", "60")}, "o1-pro") is None
        assert resolve_price({"gpt-4o": _mp("2.50", "10")}, "gpt-4o-audio-preview") is None

    def test_tags_after_a_colon_are_versions(self) -> None:
        pricing = {"meta-llama/llama-3.3-70b-instruct": _mp("0.13", "0.40")}
        assert resolve_price(pricing, "meta-llama/llama-3.3-70b-instruct:free") is not None

    def test_an_exact_override_with_a_dated_id_wins(self) -> None:
        pricing = {"claude-haiku-4-5": _mp("1", "5"), "claude-haiku-4-5-20251001": _mp("2", "10")}
        match = resolve_price(pricing, "claude-haiku-4-5-20251001")
        assert match is not None and match[0] == "claude-haiku-4-5-20251001"

    def test_the_meter_prices_a_dated_id_like_its_base_model(self) -> None:
        meter = BudgetMeter(cap_usd=None, pricing=dict(DEFAULT_PRICING))
        cost = meter.record("claude-haiku-4-5-20251001", 1_000_000, 0)
        assert cost == DEFAULT_PRICING["claude-haiku-4-5"].input_per_mtok

    def test_an_inferred_price_is_logged_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import structlog
        from structlog.testing import capture_logs

        import alphaswarm.inference.budget as budget_module

        monkeypatch.setattr(budget_module, "log", structlog.get_logger(component="inference.budget"))
        meter = BudgetMeter(cap_usd=None, pricing={"claude-opus-4": _mp("15", "75")})
        with capture_logs() as logs:
            meter.record("claude-opus-4-7", 10, 10)
            meter.record("claude-opus-4-7", 10, 10)
        inferred = [e for e in logs if e["event"] == "budget_model_price_inferred"]
        assert [(e["model"], e["priced_as"]) for e in inferred] == [("claude-opus-4-7", "claude-opus-4")]


class TestPricingTable:
    def test_pricing_table_was_verified_recently(self) -> None:
        """Re-check the vendor pages (docs/RUNBOOK.md, cloud mode) and bump the date."""
        age = (date.today() - PRICING_VERIFIED_AT).days
        assert 0 <= age <= PRICING_MAX_AGE_DAYS, (
            f"DEFAULT_PRICING was last verified {age} days ago; re-check the vendor pricing "
            "pages and update PRICING_VERIFIED_AT in src/alphaswarm/inference/budget.py"
        )

    def test_keys_are_normalized(self) -> None:
        assert all(normalize_model_id(key) == key for key in DEFAULT_PRICING)

    def test_haiku_4_5_is_no_longer_priced_like_haiku_3_5(self) -> None:
        assert DEFAULT_PRICING["claude-haiku-4-5"].input_per_mtok > DEFAULT_PRICING["claude-3-5-haiku"].input_per_mtok

    def test_unknown_model_ceiling_is_unchanged_by_the_refresh(self) -> None:
        meter = BudgetMeter(cap_usd=Decimal("100"), pricing=dict(DEFAULT_PRICING))
        assert meter.record("unknown-model-xyz", 1_000_000, 1_000_000) == Decimal("90.00")
