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


async def test_run_uses_the_inference_runtime_and_records_typed_telemetry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alphaswarm.inference.budget import BudgetMeter
    from alphaswarm.inference.factory import BuiltProviders
    from alphaswarm.inference.types import ProviderRole
    from alphaswarm.services.runtime import build_runtime
    from tests.inference.fakes import FakeInferenceProvider

    runtime = build_runtime(route_test_settings(tmp_path), with_ollama=False, with_neo4j=False)
    runtime.app_state.graph_manager = MagicMock()
    meter = BudgetMeter(None, {})
    providers = BuiltProviders(
        orchestrator=FakeInferenceProvider(ProviderRole.ORCHESTRATOR, "o", scripted=[]),
        worker=FakeInferenceProvider(ProviderRole.WORKER, "w", scripted=[]),
        budget_meter=meter,
    )
    opened: list[str] = []

    async def _open(name: str) -> BuiltProviders:
        opened.append(name)
        object.__setattr__(runtime.inference, "_last_meter", meter)
        return providers

    monkeypatch.setattr(runtime.inference, "open_operation", _open)
    monkeypatch.setattr(runtime.inference, "build_controller", AsyncMock(return_value=MagicMock()))
    captured: dict[str, object] = {}

    async def _fake_run(*args: object, **kwargs: object) -> object:
        captured["deps"] = kwargs["deps"] if "deps" in kwargs else args[1]
        result = MagicMock()
        result.cycle_id = CYCLE_A
        return result

    monkeypatch.setattr("alphaswarm.simulation.run_simulation", _fake_run)
    sm = SimulationManager(runtime.app_state, brackets=[], inference=runtime.inference)
    await sm._run(_SEED)
    assert opened == ["simulation"]
    assert runtime.app_state.budget_meter is meter
    assert runtime.app_state.inference_mode == "local"
    assert captured["deps"].orchestrator is providers.orchestrator  # type: ignore[attr-defined]


def test_simulation_manager_has_no_attr_defined_ignores() -> None:
    import inspect

    import alphaswarm.web.simulation_manager as simulation_manager_module

    source = inspect.getsource(simulation_manager_module)  # independent of the working directory
    assert "type: ignore[attr-defined]" not in source
    assert "build_providers" not in source
