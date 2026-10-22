"""Shock window in SimulationManager and POST /api/simulate/shock."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from alphaswarm.state import StateStore
from alphaswarm.types import SimulationPhase
from alphaswarm.web.routes.simulation import router as simulation_router
from alphaswarm.web.simulation_manager import (
    ShockAlreadyQueuedError,
    ShockWindowClosedError,
    SimulationManager,
)
from tests.support.web_app import make_route_app, route_test_settings

_SHOCK = "Fed cuts 50bp at emergency session"


@pytest.fixture(autouse=True)
def _keep_logging_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop create_app_state() from reconfiguring structlog for the session.

    Logger proxies cached earlier in the run hold the processor list that was
    configured then; a new configuration would leave later capture_logs tests
    blind to their events.
    """
    monkeypatch.setattr("alphaswarm.app.configure_logging", lambda **_: None)


async def _running_manager(phase: SimulationPhase, num_rounds: int = 3) -> tuple[SimulationManager, StateStore]:
    store = StateStore()
    store.set_num_rounds(num_rounds)
    await store.set_phase(phase)
    app_state = SimpleNamespace(state_store=store)
    manager = SimulationManager(app_state, brackets=[])  # type: ignore[arg-type]
    manager._is_running = True
    return manager, store


async def test_open_window_queues_and_mirrors_into_the_store() -> None:
    manager, store = await _running_manager(SimulationPhase.ROUND_1)
    manager.inject_shock(_SHOCK)
    assert store.snapshot().pending_shock == _SHOCK
    assert manager.consume_shock() == _SHOCK
    assert store.snapshot().pending_shock is None


@pytest.mark.parametrize(
    ("phase", "num_rounds"),
    [(SimulationPhase.ROUND_3, 3), (SimulationPhase.ROUND_2, 2), (SimulationPhase.FINALIZING, 3)],
)
async def test_closed_window_refuses_the_shock(phase: SimulationPhase, num_rounds: int) -> None:
    manager, store = await _running_manager(phase, num_rounds)
    with pytest.raises(ShockWindowClosedError):
        manager.inject_shock(_SHOCK)
    assert manager.pending_shock is None
    assert store.snapshot().pending_shock is None


async def test_second_shock_while_one_is_queued() -> None:
    manager, _ = await _running_manager(SimulationPhase.SEEDING)
    manager.inject_shock(_SHOCK)
    with pytest.raises(ShockAlreadyQueuedError):
        manager.inject_shock("CEO denies acquisition talks publicly")


async def test_run_end_clears_the_store_mirror() -> None:
    manager, store = await _running_manager(SimulationPhase.ROUND_1)
    manager.inject_shock(_SHOCK)
    await manager._lock.acquire()
    task = MagicMock()
    task.cancelled.return_value = True
    manager._on_task_done(task)
    assert store.snapshot().pending_shock is None


def test_route_returns_409_when_the_window_is_closed(tmp_path: Path) -> None:
    app = make_route_app(simulation_router, settings=route_test_settings(tmp_path))
    with TestClient(app) as client:
        app.state.sim_manager._is_running = True  # live phase is IDLE: window closed
        r = client.post("/api/simulate/shock", json={"shock_text": _SHOCK})
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "shock_window_closed"


def test_route_queues_the_stripped_text_while_open(tmp_path: Path) -> None:
    app = make_route_app(simulation_router, settings=route_test_settings(tmp_path))
    with TestClient(app) as client:
        app.state.sim_manager._is_running = True
        app.state.app_state.state_store._phase = SimulationPhase.ROUND_1
        r = client.post("/api/simulate/shock", json={"shock_text": f"  {_SHOCK}  "})
        assert r.status_code == 200
        assert app.state.sim_manager.pending_shock == _SHOCK


@pytest.mark.parametrize("text", ["too short", "x" * 1001])
def test_route_rejects_bad_shock_lengths(tmp_path: Path, text: str) -> None:
    app = make_route_app(simulation_router, settings=route_test_settings(tmp_path))
    with TestClient(app) as client:
        r = client.post("/api/simulate/shock", json={"shock_text": text})
    assert r.status_code == 422
