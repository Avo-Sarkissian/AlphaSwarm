"""POST /api/replay/round/{round_num}: the round scrubber's seek (adr-replaystore-separate)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from alphaswarm.state import AgentState
from alphaswarm.types import SignalType
from alphaswarm.web.routes.replay import router as replay_router
from tests.support.web_app import CYCLE_A, make_route_app, route_test_settings

SIGNALS = {("quants_01", n): AgentState(signal=SignalType.BUY, confidence=0.5) for n in (1, 2, 3)}


class ReplayGraph:
    """The two replay reads, one bracket and one rationale per round."""

    async def read_bracket_narratives_for_round(self, cycle_id: str, round_num: int) -> list[dict[str, object]]:
        return [
            {
                "bracket": "quants",
                "buy_count": round_num,
                "sell_count": 0,
                "hold_count": 0,
                "total": round_num,
                "avg_confidence": 0.5,
                "avg_sentiment": 0.0,
            }
        ]

    async def read_rationale_entries_for_round(
        self, cycle_id: str, round_num: int, limit: int = 10
    ) -> list[dict[str, object]]:
        return [
            {
                "agent_id": "quants_01",
                "signal": "buy",
                "rationale": f"round {round_num} view",
                "round_num": round_num,
            }
        ]

    async def close(self) -> None:
        return None


@asynccontextmanager
async def _client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            yield client


async def test_seek_moves_the_active_replay(tmp_path: Path) -> None:
    graph = ReplayGraph()
    app = make_route_app(replay_router, settings=route_test_settings(tmp_path), graph=graph)
    async with _client(app) as client:
        await app.state.replay_manager.start(CYCLE_A, SIGNALS, graph)
        resp = await client.post("/api/replay/round/3")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "round_num": 3}
        assert app.state.replay_manager.round_num == 3


async def test_seek_without_a_replay_is_409(tmp_path: Path) -> None:
    app = make_route_app(replay_router, settings=route_test_settings(tmp_path), graph=ReplayGraph())
    async with _client(app) as client:
        resp = await client.post("/api/replay/round/2")
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "no_replay_active"


@pytest.mark.parametrize("path", ["/api/replay/round/0", "/api/replay/round/4", "/api/replay/round/x"])
async def test_round_out_of_range_is_a_validation_error(tmp_path: Path, path: str) -> None:
    app = make_route_app(replay_router, settings=route_test_settings(tmp_path), graph=ReplayGraph())
    async with _client(app) as client:
        resp = await client.post(path)
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "validation_error"
