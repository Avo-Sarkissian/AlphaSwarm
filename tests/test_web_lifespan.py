"""The production FastAPI lifespan (C-TEST-18).

Runs the real `create_app()` lifespan with a fake graph manager: no Neo4j,
no Ollama, and never the operator's holdings CSV. Later plans extend this
file in place (create_app(settings), shutdown order); do not add a second one.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from fastapi.testclient import TestClient
from neo4j.exceptions import AuthError as Neo4jAuthError
from neo4j.exceptions import ServiceUnavailable

import alphaswarm.manifest as manifest
import alphaswarm.web.app as web_app


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:
    yield
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


@pytest.fixture(autouse=True)
def _no_holdings_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lifespan must never read the real holdings CSV during tests."""
    monkeypatch.setattr(web_app, "load_portfolio_snapshot", lambda _path: None)


@pytest.fixture(autouse=True)
def _git_heads(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[tuple[str, bool]]]:
    """Stand-in git state, newest last: no git subprocess runs and no state leaks out."""
    heads = [("a" * 40, False)]
    monkeypatch.setattr(manifest, "git_revision", lambda _root: heads[-1])
    manifest.current_git_revision.cache_clear()
    yield heads
    manifest.current_git_revision.cache_clear()


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


def test_lifespan_pins_the_git_revision_it_started_from(
    monkeypatch: pytest.MonkeyPatch, _git_heads: list[tuple[str, bool]]
) -> None:
    """A commit after startup does not relabel the code the server is running."""
    _use_graph_manager(monkeypatch, _fake_graph_manager())

    with TestClient(web_app.create_app()):
        _git_heads.append(("b" * 40, True))  # the owner commits while the server runs

        assert manifest.current_git_revision() == ("a" * 40, False)


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
