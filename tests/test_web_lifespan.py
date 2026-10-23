"""The production FastAPI lifespan, run with fakes.

The app is built with create_app(settings) and a fake graph manager: no Neo4j,
no Ollama. Startup verifies Neo4j, then applies the schema; the server keeps
serving when Neo4j is down or rejects the password; no graph manager means not
ready. The tests also pin the settings identity, a running broadcaster, health
and the shutdown order (docs/DECISIONS.md#adr-web-lifespan). The settings put
every path setting under tmp_path (route_test_settings), so the lifespan never
reads Schwab/ or .secrets/ and never writes to reports/ or advisory/.
Extend this file in place; do not add a second one.
"""

from __future__ import annotations

import importlib.util
import logging
import os
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
from pydantic import BaseModel
from uvicorn.importer import import_from_string

import alphaswarm.manifest as manifest
import alphaswarm.settings as settings_module
import alphaswarm.web.app as web_app
from alphaswarm.app import AppState, create_app_state
from alphaswarm.errors import Neo4jUnavailableError, Neo4jWriteError
from alphaswarm.graph import GraphStateManager
from alphaswarm.logging import BRIDGE_HANDLER_NAME, reset_stdlib_bridge
from alphaswarm.readiness import NEO4J_AUTH_FIX, NEO4J_FIX
from alphaswarm.settings import AppSettings
from alphaswarm.types import AgentPersona
from alphaswarm.web.simulation_manager import SimulationManager
from tests.support.web_app import route_test_settings


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
    """Every path setting under tmp_path; the holdings CSV is never created."""
    return route_test_settings(tmp_path)


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
    result = LifespanProbe(app=app, settings=lifespan_settings, graph=graph, received_settings=received)

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
    [
        # What GraphStateManager.verify_connectivity() raises (docs/DECISIONS.md#p4-d-07).
        Neo4jUnavailableError(
            "Neo4j is unavailable (verify_connectivity)",
            ServiceUnavailable("connection refused"),
            op="verify_connectivity",
        ),
        Neo4jUnavailableError(
            "Neo4j is unavailable (verify_connectivity)",
            Neo4jAuthError("unauthorized"),
            op="verify_connectivity",
        ),
    ],
    ids=["neo4j-down", "wrong-password"],
)
async def test_lifespan_keeps_serving_when_neo4j_is_unavailable(probe: LifespanProbe, error: Exception) -> None:
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


async def test_lifespan_installs_the_redacting_log_bridge(probe: LifespanProbe) -> None:
    """create_app_state no longer configures logging, so the lifespan must (docs/DECISIONS.md#adr-security-2026-08)."""
    reset_stdlib_bridge()
    try:
        async with probe.app.router.lifespan_context(probe.app):
            assert BRIDGE_HANDLER_NAME in [h.get_name() for h in logging.getLogger().handlers]
    finally:
        reset_stdlib_bridge()


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


def test_importing_the_module_builds_no_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every alphaswarm.web import loads this module, and pytest imports it while
    collecting, before hermetic_env runs: an app built then would keep the
    operator's settings, real holdings path included, for its lifespan."""

    def forbidden_settings(*args: Any, **kwargs: Any) -> AppSettings:
        raise AssertionError("importing alphaswarm.web.app must not construct AppSettings()")

    monkeypatch.setattr(settings_module, "AppSettings", forbidden_settings)
    spec = importlib.util.spec_from_file_location("_fresh_web_app", web_app.__file__)
    assert spec is not None
    assert spec.loader is not None
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)  # a fresh import of the same source
    assert "app" not in vars(fresh)


