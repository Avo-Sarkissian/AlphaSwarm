"""Tests for /api/settings endpoints (Task 16).

Covers:
- GET /api/settings: returns masked config (no raw key), mode, model lists.
- PUT /api/settings: persists; empty api_key leaves stored key unchanged; 409 mid-run; 400 bad body.
- POST /api/settings/test: {ok:true} on success; {ok:false, error:...} on AuthError; never 500.
- GET /api/settings/estimate: calls = agents*rounds + agents(narratives) + 3; local cfg → $0.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from alphaswarm.config import (
    INFERENCE_CONFIG_PATH,
    InferenceConfig,
    ProviderType,
    RoleConfig,
)
from alphaswarm.errors import AuthError
from alphaswarm.inference.types import InferenceResult, ProviderRole

# ---------------------------------------------------------------------------
# Test app factory
# ---------------------------------------------------------------------------


def _make_settings_test_app() -> FastAPI:
    """Build an isolated FastAPI test app with the settings router registered."""
    from alphaswarm.app import create_app_state
    from alphaswarm.config import AppSettings, generate_personas, load_bracket_configs
    from alphaswarm.web.connection_manager import ConnectionManager
    from alphaswarm.web.replay_manager import ReplayManager
    from alphaswarm.web.routes.settings import router as settings_router
    from alphaswarm.web.simulation_manager import SimulationManager

    @asynccontextmanager
    async def _settings_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        settings = AppSettings(_env_file=None)  # type: ignore[call-arg]
        brackets = load_bracket_configs()
        personas = generate_personas(brackets)
        app_state = create_app_state(settings, personas, with_ollama=False, with_neo4j=False)
        replay_manager = ReplayManager(app_state)
        sim_manager = SimulationManager(app_state, brackets, replay_manager=replay_manager)
        connection_manager = ConnectionManager()

        app.state.app_state = app_state
        app.state.sim_manager = sim_manager
        app.state.replay_manager = replay_manager
        app.state.connection_manager = connection_manager

        yield

        if app_state.graph_manager is not None:
            await app_state.graph_manager.close()

    fapp = FastAPI(title="AlphaSwarm-Settings-Test", lifespan=_settings_lifespan)
    fapp.include_router(settings_router, prefix="/api")
    return fapp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ANTHROPIC_CFG = InferenceConfig(
    orchestrator=RoleConfig(
        provider=ProviderType.ANTHROPIC,
        model="claude-3-5-haiku-20241022",
        api_key="sk-test-orchestrator-key",
    ),
    worker=RoleConfig(
        provider=ProviderType.ANTHROPIC,
        model="claude-3-5-haiku-20241022",
        api_key="sk-test-worker-key",
    ),
)

_LOCAL_CFG = InferenceConfig(
    orchestrator=RoleConfig(provider=ProviderType.OLLAMA, model="local-orch"),
    worker=RoleConfig(provider=ProviderType.OLLAMA, model="local-worker"),
)


def _mock_load_cfg(cfg: InferenceConfig) -> Any:
    """Return a patch target that returns cfg from load_inference_config."""
    return patch(
        "alphaswarm.web.routes.settings.load_inference_config",
        return_value=cfg,
    )


def test_merge_role_drops_key_on_vendor_change() -> None:
    """F-13: changing provider/base_url without a new api_key must NOT carry the
    previous vendor's secret onto the new endpoint."""
    from alphaswarm.web.routes.settings import _merge_role

    stored = RoleConfig(
        provider=ProviderType.OPENAI_COMPATIBLE,
        model="gpt-4o",
        base_url="https://api.openai.com/v1",
        api_key="sk-openai-secret",
    )

    # Apply an Anthropic preset: provider + base_url change, no api_key supplied.
    switched = _merge_role(stored, {"provider": "anthropic", "base_url": None})
    assert switched.api_key is None

    # Same vendor, no key supplied -> stored key preserved.
    same_vendor = _merge_role(stored, {"model": "gpt-4o-mini"})
    assert same_vendor.api_key == "sk-openai-secret"

    # Same vendor, explicit new key -> the new key wins.
    rekeyed = _merge_role(stored, {"api_key": "sk-new"})
    assert rekeyed.api_key == "sk-new"


def _mock_save_cfg() -> Any:
    """Return a patch target that no-ops save_inference_config."""
    return patch("alphaswarm.web.routes.settings.save_inference_config")


