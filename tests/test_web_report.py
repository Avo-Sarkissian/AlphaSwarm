"""Tests for /api/report endpoints (Phase 36 Plan 01).

Covers:
- GET /api/report/{cycle_id}: 200 hit, 404 miss, 400 invalid cycle_id, 500 when a
  prior background generation failed (Codex MEDIUM / T-36-15).
- POST /api/report/{cycle_id}/generate: 202 spawn, 503 services, 409 phase,
  409 in-progress, 400 invalid cycle_id.
- Background task sequence (load -> engine -> assemble -> write -> sentinel -> unload)
  and orchestrator unload on error.
- Static check that the GET handler uses `aiofiles.os` for non-blocking I/O
  (Codex MEDIUM / T-36-14).
- done_callback records task exceptions into app.state.report_generation_error
  so the frontend can surface 500 and stop polling.
"""

from __future__ import annotations

import asyncio
import datetime
import inspect
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from alphaswarm.types import SimulationPhase


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_report_test_app() -> FastAPI:
    """Build a test-friendly FastAPI app that includes the report router.

    Copies the pattern from _make_interview_test_app() in test_web_interview.py.
    Adds:
    - app.state.report_task = None in lifespan (D-02 in-progress guard)
    - app.state.report_generation_error = {} in lifespan (T-36-15 error surface)
    - report_router registered at prefix="/api"
    """
    from alphaswarm.app import create_app_state
    from alphaswarm.config import AppSettings, generate_personas, load_bracket_configs
    from alphaswarm.web.connection_manager import ConnectionManager
    from alphaswarm.web.replay_manager import ReplayManager
    from alphaswarm.web.routes.report import router as report_router
    from alphaswarm.web.simulation_manager import SimulationManager

    @asynccontextmanager
    async def _report_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        settings = AppSettings(_env_file=None)  # type: ignore[call-arg]
        brackets = load_bracket_configs()
        personas = generate_personas(brackets)
        app_state = create_app_state(
            settings, personas, with_ollama=False, with_neo4j=False,
        )
        app.state.interview_sessions = {}
        # Phase 36 D-02: in-progress report generation handle.
        app.state.report_task = None
        # Phase 36 T-36-15: per-cycle error capture from background task done_callback.
        app.state.report_generation_error = {}
        replay_manager = ReplayManager(app_state)
        sim_manager = SimulationManager(
            app_state,
            brackets,
            on_start=lambda: app.state.interview_sessions.clear(),
            replay_manager=replay_manager,
        )
        connection_manager = ConnectionManager()

        app.state.app_state = app_state
        app.state.sim_manager = sim_manager
        app.state.replay_manager = replay_manager
        app.state.connection_manager = connection_manager

        yield

        if app_state.graph_manager is not None:
            await app_state.graph_manager.close()

    app = FastAPI(title="AlphaSwarm-Report-Test", lifespan=_report_lifespan)
    app.include_router(report_router, prefix="/api")
    return app


def _mock_complete_app_state(app: FastAPI) -> None:
    """Set app.state.app_state.state_store snapshot to COMPLETE phase."""
    mock_snap = MagicMock()
    mock_snap.phase = SimulationPhase.COMPLETE
    app.state.app_state.state_store = MagicMock()
    app.state.app_state.state_store.snapshot = MagicMock(return_value=mock_snap)


def _mock_all_services(app: FastAPI) -> None:
    """Assign mock services so the 503 guard passes."""
    app.state.app_state.graph_manager = AsyncMock()
    app.state.app_state.ollama_client = MagicMock()
    app.state.app_state.model_manager = AsyncMock()


# ---------------------------------------------------------------------------
# GET /api/report/{cycle_id}
# ---------------------------------------------------------------------------


def test_get_report_returns_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /api/report/{cycle_id} returns 200 + JSON when file exists."""
    monkeypatch.chdir(tmp_path)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "abc-123_report.md").write_text(
        "# Report\n\nTest content.", encoding="utf-8",
    )
    app = _make_report_test_app()
    with TestClient(app) as client:
        r = client.get("/api/report/abc-123")
        assert r.status_code == 200
        data = r.json()
        assert data["cycle_id"] == "abc-123"
        assert data["content"] == "# Report\n\nTest content."
        assert "generated_at" in data
        # generated_at must be a parseable ISO-8601 timestamp
        datetime.datetime.fromisoformat(data["generated_at"].replace("Z", "+00:00"))


def test_get_report_404_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /api/report/{cycle_id} returns 404 when file is absent and no failure recorded."""
    monkeypatch.chdir(tmp_path)
    app = _make_report_test_app()
    with TestClient(app) as client:
        r = client.get("/api/report/does-not-exist")
        assert r.status_code == 404
        assert r.json()["detail"]["error"] == "report_not_found"


