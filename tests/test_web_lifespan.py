"""The production FastAPI lifespan, run with fakes.

The app is built with create_app(settings) and a fake graph manager: no Neo4j,
no Ollama. Startup verifies Neo4j, then applies the schema; the server keeps
serving when Neo4j is down or rejects the password; no graph manager means not
ready. The tests also pin the settings identity, a running broadcaster, health
and the shutdown order (docs/DECISIONS.md#adr-web-lifespan). The settings point
every file path at tmp_path, so the lifespan never reads Schwab/ or .secrets/.
Extend this file in place; do not add a second one.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, create_autospec

import httpx
import pytest
import structlog
from fastapi import FastAPI
from neo4j.exceptions import AuthError as Neo4jAuthError
from neo4j.exceptions import ServiceUnavailable

import alphaswarm.manifest as manifest
import alphaswarm.web.app as web_app
from alphaswarm.app import AppState, create_app_state
from alphaswarm.config import AppSettings
from alphaswarm.graph import GraphStateManager
from alphaswarm.types import AgentPersona
from alphaswarm.web.simulation_manager import SimulationManager


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:
    """create_app_state() configures structlog globally; undo it after each test."""
    yield
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


@pytest.fixture(autouse=True)
def _git_heads(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[tuple[str, bool]]]:
    """Stand-in git state, newest last: no git subprocess runs and no state leaks out."""
    heads = [("a" * 40, False)]
    monkeypatch.setattr(manifest, "git_revision", lambda _root: heads[-1])
    manifest.current_git_revision.cache_clear()
    yield heads
    manifest.current_git_revision.cache_clear()


@dataclass
class LifespanProbe:
    app: FastAPI
    settings: AppSettings
    graph: MagicMock
    received_settings: list[AppSettings] = field(default_factory=list)
    events: list[tuple[str, bool]] = field(default_factory=list)


@pytest.fixture
def lifespan_settings(tmp_path: Path) -> AppSettings:
    return AppSettings(  # type: ignore[call-arg]
        _env_file=None,
        holdings_csv_path=tmp_path / "absent-holdings.csv",
        inference_config_path=tmp_path / "inference.json",
    )


@pytest.fixture
def probe(lifespan_settings: AppSettings, monkeypatch: pytest.MonkeyPatch) -> LifespanProbe:
    graph = create_autospec(GraphStateManager, instance=True)
    received: list[AppSettings] = []

    def fake_create_app_state(
        settings: AppSettings,
        personas: list[AgentPersona],
        *,
        with_ollama: bool = False,
        with_neo4j: bool = False,
    ) -> AppState:
        received.append(settings)
        state = create_app_state(settings, personas, with_ollama=False, with_neo4j=False)
        state.graph_manager = graph
        return state

    def forbidden_settings(*args: Any, **kwargs: Any) -> AppSettings:
        raise AssertionError("create_app(settings) must not construct AppSettings() again")

    monkeypatch.setattr(web_app, "create_app_state", fake_create_app_state)
    monkeypatch.setattr(web_app, "AppSettings", forbidden_settings)
    app = web_app.create_app(lifespan_settings)
    result = LifespanProbe(
        app=app, settings=lifespan_settings, graph=graph, received_settings=received
    )

    original_shutdown = SimulationManager.shutdown

    async def recording_shutdown(self: SimulationManager) -> None:
        result.events.append(("sim_shutdown", app.state.broadcaster_task.done()))
        await original_shutdown(self)

    async def recording_close() -> None:
        result.events.append(("graph_close", app.state.broadcaster_task.done()))

    monkeypatch.setattr(SimulationManager, "shutdown", recording_shutdown)
    graph.close.side_effect = recording_close
    return result


async def _get_health(app: FastAPI) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        return await client.get("/api/health")


async def test_lifespan_verifies_neo4j_then_applies_the_schema(probe: LifespanProbe) -> None:
    async with probe.app.router.lifespan_context(probe.app):
        assert [c[0] for c in probe.graph.method_calls] == [
            "verify_connectivity",
            "ensure_schema",
        ]
        assert probe.app.state.neo4j_ready is True
    probe.graph.close.assert_awaited_once()


@pytest.mark.parametrize(
    "error",
    [ServiceUnavailable("connection refused"), Neo4jAuthError("unauthorized")],
    ids=["neo4j-down", "wrong-password"],
)
async def test_lifespan_keeps_serving_when_neo4j_is_unavailable(
    probe: LifespanProbe, error: Exception
) -> None:
    probe.graph.verify_connectivity.side_effect = error
    async with probe.app.router.lifespan_context(probe.app):
        assert probe.app.state.neo4j_ready is False
        probe.graph.ensure_schema.assert_not_awaited()
        response = await _get_health(probe.app)
        assert response.status_code == 200


async def test_lifespan_without_a_graph_manager_is_not_ready(
    probe: LifespanProbe, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_graph(
        settings: AppSettings,
        personas: list[AgentPersona],
        *,
        with_ollama: bool = False,
        with_neo4j: bool = False,
    ) -> AppState:
        return create_app_state(settings, personas, with_ollama=False, with_neo4j=False)

    monkeypatch.setattr(web_app, "create_app_state", no_graph)
    async with probe.app.router.lifespan_context(probe.app):
        assert probe.app.state.neo4j_ready is False
    probe.graph.close.assert_not_awaited()


async def test_lifespan_uses_given_settings_and_applies_schema(probe: LifespanProbe) -> None:
    async with probe.app.router.lifespan_context(probe.app):
        assert probe.app.state.settings is probe.settings
        assert len(probe.received_settings) == 1
        assert probe.received_settings[0] is probe.settings
        probe.graph.verify_connectivity.assert_awaited_once()
        probe.graph.ensure_schema.assert_awaited_once()
        assert probe.app.state.neo4j_ready is True


async def test_health_is_served_and_the_broadcaster_runs(probe: LifespanProbe) -> None:
    async with probe.app.router.lifespan_context(probe.app):
        task = probe.app.state.broadcaster_task
        assert task.get_name() == "broadcaster"
        assert not task.done()
        response = await _get_health(probe.app)
        assert response.status_code == 200
        assert response.json()["simulation_phase"] == "idle"


async def test_shutdown_stops_broadcaster_before_simulation_and_graph(
    probe: LifespanProbe,
) -> None:
    async with probe.app.router.lifespan_context(probe.app):
        pass
    assert probe.events == [("sim_shutdown", True), ("graph_close", True)]
    assert probe.app.state.broadcaster_task.cancelled()


def test_create_app_without_settings_reads_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALPHASWARM_LOG_LEVEL", "DEBUG")
    app = web_app.create_app()
    assert isinstance(app.state.settings, AppSettings)
    assert app.state.settings.log_level == "DEBUG"


class _RecordingLog:
    """Stand-in for alphaswarm.web.app's module logger; records (event, kwargs)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __getattr__(self, _level: str) -> Callable[..., None]:
        def _log(event: str, **kw: Any) -> None:
            self.calls.append((event, kw))

        return _log