def _mock_ollama_list(models: list[str]) -> Any:
    """Patch _local_model_names to return a known list."""
    return patch(
        "alphaswarm.web.routes.settings._local_model_names",
        new=AsyncMock(return_value=models),
    )


# ---------------------------------------------------------------------------
# GET /api/settings
# ---------------------------------------------------------------------------


class TestGetSettings:
    def test_returns_200(self) -> None:
        with _mock_load_cfg(_LOCAL_CFG), _mock_ollama_list([]), TestClient(
            _make_settings_test_app()
        ) as client:
            r = client.get("/api/settings")
        assert r.status_code == 200

    def test_keys_are_masked_no_raw_key(self) -> None:
        """GET must NEVER expose a raw API key in the response."""
        with _mock_load_cfg(_ANTHROPIC_CFG), _mock_ollama_list([]), TestClient(
            _make_settings_test_app()
        ) as client:
            r = client.get("/api/settings")
        data = r.json()
        assert r.status_code == 200

        # Verify no "sk-" value anywhere in the serialized response
        raw = json.dumps(data)
        assert "sk-test-orchestrator-key" not in raw
        assert "sk-test-worker-key" not in raw

        # Mask objects are present
        orch_key = data["config"]["orchestrator"]["api_key"]
        worker_key = data["config"]["worker"]["api_key"]
        assert isinstance(orch_key, dict)
        assert orch_key["set"] is True
        assert orch_key["last4"] == "-key"  # last 4 chars of "sk-test-orchestrator-key"
        assert isinstance(worker_key, dict)
        assert worker_key["set"] is True

    def test_mode_field_present(self) -> None:
        with _mock_load_cfg(_LOCAL_CFG), _mock_ollama_list([]), TestClient(
            _make_settings_test_app()
        ) as client:
            r = client.get("/api/settings")
        data = r.json()
        assert data["mode"] == "local"

    def test_mode_cloud(self) -> None:
        with _mock_load_cfg(_ANTHROPIC_CFG), _mock_ollama_list([]), TestClient(
            _make_settings_test_app()
        ) as client:
            r = client.get("/api/settings")
        data = r.json()
        assert data["mode"] == "cloud"

    def test_available_local_models_from_ollama(self) -> None:
        """When ollama_client is present and list succeeds, models are returned."""
        with (
            _mock_load_cfg(_LOCAL_CFG),
            _mock_ollama_list(["qwen3:8b", "qwen3:14b"]),
            TestClient(_make_settings_test_app()) as client,
        ):
            # Inject a dummy ollama_client so the conditional branch fires
            client.app.state.app_state.ollama_client = MagicMock()
            r = client.get("/api/settings")
        data = r.json()
        assert data["available_local_models"] == ["qwen3:8b", "qwen3:14b"]

    def test_available_local_models_empty_on_failure(self) -> None:
        """If Ollama is down, available_local_models silently returns []."""
        with _mock_load_cfg(_LOCAL_CFG), patch(
            "alphaswarm.web.routes.settings._local_model_names",
            new=AsyncMock(return_value=[]),
        ), TestClient(_make_settings_test_app()) as client:
            # With ollama_client=None (default with_ollama=False), branch skips entirely
            r = client.get("/api/settings")
        assert r.json()["available_local_models"] == []

    def test_known_api_models_is_list_of_strings(self) -> None:
        with _mock_load_cfg(_LOCAL_CFG), _mock_ollama_list([]), TestClient(
            _make_settings_test_app()
        ) as client:
            r = client.get("/api/settings")
        models = r.json()["known_api_models"]
        assert isinstance(models, list)
        assert all(isinstance(m, str) for m in models)
        assert len(models) > 0

    def test_known_api_models_contains_claude_ids(self) -> None:
        with _mock_load_cfg(_LOCAL_CFG), _mock_ollama_list([]), TestClient(
            _make_settings_test_app()
        ) as client:
            r = client.get("/api/settings")
        models = r.json()["known_api_models"]
        assert any("claude" in m for m in models)


# ---------------------------------------------------------------------------
# PUT /api/settings
# ---------------------------------------------------------------------------


