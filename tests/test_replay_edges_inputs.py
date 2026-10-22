"""Replay and edges routes: id validation and handler-mapped conflicts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from alphaswarm.web.replay_manager import NoReplayActiveError
from alphaswarm.web.routes.edges import router as edges_router
from alphaswarm.web.routes.replay import router as replay_router
from tests.support.web_app import CYCLE_A, FakeCycleGraph, make_route_app, route_test_settings


def _client(tmp_path: Path, graph: FakeCycleGraph | None = None) -> TestClient:
    app = make_route_app(
        replay_router,
        edges_router,
        settings=route_test_settings(tmp_path),
        graph=graph if graph is not None else FakeCycleGraph(latest=CYCLE_A),
    )
    return TestClient(app)


@pytest.mark.parametrize("bad", ["test-cycle", f"{CYCLE_A}%0A", "cycle_01"])
def test_replay_start_rejects_malformed_ids(tmp_path: Path, bad: str) -> None:
    with _client(tmp_path) as client:
        r = client.post(f"/api/replay/start/{bad}")
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "validation_error"


def test_edges_accept_uuid_and_the_current_alias(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        assert client.get(f"/api/edges/{CYCLE_A}?round=2").json() == {"edges": []}
        assert client.get("/api/edges/current?round=2").json() == {"edges": []}


@pytest.mark.parametrize("bad", ["test-cycle", "c1", f"{CYCLE_A}%0A"])
def test_edges_reject_malformed_ids(tmp_path: Path, bad: str) -> None:
    with _client(tmp_path) as client:
        assert client.get(f"/api/edges/{bad}?round=1").status_code == 422


def test_replay_advance_race_is_json_409(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        replay = client.app.state.replay_manager  # type: ignore[attr-defined]
        with (
            patch.object(type(replay), "is_active", new=True),
            patch.object(
                replay,
                "advance",
                new=AsyncMock(side_effect=NoReplayActiveError("No replay active")),
            ),
        ):
            r = client.post("/api/replay/advance")
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "no_replay_active"


def test_replay_cycles_without_graph_is_503(tmp_path: Path) -> None:
    app = make_route_app(replay_router, settings=route_test_settings(tmp_path), graph=None)
    with TestClient(app) as client:
        r = client.get("/api/replay/cycles")
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "graph_unavailable"