def test_get_report_400_invalid_cycle_id() -> None:
    """GET /api/report/{cycle_id} returns 400 when cycle_id fails regex (T-36-01)."""
    app = _make_report_test_app()
    with TestClient(app) as client:
        r = client.get("/api/report/..bad..traversal..")
        assert r.status_code == 400
        assert r.json()["detail"]["error"] == "invalid_cycle_id"


def test_get_report_500_when_generation_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the last generation for a cycle failed, GET must surface 500 so the
    frontend stops polling instead of timing out after 10 minutes (T-36-15)."""
    monkeypatch.chdir(tmp_path)
    app = _make_report_test_app()
    with TestClient(app) as client:
        # Simulate a prior failed generation for this cycle.
        app.state.report_generation_error = {
            "abc-123": {"error": "report_generation_failed", "message": "boom"},
        }
        r = client.get("/api/report/abc-123")
        assert r.status_code == 500
        detail = r.json()["detail"]
        assert detail["error"] == "report_generation_failed"
        assert detail["message"] == "boom"
        assert detail["cycle_id"] == "abc-123"


def test_get_report_uses_async_filesystem() -> None:
    """Static check: the GET route must NOT call synchronous Path.exists/Path.stat
    inside the async handler. Verifies we use aiofiles.os.* instead (T-36-14)."""
    from alphaswarm.web.routes import report as report_module

    src = inspect.getsource(report_module.get_report)
    # Must use async filesystem helpers.
    assert "aiofiles.os" in src, (
        "GET handler must use aiofiles.os for non-blocking I/O"
    )
    # Must NOT use blocking stdlib filesystem calls on the Path object directly.
    assert ".exists()" not in src, "Do not use Path.exists() in async handler"
    assert ".stat()" not in src, "Do not use Path.stat() in async handler"


# ---------------------------------------------------------------------------
# POST /api/report/{cycle_id}/generate
# ---------------------------------------------------------------------------


def test_generate_report_503_no_services() -> None:
    """POST /api/report/{cycle_id}/generate returns 503 when services are missing."""
    app = _make_report_test_app()
    _mock_complete_app_state(app)
    with TestClient(app) as client:
        r = client.post("/api/report/abc-123/generate")
        assert r.status_code == 503
        assert r.json()["detail"]["error"] == "services_unavailable"


def test_generate_report_409_wrong_phase() -> None:
    """POST returns 409 when snapshot.phase != COMPLETE (D-01)."""
    app = _make_report_test_app()
    _mock_all_services(app)
    mock_snap = MagicMock()
    mock_snap.phase = SimulationPhase.ROUND_2
    app.state.app_state.state_store = MagicMock()
    app.state.app_state.state_store.snapshot = MagicMock(return_value=mock_snap)
    with TestClient(app) as client:
        r = client.post("/api/report/abc-123/generate")
        assert r.status_code == 409
        assert r.json()["detail"]["error"] == "report_unavailable"
        assert r.json()["detail"]["current_phase"] == "round_2"


def test_generate_report_409_in_progress() -> None:
    """POST returns 409 when app.state.report_task is a live (not .done()) task (D-02)."""
    app = _make_report_test_app()
    _mock_all_services(app)
    _mock_complete_app_state(app)
    with TestClient(app) as client:
        fake_task = MagicMock()
        fake_task.done = MagicMock(return_value=False)
        app.state.report_task = fake_task
        r = client.post("/api/report/abc-123/generate")
        assert r.status_code == 409
        assert r.json()["detail"]["error"] == "report_generation_in_progress"


def test_generate_report_202_spawns_task() -> None:
    """POST returns 202, spawns asyncio.Task, and clears any stale error for this cycle."""

    async def _noop(*args: object, **kwargs: object) -> None:
        return None

    app = _make_report_test_app()
    _mock_all_services(app)
    _mock_complete_app_state(app)
    with TestClient(app) as client:
        # Pre-seed a stale error for this cycle — it must be cleared on the new spawn.
        app.state.report_generation_error = {
            "abc-123": {"error": "report_generation_failed", "message": "old"},
        }
        with patch(
            "alphaswarm.web.routes.report._run_report_generation",
            side_effect=_noop,
        ):
            r = client.post("/api/report/abc-123/generate")
            assert r.status_code == 202
            data = r.json()
            assert data["status"] == "accepted"
            assert data["cycle_id"] == "abc-123"
            assert app.state.report_task is not None
            assert isinstance(app.state.report_task, asyncio.Task)
            # Stale error for the same cycle must have been cleared.
            assert "abc-123" not in app.state.report_generation_error


def test_generate_report_400_invalid_cycle_id() -> None:
    """POST returns 400 when cycle_id fails regex (T-36-01)."""
    app = _make_report_test_app()
    _mock_all_services(app)
    _mock_complete_app_state(app)
    with TestClient(app) as client:
        r = client.post("/api/report/..bad..traversal../generate")
        assert r.status_code == 400
        assert r.json()["detail"]["error"] == "invalid_cycle_id"


# ---------------------------------------------------------------------------
# Background task pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_generation_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_run_report_generation runs the exact CLI sequence:
    load_model -> engine.run -> assembler.assemble -> write_report -> write_sentinel
    -> unload_model. Mirrors cli.py _handle_report (D-03).
    """
    monkeypatch.chdir(tmp_path)
    from alphaswarm.web.routes import report as report_module

    call_order: list[str] = []

    mock_model_manager = AsyncMock()

    async def _load(_m: str) -> None:
        call_order.append("load_model")

    async def _unload(_m: str) -> None:
        call_order.append("unload_model")

    mock_model_manager.load_model = _load
    mock_model_manager.unload_model = _unload

    mock_gm = AsyncMock()
    mock_gm.read_shock_event = AsyncMock(return_value=None)

    mock_ollama = MagicMock()

    mock_app_state = MagicMock()
    mock_app_state.model_manager = mock_model_manager
    mock_app_state.graph_manager = mock_gm
    mock_app_state.ollama_client = mock_ollama
    mock_app_state.settings = MagicMock()
    mock_app_state.settings.ollama.orchestrator_model_alias = "alphaswarm-orchestrator"

    async def _fake_run(_cid: str) -> list:
        call_order.append("engine_run")
        return []

    def _fake_assemble(_obs: list, _cid: str) -> str:
        call_order.append("assemble")
        return "# Report content"

    async def _fake_write_report(_path: Path, _content: str) -> None:
        call_order.append("write_report")

    async def _fake_write_sentinel(_cid: str, _path: str) -> None:
        call_order.append("write_sentinel")

    with patch.object(report_module, "ReportEngine") as MockEngine, \
            patch.object(report_module, "ReportAssembler") as MockAssembler, \
            patch.object(report_module, "write_report", side_effect=_fake_write_report), \
            patch.object(report_module, "write_sentinel", side_effect=_fake_write_sentinel):
        engine_instance = MagicMock()
        engine_instance.run = _fake_run
        MockEngine.return_value = engine_instance
        assembler_instance = MagicMock()
        assembler_instance.assemble = _fake_assemble
        MockAssembler.return_value = assembler_instance

        await report_module._run_report_generation(mock_app_state, "abc-123")

    assert call_order == [
        "load_model",
        "engine_run",
        "assemble",
        "write_report",
        "write_sentinel",
        "unload_model",
    ]


