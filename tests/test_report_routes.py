"""Report routes: status-based gating, distinct codes, job status.

See docs/DECISIONS.md#adr-background-tasks.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import alphaswarm.web.guards as guards_module
import alphaswarm.web.routes.report as report_module
from alphaswarm.errors import InferenceConfigError, Neo4jUnavailableError
from alphaswarm.state import JobStatus, StateStore
from alphaswarm.web.routes.report import router as report_router
from tests.support.log_capture import RenderedLog
from tests.support.web_app import (
    CYCLE_A,
    CYCLE_B,
    CYCLE_UNKNOWN,
    FakeCycleGraph,
    make_route_app,
    route_test_settings,
)

_REAL_GENERATION = report_module._run_report_generation


@pytest.fixture(autouse=True)
def _blocked_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the real report run with a coroutine that waits until cancelled."""

    async def _blocked(app_state: Any, cycle_id: str) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(report_module, "_run_report_generation", _blocked)


def _app(tmp_path: Path, graph: FakeCycleGraph | None = None) -> FastAPI:
    return make_route_app(
        report_router,
        settings=route_test_settings(tmp_path),
        graph=graph if graph is not None else FakeCycleGraph({CYCLE_A: "complete"}),
    )


def _store(app: FastAPI) -> StateStore:
    store: StateStore = app.state.app_state.state_store
    return store


def _write_report(tmp_path: Path, cycle_id: str, text: str = "# Report\n") -> None:
    (tmp_path / "reports").mkdir(exist_ok=True)
    (tmp_path / "reports" / f"{cycle_id}_report.md").write_text(text, encoding="utf-8")


def test_get_reads_from_settings_dir_not_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_report(tmp_path, CYCLE_A)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    with TestClient(_app(tmp_path)) as client:
        r = client.get(f"/api/report/{CYCLE_A}")
    assert r.status_code == 200
    assert r.json()["cycle_id"] == CYCLE_A
    assert r.json()["content"] == "# Report\n"


