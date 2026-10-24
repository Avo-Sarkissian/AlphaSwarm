"""Cycle endpoints against the seeded cycle on neo4j-test.

httpx's ASGITransport keeps the request on the session event loop that owns the
neo4j driver; TestClient would run the app on another loop.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from alphaswarm.export import CycleExport
from alphaswarm.graph import GraphStateManager
from alphaswarm.web.routes.cycles import router as cycles_router
from tests.support.seed_builder import SeededCycle
from tests.support.web_app import make_route_app, route_test_settings

pytestmark = pytest.mark.neo4j


@asynccontextmanager
async def _client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            yield client


async def test_citations_endpoint_returns_cited_signal(
    seeded_cycle: SeededCycle, graph_reader: GraphStateManager, tmp_path: Path
) -> None:
    app = make_route_app(cycles_router, settings=route_test_settings(tmp_path), graph=graph_reader)
    url = f"/api/cycles/{seeded_cycle.cycle_id}/citations"
    async with _client(app) as client:
        round_two = await client.get(url, params={"round": 2})
        round_one = await client.get(url, params={"round": 1})

    assert round_two.status_code == 200
    citations = round_two.json()["citations"]
    previous = {agent_id: d.signal.value for agent_id, d in seeded_cycle.decisions[1]}
    assert {(c["source_id"], c["target_id"]) for c in citations} == set(seeded_cycle.cited_pairs[2])
    assert all(c["cited_signal"] == previous[c["target_id"]] for c in citations)
    assert round_one.json()["citations"] == []


async def test_export_endpoint_round_trips_the_seeded_cycle(
    seeded_cycle: SeededCycle, graph_reader: GraphStateManager, tmp_path: Path
) -> None:
    app = make_route_app(cycles_router, settings=route_test_settings(tmp_path), graph=graph_reader)
    async with _client(app) as client:
        resp = await client.get(f"/api/cycles/{seeded_cycle.cycle_id}/export")

    assert resp.status_code == 200
    assert len(resp.content) < 300_000
    export = CycleExport.model_validate_json(resp.content)
    assert export.cycle.cycle_id == seeded_cycle.cycle_id
    assert [r.round_num for r in export.rounds] == [1, 2, 3]