@pytest.mark.asyncio
async def test_report_generation_unloads_on_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Orchestrator unload runs in finally even when engine.run raises."""
    monkeypatch.chdir(tmp_path)
    from alphaswarm.web.routes import report as report_module

    unload_called: list[bool] = []
    mock_model_manager = AsyncMock()
    mock_model_manager.load_model = AsyncMock()

    async def _unload(_m: str) -> None:
        unload_called.append(True)

    mock_model_manager.unload_model = _unload

    mock_app_state = MagicMock()
    mock_app_state.model_manager = mock_model_manager
    mock_app_state.graph_manager = AsyncMock()
    mock_app_state.graph_manager.read_shock_event = AsyncMock(return_value=None)
    mock_app_state.ollama_client = MagicMock()
    mock_app_state.settings = MagicMock()
    mock_app_state.settings.ollama.orchestrator_model_alias = "alphaswarm-orchestrator"

    async def _raise(_cid: str) -> list:
        raise RuntimeError("boom")

    with patch.object(report_module, "ReportEngine") as MockEngine:
        engine_instance = MagicMock()
        engine_instance.run = _raise
        MockEngine.return_value = engine_instance

        with pytest.raises(RuntimeError, match="boom"):
            await report_module._run_report_generation(mock_app_state, "abc-123")

    assert unload_called == [True], "unload_model must be called in finally"


@pytest.mark.asyncio
async def test_report_done_callback_records_error() -> None:
    """done_callback must capture task exceptions into
    app.state.report_generation_error[cycle_id] (T-36-15)."""
    from alphaswarm.web.routes import report as report_module

    app = FastAPI()
    app.state.report_generation_error = {}

    # Failed task path — the callback must record the exception.
    async def _raise() -> None:
        raise RuntimeError("boom")

    failed_task = asyncio.create_task(_raise())
    with pytest.raises(RuntimeError):
        await failed_task

    report_module._on_report_task_done(failed_task, "abc-123", app)

    assert "abc-123" in app.state.report_generation_error
    err = app.state.report_generation_error["abc-123"]
    assert err["error"] == "report_generation_failed"
    assert err["message"] == "boom"

    # Successful task path — callback must NOT touch the dict.
    async def _ok() -> None:
        return None

    good_task = asyncio.create_task(_ok())
    await good_task
    report_module._on_report_task_done(good_task, "other-cycle", app)
    assert "other-cycle" not in app.state.report_generation_error