def test_the_uvicorn_target_builds_the_app_on_first_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`uvicorn alphaswarm.web.app:app` still resolves, to an app whose settings are
    read at that moment: here, inside the hermetic test environment."""
    module_globals = vars(web_app)
    monkeypatch.delitem(module_globals, "app", raising=False)
    monkeypatch.setenv("ALPHASWARM_LOG_LEVEL", "DEBUG")
    try:
        built = import_from_string("alphaswarm.web.app:app")
        assert isinstance(built, FastAPI)
        assert built.state.settings.log_level == "DEBUG"
        hermetic_csv = Path(os.environ["ALPHASWARM_HOLDINGS_CSV_PATH"])
        assert built.state.settings.holdings_csv_path == hermetic_csv
        assert import_from_string("alphaswarm.web.app:app") is built
    finally:
        module_globals.pop("app", None)  # leave the module as a fresh import left it


class _RecordingLog:
    """Stand-in for alphaswarm.web.app's module logger; records (event, kwargs)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __getattr__(self, _level: str) -> Callable[..., None]:
        def _log(event: str, **kw: Any) -> None:
            self.calls.append((event, kw))

        return _log


@pytest.mark.parametrize(
    ("error", "expected_fix"),
    [
        (
            Neo4jUnavailableError(
                "Neo4j is unavailable (verify_connectivity)",
                ServiceUnavailable("connection refused"),
                op="verify_connectivity",
            ),
            NEO4J_FIX,
        ),
        (
            Neo4jUnavailableError(
                "Neo4j is unavailable (verify_connectivity)",
                Neo4jAuthError("unauthorized"),
                op="verify_connectivity",
            ),
            NEO4J_AUTH_FIX,
        ),
    ],
    ids=["neo4j-down", "wrong-password"],
)
async def test_the_startup_warning_names_the_fix(
    monkeypatch: pytest.MonkeyPatch, error: Exception, expected_fix: str
) -> None:
    """One neo4j_unavailable_at_startup warning, with the fix /api/health shows.

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
    assert warnings[0]["fix"] == expected_fix


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


async def test_lifespan_starts_with_a_holdings_file_that_is_not_utf8(
    probe: LifespanProbe,
) -> None:
    """An Excel cp1252 export makes holdings unavailable (503); it does not stop startup."""
    probe.settings.holdings_csv_path.write_bytes(
        "account,symbol,shares,cost_basis_per_share\nÉpargne,ZZZT,1,1\n".encode("cp1252")
    )
    async with probe.app.router.lifespan_context(probe.app):
        transport = httpx.ASGITransport(app=probe.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            response = await client.get("/api/holdings")
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "holdings_unavailable"


def _path_settings(model: BaseModel, prefix: str = "") -> dict[str, Path]:
    """Every Path-valued setting of *model*, nested models included, by dotted name."""
    found: dict[str, Path] = {}
    for name, value in model:
        if isinstance(value, Path):
            found[f"{prefix}{name}"] = value
        elif isinstance(value, BaseModel):
            found.update(_path_settings(value, f"{prefix}{name}."))
    return found


def test_every_path_setting_points_under_tmp_path(lifespan_settings: AppSettings, tmp_path: Path) -> None:
    """The lifespan reads the holdings CSV and the inference config, and the post-run
    jobs write to reports_dir and advisory_dir: none of them may reach the repo's
    Schwab/, .secrets/, reports/ or advisory/."""
    paths = _path_settings(lifespan_settings)
    expected = {"holdings_csv_path", "inference_config_path", "reports_dir", "advisory_dir"}
    assert expected <= set(paths)
    outside = {
        name: path for name, path in paths.items() if not lifespan_settings.resolve_path(path).is_relative_to(tmp_path)
    }
    assert outside == {}


async def test_lifespan_keeps_serving_when_the_schema_write_fails(probe: LifespanProbe) -> None:
    # A reachable database that rejects a schema statement is not ready either.
    probe.graph.ensure_schema.side_effect = Neo4jWriteError(
        "Neo4j write failed (ensure_schema)",
        op="ensure_schema",
    )
    async with probe.app.router.lifespan_context(probe.app):
        assert probe.app.state.neo4j_ready is False
        response = await _get_health(probe.app)
        assert response.status_code == 200
