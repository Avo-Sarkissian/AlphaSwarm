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

import asyncio
import importlib.util
import logging
import os
from collections.abc import Iterator
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
import alphaswarm.services.runtime as runtime_module
import alphaswarm.settings as settings_module
import alphaswarm.web.app as web_app
from alphaswarm.errors import Neo4jUnavailableError, Neo4jWriteError
from alphaswarm.graph import GraphStateManager
from alphaswarm.logging import BRIDGE_HANDLER_NAME, configure_logging, reset_stdlib_bridge
from alphaswarm.services.runtime import Runtime
from alphaswarm.settings import AppSettings
from alphaswarm.web.simulation_manager import SimulationManager
from tests.support.web_app import offline_runtime, route_test_settings


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:
    """open_runtime() configures structlog globally; undo it after each test."""
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
    runtime: Runtime
    received_settings: list[AppSettings] = field(default_factory=list)
    events: list[str] = field(default_factory=list)


@pytest.fixture
def lifespan_settings(tmp_path: Path) -> AppSettings:
    """Every path setting under tmp_path; the holdings CSV is never created."""
    return route_test_settings(tmp_path)


@pytest.fixture
def probe(lifespan_settings: AppSettings, monkeypatch: pytest.MonkeyPatch) -> LifespanProbe:
    """The production open_runtime as the runtime factory, offline.

    Only build_runtime (no Ollama, no driver: an autospec graph instead) and
    configure_logging are replaced inside alphaswarm.services.runtime, so the
    schema, readiness and teardown assertions test production code.
    """
    graph = create_autospec(GraphStateManager, instance=True)
    runtime = offline_runtime(lifespan_settings, graph=graph)
    received: list[AppSettings] = []
    events: list[str] = []

    def fake_build_runtime(settings: AppSettings, **_: object) -> Runtime:
        received.append(settings)
        events.append("runtime_open")
        return runtime

    original_jobs_shutdown = runtime.jobs.shutdown

    async def recording_jobs_shutdown() -> None:
        events.append("jobs_shutdown")
        await original_jobs_shutdown()

    object.__setattr__(runtime.jobs, "shutdown", recording_jobs_shutdown)
    monkeypatch.setattr(runtime_module, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(runtime_module, "configure_logging", lambda **_: None)

    def forbidden_settings(*args: Any, **kwargs: Any) -> AppSettings:
        raise AssertionError("create_app(settings) must not construct AppSettings() again")

    monkeypatch.setattr(web_app, "AppSettings", forbidden_settings)
    app = web_app.create_app(lifespan_settings, runtime_factory=runtime_module.open_runtime)
    result = LifespanProbe(
        app=app,
        settings=lifespan_settings,
        graph=graph,
        runtime=runtime,
        received_settings=received,
        events=events,
    )

    original_shutdown = SimulationManager.shutdown

    def _broadcaster_done() -> bool | None:
        # None when startup failed before the broadcaster existed.
        task = getattr(app.state, "broadcaster_task", None)
        return task.done() if task is not None else None

    async def recording_shutdown(self: SimulationManager) -> None:
        events.append(f"sim_shutdown:broadcaster_done={_broadcaster_done()}")
        await original_shutdown(self)

    async def recording_close() -> None:
        events.append(f"graph_close:broadcaster_done={_broadcaster_done()}")

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


async def test_lifespan_without_a_graph_manager_is_not_ready(probe: LifespanProbe) -> None:
    probe.runtime.app_state.graph_manager = None
    async with probe.app.router.lifespan_context(probe.app):
        assert probe.app.state.neo4j_ready is False
        assert probe.app.state.report_service is None
        assert probe.app.state.advisory_service is None
    probe.graph.close.assert_not_awaited()


async def test_lifespan_uses_given_settings_and_applies_schema(probe: LifespanProbe) -> None:
    async with probe.app.router.lifespan_context(probe.app):
        assert probe.app.state.settings is probe.settings
        assert len(probe.received_settings) == 1
        assert probe.received_settings[0] is probe.settings
        probe.graph.verify_connectivity.assert_awaited_once()
        probe.graph.ensure_schema.assert_awaited_once()
        assert probe.app.state.neo4j_ready is True


async def test_lifespan_installs_the_redacting_log_bridge(
    probe: LifespanProbe,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """open_runtime configures logging for the lifespan (docs/DECISIONS.md#adr-security-2026-08)."""
    monkeypatch.setattr(runtime_module, "configure_logging", configure_logging)
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
    assert probe.events == [
        "runtime_open",
        "sim_shutdown:broadcaster_done=True",
        "jobs_shutdown",
        "graph_close:broadcaster_done=True",
    ]
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


def test_the_uvicorn_factory_target_builds_the_app_with_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`uvicorn --factory alphaswarm.web.app:create_app` builds an app whose settings
    are read at that moment: here, inside the hermetic test environment. The
    module has no import-time ``app`` attribute any more."""
    monkeypatch.setenv("ALPHASWARM_LOG_LEVEL", "DEBUG")
    factory = import_from_string("alphaswarm.web.app:create_app")
    built = factory()
    assert isinstance(built, FastAPI)
    assert built.state.settings.log_level == "DEBUG"
    hermetic_csv = Path(os.environ["ALPHASWARM_HOLDINGS_CSV_PATH"])
    assert built.state.settings.holdings_csv_path == hermetic_csv
    assert "app" not in vars(web_app)


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
        from alphaswarm.services.post_run import PostRunPipeline

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


async def test_runtime_and_services_are_wired(probe: LifespanProbe) -> None:
    from alphaswarm.services.advisory import AdvisoryService
    from alphaswarm.services.post_run import PostRunPipeline
    from alphaswarm.services.report import ReportService

    async with probe.app.router.lifespan_context(probe.app):
        state = probe.app.state
        assert state.app_state is state.runtime.app_state
        assert isinstance(state.report_service, ReportService)
        assert isinstance(state.advisory_service, AdvisoryService)
        assert isinstance(state.post_run_pipeline, PostRunPipeline)
        assert state.sim_manager._on_complete == state.post_run_pipeline.on_complete
        assert state.sim_manager._orchestrator_busy == state.runtime.jobs.is_busy
        assert state.sim_manager._inference is state.runtime.inference
        assert not hasattr(state, "market_provider")


async def test_shutdown_order_with_running_job(probe: LifespanProbe) -> None:
    async with probe.app.router.lifespan_context(probe.app):
        task = probe.app.state.runtime.jobs.start("report", "c1", asyncio.Event().wait)
    assert task.cancelled()
    assert probe.app.state.runtime.jobs.status("report").state == "failed"
    assert probe.events.index("sim_shutdown:broadcaster_done=True") < probe.events.index("jobs_shutdown")


async def test_shutdown_closes_interview_providers(probe: LifespanProbe) -> None:
    provider = MagicMock()
    provider.aclose = AsyncMock()
    async with probe.app.router.lifespan_context(probe.app):
        probe.app.state.interview_sessions[("c1", "quants_01")] = {
            "engine": None,
            "lock": asyncio.Lock(),
            "provider": provider,
        }
    provider.aclose.assert_awaited_once()
    assert probe.app.state.interview_sessions == {}


async def test_startup_failure_still_closes_the_runtime(
    probe: LifespanProbe,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("broadcaster failed to start")

    monkeypatch.setattr(web_app, "start_broadcaster", _broken)
    with pytest.raises(RuntimeError, match="broadcaster failed"):
        async with probe.app.router.lifespan_context(probe.app):
            pass
    assert probe.events[0] == "runtime_open"
    assert "jobs_shutdown" in probe.events
    probe.graph.close.assert_awaited_once()


def test_module_has_no_import_time_app() -> None:
    assert not hasattr(web_app, "app")
    assert not hasattr(web_app, "WebPostRunJobs")


def test_default_runtime_factory_is_open_runtime(lifespan_settings: AppSettings) -> None:
    from alphaswarm.services.runtime import open_runtime

    assert web_app.create_app(lifespan_settings).state.runtime_factory is open_runtime