@pytest.mark.parametrize(
    ("error", "fix_fragment"),
    [
        (ServiceUnavailable("connection refused"), "docker compose up -d neo4j"),
        (Neo4jAuthError("unauthorized"), "ALPHASWARM_NEO4J__PASSWORD"),
    ],
    ids=["neo4j-down", "wrong-password"],
)
async def test_the_startup_warning_names_the_fix(
    monkeypatch: pytest.MonkeyPatch, error: Exception, fix_fragment: str
) -> None:
    """One neo4j_unavailable_at_startup warning, with the fix for that failure.

    Calls the lifespan helper directly with self-contained fakes, so it does not
    depend on how the other tests in this file build the app.
    """
    log = _RecordingLog()
    monkeypatch.setattr(web_app, "log", log)
    gm = MagicMock()
    gm.verify_connectivity = AsyncMock(side_effect=error)
    gm.ensure_schema = AsyncMock()

    assert await web_app._prepare_neo4j(gm) is False

    gm.ensure_schema.assert_not_awaited()
    warnings = [kw for event, kw in log.calls if event == "neo4j_unavailable_at_startup"]
    assert len(warnings) == 1
    assert warnings[0]["error_type"] == type(error).__name__
    assert fix_fragment in warnings[0]["fix"]


async def test_lifespan_pins_the_git_revision_it_started_from(
    probe: LifespanProbe, _git_heads: list[tuple[str, bool]]
) -> None:
    """A commit after startup does not relabel the code the server is running."""
    async with probe.app.router.lifespan_context(probe.app):
        _git_heads.append(("b" * 40, True))  # the owner commits while the server runs

        assert manifest.current_git_revision() == ("a" * 40, False)


async def test_lifespan_wires_post_run_and_holdings(probe: LifespanProbe) -> None:
    """The lifespan builds PortfolioCache on app.state (never on AppState)."""
    from alphaswarm.web.routes.holdings import PortfolioCache

    app = probe.app
    async with app.router.lifespan_context(app):
        assert isinstance(app.state.portfolio_cache, PortfolioCache)
        assert not hasattr(app.state.app_state, "portfolio_snapshot")
        from alphaswarm.web.post_run import PostRunPipeline

        assert isinstance(app.state.post_run_pipeline, PostRunPipeline)
        assert app.state.sim_manager._on_complete == app.state.post_run_pipeline.on_complete
        from alphaswarm.state import JobStatus

        assert app.state.sim_manager._orchestrator_busy() is False
        app.state.app_state.state_store.set_job_status(
            "report",
            JobStatus("running", "00000000-0000-4000-8000-0000000000a1"),
        )
        assert app.state.sim_manager._orchestrator_busy() is True
