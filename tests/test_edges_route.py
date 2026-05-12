"""Regression test for GET /api/edges/{cycle_id} (ITEM 2 of quick task 260512-jqn).

Symptom that motivated this test:
    On cycle 7ab3984d-36a5-4d6a-9178-bfaa842b15d2 (100 R3 decisions written),
    `curl /api/edges/{cycle_id}?round=3` returned {"edges": []} despite the
    cycle clearly having peer citations. Root cause: simulation.py only calls
    compute_influence_edges() for up_to_round=1 and up_to_round=2 — round 3
    INFLUENCED_BY edges are never materialized into Neo4j.

These tests assert:
    1. The route envelope is { "edges": [...] } (NOT a flat array).
    2. The route returns whatever graph_manager.read_influence_edges yields
       (no filtering / transformation that could drop rows).
    3. Missing cycle / empty result → { "edges": [] }, NOT 404.

We mock the graph_manager.read_influence_edges call so the route test runs
hermetically (--disable-socket / --allow-unix-socket pytest config).
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_test_app_with_fake_graph(fake_edges: list[dict[str, Any]]) -> FastAPI:
    """Build a test FastAPI app with a fake graph_manager returning fake_edges.

    Mirrors the lifespan pattern in tests/test_web.py:_make_test_app, but
    overrides graph_manager.read_influence_edges with a controllable fake so
    the route's Cypher path is exercised without hitting Neo4j.
    """
    from collections.abc import AsyncGenerator
    from contextlib import asynccontextmanager

    from alphaswarm.app import create_app_state
    from alphaswarm.config import AppSettings, generate_personas, load_bracket_configs
    from alphaswarm.web.routes.edges import router as edges_router

    class _FakeGraphManager:
        def __init__(self, edges: list[dict[str, Any]]) -> None:
            self._edges = edges
            self.calls: list[tuple[str, int]] = []

        async def read_influence_edges(
            self, cycle_id: str, round_num: int,
        ) -> list[dict[str, Any]]:
            self.calls.append((cycle_id, round_num))
            return list(self._edges)

        async def read_latest_cycle_id(self) -> str | None:
            return "latest-cycle"

        async def close(self) -> None:
            return None

    @asynccontextmanager
    async def _unit_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        settings = AppSettings(_env_file=None)  # type: ignore[call-arg]
        brackets = load_bracket_configs()
        personas = generate_personas(brackets)
        app_state = create_app_state(
            settings, personas, with_ollama=False, with_neo4j=False,
        )
        # Override with our fake — production path goes through app.state.app_state.graph_manager
        app_state.graph_manager = _FakeGraphManager(fake_edges)
        app.state.app_state = app_state
        yield

    app = FastAPI(lifespan=_unit_lifespan)
    app.include_router(edges_router, prefix="/api")
    return app


def test_edges_route_returns_envelope_with_edges() -> None:
    """Non-empty result MUST come back wrapped in { "edges": [...] }."""
    fake_edges = [
        {"source_id": "quants_01", "target_id": "insiders_04", "weight": 0.42},
        {"source_id": "quants_02", "target_id": "degens_07", "weight": 0.33},
        {"source_id": "macro_05",  "target_id": "quants_01", "weight": 0.21},
    ]
    app = _make_test_app_with_fake_graph(fake_edges)
    with TestClient(app) as client:
        resp = client.get("/api/edges/test-cycle?round=3")
    assert resp.status_code == 200
    body = resp.json()
    assert "edges" in body, f"Response envelope must contain 'edges' key, got {body!r}"
    assert isinstance(body["edges"], list)
    assert len(body["edges"]) == 3
    assert body["edges"][0]["source_id"] == "quants_01"
    assert body["edges"][0]["target_id"] == "insiders_04"


def test_edges_route_empty_result_returns_empty_array() -> None:
    """No edges in store → { "edges": [] } with 200 status (NOT 404)."""
    app = _make_test_app_with_fake_graph([])
    with TestClient(app) as client:
        resp = client.get("/api/edges/cycle-with-no-edges?round=3")
    assert resp.status_code == 200
    assert resp.json() == {"edges": []}


def test_edges_route_passes_round_param_through() -> None:
    """The `round` query param must reach the graph_manager call verbatim."""
    fake_edges = [{"source_id": "a", "target_id": "b", "weight": 0.1}]
    app = _make_test_app_with_fake_graph(fake_edges)
    with TestClient(app) as client:
        # Round 1
        resp1 = client.get("/api/edges/c1?round=1")
        assert resp1.status_code == 200
        # Round 3
        resp3 = client.get("/api/edges/c1?round=3")
        assert resp3.status_code == 200
        # Both should hit the graph manager with the right round
        gm = client.app.state.app_state.graph_manager
        rounds = [call[1] for call in gm.calls]
        assert 1 in rounds
        assert 3 in rounds


def test_edges_route_rejects_invalid_round() -> None:
    """Round must be in [1, 3] — FastAPI Query validation rejects 0, 4, etc."""
    app = _make_test_app_with_fake_graph([])
    with TestClient(app) as client:
        r0 = client.get("/api/edges/c1?round=0")
        assert r0.status_code == 422  # Pydantic validation error
        r4 = client.get("/api/edges/c1?round=4")
        assert r4.status_code == 422
