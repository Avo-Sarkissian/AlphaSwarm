"""NR-5: GET /api/edges/{cycle_id} validation + happy path tests.

Pins the contract for Plan 41.1-08:
- round=0 returns 200 with empty list (pre-simulation, NOT 422)
- round=1..3 returns 200 with INFLUENCED_BY edge list
- round=-1 / round=4 → 422 (out of range)
- graph_manager None → 503
- cycle_id="current" resolves via read_latest_cycle_id
- EdgeItem schema field names are source_id / target_id (NOT source / target)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from alphaswarm.web.routes.edges import router as edges_router


def _make_app(graph_manager: object | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(edges_router, prefix="/api")
    app_state = MagicMock()
    app_state.graph_manager = graph_manager
    app.state.app_state = app_state
    return app


def test_round_zero_returns_empty_list() -> None:
    """Round 0 = pre-simulation; valid call → 200 with empty edge list (NR-5 fix)."""
    gm = MagicMock()
    gm.read_influence_edges = AsyncMock(return_value=[])
    client = TestClient(_make_app(gm))
    r = client.get("/api/edges/cyc-1?round=0")
    assert r.status_code == 200
    assert r.json() == {"edges": []}


def test_round_negative_rejected() -> None:
    """Round -1 is invalid → 422."""
    gm = MagicMock()
    client = TestClient(_make_app(gm))
    r = client.get("/api/edges/cyc-1?round=-1")
    assert r.status_code == 422


def test_round_too_high_rejected() -> None:
    """Round 4 is out of range → 422."""
    gm = MagicMock()
    client = TestClient(_make_app(gm))
    r = client.get("/api/edges/cyc-1?round=4")
    assert r.status_code == 422


def test_round_in_range_returns_edges() -> None:
    """Round 1..3 with mocked manager → 200 with EdgeItem list."""
    gm = MagicMock()
    gm.read_influence_edges = AsyncMock(return_value=[
        {"source_id": "Q-01", "target_id": "Q-03", "weight": 0.7},
        {"source_id": "D-04", "target_id": "Q-03", "weight": 0.4},
    ])
    client = TestClient(_make_app(gm))
    r = client.get("/api/edges/cyc-1?round=2")
    assert r.status_code == 200
    body = r.json()
    assert len(body["edges"]) == 2
    assert body["edges"][0]["source_id"] == "Q-01"
    assert body["edges"][0]["target_id"] == "Q-03"
    assert body["edges"][0]["weight"] == pytest.approx(0.7)


def test_graph_manager_none_returns_503() -> None:
    """No graph_manager attached → 503 service unavailable."""
    client = TestClient(_make_app(graph_manager=None))
    r = client.get("/api/edges/cyc-1?round=1")
    assert r.status_code == 503


def test_current_resolves_latest() -> None:
    """cycle_id='current' triggers read_latest_cycle_id then read_influence_edges."""
    gm = MagicMock()
    gm.read_latest_cycle_id = AsyncMock(return_value="cyc-resolved")
    gm.read_influence_edges = AsyncMock(return_value=[])
    client = TestClient(_make_app(gm))
    r = client.get("/api/edges/current?round=1")
    assert r.status_code == 200
    gm.read_influence_edges.assert_awaited_once_with("cyc-resolved", 1)


def test_edge_keys_are_source_id_target_id() -> None:
    """EdgeItem schema field names lock to source_id / target_id (NR-5 contract)."""
    from alphaswarm.web.routes.edges import EdgeItem
    e = EdgeItem(source_id="A", target_id="B", weight=0.5)
    assert e.model_dump() == {"source_id": "A", "target_id": "B", "weight": 0.5}
