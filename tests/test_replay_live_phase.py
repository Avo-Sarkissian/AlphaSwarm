"""Replay never overwrites the live phase (docs/DECISIONS.md#adr-replaystore-separate)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from alphaswarm.state import AgentState, StateStore
from alphaswarm.types import SignalType, SimulationPhase
from alphaswarm.web.broadcaster import snapshot_to_json
from alphaswarm.web.replay_manager import ReplayManager
from alphaswarm.web.routes.replay import router as replay_router
from alphaswarm.web.routes.report import router as report_router
from tests.support.web_app import CYCLE_A, FakeCycleGraph, block_service_jobs, make_route_app, route_test_settings

_SIGNALS = {CYCLE_A: {("quants_01", 1): AgentState(signal=SignalType.BUY, confidence=0.8)}}


async def test_replay_start_and_stop_leave_the_live_phase_alone() -> None:
    store = StateStore()
    await store.set_phase(SimulationPhase.COMPLETE)
    replay = ReplayManager(SimpleNamespace(state_store=store))  # type: ignore[arg-type]
    graph = FakeCycleGraph(signals=_SIGNALS)
    await replay.start(CYCLE_A, await graph.read_full_cycle_signals(CYCLE_A), MagicMock(), graph)  # type: ignore[arg-type]
    assert store.snapshot().phase is SimulationPhase.COMPLETE
    assert json.loads(snapshot_to_json(store, replay))["phase"] == "replay"
    await replay.stop()
    assert store.snapshot().phase is SimulationPhase.COMPLETE
    assert json.loads(snapshot_to_json(store, replay))["phase"] == "complete"


def test_report_after_replay_start_and_stop_is_202(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    block_service_jobs(monkeypatch)
    graph = FakeCycleGraph({CYCLE_A: "complete"}, signals=_SIGNALS)
    app = make_route_app(replay_router, report_router, settings=route_test_settings(tmp_path), graph=graph)
    with TestClient(app) as client:
        assert client.post(f"/api/replay/start/{CYCLE_A}").status_code == 200
        assert client.post("/api/replay/stop").status_code == 200
        assert client.post(f"/api/report/{CYCLE_A}/generate").status_code == 202
