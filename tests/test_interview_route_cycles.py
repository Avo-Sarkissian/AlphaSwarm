"""Interview cycle selection, (cycle, agent) sessions and gating (docs/DECISIONS.md#p35-d-06)."""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import alphaswarm.web.routes.interview as interview_module
from alphaswarm.errors import INFERENCE_CONFIG_INCOMPLETE_MESSAGE
from alphaswarm.web.routes.interview import router as interview_router
from tests.support.web_app import (
    CYCLE_A,
    CYCLE_B,
    CYCLE_UNKNOWN,
    FakeCycleGraph,
    make_route_app,
    route_test_settings,
)

AGENT = "quants_01"


def _context() -> object:
    """A stored interview context; the route only checks that it names the agent."""
    return SimpleNamespace(agent_name="Quants 01")


async def _context_unchanged(graph: object, provider: object, context: object, *, cycle_id: str) -> object:
    return context


@pytest.fixture()
def engine_cls() -> Iterator[MagicMock]:
    """Patch InterviewEngine and, once the route builds lazy narratives, that step too."""
    engine = MagicMock()
    engine.ask = AsyncMock(return_value="answer")
    with contextlib.ExitStack() as stack:
        cls = stack.enter_context(
            patch.object(interview_module, "InterviewEngine", return_value=engine),
        )
        if hasattr(interview_module, "ensure_decision_narrative"):
            stack.enter_context(
                patch.object(
                    interview_module,
                    "ensure_decision_narrative",
                    new=AsyncMock(side_effect=_context_unchanged),
                ),
            )
        yield cls


def _app(tmp_path: Path, graph: FakeCycleGraph | None) -> FastAPI:
    return make_route_app(interview_router, settings=route_test_settings(tmp_path), graph=graph)


def test_default_cycle_is_the_latest_complete_one(tmp_path: Path, engine_cls: MagicMock) -> None:
    graph = FakeCycleGraph({CYCLE_A: "complete"}, latest=CYCLE_A, contexts={(CYCLE_A, AGENT): _context()})
    app = _app(tmp_path, graph)
    with TestClient(app) as client:
        r = client.post(f"/api/interview/{AGENT}", json={"message": "Why?"})
        assert r.status_code == 200
        assert r.json() == {"response": "answer"}
        assert (CYCLE_A, AGENT) in app.state.interview_sessions
    assert graph.context_calls == [(CYCLE_A, AGENT)]


def test_sessions_are_per_cycle_and_reused(tmp_path: Path, engine_cls: MagicMock) -> None:
    graph = FakeCycleGraph(
        {CYCLE_A: "complete", CYCLE_B: "complete"},
        latest=CYCLE_B,
        contexts={(CYCLE_A, AGENT): _context(), (CYCLE_B, AGENT): _context()},
    )
    app = _app(tmp_path, graph)
    with TestClient(app) as client:
        assert (
            client.post(
                f"/api/interview/{AGENT}",
                json={"message": "Q1", "cycle_id": CYCLE_A},
            ).status_code
            == 200
        )
        assert client.post(f"/api/interview/{AGENT}", json={"message": "Q2"}).status_code == 200
        assert (
            client.post(
                f"/api/interview/{AGENT}",
                json={"message": "Q3", "cycle_id": CYCLE_A},
            ).status_code
            == 200
        )
        assert set(app.state.interview_sessions) == {(CYCLE_A, AGENT), (CYCLE_B, AGENT)}
    assert engine_cls.call_count == 2
    assert graph.context_calls == [(CYCLE_A, AGENT), (CYCLE_B, AGENT)]


@pytest.mark.parametrize(
    ("cycle_id", "status", "code"),
    [(CYCLE_UNKNOWN, None, "cycle_not_found"), (CYCLE_A, "running", "cycle_not_ready")],
)
def test_explicit_cycle_is_gated(
    tmp_path: Path,
    engine_cls: MagicMock,
    cycle_id: str,
    status: str | None,
    code: str,
) -> None:
    graph = FakeCycleGraph({CYCLE_A: status} if status else {}, latest=CYCLE_B)
    with TestClient(_app(tmp_path, graph)) as client:
        r = client.post(f"/api/interview/{AGENT}", json={"message": "Q", "cycle_id": cycle_id})
    assert r.json()["detail"]["error"] == code


