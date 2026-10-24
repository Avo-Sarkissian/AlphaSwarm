"""InferenceRuntime.run_provenance and open_simulation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest
from ollama import ListResponse

from alphaswarm.graph import GraphStateManager
from alphaswarm.inference.budget import BudgetMeter
from alphaswarm.inference.config import (
    InferenceConfig,
    ProviderType,
    RoleConfig,
    default_inference_config,
)
from alphaswarm.inference.factory import BuiltProviders
from alphaswarm.inference.types import ProviderRole
from alphaswarm.manifest import ModelRef, RunProvenance
from alphaswarm.services.runtime import InferenceRuntime, build_runtime, open_simulation
from alphaswarm.settings import AppSettings
from tests.inference.fakes import FakeInferenceProvider

DIGEST_W = "sha256:" + "1" * 64
DIGEST_O = "sha256:" + "2" * 64


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings(_env_file=None, inference_config_path=tmp_path / "inference.json")  # type: ignore[call-arg]


def _ollama_client() -> MagicMock:
    client = MagicMock()
    client.raw_client.list = AsyncMock(
        return_value=ListResponse(
            models=[
                ListResponse.Model(model="alphaswarm-worker:latest", digest=DIGEST_W),
                ListResponse.Model(model="alphaswarm-orchestrator:latest", digest=DIGEST_O),
            ]
        )
    )
    return client


def _built(orchestrator_model: str, worker_model: str, *, worker_local: bool = True) -> BuiltProviders:
    return BuiltProviders(
        orchestrator=FakeInferenceProvider(ProviderRole.ORCHESTRATOR, orchestrator_model, scripted=[]),
        worker=FakeInferenceProvider(ProviderRole.WORKER, worker_model, scripted=[], is_local=worker_local),
        budget_meter=BudgetMeter(None, {}),
    )


async def test_local_roles_report_ollama_and_their_digests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)
    runtime = InferenceRuntime(settings, ollama_client=_ollama_client(), model_manager=None)
    monkeypatch.setattr(runtime, "config", AsyncMock(return_value=default_inference_config(settings)))

    prov = await runtime.run_provenance(_built("alphaswarm-orchestrator", "alphaswarm-worker"))

    assert prov == RunProvenance(
        orchestrator=ModelRef(provider="ollama", model="alphaswarm-orchestrator", digest=DIGEST_O),
        worker=ModelRef(provider="ollama", model="alphaswarm-worker", digest=DIGEST_W),
        inference_mode="local",
    )


async def test_a_cloud_role_reports_its_exact_type_and_no_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = InferenceConfig(
        orchestrator=RoleConfig(provider=ProviderType.OLLAMA, model="alphaswarm-orchestrator"),
        worker=RoleConfig(
            provider=ProviderType.OPENAI_COMPATIBLE,
            model="fictional-cloud-worker",
            base_url="https://example.invalid/v1",
            api_key="fake-key-for-tests",
        ),
    )
    client = _ollama_client()
    runtime = InferenceRuntime(_settings(tmp_path), ollama_client=client, model_manager=None)
    monkeypatch.setattr(runtime, "config", AsyncMock(return_value=cfg))

    prov = await runtime.run_provenance(_built("alphaswarm-orchestrator", "fictional-cloud-worker", worker_local=False))

    assert prov.worker == ModelRef(provider="openai_compatible", model="fictional-cloud-worker")
    assert prov.orchestrator.digest == DIGEST_O
    assert prov.inference_mode == "mixed"
    assert client.raw_client.list.await_count == 1  # only the Ollama role is looked up


async def test_without_an_ollama_client_digests_are_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)
    runtime = InferenceRuntime(settings, ollama_client=None, model_manager=None)
    monkeypatch.setattr(runtime, "config", AsyncMock(return_value=default_inference_config(settings)))

    prov = await runtime.run_provenance(_built("alphaswarm-orchestrator", "alphaswarm-worker"))

    assert (prov.orchestrator.digest, prov.worker.digest) == (None, None)
    assert prov.orchestrator.provider == "ollama"


async def test_open_simulation_puts_the_provenance_on_the_deps(tmp_path: Path) -> None:
    runtime = build_runtime(_settings(tmp_path), with_ollama=False, with_neo4j=False)
    runtime.app_state.graph_manager = create_autospec(GraphStateManager, instance=True)
    built = _built("alphaswarm-orchestrator", "alphaswarm-worker")
    for provider in (built.orchestrator, built.worker):
        provider.aclose = AsyncMock()  # type: ignore[method-assign]
    provenance = RunProvenance(
        orchestrator=ModelRef(provider="ollama", model="alphaswarm-orchestrator", digest=DIGEST_O),
        worker=ModelRef(provider="ollama", model="alphaswarm-worker", digest=DIGEST_W),
        inference_mode="local",
    )
    inference = MagicMock()
    inference.open_operation = AsyncMock(return_value=built)
    inference.build_controller = AsyncMock(return_value=object())
    inference.run_provenance = AsyncMock(return_value=provenance)

    async with open_simulation(inference, runtime.app_state, state=None) as deps:
        assert deps.provenance is provenance

    inference.run_provenance.assert_awaited_once_with(built)
