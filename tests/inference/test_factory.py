"""Tests for inference.factory — provider + controller factory from InferenceConfig.

TDD cycle: tests written first (RED), factory implemented second (GREEN).
All tests are purely constructive — no network, no Ollama, no real LLM calls.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from alphaswarm.config import InferenceConfig, ProviderLimits, ProviderType, RoleConfig
from alphaswarm.governor import ResourceGovernor
from alphaswarm.inference import (
    RateLimitController,
)
from alphaswarm.inference.anthropic_provider import AnthropicProvider
from alphaswarm.inference.budget import BudgetTrackingProvider
from alphaswarm.inference.factory import (
    BuiltProviders,
    build_controller,
    build_providers,
    inference_mode,
)
from alphaswarm.inference.ollama_provider import OllamaProvider
from alphaswarm.inference.openai_provider import OpenAICompatProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ollama_role(model: str = "alphaswarm-worker") -> RoleConfig:
    return RoleConfig(provider=ProviderType.OLLAMA, model=model)


def _anthropic_role(model: str = "claude-3-5-haiku-20241022") -> RoleConfig:
    return RoleConfig(
        provider=ProviderType.ANTHROPIC,
        model=model,
        api_key="sk-test-anthropic-key",
    )


def _openai_role(model: str = "gpt-4o-mini") -> RoleConfig:
    return RoleConfig(
        provider=ProviderType.OPENAI_COMPATIBLE,
        model=model,
        base_url="https://api.openai.com/v1",
        api_key="sk-test-openai-key",
    )


def _fake_ollama_client() -> MagicMock:
    """Stub OllamaClient — not called at build time."""
    return MagicMock(name="OllamaClient")


def _fake_model_manager() -> MagicMock:
    """Stub OllamaModelManager — not called at build time."""
    return MagicMock(name="OllamaModelManager")


def _governor_settings() -> MagicMock:
    """Stub GovernorSettings."""
    return MagicMock(name="GovernorSettings")


# ---------------------------------------------------------------------------
# inference_mode
# ---------------------------------------------------------------------------


class TestInferenceMode:
    def test_both_ollama_is_local(self) -> None:
        cfg = InferenceConfig(orchestrator=_ollama_role("orch"), worker=_ollama_role("wrk"))
        assert inference_mode(cfg) == "local"

    def test_both_cloud_is_cloud(self) -> None:
        cfg = InferenceConfig(orchestrator=_openai_role(), worker=_anthropic_role())
        assert inference_mode(cfg) == "cloud"

    def test_ollama_orch_cloud_worker_is_mixed(self) -> None:
        cfg = InferenceConfig(orchestrator=_ollama_role(), worker=_anthropic_role())
        assert inference_mode(cfg) == "mixed"

    def test_cloud_orch_ollama_worker_is_mixed(self) -> None:
        cfg = InferenceConfig(orchestrator=_anthropic_role(), worker=_ollama_role())
        assert inference_mode(cfg) == "mixed"


# ---------------------------------------------------------------------------
# build_providers — all-Ollama
# ---------------------------------------------------------------------------


class TestBuildProvidersAllOllama:
    def setup_method(self) -> None:
        self.cfg = InferenceConfig(
            orchestrator=_ollama_role("alphaswarm-orch"),
            worker=_ollama_role("alphaswarm-worker"),
        )
        self.client = _fake_ollama_client()
        self.manager = _fake_model_manager()
        self.built: BuiltProviders = build_providers(
            self.cfg,
            ollama_client=self.client,
            ollama_model_manager=self.manager,
        )

    def test_orchestrator_is_ollama_provider(self) -> None:
        assert isinstance(self.built.orchestrator, OllamaProvider)

    def test_worker_is_ollama_provider(self) -> None:
        assert isinstance(self.built.worker, OllamaProvider)

    def test_orchestrator_not_budget_wrapped(self) -> None:
        assert not isinstance(self.built.orchestrator, BudgetTrackingProvider)

    def test_worker_not_budget_wrapped(self) -> None:
        assert not isinstance(self.built.worker, BudgetTrackingProvider)

    def test_budget_meter_cap_is_none(self) -> None:
        assert self.built.budget_meter._cap is None  # no cap set in config

    def test_orchestrator_model(self) -> None:
        assert self.built.orchestrator.model == "alphaswarm-orch"

    def test_worker_model(self) -> None:
        assert self.built.worker.model == "alphaswarm-worker"


# ---------------------------------------------------------------------------
# build_providers — mixed (Ollama orch + Anthropic worker)
# ---------------------------------------------------------------------------


class TestBuildProvidersMixed:
    def setup_method(self) -> None:
        self.cap = Decimal("5.00")
        self.cfg = InferenceConfig(
            orchestrator=_ollama_role("alphaswarm-orch"),
            worker=_anthropic_role("claude-3-5-haiku-20241022"),
            spend_cap_usd=self.cap,
        )
        self.built: BuiltProviders = build_providers(
            self.cfg,
            ollama_client=_fake_ollama_client(),
            ollama_model_manager=_fake_model_manager(),
        )

    def test_orchestrator_is_ollama_provider(self) -> None:
        assert isinstance(self.built.orchestrator, OllamaProvider)

    def test_worker_is_budget_tracking_provider(self) -> None:
        assert isinstance(self.built.worker, BudgetTrackingProvider)

    def test_worker_inner_is_anthropic_provider(self) -> None:
        assert isinstance(self.built.worker._inner, AnthropicProvider)  # type: ignore[union-attr]

    def test_meter_cap_matches_config(self) -> None:
        assert self.built.budget_meter._cap == self.cap

    def test_mode_is_mixed(self) -> None:
        assert inference_mode(self.cfg) == "mixed"


# ---------------------------------------------------------------------------
# build_providers — both cloud (OpenAI compatible for both roles)
# ---------------------------------------------------------------------------


class TestBuildProvidersBothCloud:
    def setup_method(self) -> None:
        self.cap = Decimal("10.00")
        self.cfg = InferenceConfig(
            orchestrator=_openai_role("gpt-4o"),
            worker=_openai_role("gpt-4o-mini"),
            spend_cap_usd=self.cap,
        )
        self.built: BuiltProviders = build_providers(
            self.cfg,
            ollama_client=_fake_ollama_client(),
            ollama_model_manager=_fake_model_manager(),
        )

    def test_orchestrator_is_budget_tracking_provider(self) -> None:
        assert isinstance(self.built.orchestrator, BudgetTrackingProvider)

    def test_worker_is_budget_tracking_provider(self) -> None:
        assert isinstance(self.built.worker, BudgetTrackingProvider)

    def test_orchestrator_inner_is_openai_compat(self) -> None:
        assert isinstance(self.built.orchestrator._inner, OpenAICompatProvider)  # type: ignore[union-attr]

    def test_worker_inner_is_openai_compat(self) -> None:
        assert isinstance(self.built.worker._inner, OpenAICompatProvider)  # type: ignore[union-attr]

    def test_shared_meter_same_object(self) -> None:
        """Both cloud providers must reference the SAME BudgetMeter instance."""
        orch_meter = self.built.orchestrator._meter  # type: ignore[union-attr]
        worker_meter = self.built.worker._meter  # type: ignore[union-attr]
        assert orch_meter is worker_meter

    def test_shared_meter_is_built_meter(self) -> None:
        assert self.built.orchestrator._meter is self.built.budget_meter  # type: ignore[union-attr]

    def test_mode_is_cloud(self) -> None:
        assert inference_mode(self.cfg) == "cloud"

    def test_meter_cap(self) -> None:
        assert self.built.budget_meter._cap == self.cap


# ---------------------------------------------------------------------------
# build_providers — validation errors (missing credentials)
# ---------------------------------------------------------------------------


class TestBuildProvidersValidation:
    def test_anthropic_missing_api_key_raises_value_error(self) -> None:
        cfg = InferenceConfig(
            orchestrator=_ollama_role(),
            worker=RoleConfig(
                provider=ProviderType.ANTHROPIC,
                model="claude-3-5-haiku-20241022",
                api_key=None,  # missing
            ),
        )
        with pytest.raises(ValueError, match="api_key"):
            build_providers(
                cfg,
                ollama_client=_fake_ollama_client(),
                ollama_model_manager=_fake_model_manager(),
            )

    def test_openai_compat_missing_api_key_raises_value_error(self) -> None:
        cfg = InferenceConfig(
            orchestrator=_ollama_role(),
            worker=RoleConfig(
                provider=ProviderType.OPENAI_COMPATIBLE,
                model="gpt-4o-mini",
                base_url="https://api.openai.com/v1",
                api_key=None,  # missing
            ),
        )
        with pytest.raises(ValueError, match="api_key"):
            build_providers(
                cfg,
                ollama_client=_fake_ollama_client(),
                ollama_model_manager=_fake_model_manager(),
            )

    def test_openai_compat_missing_base_url_raises_value_error(self) -> None:
        cfg = InferenceConfig(
            orchestrator=_ollama_role(),
            worker=RoleConfig(
                provider=ProviderType.OPENAI_COMPATIBLE,
                model="gpt-4o-mini",
                base_url=None,  # missing
                api_key="sk-test",
            ),
        )
        with pytest.raises(ValueError, match="base_url"):
            build_providers(
                cfg,
                ollama_client=_fake_ollama_client(),
                ollama_model_manager=_fake_model_manager(),
            )

    def test_anthropic_empty_api_key_raises_value_error(self) -> None:
        cfg = InferenceConfig(
            orchestrator=_ollama_role(),
            worker=RoleConfig(
                provider=ProviderType.ANTHROPIC,
                model="claude-3-5-haiku-20241022",
                api_key="",  # empty string
            ),
        )
        with pytest.raises(ValueError, match="api_key"):
            build_providers(
                cfg,
                ollama_client=_fake_ollama_client(),
                ollama_model_manager=_fake_model_manager(),
            )


# ---------------------------------------------------------------------------
# build_controller — worker=Ollama → ResourceGovernor
# ---------------------------------------------------------------------------


class TestBuildControllerLocal:
    def test_ollama_worker_returns_resource_governor(self) -> None:
        cfg = InferenceConfig(
            orchestrator=_ollama_role(),
            worker=_ollama_role(),
        )
        gov_settings = _governor_settings()
        ctrl = build_controller(cfg, gov_settings)
        assert isinstance(ctrl, ResourceGovernor)


# ---------------------------------------------------------------------------
# build_controller — worker=cloud → RateLimitController
# ---------------------------------------------------------------------------


class TestBuildControllerCloud:
    def test_anthropic_worker_returns_rate_limit_controller(self) -> None:
        cfg = InferenceConfig(
            orchestrator=_ollama_role(),
            worker=_anthropic_role(),
        )
        ctrl = build_controller(cfg, _governor_settings())
        assert isinstance(ctrl, RateLimitController)

    def test_openai_compat_worker_returns_rate_limit_controller(self) -> None:
        cfg = InferenceConfig(
            orchestrator=_ollama_role(),
            worker=_openai_role(),
        )
        ctrl = build_controller(cfg, _governor_settings())
        assert isinstance(ctrl, RateLimitController)

    def test_limits_propagated_to_rate_limit_controller(self) -> None:
        limits = ProviderLimits(
            requests_per_min=60,
            tokens_per_min=100_000,
            max_in_flight=8,
        )
        cfg = InferenceConfig(
            orchestrator=_ollama_role(),
            worker=_anthropic_role(),
            limits={ProviderType.ANTHROPIC: limits},
        )
        ctrl = build_controller(cfg, _governor_settings())
        assert isinstance(ctrl, RateLimitController)
        # Verify the settings were picked up
        assert ctrl._max_in_flight == 8
        assert ctrl._requests_per_min == 60
        assert ctrl._tokens_per_min == 100_000

    def test_default_limits_used_when_not_specified(self) -> None:
        """When cfg.limits has no entry for the worker provider, ProviderLimits() defaults apply."""
        cfg = InferenceConfig(
            orchestrator=_ollama_role(),
            worker=_anthropic_role(),
            limits={},  # no entry for ANTHROPIC
        )
        ctrl = build_controller(cfg, _governor_settings())
        assert isinstance(ctrl, RateLimitController)
        # ProviderLimits default max_in_flight is 24
        assert ctrl._max_in_flight == 24