def test_malformed_cycle_id_is_422(tmp_path: Path, engine_cls: MagicMock) -> None:
    with TestClient(_app(tmp_path, FakeCycleGraph())) as client:
        r = client.post(f"/api/interview/{AGENT}", json={"message": "Q", "cycle_id": "c1"})
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "validation_error"


def test_simulation_running_is_409_without_graph_reads(tmp_path: Path, engine_cls: MagicMock) -> None:
    graph = FakeCycleGraph({CYCLE_A: "complete"}, latest=CYCLE_A)
    app = _app(tmp_path, graph)
    with TestClient(app) as client:
        app.state.sim_manager._is_running = True
        r = client.post(f"/api/interview/{AGENT}", json={"message": "Q"})
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "simulation_running"
    assert graph.status_calls == []


def test_no_completed_cycle_is_404(tmp_path: Path, engine_cls: MagicMock) -> None:
    with TestClient(_app(tmp_path, FakeCycleGraph(latest=None))) as client:
        r = client.post(f"/api/interview/{AGENT}", json={"message": "Q"})
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "no_completed_cycle"


def test_unknown_agent_is_404_and_leaves_no_session(tmp_path: Path, engine_cls: MagicMock) -> None:
    app = _app(tmp_path, FakeCycleGraph({CYCLE_A: "complete"}, latest=CYCLE_A))
    with TestClient(app) as client:
        r = client.post("/api/interview/nobody_99", json={"message": "Q"})
        assert r.status_code == 404
        assert r.json()["detail"]["error"] == "agent_not_found"
        assert app.state.interview_sessions == {}


def test_missing_graph_is_503(tmp_path: Path, engine_cls: MagicMock) -> None:
    with TestClient(_app(tmp_path, None)) as client:
        r = client.post(f"/api/interview/{AGENT}", json={"message": "Q"})
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "graph_unavailable"


def test_invalid_stored_config_is_422_and_leaves_no_session(tmp_path: Path, engine_cls: MagicMock) -> None:
    """A file the strict models reject gets Settings' 422, not a 500, and never its path."""
    (tmp_path / "inference.json").write_text('{"spend_cap": 5}', encoding="utf-8")
    graph = FakeCycleGraph({CYCLE_A: "complete"}, latest=CYCLE_A, contexts={(CYCLE_A, AGENT): _context()})
    app = _app(tmp_path, graph)
    with TestClient(app) as client:
        r = client.post(f"/api/interview/{AGENT}", json={"message": "Q"})
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert detail["error"] == "inference_config_invalid"
        assert "move aside" in detail["message"]
        assert str(tmp_path) not in r.text
        assert app.state.interview_sessions == {}
    engine_cls.assert_not_called()


def test_cloud_worker_without_api_key_is_422_pointing_at_settings(tmp_path: Path, engine_cls: MagicMock) -> None:
    """The file loads, but the worker cannot be built: the fix is in Settings."""
    stored = {
        "orchestrator": {"provider": "ollama", "model": "alphaswarm-orchestrator"},
        "worker": {"provider": "anthropic", "model": "fictional-model-3"},
    }
    (tmp_path / "inference.json").write_text(json.dumps(stored), encoding="utf-8")
    graph = FakeCycleGraph({CYCLE_A: "complete"}, latest=CYCLE_A, contexts={(CYCLE_A, AGENT): _context()})
    app = _app(tmp_path, graph)
    with TestClient(app) as client:
        r = client.post(f"/api/interview/{AGENT}", json={"message": "Q"})
        assert r.status_code == 422
        assert r.json()["detail"] == {
            "error": "inference_config_invalid",
            "message": INFERENCE_CONFIG_INCOMPLETE_MESSAGE,
        }
        assert app.state.interview_sessions == {}
    engine_cls.assert_not_called()