def test_get_404_when_absent(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        r = client.get(f"/api/report/{CYCLE_A}")
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "report_not_found"


def test_get_500_when_failure_recorded(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        app.state.report_generation_error = {
            CYCLE_A: {"error": "report_generation_failed", "message": "Report generation failed"},
        }
        r = client.get(f"/api/report/{CYCLE_A}")
    assert r.status_code == 500
    assert r.json()["detail"] == {
        "error": "report_generation_failed",
        "message": "Report generation failed",
        "cycle_id": CYCLE_A,
    }


def test_get_409_while_that_cycles_job_runs(tmp_path: Path) -> None:
    _write_report(tmp_path, CYCLE_A, "old")
    app = _app(tmp_path)
    with TestClient(app) as client:
        _store(app).set_job_status("report", JobStatus("running", CYCLE_A))
        r = client.get(f"/api/report/{CYCLE_A}")
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "report_generation_in_progress"


def test_get_ignores_a_job_for_another_cycle(tmp_path: Path) -> None:
    _write_report(tmp_path, CYCLE_A)
    app = _app(tmp_path)
    with TestClient(app) as client:
        _store(app).set_job_status("report", JobStatus("running", CYCLE_B))
        assert client.get(f"/api/report/{CYCLE_A}").status_code == 200


@pytest.mark.parametrize("bad", ["abc-123", f"{CYCLE_A}%0A", CYCLE_A.upper()])
def test_malformed_ids_are_422(tmp_path: Path, bad: str) -> None:
    with TestClient(_app(tmp_path)) as client:
        for r in (client.get(f"/api/report/{bad}"), client.post(f"/api/report/{bad}/generate")):
            assert r.status_code == 422
            assert r.json()["detail"]["error"] == "validation_error"


def test_post_202_for_complete_cycle_while_phase_is_idle(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        assert _store(app).snapshot().phase.value == "idle"  # e.g. right after a restart
        app.state.report_generation_error = {CYCLE_A: {"error": "x", "message": "old"}}
        r = client.post(f"/api/report/{CYCLE_A}/generate")
        assert r.status_code == 202
        assert r.json() == {"status": "accepted", "cycle_id": CYCLE_A}
        assert _store(app).job_statuses().report == JobStatus("running", CYCLE_A)
        assert CYCLE_A not in app.state.report_generation_error
        assert isinstance(app.state.report_task, asyncio.Task)


def test_post_404_for_unknown_cycle_starts_nothing(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        r = client.post(f"/api/report/{CYCLE_UNKNOWN}/generate")
        assert r.status_code == 404
        assert r.json()["detail"]["error"] == "cycle_not_found"
        assert app.state.report_task is None
        assert _store(app).job_statuses().report == JobStatus()


@pytest.mark.parametrize("status", ["running", "failed", "cancelled"])
def test_post_422_for_unfinished_cycle(tmp_path: Path, status: str) -> None:
    with TestClient(_app(tmp_path, FakeCycleGraph({CYCLE_A: status}))) as client:
        r = client.post(f"/api/report/{CYCLE_A}/generate")
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "cycle_not_ready"
    assert r.json()["detail"]["cycle_status"] == status


def test_post_409_while_a_simulation_runs(tmp_path: Path) -> None:
    graph = FakeCycleGraph({CYCLE_A: "complete"})
    app = _app(tmp_path, graph)
    with TestClient(app) as client:
        app.state.sim_manager._is_running = True
        r = client.post(f"/api/report/{CYCLE_A}/generate")
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "simulation_running"
    assert graph.status_calls == []


class _RunStartsDuringStatusRead(FakeCycleGraph):
    """POST /api/simulate/start lands while the route awaits the cycle status.

    The run's start() probe passes because no job is marked running yet, so
    the route must check again before it starts the job.
    """

    def __init__(self, statuses: dict[str, str]) -> None:
        super().__init__(statuses)
        self.sim_manager: Any = None

    async def read_cycle_status(self, cycle_id: str) -> str | None:
        status = await super().read_cycle_status(cycle_id)
        self.sim_manager._is_running = True
        return status


def test_post_409_when_a_run_starts_during_the_status_read(tmp_path: Path) -> None:
    graph = _RunStartsDuringStatusRead({CYCLE_A: "complete"})
    app = _app(tmp_path, graph)
    with TestClient(app) as client:
        graph.sim_manager = app.state.sim_manager
        r = client.post(f"/api/report/{CYCLE_A}/generate")
        assert r.status_code == 409
        assert r.json()["detail"]["error"] == "simulation_running"
        assert app.state.report_task is None
        assert _store(app).job_statuses().report == JobStatus()


@pytest.mark.parametrize(
    ("kind", "code"),
    [("report", "report_generation_in_progress"), ("advisory", "advisory_generation_in_progress")],
)
def test_post_409_when_the_orchestrator_is_busy(tmp_path: Path, kind: str, code: str) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        _store(app).set_job_status(kind, JobStatus("running", CYCLE_B))  # type: ignore[arg-type]
        r = client.post(f"/api/report/{CYCLE_A}/generate")
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == code


def test_second_post_while_first_runs_is_409(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        assert client.post(f"/api/report/{CYCLE_A}/generate").status_code == 202
        r = client.post(f"/api/report/{CYCLE_A}/generate")
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "report_generation_in_progress"


def test_post_503_when_neo4j_is_down(tmp_path: Path) -> None:
    graph = FakeCycleGraph(error=Neo4jUnavailableError("down", op="read_cycle_status"))
    with TestClient(_app(tmp_path, graph)) as client:
        r = client.post(f"/api/report/{CYCLE_A}/generate")
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "graph_unavailable"


async def test_generation_fails_with_a_fixed_error_on_an_invalid_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The config error's text quotes the path and raw values, keys included, so the
    job logs only its type and raises a fixed InferenceConfigError from None."""
    canary = "".join(["sk-", "fictional", "-REPORT-CANARY"])  # never in this source
    settings = route_test_settings(tmp_path)
    roles = {
        "orchestrator": {"provider": "anthropic", "api_key": canary},
        "worker": {"provider": "ollama", "model": "alphaswarm-worker"},
    }
    settings.inference_config_path.write_text(json.dumps(roles), encoding="utf-8")
    rendered = RenderedLog()
    monkeypatch.setattr(report_module, "log", rendered)
    monkeypatch.setattr(guards_module, "log", rendered, raising=False)
    app_state = SimpleNamespace(
        settings=settings, graph_manager=object(), ollama_client=object(), model_manager=object(),
    )
    with pytest.raises(InferenceConfigError) as exc_info:
        await _REAL_GENERATION(app_state, CYCLE_A)  # type: ignore[arg-type]
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True
    assert canary not in str(exc_info.value)
    assert rendered.events == ["job_inference_config_invalid"]
    assert canary not in rendered.text
    assert str(tmp_path) not in rendered.text


def test_reports_dir_is_resolved_from_settings(tmp_path: Path) -> None:
    app_state = SimpleNamespace(settings=route_test_settings(tmp_path))
    assert report_module.reports_dir(app_state) == tmp_path / "reports"  # type: ignore[arg-type]


def _callback_app() -> FastAPI:
    app = FastAPI()
    app.state.app_state = SimpleNamespace(state_store=StateStore())
    app.state.report_generation_error = {}
    return app


async def test_done_callback_success_sets_idle() -> None:
    app = _callback_app()

    async def _ok() -> None:
        return None

    task = asyncio.create_task(_ok())
    await task
    report_module._on_report_task_done(task, CYCLE_A, app)
    assert app.state.app_state.state_store.job_statuses().report == JobStatus("idle", CYCLE_A)
    assert app.state.report_generation_error == {}


async def test_done_callback_failure_records_class_name_only() -> None:
    app = _callback_app()

    async def _fail() -> None:
        raise RuntimeError("boom at /Users/someone/secret")

    task = asyncio.create_task(_fail())
    with pytest.raises(RuntimeError):
        await task
    report_module._on_report_task_done(task, CYCLE_A, app)
    assert app.state.report_generation_error[CYCLE_A] == {
        "error": "report_generation_failed",
        "message": "Report generation failed (RuntimeError)",
    }
    assert app.state.app_state.state_store.job_statuses().report == JobStatus(
        "failed",
        CYCLE_A,
        "report_generation_failed",
    )


async def test_done_callback_cancelled_records_failure() -> None:
    app = _callback_app()
    task = asyncio.create_task(asyncio.sleep(10))
    await asyncio.sleep(0)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    report_module._on_report_task_done(task, CYCLE_A, app)
    recorded = app.state.report_generation_error[CYCLE_A]
    assert recorded["message"] == "Report generation was cancelled"
    assert app.state.app_state.state_store.job_statuses().report.state == "failed"