class TestPutSettings:
    def test_409_when_sim_running(self) -> None:
        with _mock_load_cfg(_LOCAL_CFG), _mock_save_cfg(), TestClient(
            _make_settings_test_app()
        ) as client:
            # Force simulation to appear running via internal flag
            client.app.state.sim_manager._is_running = True
            r = client.put(
                "/api/settings",
                json={
                    "orchestrator": {"provider": "ollama", "model": "test"},
                    "worker": {"provider": "ollama", "model": "test"},
                },
            )
        assert r.status_code == 409

    def test_400_on_invalid_body(self) -> None:
        """Invalid provider value should yield 400."""
        with _mock_load_cfg(_LOCAL_CFG), _mock_save_cfg(), TestClient(
            _make_settings_test_app()
        ) as client:
            r = client.put(
                "/api/settings",
                json={
                    "orchestrator": {"provider": "bad_provider_xyz", "model": "test"},
                    "worker": {"provider": "ollama", "model": "test"},
                },
            )
        assert r.status_code == 400

    def test_put_persists_and_returns_masked(self, tmp_path: Path) -> None:
        """PUT should call save_inference_config and return masked config."""
        saved_calls: list[InferenceConfig] = []

        def _fake_save(cfg: InferenceConfig, path: Path = INFERENCE_CONFIG_PATH) -> None:
            saved_calls.append(cfg)

        with (
            _mock_load_cfg(_LOCAL_CFG),
            patch(
                "alphaswarm.web.routes.settings.save_inference_config",
                side_effect=_fake_save,
            ),
            TestClient(_make_settings_test_app()) as client,
        ):
            r = client.put(
                "/api/settings",
                json={
                    "orchestrator": {"provider": "ollama", "model": "new-orch"},
                    "worker": {"provider": "ollama", "model": "new-worker"},
                },
            )

        assert r.status_code == 200
        data = r.json()
        assert "config" in data
        assert "mode" in data
        assert data["mode"] == "local"
        assert len(saved_calls) == 1
        assert saved_calls[0].orchestrator.model == "new-orch"
        assert saved_calls[0].worker.model == "new-worker"

    def test_empty_api_key_preserves_stored_key(self, tmp_path: Path) -> None:
        """When api_key is omitted/empty in PUT body, stored key is preserved."""
        stored_cfg = InferenceConfig(
            orchestrator=RoleConfig(
                provider=ProviderType.ANTHROPIC,
                model="claude-3-5-haiku-20241022",
                api_key="stored-key-12345",
            ),
            worker=RoleConfig(
                provider=ProviderType.ANTHROPIC,
                model="claude-3-5-haiku-20241022",
                api_key="stored-worker-key",
            ),
        )

        saved_calls: list[InferenceConfig] = []

        def _fake_save(cfg: InferenceConfig, path: Path = INFERENCE_CONFIG_PATH) -> None:
            saved_calls.append(cfg)

        with (
            _mock_load_cfg(stored_cfg),
            patch(
                "alphaswarm.web.routes.settings.save_inference_config",
                side_effect=_fake_save,
            ),
            TestClient(_make_settings_test_app()) as client,
        ):
            # PUT without api_key field
            r = client.put(
                "/api/settings",
                json={
                    "orchestrator": {
                        "provider": "anthropic",
                        "model": "claude-3-5-haiku-20241022",
                        # api_key deliberately omitted
                    },
                    "worker": {
                        "provider": "anthropic",
                        "model": "claude-3-5-haiku-20241022",
                        "api_key": "",  # empty string → preserve stored
                    },
                },
            )

        assert r.status_code == 200
        assert len(saved_calls) == 1
        # Keys should be preserved from stored_cfg
        assert saved_calls[0].orchestrator.api_key == "stored-key-12345"
        assert saved_calls[0].worker.api_key == "stored-worker-key"

        # Response must not expose raw key
        raw = json.dumps(r.json())
        assert "stored-key-12345" not in raw
        assert "stored-worker-key" not in raw

    def test_422_when_load_raises_value_error(self) -> None:
        """PUT → 422 when load_inference_config raises ValueError (corrupt stored config)."""
        with patch(
            "alphaswarm.web.routes.settings.load_inference_config",
            side_effect=ValueError("corrupt: missing required field"),
        ), TestClient(_make_settings_test_app()) as client:
            r = client.put(
                "/api/settings",
                json={
                    "orchestrator": {"provider": "ollama", "model": "test"},
                    "worker": {"provider": "ollama", "model": "test"},
                },
            )
        assert r.status_code == 422
        assert "stored inference config is invalid" in r.json()["detail"]

    def test_500_when_save_raises_oserror(self) -> None:
        """PUT → 500 when save_inference_config raises OSError (write failure)."""
        with _mock_load_cfg(_LOCAL_CFG), patch(
            "alphaswarm.web.routes.settings.save_inference_config",
            side_effect=OSError("disk full"),
        ), TestClient(_make_settings_test_app()) as client:
            r = client.put(
                "/api/settings",
                json={
                    "orchestrator": {"provider": "ollama", "model": "test"},
                    "worker": {"provider": "ollama", "model": "test"},
                },
            )
        assert r.status_code == 500
        assert "failed to persist settings" in r.json()["detail"]

    def test_whitespace_only_api_key_preserves_stored(self) -> None:
        """Whitespace-only api_key (e.g. '   ') is treated as absent → stored key preserved."""
        stored_cfg = InferenceConfig(
            orchestrator=RoleConfig(
                provider=ProviderType.ANTHROPIC,
                model="claude-3-5-haiku-20241022",
                api_key="stored-key-abc",
            ),
            worker=RoleConfig(
                provider=ProviderType.ANTHROPIC,
                model="claude-3-5-haiku-20241022",
                api_key="stored-worker-abc",
            ),
        )

        saved_calls: list[InferenceConfig] = []

        def _fake_save(cfg: InferenceConfig, path: Path = INFERENCE_CONFIG_PATH) -> None:
            saved_calls.append(cfg)

        with (
            _mock_load_cfg(stored_cfg),
            patch("alphaswarm.web.routes.settings.save_inference_config", side_effect=_fake_save),
            TestClient(_make_settings_test_app()) as client,
        ):
            r = client.put(
                "/api/settings",
                json={
                    "orchestrator": {
                        "provider": "anthropic",
                        "model": "claude-3-5-haiku-20241022",
                        "api_key": "   ",  # whitespace-only → treat as empty
                    },
                    "worker": {
                        "provider": "anthropic",
                        "model": "claude-3-5-haiku-20241022",
                    },
                },
            )

        assert r.status_code == 200
        assert len(saved_calls) == 1
        assert saved_calls[0].orchestrator.api_key == "stored-key-abc"
        assert saved_calls[0].worker.api_key == "stored-worker-abc"

    def test_new_api_key_replaces_stored(self) -> None:
        """When a non-empty api_key is provided it replaces the stored key."""
        stored_cfg = InferenceConfig(
            orchestrator=RoleConfig(
                provider=ProviderType.ANTHROPIC,
                model="claude-3-5-haiku-20241022",
                api_key="old-key",
            ),
            worker=RoleConfig(
                provider=ProviderType.ANTHROPIC,
                model="claude-3-5-haiku-20241022",
                api_key="old-worker-key",
            ),
        )

        saved_calls: list[InferenceConfig] = []

        def _fake_save(cfg: InferenceConfig, path: Path = INFERENCE_CONFIG_PATH) -> None:
            saved_calls.append(cfg)

        with (
            _mock_load_cfg(stored_cfg),
            patch("alphaswarm.web.routes.settings.save_inference_config", side_effect=_fake_save),
            TestClient(_make_settings_test_app()) as client,
        ):
            r = client.put(
                "/api/settings",
                json={
                    "orchestrator": {
                        "provider": "anthropic",
                        "model": "claude-3-5-haiku-20241022",
                        "api_key": "new-key-xyz",
                    },
                    "worker": {
                        "provider": "anthropic",
                        "model": "claude-3-5-haiku-20241022",
                        "api_key": "new-worker-key",
                    },
                },
            )

        assert r.status_code == 200
        assert saved_calls[0].orchestrator.api_key == "new-key-xyz"
        assert saved_calls[0].worker.api_key == "new-worker-key"


