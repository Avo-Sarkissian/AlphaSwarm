"""Runtime assembly: no-I/O build, one composition root, ordered teardown."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest
from neo4j.exceptions import AuthError as Neo4jAuthError
from neo4j.exceptions import ServiceUnavailable

import alphaswarm.app as app_module
import alphaswarm.services.runtime as runtime_module
from alphaswarm.app import AppState
from alphaswarm.errors import Neo4jUnavailableError
from alphaswarm.graph import GraphStateManager
from alphaswarm.inference.budget import BudgetMeter
from alphaswarm.inference.factory import BuiltProviders
from alphaswarm.inference.types import ProviderRole
from alphaswarm.ingestion import RSSNewsProvider, YFinanceMarketDataProvider
from alphaswarm.ollama_client import OllamaClient
from alphaswarm.services.runtime import Runtime, build_runtime, open_runtime, open_simulation
from alphaswarm.state import JobStatus
from tests.inference.fakes import FakeInferenceProvider
from tests.support.web_app import route_test_settings


def test_build_runtime_does_no_io_and_wires_providers(tmp_path: Path) -> None:
    runtime = build_runtime(route_test_settings(tmp_path), with_ollama=False, with_neo4j=False)
    assert isinstance(runtime, Runtime)
    assert runtime.neo4j_ready is False
    state = runtime.app_state
    assert state.graph_manager is None and state.ollama_client is None
    assert isinstance(state.market_provider, YFinanceMarketDataProvider)
    assert isinstance(state.news_provider, RSSNewsProvider)
    assert len(state.personas) == 100
    state.state_store.set_job_status("report", JobStatus("running", "c"))
    assert runtime.jobs.is_busy()  # the runner reads the same store


def test_app_state_declares_telemetry_fields_and_does_not_configure_logging(tmp_path: Path) -> None:
    state = build_runtime(route_test_settings(tmp_path), with_ollama=False, with_neo4j=False).app_state
    assert state.budget_meter is None and state.inference_mode == "local"
    assert not hasattr(app_module, "configure_logging")
    assert "budget_meter" in AppState.__dataclass_fields__


def _faked(tmp_path: Path, events: list[str]) -> Runtime:
    runtime = build_runtime(route_test_settings(tmp_path), with_ollama=False, with_neo4j=False)
    graph = create_autospec(GraphStateManager, instance=True)
    graph.close.side_effect = lambda: events.append("graph_close")
    client = create_autospec(OllamaClient, instance=True)
    client.aclose.side_effect = lambda: events.append("ollama_aclose")
    runtime.app_state.graph_manager = graph
    runtime.app_state.ollama_client = client
    original_shutdown = runtime.jobs.shutdown

    async def _shutdown() -> None:
        events.append("jobs_shutdown")
        await original_shutdown()

    object.__setattr__(runtime.jobs, "shutdown", _shutdown)
    return runtime


async def test_open_runtime_applies_schema_and_tears_down_in_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    runtime = _faked(tmp_path, events)
    configured: list[str] = []
    monkeypatch.setattr(runtime_module, "build_runtime", lambda *a, **k: runtime)
    monkeypatch.setattr(runtime_module, "configure_logging", lambda **k: configured.append("x"))
    async with open_runtime(runtime.settings) as opened:
        assert opened.neo4j_ready is True
        graph: Any = opened.app_state.graph_manager
        graph.verify_connectivity.assert_awaited_once()
        graph.ensure_schema.assert_awaited_once()
        assert events == []
    assert configured == ["x"]
    assert events == ["jobs_shutdown", "ollama_aclose", "graph_close"]


async def test_open_runtime_keeps_going_when_neo4j_is_down(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    runtime = _faked(tmp_path, events)
    graph: Any = runtime.app_state.graph_manager
    graph.verify_connectivity.side_effect = ServiceUnavailable("down")
    monkeypatch.setattr(runtime_module, "build_runtime", lambda *a, **k: runtime)
    monkeypatch.setattr(runtime_module, "configure_logging", lambda **k: None)
    async with open_runtime(runtime.settings) as opened:
        assert opened.neo4j_ready is False
        graph.ensure_schema.assert_not_awaited()
    assert events[-1] == "graph_close"


@pytest.mark.parametrize(
    ("error", "fix_fragment"),
    [
        (ServiceUnavailable("connection refused"), "docker compose up -d neo4j"),
        (Neo4jAuthError("unauthorized"), "ALPHASWARM_NEO4J__PASSWORD"),
        (
            Neo4jUnavailableError("down", Neo4jAuthError("unauthorized"), op="verify_connectivity"),
            "ALPHASWARM_NEO4J__PASSWORD",
        ),
    ],
    ids=["neo4j-down", "wrong-password", "mapped-wrong-password"],
)
async def test_startup_warning_names_the_fix(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    fix_fragment: str,
) -> None:
    """One startup warning per failure, naming the fix (docs/DECISIONS.md#p4-d-05)."""
    fake_log = MagicMock()
    monkeypatch.setattr(runtime_module, "log", fake_log)
    graph = create_autospec(GraphStateManager, instance=True)
    graph.verify_connectivity.side_effect = error
    assert await runtime_module._prepare_graph(graph) is False
    graph.ensure_schema.assert_not_awaited()
    fake_log.warning.assert_called_once()
    args, kwargs = fake_log.warning.call_args
    assert args == ("neo4j_unavailable_at_startup",)
    assert kwargs["error_type"] == type(error).__name__
    assert fix_fragment in kwargs["fix"]


async def test_open_runtime_closes_even_when_the_body_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    runtime = _faked(tmp_path, events)
    monkeypatch.setattr(runtime_module, "build_runtime", lambda *a, **k: runtime)
    monkeypatch.setattr(runtime_module, "configure_logging", lambda **k: None)
    with pytest.raises(RuntimeError, match="body"):
        async with open_runtime(runtime.settings, apply_schema=False):
            raise RuntimeError("body")
    assert events == ["jobs_shutdown", "ollama_aclose", "graph_close"]


async def test_open_simulation_yields_deps_and_closes_providers_without_teardown(tmp_path: Path) -> None:
    runtime = build_runtime(route_test_settings(tmp_path), with_ollama=False, with_neo4j=False)
    runtime.app_state.graph_manager = create_autospec(GraphStateManager, instance=True)
    orchestrator = FakeInferenceProvider(ProviderRole.ORCHESTRATOR, "o", scripted=[])
    worker = FakeInferenceProvider(ProviderRole.WORKER, "w", scripted=[])
    for provider in (orchestrator, worker):
        provider.aclose = AsyncMock()  # type: ignore[method-assign]
        provider.teardown = AsyncMock()  # type: ignore[method-assign]
    inference = MagicMock()
    inference.open_operation = AsyncMock(
        return_value=BuiltProviders(orchestrator=orchestrator, worker=worker, budget_meter=BudgetMeter(None, {})),
    )
    controller = object()
    inference.build_controller = AsyncMock(return_value=controller)
    async with open_simulation(inference, runtime.app_state, state=runtime.app_state.state_store) as deps:
        assert (deps.orchestrator, deps.worker, deps.controller) == (orchestrator, worker, controller)
        assert deps.graph is runtime.app_state.graph_manager
        assert deps.market is runtime.app_state.market_provider
        assert deps.state is runtime.app_state.state_store
    inference.open_operation.assert_awaited_once_with("simulation")
    orchestrator.aclose.assert_awaited_once()
    worker.aclose.assert_awaited_once()
    orchestrator.teardown.assert_not_awaited()


async def test_open_simulation_without_a_graph(tmp_path: Path) -> None:
    runtime = build_runtime(route_test_settings(tmp_path), with_ollama=False, with_neo4j=False)
    with pytest.raises(Neo4jUnavailableError):
        async with open_simulation(MagicMock(), runtime.app_state, state=None):
            pass


def test_runtime_is_frozen(tmp_path: Path) -> None:
    runtime = build_runtime(route_test_settings(tmp_path), with_ollama=False, with_neo4j=False)
    assert replace(runtime, neo4j_ready=True).neo4j_ready is True
    with pytest.raises(AttributeError):
        runtime.neo4j_ready = True  # type: ignore[misc]


async def test_open_simulation_shares_the_rate_limit_gate(tmp_path: Path) -> None:
    """Cloud worker: both same-vendor providers retry through the controller."""
    import httpx

    from alphaswarm.inference.budget import BudgetTrackingProvider
    from alphaswarm.inference.config import InferenceConfig, ProviderType, RoleConfig
    from alphaswarm.inference.openai_provider import OpenAICompatProvider
    from alphaswarm.inference.rate_limit import RateLimitController

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":  # the preflight's model listing
            return httpx.Response(200, json={"data": [{"id": "gpt-4o-mini"}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}], "usage": {}})

    def cloud(role: ProviderRole) -> OpenAICompatProvider:
        return OpenAICompatProvider(
            role,
            "gpt-4o-mini",
            base_url="https://api.example.com/v1",
            api_key="test-key",
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

    runtime = build_runtime(route_test_settings(tmp_path), with_ollama=False, with_neo4j=False)
    runtime.app_state.graph_manager = create_autospec(GraphStateManager, instance=True)
    meter = BudgetMeter(None, {})
    orchestrator, worker = cloud(ProviderRole.ORCHESTRATOR), cloud(ProviderRole.WORKER)
    role = RoleConfig(
        provider=ProviderType.OPENAI_COMPATIBLE,
        model="gpt-4o-mini",
        base_url="https://api.example.com/v1",
        api_key="test-key",
    )
    controller = RateLimitController(max_in_flight=1, requests_per_min=40, tokens_per_min=None)
    inference = MagicMock()
    inference.open_operation = AsyncMock(
        return_value=BuiltProviders(
            orchestrator=BudgetTrackingProvider(orchestrator, meter),
            worker=BudgetTrackingProvider(worker, meter),
            budget_meter=meter,
        ),
    )
    inference.build_controller = AsyncMock(return_value=controller)
    inference.config = AsyncMock(return_value=InferenceConfig(orchestrator=role, worker=role))
    async with open_simulation(inference, runtime.app_state, state=None) as deps:
        assert deps.controller is controller
        assert worker.retry_gate is controller
        assert orchestrator.retry_gate is controller
