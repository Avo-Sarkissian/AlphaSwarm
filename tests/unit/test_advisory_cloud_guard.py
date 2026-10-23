"""The advisory job honours the cloud-advisory guard (docs/DECISIONS.md#adr-advisory-pipeline).

The job re-checks the config and a refused job records its own error code. The
post-run skip is pinned in tests/test_post_run_pipeline.py.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from alphaswarm.config import (
    AppSettings,
    InferenceConfig,
    OllamaSettings,
    ProviderType,
    RoleConfig,
)
from alphaswarm.holdings.types import Holding, PortfolioSnapshot
from alphaswarm.web.routes import advisory as advisory_route


def _cloud_cfg(*, opt_in: bool) -> InferenceConfig:
    role = RoleConfig(provider=ProviderType.ANTHROPIC, model="claude-fictional", api_key="sk-fictional-4444")
    return InferenceConfig(orchestrator=role, worker=role, allow_cloud_advisory=opt_in)


def _fictional_portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        holdings=(Holding(ticker="ZZZT", qty=Decimal("12.3456"), cost_basis=Decimal("1234.56")),),
        as_of=datetime(2026, 10, 3, tzinfo=UTC),
        account_number_hash="fictional",
    )


def _local_cfg(model: str = "alphaswarm-orchestrator", *, opt_in: bool = False) -> InferenceConfig:
    return InferenceConfig(
        orchestrator=RoleConfig(provider=ProviderType.OLLAMA, model=model),
        worker=RoleConfig(provider=ProviderType.OLLAMA, model="alphaswarm-worker"),
        allow_cloud_advisory=opt_in,
    )


def _ollama_client(*, base_url: str = "http://127.0.0.1:11434", remote: bool | Exception = False) -> MagicMock:
    """A shared OllamaClient stand-in whose /api/show answers *remote* (or raises it)."""
    client = MagicMock(base_url=base_url)
    if isinstance(remote, Exception):
        client.is_remote_model = AsyncMock(side_effect=remote)
    else:
        client.is_remote_model = AsyncMock(return_value=remote)
    return client


class _ReachedError(Exception):
    """Raised by a stubbed build_providers: the job got past every locality check."""


async def test_the_job_refuses_a_cloud_orchestrator_without_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The config can change between the POST and the job: the job checks again."""
    build_providers = MagicMock()
    synthesize = AsyncMock()
    monkeypatch.setattr(advisory_route, "load_inference_config", lambda _s: _cloud_cfg(opt_in=False))
    monkeypatch.setattr(advisory_route, "build_providers", build_providers)
    monkeypatch.setattr(advisory_route, "synthesize", synthesize)
    app_state = SimpleNamespace(
        settings=MagicMock(),
        graph_manager=MagicMock(),
        ollama_client=MagicMock(),
        model_manager=MagicMock(),
    )

    with pytest.raises(advisory_route.CloudAdvisoryDisabledError):
        await advisory_route._run_advisory_synthesis(
            app_state,
            "cycle-1",
            _fictional_portfolio(),  # type: ignore[arg-type]
        )

    build_providers.assert_not_called()
    synthesize.assert_not_awaited()


