"""InferenceRuntime: one cached config, per-operation providers."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import alphaswarm.inference.config as config_module
import alphaswarm.telemetry as telemetry_module
from alphaswarm.errors import (
    INFERENCE_CONFIG_INCOMPLETE_MESSAGE,
    InferenceConfigError,
    InferenceConfigIncompleteError,
)
from alphaswarm.governor import ResourceGovernor
from alphaswarm.inference.config import (
    InferenceConfig,
    ProviderType,
    RoleConfig,
    default_inference_config,
    save_inference_config,
)
from alphaswarm.inference.ollama_provider import OllamaProvider
from alphaswarm.inference.types import ProviderRole
from alphaswarm.ollama_models import OllamaModelManager
from alphaswarm.services.runtime import InferenceRuntime
from alphaswarm.settings import AppSettings
from alphaswarm.state import StateStore
from tests.support.web_app import route_test_settings


def _runtime(settings: AppSettings) -> InferenceRuntime:
    return InferenceRuntime(settings, ollama_client=MagicMock(name="OllamaClient"), model_manager=None)


def _bump(path: Path) -> None:
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))


async def test_config_is_cached_until_the_file_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = route_test_settings(tmp_path)
    save_inference_config(default_inference_config(settings), settings.inference_config_path)
    loads: list[int] = []
    real = config_module.load_inference_config

    def _counting(app_settings: AppSettings, path: Path | None = None) -> InferenceConfig:
        loads.append(1)
        return real(app_settings, path)

    monkeypatch.setattr(config_module, "load_inference_config", _counting)
    runtime = _runtime(settings)
    first = await runtime.config()
    assert await runtime.config() is first
    assert len(loads) == 1
    cloud = InferenceConfig(
        orchestrator=RoleConfig(provider=ProviderType.ANTHROPIC, model="claude-test", api_key="sk-x"),
        worker=RoleConfig(provider=ProviderType.OLLAMA, model="alphaswarm-worker"),
    )
    save_inference_config(cloud, settings.inference_config_path)
    _bump(settings.inference_config_path)
    assert (await runtime.config()).orchestrator.provider is ProviderType.ANTHROPIC
    assert await runtime.mode() == "mixed"
    assert len(loads) == 2


async def test_missing_file_means_local_defaults(tmp_path: Path) -> None:
    runtime = _runtime(route_test_settings(tmp_path))
    assert await runtime.mode() == "local"


async def test_invalid_config_raises_without_a_path(tmp_path: Path) -> None:
    settings = route_test_settings(tmp_path)
    settings.inference_config_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(InferenceConfigError) as exc:
        await _runtime(settings).config()
    assert str(tmp_path) not in str(exc.value)


async def test_open_operation_builds_both_roles_with_a_fresh_meter(tmp_path: Path) -> None:
    runtime = _runtime(route_test_settings(tmp_path))
    first = await runtime.open_operation("report")
    second = await runtime.open_operation("advisory")
    assert isinstance(first.orchestrator, OllamaProvider)
    assert first.orchestrator.role is ProviderRole.ORCHESTRATOR
    assert first.budget_meter is not second.budget_meter
    assert runtime.last_meter is second.budget_meter


async def test_incomplete_cloud_role_is_a_config_error(tmp_path: Path) -> None:
    settings = route_test_settings(tmp_path)
    keyless = InferenceConfig(
        orchestrator=RoleConfig(provider=ProviderType.ANTHROPIC, model="claude-test"),
        worker=RoleConfig(provider=ProviderType.OLLAMA, model="alphaswarm-worker"),
    )
    save_inference_config(keyless, settings.inference_config_path)
    runtime = _runtime(settings)
    with pytest.raises(InferenceConfigError):
        await runtime.open_operation("report")
    worker = await runtime.open_role(ProviderRole.WORKER, "interview")  # only the worker is built
    assert worker.role is ProviderRole.WORKER


async def test_build_controller_is_the_governor_locally(tmp_path: Path) -> None:
    controller = await _runtime(route_test_settings(tmp_path)).build_controller(StateStore())
    assert isinstance(controller, ResourceGovernor)


async def test_incomplete_role_raises_the_fixed_settings_message(tmp_path: Path) -> None:
    settings = route_test_settings(tmp_path)
    keyless = InferenceConfig(
        orchestrator=RoleConfig(provider=ProviderType.ANTHROPIC, model="claude-test"),
        worker=RoleConfig(provider=ProviderType.OLLAMA, model="alphaswarm-worker"),
    )
    save_inference_config(keyless, settings.inference_config_path)
    with pytest.raises(InferenceConfigIncompleteError) as exc:
        await _runtime(settings).open_role(ProviderRole.ORCHESTRATOR, "settings_test")
    assert str(exc.value) == INFERENCE_CONFIG_INCOMPLETE_MESSAGE
    assert exc.value.__cause__ is None and exc.value.__suppress_context__


def test_ollama_client_is_the_injected_client(tmp_path: Path) -> None:
    settings = route_test_settings(tmp_path)
    assert InferenceRuntime(settings, ollama_client=None, model_manager=None).ollama_client is None
    client = object()
    runtime = InferenceRuntime(settings, ollama_client=client, model_manager=None)  # type: ignore[arg-type]
    assert runtime.ollama_client is client


async def test_local_controller_gets_the_transition_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telemetry_module, "docker_vm_rss_mb", lambda: 512.0)
    settings = AppSettings(_env_file=None, inference_config_path=tmp_path / "inference.json")
    manager = MagicMock(spec=OllamaModelManager)
    manager.loaded_models = AsyncMock(return_value=["alphaswarm-worker"])
    runtime = InferenceRuntime(settings, ollama_client=None, model_manager=manager)
    controller = await runtime.build_controller(StateStore())
    assert isinstance(controller, ResourceGovernor)
    assert controller.transition_probe is not None
    assert await controller.transition_probe() == {
        "loaded_models": "alphaswarm-worker",
        "docker_vm_rss_mb": 512.0,
    }