# ---------------------------------------------------------------------------
# POST /api/settings/test
# ---------------------------------------------------------------------------


_PING_RESULT = InferenceResult(
    content="pong",
    model="test-model",
    input_tokens=1,
    output_tokens=1,
)


class TestConnectionTest:
    def test_ok_true_on_success(self) -> None:
        """Successful 1-token ping → {ok: true}."""
        from tests.inference.fakes import FakeInferenceProvider

        fake_provider = FakeInferenceProvider(
            role=ProviderRole.ORCHESTRATOR,
            model="test-model",
            scripted=[_PING_RESULT],
            is_local=False,
        )

        with _mock_load_cfg(_ANTHROPIC_CFG), patch(
            "alphaswarm.web.routes.settings._build_single_provider",
            return_value=fake_provider,
        ), TestClient(_make_settings_test_app()) as client:
            r = client.post("/api/settings/test", json={"role": "orchestrator"})

        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data.get("error") is None

    def test_ok_false_on_auth_error(self) -> None:
        """AuthError from the provider → {ok: false, error: message}; never 500."""
        async def _fake_chat(*args: Any, **kwargs: Any) -> InferenceResult:
            raise AuthError(
                "Invalid API key",
                provider="anthropic",
                model="claude-3-5-haiku-20241022",
            )

        fake_provider = MagicMock()
        fake_provider.chat = _fake_chat
        fake_provider.aclose = AsyncMock()

        with _mock_load_cfg(_ANTHROPIC_CFG), patch(
            "alphaswarm.web.routes.settings._build_single_provider",
            return_value=fake_provider,
        ), TestClient(_make_settings_test_app()) as client:
            r = client.post("/api/settings/test", json={"role": "orchestrator"})

        assert r.status_code == 200  # never 500
        data = r.json()
        assert data["ok"] is False
        assert data["error"] is not None
        assert "Invalid API key" in data["error"]

    def test_ok_false_on_inference_error(self) -> None:
        """Any InferenceError → {ok: false}; not a 500."""
        from alphaswarm.errors import InferenceError

        async def _fake_chat(*args: Any, **kwargs: Any) -> InferenceResult:
            raise InferenceError("connection refused", provider="anthropic", model="m")

        fake_provider = MagicMock()
        fake_provider.chat = _fake_chat
        fake_provider.aclose = AsyncMock()

        with _mock_load_cfg(_ANTHROPIC_CFG), patch(
            "alphaswarm.web.routes.settings._build_single_provider",
            return_value=fake_provider,
        ), TestClient(_make_settings_test_app()) as client:
            r = client.post("/api/settings/test", json={"role": "worker"})

        assert r.status_code == 200
        assert r.json()["ok"] is False

    def test_ok_false_on_generic_exception(self) -> None:
        """Any unexpected exception → {ok: false}; never 500."""
        async def _fake_chat(*args: Any, **kwargs: Any) -> InferenceResult:
            raise RuntimeError("unexpected boom")

        fake_provider = MagicMock()
        fake_provider.chat = _fake_chat
        fake_provider.aclose = AsyncMock()

        with _mock_load_cfg(_ANTHROPIC_CFG), patch(
            "alphaswarm.web.routes.settings._build_single_provider",
            return_value=fake_provider,
        ), TestClient(_make_settings_test_app()) as client:
            r = client.post("/api/settings/test", json={"role": "orchestrator"})

        assert r.status_code == 200
        assert r.json()["ok"] is False


