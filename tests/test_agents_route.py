"""GET /api/agents/{agent_id}/decisions. Fictional data only."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alphaswarm.web.app import create_app
from alphaswarm.web.routes.agents import router as agents_router
from tests.support.web_app import (
    CYCLE_A,
    CYCLE_UNKNOWN,
    FakeCycleGraph,
    make_route_app,
    route_test_settings,
)

ROWS: list[dict[str, object]] = [
    {
        "round_num": 1,
        "signal": "buy",
        "confidence": 0.8,
        "sentiment": 0.4,
        "rationale": "ZZZT deal looks accretive",
        "cited_agents": [],
    },
    {
        "round_num": 2,
        "signal": "sell",
        "confidence": 0.65,
        "sentiment": -0.2,
        "rationale": "Financing risk on QQQX",
        "cited_agents": ["degens_02", "macro_03"],
    },
]
URL = "/api/agents/quants_01/decisions"


def _client(tmp_path: Path, graph: FakeCycleGraph | None) -> TestClient:
    return TestClient(
        make_route_app(agents_router, settings=route_test_settings(tmp_path), graph=graph)
    )


def test_returns_the_agents_decisions_for_the_cycle(tmp_path: Path) -> None:
    graph = FakeCycleGraph({CYCLE_A: "complete"}, decisions={(CYCLE_A, "quants_01"): ROWS})
    with _client(tmp_path, graph) as client:
        resp = client.get(URL, params={"cycle_id": CYCLE_A})
    assert resp.status_code == 200
    assert resp.json() == {"agent_id": "quants_01", "cycle_id": CYCLE_A, "decisions": ROWS}
    assert graph.decision_calls == [(CYCLE_A, "quants_01")]


def test_running_cycle_is_readable(tmp_path: Path) -> None:
    graph = FakeCycleGraph({CYCLE_A: "running"}, decisions={(CYCLE_A, "quants_01"): ROWS[:1]})
    with _client(tmp_path, graph) as client:
        resp = client.get(URL, params={"cycle_id": CYCLE_A})
    assert resp.status_code == 200
    assert [d["round_num"] for d in resp.json()["decisions"]] == [1]


def test_unknown_cycle_is_404_and_skips_the_read(tmp_path: Path) -> None:
    graph = FakeCycleGraph({CYCLE_A: "complete"})
    with _client(tmp_path, graph) as client:
        resp = client.get(URL, params={"cycle_id": CYCLE_UNKNOWN})
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "cycle_not_found"
    assert graph.decision_calls == []


def test_agent_outside_the_roster_is_404(tmp_path: Path) -> None:
    with _client(tmp_path, FakeCycleGraph({CYCLE_A: "complete"})) as client:
        resp = client.get("/api/agents/quants_99/decisions", params={"cycle_id": CYCLE_A})
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "agent_not_found"


@pytest.mark.parametrize(
    "path",
    [
        f"/api/agents/Q-03/decisions?cycle_id={CYCLE_A}",
        URL,
        f"{URL}?cycle_id=not-a-uuid",
        f"{URL}?cycle_id={CYCLE_A}%0A",
    ],
)
def test_malformed_input_is_a_validation_error(tmp_path: Path, path: str) -> None:
    with _client(tmp_path, FakeCycleGraph({CYCLE_A: "complete"})) as client:
        resp = client.get(path)
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "validation_error"


def test_without_neo4j_returns_503(tmp_path: Path) -> None:
    with _client(tmp_path, None) as client:
        resp = client.get(URL, params={"cycle_id": CYCLE_A})
    assert resp.status_code == 503
    assert resp.json()["detail"]["error"] == "graph_unavailable"


def test_production_app_registers_the_route(tmp_path: Path) -> None:
    app = create_app(route_test_settings(tmp_path))
    assert "/api/agents/{agent_id}/decisions" in {getattr(r, "path", None) for r in app.routes}
