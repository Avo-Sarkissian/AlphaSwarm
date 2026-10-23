"""Report routes over ReportService + JobRunner.

GET serves the markdown and its structured sections; POST starts a report job.
See docs/DECISIONS.md#adr-background-tasks.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import alphaswarm.services.runtime as runtime_module
from alphaswarm.errors import InferenceConfigError, Neo4jUnavailableError
from alphaswarm.services.report import ReportService
from alphaswarm.state import JobStatus, StateStore
from alphaswarm.web.routes.report import router as report_router
from tests.support.log_capture import RenderedLog
from tests.support.web_app import (
    CYCLE_A,
    CYCLE_B,
    CYCLE_UNKNOWN,
    FakeCycleGraph,
    block_service_jobs,
    make_route_app,
    offline_runtime,
    route_test_settings,
)

SECTIONS = {
    "summary": "Consensus ended BUY.",
    "convergence": [
        {
            "round_num": 1,
            "buy_count": 40,
            "sell_count": 30,
            "hold_count": 28,
            "parse_error_count": 2,
            "total": 100,
        }
    ],
    "influence": [
        {
            "agent_id": "sell_side_03",
            "name": "Sell-Side 3",
            "bracket": "sell_side",
            "citation_count": 9,
            "influence_share": 0.09,
        }
    ],
    "moments": ["R2: sell_side_03 became the most cited agent."],
    "dissent": [],
    "followups": ["Watch QQQX Robotics guidance."],
}


@pytest.fixture(autouse=True)
def _blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    block_service_jobs(monkeypatch)


def _app(tmp_path: Path, graph: FakeCycleGraph | None = None) -> FastAPI:
    return make_route_app(
        report_router,
        settings=route_test_settings(tmp_path),
        graph=graph if graph is not None else FakeCycleGraph({CYCLE_A: "complete"}),
    )


def _store(app: FastAPI) -> StateStore:
    store: StateStore = app.state.app_state.state_store
    return store


def _write(tmp_path: Path, cycle_id: str, text: str = "# Report\n", sections: object = None) -> None:
    reports = tmp_path / "reports"
    reports.mkdir(exist_ok=True)
    (reports / f"{cycle_id}_report.md").write_text(text, encoding="utf-8")
    if sections is not None:
        payload = sections if isinstance(sections, str) else json.dumps(sections)
        (reports / f"{cycle_id}_report.json").write_text(payload, encoding="utf-8")


@contextlib.asynccontextmanager
async def _client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            yield client


def test_get_returns_markdown_and_sections(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, CYCLE_A, sections=SECTIONS)
    monkeypatch.chdir(tmp_path / "reports")  # paths come from settings, not CWD
    with TestClient(_app(tmp_path)) as client:
        body = client.get(f"/api/report/{CYCLE_A}").json()
    assert body["content"] == "# Report\n"
    assert body["sections"] == SECTIONS
    assert body["cycle_id"] == CYCLE_A
    assert body["generated_at"].endswith("+00:00")


def test_get_legacy_report_has_null_sections(tmp_path: Path) -> None:
    _write(tmp_path, CYCLE_A)
    with TestClient(_app(tmp_path)) as client:
        response = client.get(f"/api/report/{CYCLE_A}")
    assert response.status_code == 200
    assert response.json()["sections"] is None


def test_get_unreadable_sidecar_is_null_sections(tmp_path: Path) -> None:
    _write(tmp_path, CYCLE_A, sections="{not json")
    with TestClient(_app(tmp_path)) as client:
        assert client.get(f"/api/report/{CYCLE_A}").json()["sections"] is None


def test_get_404_when_absent(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.get(f"/api/report/{CYCLE_A}")
    assert (response.status_code, response.json()["detail"]["error"]) == (404, "report_not_found")


def test_get_409_only_for_that_cycles_running_job(tmp_path: Path) -> None:
    _write(tmp_path, CYCLE_A)
    app = _app(tmp_path)
    with TestClient(app) as client:
        _store(app).set_job_status("report", JobStatus("running", CYCLE_B))
        assert client.get(f"/api/report/{CYCLE_A}").status_code == 200
        _store(app).set_job_status("report", JobStatus("running", CYCLE_A))
        response = client.get(f"/api/report/{CYCLE_A}")
    assert (response.status_code, response.json()["detail"]["error"]) == (409, "report_generation_in_progress")


async def test_get_500_after_a_failed_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fail(self: ReportService, cycle_id: str) -> None:
        raise RuntimeError("boom at /Users/someone/secret")

    monkeypatch.setattr(ReportService, "generate", _fail)
    app = _app(tmp_path)
    async with _client(app) as client:
        assert (await client.post(f"/api/report/{CYCLE_A}/generate")).status_code == 202
        task = next(t for t in asyncio.all_tasks() if t.get_name() == f"report_{CYCLE_A}")
        with contextlib.suppress(RuntimeError):
            await task
        response = await client.get(f"/api/report/{CYCLE_A}")
    assert response.status_code == 500
    assert response.json()["detail"] == {
        "error": "report_generation_failed",
        "message": "Report generation failed; see the server log",
        "cycle_id": CYCLE_A,
    }


@pytest.mark.parametrize("bad", ["abc-123", f"{CYCLE_A}%0A", CYCLE_A.upper()])
def test_malformed_ids_are_422(tmp_path: Path, bad: str) -> None:
    with TestClient(_app(tmp_path)) as client:
        for response in (client.get(f"/api/report/{bad}"), client.post(f"/api/report/{bad}/generate")):
            assert (response.status_code, response.json()["detail"]["error"]) == (422, "validation_error")


def test_post_202_starts_a_report_job_while_phase_is_idle(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        assert _store(app).snapshot().phase.value == "idle"
        response = client.post(f"/api/report/{CYCLE_A}/generate")
        assert response.status_code == 202
        assert response.json() == {"status": "accepted", "cycle_id": CYCLE_A}
        assert _store(app).job_statuses().report == JobStatus("running", CYCLE_A)


def test_post_404_for_unknown_cycle_starts_nothing(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post(f"/api/report/{CYCLE_UNKNOWN}/generate")
        assert (response.status_code, response.json()["detail"]["error"]) == (404, "cycle_not_found")
        assert _store(app).job_statuses().report == JobStatus()


@pytest.mark.parametrize("cycle_status", ["running", "failed", "cancelled"])
def test_post_422_for_unfinished_cycle(tmp_path: Path, cycle_status: str) -> None:
    with TestClient(_app(tmp_path, FakeCycleGraph({CYCLE_A: cycle_status}))) as client:
        response = client.post(f"/api/report/{CYCLE_A}/generate")
    assert response.status_code == 422
    assert response.json()["detail"]["cycle_status"] == cycle_status


def test_post_409_while_a_simulation_runs(tmp_path: Path) -> None:
    graph = FakeCycleGraph({CYCLE_A: "complete"})
    app = _app(tmp_path, graph)
    with TestClient(app) as client:
        app.state.sim_manager._is_running = True
        response = client.post(f"/api/report/{CYCLE_A}/generate")
    assert (response.status_code, response.json()["detail"]["error"]) == (409, "simulation_running")
    assert graph.status_calls == []


class _RunStartsDuringStatusRead(FakeCycleGraph):
    """A simulation starts while the route awaits the cycle status."""

    sim_manager: Any = None

    async def read_cycle_status(self, cycle_id: str) -> str | None:
        status = await super().read_cycle_status(cycle_id)
        self.sim_manager._is_running = True
        return status


def test_post_409_when_a_run_starts_during_the_status_read(tmp_path: Path) -> None:
    graph = _RunStartsDuringStatusRead({CYCLE_A: "complete"})
    app = _app(tmp_path, graph)
    with TestClient(app) as client:
        graph.sim_manager = app.state.sim_manager
        response = client.post(f"/api/report/{CYCLE_A}/generate")
        assert (response.status_code, response.json()["detail"]["error"]) == (409, "simulation_running")
        assert _store(app).job_statuses().report == JobStatus()


@pytest.mark.parametrize(
    ("kind", "code"),
    [("report", "report_generation_in_progress"), ("advisory", "advisory_generation_in_progress")],
)
def test_post_409_names_the_job_holding_the_orchestrator(tmp_path: Path, kind: str, code: str) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        _store(app).set_job_status(kind, JobStatus("running", CYCLE_B))  # type: ignore[arg-type]
        response = client.post(f"/api/report/{CYCLE_A}/generate")
    assert (response.status_code, response.json()["detail"]["error"]) == (409, code)


def test_second_post_while_first_runs_is_409(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        assert client.post(f"/api/report/{CYCLE_A}/generate").status_code == 202
        response = client.post(f"/api/report/{CYCLE_A}/generate")
    assert response.json()["detail"]["error"] == "report_generation_in_progress"


def test_post_503_when_neo4j_is_down(tmp_path: Path) -> None:
    graph = FakeCycleGraph(error=Neo4jUnavailableError("down", op="read_cycle_status"))
    with TestClient(_app(tmp_path, graph)) as client:
        response = client.post(f"/api/report/{CYCLE_A}/generate")
    assert (response.status_code, response.json()["detail"]["error"]) == (503, "graph_unavailable")


def test_post_503_without_a_graph(tmp_path: Path) -> None:
    app = make_route_app(report_router, settings=route_test_settings(tmp_path), graph=None)
    with TestClient(app) as client:
        response = client.post(f"/api/report/{CYCLE_A}/generate")
    assert (response.status_code, response.json()["detail"]["error"]) == (503, "graph_unavailable")


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
    monkeypatch.setattr(runtime_module, "log", rendered)
    runtime = offline_runtime(settings, graph=FakeCycleGraph({CYCLE_A: "complete"}))
    graph: Any = runtime.app_state.graph_manager
    service = ReportService(
        graph=graph,
        inference=runtime.inference,
        jobs=runtime.jobs,
        reports_dir=tmp_path / "reports",
    )
    monkeypatch.undo()  # the real generate, not block_service_jobs' stand-in
    monkeypatch.setattr(runtime_module, "log", rendered)
    with pytest.raises(InferenceConfigError) as exc_info:
        await service.generate(CYCLE_A)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True
    assert canary not in str(exc_info.value)
    assert rendered.events == ["inference_config_invalid"]
    assert canary not in rendered.text
    assert str(tmp_path) not in rendered.text


def test_routes_use_async_filesystem_probes() -> None:
    import inspect

    import alphaswarm.web.routes.report as report_module

    source = inspect.getsource(report_module)
    assert "aiofiles.os.path.exists" in source
    assert "Path.exists" not in source and ".exists()" not in source
