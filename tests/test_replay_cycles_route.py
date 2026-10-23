"""GET /api/replay/cycles: paging, stored metrics, cursor parsing."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alphaswarm.web.routes.replay import router as replay_router
from tests.support.web_app import (
    CYCLE_A,
    CYCLE_B,
    FakeCycleGraph,
    make_route_app,
    route_test_settings,
)

RUMOR = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."
ROW_A: dict[str, object] = {
    "cycle_id": CYCLE_A,
    "created_at": "2099-01-03T00:00:00.123456789+00:00",
    "seed_rumor": RUMOR,
    "round_count": 3,
    "status": "complete",
    "final_buy": 60,
    "final_sell": 25,
    "final_hold": 10,
    "total_flips": 7,
    "total_seconds": 754.3,
    "agent_count": 100,
}
ROW_B: dict[str, object] = {
    "cycle_id": CYCLE_B,
    "created_at": "2099-01-02T00:00:00.000000000+00:00",
    "seed_rumor": RUMOR,
    "round_count": 3,
    "status": "complete",
    "final_buy": None,
    "final_sell": None,
    "final_hold": None,
    "total_flips": None,
    "total_seconds": None,
    "agent_count": None,
}


def _client(tmp_path: Path, graph: FakeCycleGraph | None) -> TestClient:
    return TestClient(make_route_app(replay_router, settings=route_test_settings(tmp_path), graph=graph))


def test_default_page_returns_metrics_and_no_cursor(tmp_path: Path) -> None:
    graph = FakeCycleGraph(cycles=[ROW_A, ROW_B])
    with _client(tmp_path, graph) as client:
        resp = client.get("/api/replay/cycles")
    assert resp.status_code == 200
    assert resp.json() == {"cycles": [ROW_A, ROW_B], "next_before": None}
    assert graph.cycle_calls == [(20, None)]


def test_full_page_returns_the_last_created_at_as_cursor(tmp_path: Path) -> None:
    graph = FakeCycleGraph(cycles=[ROW_A, ROW_B])
    with _client(tmp_path, graph) as client:
        body = client.get("/api/replay/cycles", params={"limit": 1}).json()
    assert [c["cycle_id"] for c in body["cycles"]] == [CYCLE_A]
    assert body["next_before"] == ROW_A["created_at"]


def test_cursor_from_the_previous_page_is_parsed_and_forwarded(tmp_path: Path) -> None:
    graph = FakeCycleGraph(cycles=[ROW_A, ROW_B])
    with _client(tmp_path, graph) as client:
        body = client.get("/api/replay/cycles", params={"limit": 1, "before": ROW_A["created_at"]}).json()
    assert [c["cycle_id"] for c in body["cycles"]] == [CYCLE_B]
    limit, before = graph.cycle_calls[-1]
    assert limit == 1
    assert before == datetime(2099, 1, 3, 0, 0, 0, 123456, tzinfo=UTC)


def test_unencoded_plus_in_the_cursor_is_rejected(tmp_path: Path) -> None:
    # A raw "+" decodes to a space; the frontend must URL-encode the cursor.
    with _client(tmp_path, FakeCycleGraph(cycles=[ROW_A])) as client:
        resp = client.get("/api/replay/cycles?before=2099-01-03T00:00:00+00:00")
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "validation_error"


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "limit=abc", "before=yesterday"])
def test_invalid_query_is_a_validation_error(tmp_path: Path, query: str) -> None:
    with _client(tmp_path, FakeCycleGraph()) as client:
        resp = client.get(f"/api/replay/cycles?{query}")
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "validation_error"


def test_without_neo4j_returns_503(tmp_path: Path) -> None:
    with _client(tmp_path, None) as client:
        resp = client.get("/api/replay/cycles")
    assert resp.status_code == 503
    assert resp.json()["detail"]["error"] == "graph_unavailable"