# ---------------------------------------------------------------------------
# GET /api/settings/estimate
# ---------------------------------------------------------------------------


class TestGetEstimate:
    def test_calls_count_includes_narratives(self) -> None:
        """calls = agents*rounds + agents(narratives) + 3."""
        with _mock_load_cfg(_LOCAL_CFG), TestClient(_make_settings_test_app()) as client:
            agents = len(client.app.state.app_state.personas)
            rounds = client.app.state.app_state.settings.num_rounds
            r = client.get("/api/settings/estimate")

        assert r.status_code == 200
        data = r.json()
        expected_calls = agents * rounds + agents + 3
        assert data["calls"] == expected_calls

    def test_local_config_zero_cost(self) -> None:
        """Local (OLLAMA) config → cost is $0."""
        with _mock_load_cfg(_LOCAL_CFG), TestClient(_make_settings_test_app()) as client:
            r = client.get("/api/settings/estimate")

        data = r.json()
        assert Decimal(data["low_usd"]) == Decimal("0.00")
        assert Decimal(data["high_usd"]) == Decimal("0.00")
        assert data["mode"] == "local"

    def test_cloud_config_nonzero_cost(self) -> None:
        """Cloud (Anthropic) config → low/high > 0 for known model."""
        with (
            _mock_load_cfg(_ANTHROPIC_CFG),
            TestClient(_make_settings_test_app()) as client,
        ):
            r = client.get("/api/settings/estimate")

        data = r.json()
        assert data["mode"] == "cloud"
        assert Decimal(data["low_usd"]) > Decimal("0.00")
        assert Decimal(data["high_usd"]) > Decimal("0.00")
        assert Decimal(data["low_usd"]) < Decimal(data["high_usd"])

    def test_mode_field_present(self) -> None:
        with _mock_load_cfg(_LOCAL_CFG), TestClient(_make_settings_test_app()) as client:
            r = client.get("/api/settings/estimate")
        assert "mode" in r.json()
