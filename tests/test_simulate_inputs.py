"""POST /api/simulate/start rejects empty and oversized seeds (T4.8)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from alphaswarm.web.routes.simulation import router as simulation_router
from alphaswarm.web.simulation_manager import ReplayActiveError, SimulationAlreadyRunningError
from tests.support.web_app import make_route_app, route_test_settings

_SEED = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."


@pytest.fixture(autouse=True)
def _keep_logging_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop create_app_state() from reconfiguring structlog for the session.

    Logger proxies cached earlier in the run hold the processor list that was
    configured then; a new configuration would leave later capture_logs tests
    blind to their events.
    """
    monkeypatch.setattr("alphaswarm.app.configure_logging", lambda **_: None)


@pytest.mark.parametrize("seed", ["", "    ", "nine char", "x" * 2001])
def test_bad_seeds_are_422_and_never_reach_the_manager(tmp_path: Path, seed: str) -> None:
    app = make_route_app(simulation_router, settings=route_test_settings(tmp_path))
    with (
        TestClient(app) as client,
        patch.object(app.state.sim_manager, "start", new=AsyncMock()) as start,
    ):
        r = client.post("/api/simulate/start", json={"seed": seed})
    assert r.status_code == 422
    assert r.json()["detail"]["fields"][0]["loc"] == ["body", "seed"]
    start.assert_not_awaited()


def test_seed_is_stripped_before_start(tmp_path: Path) -> None:
    app = make_route_app(simulation_router, settings=route_test_settings(tmp_path))
    with (
        TestClient(app) as client,
        patch.object(app.state.sim_manager, "start", new=AsyncMock()) as start,
    ):
        r = client.post("/api/simulate/start", json={"seed": f"  {_SEED}  "})
    assert r.status_code == 202
    start.assert_awaited_once_with(_SEED)


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (SimulationAlreadyRunningError("Simulation already running"), "simulation_already_running"),
        (ReplayActiveError("Cannot start simulation while replay is active"), "replay_active"),
    ],
)
def test_manager_conflicts_are_409(tmp_path: Path, exc: Exception, code: str) -> None:
    app = make_route_app(simulation_router, settings=route_test_settings(tmp_path))
    with (
        TestClient(app) as client,
        patch.object(app.state.sim_manager, "start", new=AsyncMock(side_effect=exc)),
    ):
        r = client.post("/api/simulate/start", json={"seed": _SEED})
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == code


def test_stop_without_a_run_is_409(tmp_path: Path) -> None:
    app = make_route_app(simulation_router, settings=route_test_settings(tmp_path))
    with TestClient(app) as client:
        r = client.post("/api/simulate/stop")
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "no_simulation_running"
