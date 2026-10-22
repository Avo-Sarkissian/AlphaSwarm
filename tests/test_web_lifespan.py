"""The production FastAPI lifespan (C-TEST-18).

Runs the real `create_app()` lifespan with a fake graph manager: no Neo4j,
no Ollama, and never the operator's holdings CSV. Later plans extend this
file in place (create_app(settings), shutdown order); do not add a second one.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from fastapi.testclient import TestClient
from neo4j.exceptions import AuthError as Neo4jAuthError
from neo4j.exceptions import ServiceUnavailable

import alphaswarm.web.app as web_app
import alphaswarm.web.routes.holdings as holdings_routes


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:
    yield
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


@pytest.fixture(autouse=True)
def _no_holdings_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lifespan must never read the real holdings CSV during tests."""
    monkeypatch.setattr(holdings_routes, "load_portfolio_snapshot", lambda _path: None)


def _fake_graph_manager(verify_error: BaseException | None = None) -> MagicMock:
    gm = MagicMock()
    gm.calls = []

    async def _verify() -> None:
        gm.calls.append("verify_connectivity")
        if verify_error is not None:
            raise verify_error

    async def _schema() -> None:
        gm.calls.append("ensure_schema")

    gm.verify_connectivity = AsyncMock(side_effect=_verify)
    gm.ensure_schema = AsyncMock(side_effect=_schema)
    gm.close = AsyncMock()
    return gm


def _use_graph_manager(monkeypatch: pytest.MonkeyPatch, gm: MagicMock) -> None:
    real_create_app_state: Callable[..., Any] = web_app.create_app_state

    def _create(settings: Any, personas: Any, **_kwargs: Any) -> Any:
        state = real_create_app_state(settings, personas, with_ollama=False, with_neo4j=False)
        state.graph_manager = gm
        return state

    monkeypatch.setattr(web_app, "create_app_state", _create)


def test_lifespan_verifies_neo4j_then_applies_the_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    gm = _fake_graph_manager()
    _use_graph_manager(monkeypatch, gm)

    with TestClient(web_app.create_app()) as client:
        assert gm.calls == ["verify_connectivity", "ensure_schema"]
        assert client.app.state.neo4j_ready is True  # type: ignore[attr-defined]

    gm.close.assert_awaited_once()


@pytest.mark.parametrize(
    "error",
    [ServiceUnavailable("connection refused"), Neo4jAuthError("unauthorized")],
    ids=["neo4j-down", "wrong-password"],
)
def test_lifespan_keeps_serving_when_neo4j_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    gm = _fake_graph_manager(verify_error=error)
    _use_graph_manager(monkeypatch, gm)

    with TestClient(web_app.create_app()) as client:
        assert gm.calls == ["verify_connectivity"]
        assert client.app.state.neo4j_ready is False  # type: ignore[attr-defined]
        assert client.get("/api/health").status_code == 200


def test_lifespan_without_a_graph_manager_is_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    real_create_app_state: Callable[..., Any] = web_app.create_app_state

    def _create(settings: Any, personas: Any, **_kwargs: Any) -> Any:
        return real_create_app_state(settings, personas, with_ollama=False, with_neo4j=False)

    monkeypatch.setattr(web_app, "create_app_state", _create)

    with TestClient(web_app.create_app()) as client:
        assert client.app.state.neo4j_ready is False  # type: ignore[attr-defined]


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


def test_lifespan_wires_post_run_and_holdings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The lifespan builds PortfolioCache on app.state (never on AppState)."""
    from alphaswarm.app import create_app_state as real_create_app_state
    from alphaswarm.web.routes.holdings import PortfolioCache
    from tests.support.web_app import route_test_settings

    def _offline_app_state(settings: object, personas: object, **_: object) -> object:
        state = real_create_app_state(settings, personas, with_ollama=False, with_neo4j=False)  # type: ignore[arg-type]
        graph = MagicMock()
        graph.verify_connectivity = AsyncMock()
        graph.ensure_schema = AsyncMock()
        graph.close = AsyncMock()
        state.graph_manager = graph
        return state

    settings = route_test_settings(tmp_path)
    monkeypatch.setattr(web_app, "create_app_state", _offline_app_state)
    monkeypatch.setattr(web_app, "AppSettings", lambda: settings)
    app = web_app.create_app()
    with TestClient(app):
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
