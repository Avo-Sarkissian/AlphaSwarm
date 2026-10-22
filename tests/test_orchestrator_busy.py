"""start() refuses a run while post-run jobs hold the orchestrator.

See docs/DECISIONS.md#adr-sequential-model-lifecycle.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from alphaswarm.state import JobStatus
from alphaswarm.web.routes.settings import router as settings_router
from alphaswarm.web.routes.simulation import router as simulation_router
from alphaswarm.web.simulation_manager import PostRunJobsInProgressError, SimulationManager
from tests.support.web_app import CYCLE_A, make_route_app, route_test_settings

_SEED = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."


async def test_start_refused_while_the_probe_reports_busy() -> None:
    sm = SimulationManager(MagicMock(), brackets=[], orchestrator_busy=lambda: True)
    with pytest.raises(PostRunJobsInProgressError):
        await sm.start(_SEED)
    assert not sm._lock.locked()
    assert sm.is_running is False


async def test_start_refused_while_post_run_task_pending() -> None:
    sm = SimulationManager(MagicMock(), brackets=[])
    pending = asyncio.create_task(asyncio.sleep(10))
    sm._bg_tasks.add(pending)
    try:
        with pytest.raises(PostRunJobsInProgressError):
            await sm.start(_SEED)
        assert not sm._lock.locked()
    finally:
        pending.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pending


async def test_start_allowed_when_nothing_is_busy() -> None:
    app_state = MagicMock()
    app_state.state_store.set_last_error = AsyncMock()  # StateStore.set_last_error is a coroutine
    sm = SimulationManager(app_state, brackets=[], orchestrator_busy=lambda: False)
    with patch.object(sm, "_run", AsyncMock(return_value=None)):
        await sm.start(_SEED)
        assert sm._task is not None
        await sm._task
    await asyncio.sleep(0)
    assert not sm._lock.locked()


def test_simulate_start_409_during_advisory_job(tmp_path: Path) -> None:
    app = make_route_app(simulation_router, settings=route_test_settings(tmp_path))
    with TestClient(app) as client:
        app.state.app_state.state_store.set_job_status("advisory", JobStatus("running", CYCLE_A))
        r = client.post("/api/simulate/start", json={"seed": _SEED})
        assert r.status_code == 409
        assert r.json()["detail"]["error"] == "post_run_jobs_in_progress"
        assert app.state.sim_manager.is_running is False


def test_settings_connection_test_409_while_simulation_runs(tmp_path: Path) -> None:
    app = make_route_app(settings_router, settings=route_test_settings(tmp_path))
    with TestClient(app) as client:
        app.state.sim_manager._is_running = True
        r = client.post("/api/settings/test", json={"role": "worker"})
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "simulation_running"
