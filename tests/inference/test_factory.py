"""Tests for inference.factory — provider + controller factory from InferenceConfig.

TDD cycle: tests written first (RED), factory implemented second (GREEN).
All tests are purely constructive — no network, no Ollama, no real LLM calls.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from alphaswarm.governor import ResourceGovernor
from alphaswarm.inference import (
    RateLimitController,
)
from alphaswarm.inference.anthropic_provider import AnthropicProvider
from alphaswarm.inference.budget import BudgetTrackingProvider
from alphaswarm.inference.caps import ANTHROPIC_WORKER_DEFAULT_MAX_TOKENS
from alphaswarm.inference.config import InferenceConfig, ProviderLimits, ProviderType, RoleConfig
from alphaswarm.inference.factory import (
    BuiltProviders,
    advisory_allowed,
    advisory_block_reason,
    attach_retry_gate,
    build_controller,
    build_providers,
    effective_ollama_host,
    inference_mode,
    is_cloud_ollama_model,
    is_local_ollama,
    is_loopback_url,
    preflight_cloud_roles,
)
from alphaswarm.inference.ollama_provider import OllamaProvider
from alphaswarm.inference.openai_provider import OpenAICompatProvider
from alphaswarm.settings import GovernorSettings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_LOCAL_OLLAMA = "http://localhost:11434"


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


def _governor_settings() -> GovernorSettings:
    """Default GovernorSettings (the governor reads real field values)."""
    return GovernorSettings()


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

    def test_only_the_worker_cleans_state_before_loading(self) -> None:
        assert isinstance(self.built.worker, OllamaProvider)
        assert isinstance(self.built.orchestrator, OllamaProvider)
        assert self.built.worker.clean_state_on_prepare is True
        assert self.built.orchestrator.clean_state_on_prepare is False


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

    def test_anthropic_worker_default_cap(self) -> None:
        inner = self.built.worker._inner  # type: ignore[union-attr]
        assert inner._max_tokens_default == ANTHROPIC_WORKER_DEFAULT_MAX_TOKENS == 512

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
    def test_tpm_reservation_comes_from_the_limits(self) -> None:
        cfg = InferenceConfig(
            orchestrator=_ollama_role(),
            worker=_anthropic_role(),
            limits={ProviderType.ANTHROPIC: ProviderLimits(tokens_per_min=100_000, avg_tokens_per_call=900)},
        )
        ctrl = build_controller(cfg, _governor_settings())
        assert isinstance(ctrl, RateLimitController)
        assert ctrl._avg_tokens_per_call == 900

    def test_tpm_reservation_defaults_to_1500(self) -> None:
        cfg = InferenceConfig(orchestrator=_ollama_role(), worker=_anthropic_role())
        ctrl = build_controller(cfg, _governor_settings())
        assert ctrl._avg_tokens_per_call == 1500  # type: ignore[attr-defined]

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


# ---------------------------------------------------------------------------
# advisory_allowed (docs/DECISIONS.md#adr-advisory-pipeline): no portfolio to a cloud orchestrator
# without the explicit opt-in
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("orchestrator", "worker", "opt_in", "allowed"),
    [
        (_ollama_role(), _ollama_role(), False, True),
        (_ollama_role(), _anthropic_role(), False, True),  # mixed, local orchestrator
        (_anthropic_role(), _ollama_role(), False, False),  # mixed, cloud orchestrator
        (_anthropic_role(), _anthropic_role(), False, False),
        (_openai_role(), _openai_role(), False, False),
        (_anthropic_role(), _anthropic_role(), True, True),
    ],
    ids=["local", "mixed-local-orch", "mixed-cloud-orch", "cloud", "openai", "cloud-opted-in"],
)
def test_advisory_allowed(orchestrator: RoleConfig, worker: RoleConfig, opt_in: bool, allowed: bool) -> None:
    cfg = InferenceConfig(orchestrator=orchestrator, worker=worker, allow_cloud_advisory=opt_in)
    assert advisory_allowed(cfg, ollama_base_url=_LOCAL_OLLAMA) is allowed


# An Ollama orchestrator is local only when its model runs on this machine and the
# server it talks to is on loopback. An Ollama cloud model ("-cloud" / ":cloud" tag)
# or a remote Ollama host sends the portfolio off the machine, so it needs the same
# opt-in as a cloud provider.


@pytest.mark.parametrize(
    ("model", "cloud"),
    [
        ("alphaswarm-orchestrator", False),
        ("qwen3.6:27b-nvfp4", False),
        ("llama3.1:8b", False),
        ("cloudy-model:7b", False),  # "cloud" inside the name is not a cloud tag
        ("cloud", True),  # a bare "cloud" name fails closed
        ("word-cloud-gen:7b", True),  # a "cloud" part of the name fails closed
        ("gpt-oss:120b-cloud", True),
        ("qwen3-coder:480b-cloud", True),
        ("glm-4.6:cloud", True),
        ("GPT-OSS:120B-CLOUD", True),
        ("  gpt-oss:20b-cloud  ", True),
        ("library/deepseek-v3.1:671b-cloud", True),
        ("gpt-oss:120b-cloud@sha256:abc123", True),
        ("my-model-cloud", True),  # untagged name with a -cloud suffix fails closed
        ("my-model-cloud:latest", True),  # same model as "my-model-cloud"
        ("qwen3:cloud-preview", True),  # a "cloud" part of the tag
        ("cloud_model:7b", False),  # only dash- or colon-separated parts count
        ("qwen3:7b-cloudless", False),
    ],
)
def test_is_cloud_ollama_model(model: str, cloud: bool) -> None:
    assert is_cloud_ollama_model(model) is cloud


@pytest.mark.parametrize(
    ("url", "loopback"),
    [
        ("http://localhost:11434", True),
        ("http://LOCALHOST:11434", True),
        ("localhost:11434", True),
        ("http://127.0.0.1:11434", True),
        ("http://127.8.9.10:11434", True),
        ("127.0.0.1", True),
        ("http://[::1]:11434", True),
        ("[::1]:11434", True),
        ("http://[::ffff:127.0.0.1]:11434", True),
        (":11434", True),  # ollama reads an empty host as 127.0.0.1
        ("http://192.168.1.20:11434", False),
        ("http://10.0.0.5:11434", False),
        ("http://0.0.0.0:11434", False),  # a bind address, not loopback: fail closed
        ("https://ollama.com", False),
        ("http://gpu-box.local:11434", False),
        ("http://localhost.evil.example:11434", False),
        ("http://127.0.0.1.nip.io:11434", False),
        ("http://user@remote.example:11434", False),
        ("http://[2001:db8::1]:11434", False),
        ("http://localhost:notaport", False),  # unparseable fails closed
    ],
)
def test_is_loopback_url(url: str, loopback: bool) -> None:
    assert is_loopback_url(url) is loopback


def test_effective_ollama_host_mirrors_the_ollama_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """ollama.AsyncClient uses ``host or OLLAMA_HOST`` and then 127.0.0.1:11434."""
    monkeypatch.setenv("OLLAMA_HOST", "http://gpu-box.local:11434")
    assert effective_ollama_host("http://localhost:11434") == "http://localhost:11434"
    assert effective_ollama_host("") == "http://gpu-box.local:11434"
    assert effective_ollama_host(None) == "http://gpu-box.local:11434"
    monkeypatch.delenv("OLLAMA_HOST")
    assert is_loopback_url(effective_ollama_host(None))
    assert is_loopback_url(effective_ollama_host(""))


@pytest.mark.parametrize(
    ("model", "base_url", "local"),
    [
        ("alphaswarm-orchestrator", "http://localhost:11434", True),
        ("alphaswarm-orchestrator", "http://192.168.1.20:11434", False),
        ("gpt-oss:120b-cloud", "http://localhost:11434", False),
        ("gpt-oss:120b-cloud", "http://192.168.1.20:11434", False),
    ],
)
def test_is_local_ollama(model: str, base_url: str, local: bool) -> None:
    assert is_local_ollama(model, base_url) is local


def test_is_local_ollama_follows_ollama_host_when_base_url_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "10.0.0.5:11434")
    assert is_local_ollama("alphaswarm-orchestrator", "") is False
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11434")
    assert is_local_ollama("alphaswarm-orchestrator", "") is True


@pytest.mark.parametrize(
    ("orchestrator", "ollama_base_url", "opt_in", "allowed"),
    [
        (_ollama_role(), _LOCAL_OLLAMA, False, True),
        (_ollama_role("gpt-oss:120b-cloud"), _LOCAL_OLLAMA, False, False),
        (_ollama_role("glm-4.6:cloud"), _LOCAL_OLLAMA, False, False),
        (_ollama_role(), "http://192.168.1.20:11434", False, False),
        (_ollama_role(), "https://ollama.com", False, False),
        # The role's own base_url is checked too, so a remote one fails closed even
        # though OllamaProvider sends to the shared client's host today.
        (
            RoleConfig(
                provider=ProviderType.OLLAMA,
                model="alphaswarm-orchestrator",
                base_url="http://gpu-box.local:11434",
            ),
            _LOCAL_OLLAMA,
            False,
            False,
        ),
        (
            RoleConfig(
                provider=ProviderType.OLLAMA,
                model="alphaswarm-orchestrator",
                base_url="http://127.0.0.1:11434",
            ),
            _LOCAL_OLLAMA,
            False,
            True,
        ),
        (_ollama_role("gpt-oss:120b-cloud"), _LOCAL_OLLAMA, True, True),
        (_ollama_role(), "http://192.168.1.20:11434", True, True),
    ],
    ids=[
        "local",
        "cloud-model-dash",
        "cloud-model-colon",
        "remote-host",
        "ollama-com",
        "remote-role-base-url",
        "loopback-role-base-url",
        "cloud-model-opted-in",
        "remote-host-opted-in",
    ],
)
def test_advisory_allowed_treats_cloud_or_remote_ollama_as_cloud(
    orchestrator: RoleConfig, ollama_base_url: str, opt_in: bool, allowed: bool
) -> None:
    cfg = InferenceConfig(orchestrator=orchestrator, worker=_ollama_role(), allow_cloud_advisory=opt_in)
    assert advisory_allowed(cfg, ollama_base_url=ollama_base_url) is allowed


@pytest.mark.parametrize(
    ("orchestrator", "ollama_base_url", "opt_in", "reason"),
    [
        (_ollama_role(), _LOCAL_OLLAMA, False, None),
        (_anthropic_role(), _LOCAL_OLLAMA, False, "cloud_provider"),
        (_ollama_role("gpt-oss:120b-cloud"), _LOCAL_OLLAMA, False, "cloud_model"),
        (_ollama_role(), "http://192.168.1.20:11434", False, "remote_host"),
        (
            RoleConfig(
                provider=ProviderType.OLLAMA,
                model="alphaswarm-orchestrator",
                base_url="http://gpu-box.local:11434",
            ),
            _LOCAL_OLLAMA,
            False,
            "role_base_url_remote",
        ),
        (_anthropic_role(), "http://192.168.1.20:11434", True, None),
    ],
    ids=["local", "cloud-provider", "cloud-model", "remote-host", "role-base-url", "opted-in"],
)
def test_advisory_block_reason_names_the_failed_check(
    orchestrator: RoleConfig, ollama_base_url: str, opt_in: bool, reason: str | None
) -> None:
    """The reason goes into the refusal log, so the user knows which setting to fix."""
    cfg = InferenceConfig(orchestrator=orchestrator, worker=_ollama_role(), allow_cloud_advisory=opt_in)
    assert advisory_block_reason(cfg, ollama_base_url=ollama_base_url) == reason
    assert advisory_allowed(cfg, ollama_base_url=ollama_base_url) is (reason is None)


class TestBuildRoleProvider:
    def test_builds_only_the_requested_role(self) -> None:
        from alphaswarm.inference.config import InferenceConfig, ProviderType, RoleConfig
        from alphaswarm.inference.factory import build_role_provider
        from alphaswarm.inference.ollama_provider import OllamaProvider
        from alphaswarm.inference.types import ProviderRole

        cfg = InferenceConfig(
            orchestrator=RoleConfig(provider=ProviderType.ANTHROPIC, model="claude-test"),  # no key
            worker=RoleConfig(provider=ProviderType.OLLAMA, model="alphaswarm-worker"),
        )
        worker = build_role_provider(
            cfg,
            ProviderRole.WORKER,
            ollama_client=object(),
            ollama_model_manager=None,
        )
        assert isinstance(worker, OllamaProvider)
        assert (worker.role, worker.model) == (ProviderRole.WORKER, "alphaswarm-worker")


class TestTypedFactory:
    """Factory parameters are typed; a missing Ollama client fails at build time."""

    def test_cloud_only_config_builds_without_ollama_client(self) -> None:
        cfg = InferenceConfig(orchestrator=_anthropic_role(), worker=_openai_role())

        built = build_providers(cfg, ollama_client=None, ollama_model_manager=None)

        assert not built.orchestrator.is_local()
        assert not built.worker.is_local()

    def test_local_role_without_ollama_client_raises_clear_error(self) -> None:
        cfg = InferenceConfig(orchestrator=_anthropic_role(), worker=_ollama_role())

        with pytest.raises(ValueError, match="requires a running Ollama client") as exc_info:
            build_providers(cfg, ollama_client=None, ollama_model_manager=None)
        assert "'worker'" in str(exc_info.value)
        assert "sk-" not in str(exc_info.value)

    def test_parameters_carry_real_types(self) -> None:
        import inspect

        from alphaswarm.inference import factory

        for fn in (factory.build_providers, factory.build_role_provider):
            params = inspect.signature(fn).parameters
            assert params["ollama_client"].annotation == "OllamaClient | None", fn
            assert params["ollama_model_manager"].annotation == "OllamaModelManager | None", fn
        controller = inspect.signature(factory.build_controller).parameters
        assert controller["governor_settings"].annotation == "GovernorSettings"
        assert controller["state_store"].annotation == "StateStore | None"
        assert "Lazy import avoids circular dependency" not in inspect.getsource(factory)


def test_anthropic_receives_max_retries_from_limits() -> None:
    """The Anthropic path used to ignore ProviderLimits.max_retries."""
    cfg = InferenceConfig(
        orchestrator=_ollama_role(),
        worker=_anthropic_role(),
        limits={ProviderType.ANTHROPIC: ProviderLimits(max_retries=8)},
    )
    built = build_providers(cfg, ollama_client=_fake_ollama_client(), ollama_model_manager=_fake_model_manager())
    inner = built.worker._inner  # type: ignore[union-attr]
    assert isinstance(inner, AnthropicProvider)
    assert inner._max_retries == 8


class TestAttachRetryGate:
    """Retries share the cloud controller's cooldown and RPM bucket (docs/DECISIONS.md#adr-cloud-retry)."""

    @staticmethod
    def _gate() -> RateLimitController:
        return RateLimitController(max_in_flight=1, requests_per_min=40, tokens_per_min=None)

    @staticmethod
    def _built(cfg: InferenceConfig) -> BuiltProviders:
        return build_providers(cfg, ollama_client=_fake_ollama_client(), ollama_model_manager=_fake_model_manager())

    def test_worker_and_same_vendor_orchestrator_share_the_gate(self) -> None:
        cfg = InferenceConfig(orchestrator=_openai_role("gpt-4o"), worker=_openai_role())
        built, gate = self._built(cfg), self._gate()
        assert attach_retry_gate(built, cfg, gate) == 2
        assert built.worker.inner.retry_gate is gate  # type: ignore[attr-defined]
        assert built.orchestrator.inner.retry_gate is gate  # type: ignore[attr-defined]

    def test_orchestrator_on_another_vendor_keeps_its_own_pacing(self) -> None:
        cfg = InferenceConfig(orchestrator=_anthropic_role(), worker=_openai_role())
        built = self._built(cfg)
        assert attach_retry_gate(built, cfg, self._gate()) == 1
        assert built.orchestrator.inner.retry_gate is None  # type: ignore[attr-defined]

    def test_local_roles_are_skipped(self) -> None:
        cfg = InferenceConfig(orchestrator=_ollama_role(), worker=_openai_role())
        assert attach_retry_gate(self._built(cfg), cfg, self._gate()) == 1


async def test_preflight_cloud_roles_prepares_only_cloud_providers() -> None:
    from unittest.mock import AsyncMock

    from alphaswarm.inference.budget import BudgetMeter
    from alphaswarm.inference.types import ProviderRole
    from tests.inference.fakes import FakeInferenceProvider

    local = FakeInferenceProvider(ProviderRole.ORCHESTRATOR, "alphaswarm-orchestrator", scripted=[])
    cloud = FakeInferenceProvider(ProviderRole.WORKER, "gpt-4o-mini", scripted=[], is_local=False)
    local.prepare = AsyncMock()  # type: ignore[method-assign]
    cloud.prepare = AsyncMock()  # type: ignore[method-assign]
    await preflight_cloud_roles(BuiltProviders(orchestrator=local, worker=cloud, budget_meter=BudgetMeter(None, {})))
    local.prepare.assert_not_awaited()
    cloud.prepare.assert_awaited_once()