async def test_the_job_refuses_a_remote_ollama_orchestrator_without_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The job checks the host the shared client really connects to, not the settings."""
    build_providers = MagicMock()
    synthesize = AsyncMock()
    monkeypatch.setattr(advisory_route, "load_inference_config", lambda _s: _local_cfg())
    monkeypatch.setattr(advisory_route, "build_providers", build_providers)
    monkeypatch.setattr(advisory_route, "synthesize", synthesize)
    app_state = SimpleNamespace(
        settings=AppSettings(  # type: ignore[call-arg]
            _env_file=None, ollama=OllamaSettings(base_url="http://127.0.0.1:11434")
        ),
        graph_manager=MagicMock(),
        ollama_client=_ollama_client(base_url="http://192.168.1.20:11434"),
        model_manager=MagicMock(),
    )

    with pytest.raises(advisory_route.CloudAdvisoryDisabledError):
        await advisory_route._run_advisory_synthesis(
            app_state,
            "cycle-1",
            _fictional_portfolio(),  # type: ignore[arg-type]
        )

    build_providers.assert_not_called()
    synthesize.assert_not_awaited()


@pytest.mark.parametrize(
    "remote",
    [True, ConnectionError("ollama down"), ValueError("unexpected /api/show response shape")],
    ids=["server-says-remote", "show-failed", "show-unreadable"],
)
async def test_the_job_refuses_when_the_server_runs_the_model_remotely(
    monkeypatch: pytest.MonkeyPatch, remote: bool | Exception
) -> None:
    """An alias whose Modelfile is FROM a cloud model has a local-looking name, so
    the job asks the server; when it cannot tell, it fails closed."""
    build_providers = MagicMock()
    synthesize = AsyncMock()
    monkeypatch.setattr(advisory_route, "load_inference_config", lambda _s: _local_cfg())
    monkeypatch.setattr(advisory_route, "build_providers", build_providers)
    monkeypatch.setattr(advisory_route, "synthesize", synthesize)
    client = _ollama_client(remote=remote)
    app_state = SimpleNamespace(
        settings=MagicMock(),
        graph_manager=MagicMock(),
        ollama_client=client,
        model_manager=MagicMock(),
    )

    with pytest.raises(advisory_route.CloudAdvisoryDisabledError):
        await advisory_route._run_advisory_synthesis(
            app_state,
            "cycle-1",
            _fictional_portfolio(),  # type: ignore[arg-type]
        )

    client.is_remote_model.assert_awaited_once_with("alphaswarm-orchestrator")
    build_providers.assert_not_called()
    synthesize.assert_not_awaited()


async def test_the_job_runs_when_the_server_confirms_a_local_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(advisory_route, "load_inference_config", lambda _s: _local_cfg())
    monkeypatch.setattr(advisory_route, "build_providers", MagicMock(side_effect=_ReachedError))
    app_state = SimpleNamespace(
        settings=MagicMock(),
        graph_manager=MagicMock(),
        ollama_client=_ollama_client(remote=False),
        model_manager=MagicMock(),
    )

    with pytest.raises(_ReachedError):
        await advisory_route._run_advisory_synthesis(
            app_state,
            "cycle-1",
            _fictional_portfolio(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "cfg",
    [_local_cfg("gpt-oss:120b-cloud", opt_in=True), _cloud_cfg(opt_in=True)],
    ids=["ollama-cloud-model-opted-in", "cloud-provider-opted-in"],
)
async def test_the_opt_in_skips_the_server_check(monkeypatch: pytest.MonkeyPatch, cfg: InferenceConfig) -> None:
    monkeypatch.setattr(advisory_route, "load_inference_config", lambda _s: cfg)
    monkeypatch.setattr(advisory_route, "build_providers", MagicMock(side_effect=_ReachedError))
    client = _ollama_client(remote=True)
    app_state = SimpleNamespace(
        settings=MagicMock(),
        graph_manager=MagicMock(),
        ollama_client=client,
        model_manager=MagicMock(),
    )

    with pytest.raises(_ReachedError):
        await advisory_route._run_advisory_synthesis(
            app_state,
            "cycle-1",
            _fictional_portfolio(),  # type: ignore[arg-type]
        )

    client.is_remote_model.assert_not_awaited()


async def test_a_refused_job_records_the_cloud_advisory_code() -> None:
    async def _refused() -> None:
        raise advisory_route.CloudAdvisoryDisabledError("cloud orchestrator, no opt-in")

    task: asyncio.Task[None] = asyncio.get_running_loop().create_task(_refused())
    await asyncio.wait({task})
    app = FastAPI()

    advisory_route._on_advisory_task_done(task, "cycle-1", app)

    assert app.state.advisory_generation_error["cycle-1"]["error"] == "cloud_advisory_disabled"
