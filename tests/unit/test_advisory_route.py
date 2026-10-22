"""Unit tests for POST/GET /api/advisory/{cycle_id} (ADVIS-02)."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import alphaswarm.web.routes.advisory as advisory_module
from alphaswarm.config import (
    AppSettings,
    InferenceConfig,
    ProviderType,
    RoleConfig,
)
from alphaswarm.holdings.types import Holding, PortfolioSnapshot
from alphaswarm.types import SimulationPhase
from alphaswarm.web.routes.advisory import (
    _on_advisory_task_done,
    _report_chain_tasks,
)
from alphaswarm.web.routes.advisory import router as advisory_router


def _fake_portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        holdings=(Holding(ticker="AAPL", qty=Decimal("10"), cost_basis=Decimal("100")),),
        as_of=datetime.now(UTC),
        account_number_hash="cafebabe",
    )


def _make_app(
    *,
    phase: SimulationPhase = SimulationPhase.COMPLETE,
    portfolio: PortfolioSnapshot | None = None,
    services_available: bool = True,
    report_task: Any = None,
    advisory_task: Any = None,
    advisory_error: dict[str, dict[str, str]] | None = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(advisory_router, prefix="/api")

    # Build app_state surface the route reads
    state_snapshot = SimpleNamespace(phase=phase)
    state_store = SimpleNamespace(snapshot=lambda: state_snapshot)
    # Real settings: hermetic_env points the inference config at a missing file
    # (local defaults, so the cloud-advisory guard allows the call) and the
    # holdings CSV at a path that never exists.
    settings = AppSettings(_env_file=None)  # type: ignore[call-arg]
    app_state = SimpleNamespace(
        settings=settings,
        state_store=state_store,
        graph_manager=object() if services_available else None,
        ollama_client=(
            SimpleNamespace(base_url="http://127.0.0.1:11434") if services_available else None
        ),
        model_manager=object() if services_available else None,
    )

    app.state.app_state = app_state
    app.state.portfolio_snapshot = portfolio
    app.state.report_task = report_task
    app.state.advisory_task = advisory_task
    app.state.advisory_generation_error = advisory_error or {}
    return app


@pytest.fixture(autouse=True)
def _neutralize_background_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent real synthesize() from running in route tests."""

    async def _noop(app_state: Any, cycle_id: str, portfolio: PortfolioSnapshot) -> None:
        await asyncio.sleep(0)

    monkeypatch.setattr(
        "alphaswarm.web.routes.advisory._run_advisory_synthesis",
        _noop,
    )


# ---------------- POST tests --------------------------------------------


def test_post_advisory_202() -> None:
    app = _make_app(portfolio=_fake_portfolio())
    client = TestClient(app)
    r = client.post("/api/advisory/cycle_01")
    assert r.status_code == 202
    body = r.json()
    assert body == {"status": "accepted", "cycle_id": "cycle_01"}
    # Task slot populated
    assert app.state.advisory_task is not None


def test_post_advisory_503_no_services() -> None:
    app = _make_app(portfolio=_fake_portfolio(), services_available=False)
    r = TestClient(app).post("/api/advisory/cycle_01")
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "services_unavailable"


def test_post_advisory_503_no_portfolio() -> None:
    app = _make_app(portfolio=None)
    r = TestClient(app).post("/api/advisory/cycle_01")
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "holdings_unavailable"


def test_post_advisory_409_wrong_phase() -> None:
    app = _make_app(phase=SimulationPhase.ROUND_2, portfolio=_fake_portfolio())
    r = TestClient(app).post("/api/advisory/cycle_01")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["error"] == "advisory_unavailable"
    assert detail["current_phase"] == "round_2"


def test_post_advisory_409_report_in_progress() -> None:
    fake_task = SimpleNamespace(done=lambda: False)
    app = _make_app(portfolio=_fake_portfolio(), report_task=fake_task)
    r = TestClient(app).post("/api/advisory/cycle_01")
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "report_generation_in_progress"


def test_post_advisory_409_conflict() -> None:
    fake_task = SimpleNamespace(done=lambda: False)
    app = _make_app(portfolio=_fake_portfolio(), advisory_task=fake_task)
    r = TestClient(app).post("/api/advisory/cycle_01")
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "advisory_generation_in_progress"


def test_post_advisory_400_bad_cycle_id() -> None:
    app = _make_app(portfolio=_fake_portfolio())
    r = TestClient(app).post("/api/advisory/..%2Fetc")
    # Either 400 from the regex guard OR 404 from FastAPI path parsing — both
    # indicate the path-traversal attempt did NOT reach the handler with
    # a dangerous cycle_id. Accept 400 (preferred) and also tolerate 404
    # for path encoding edge cases at the framework layer.
    assert r.status_code in (400, 404)
    if r.status_code == 400:
        assert r.json()["detail"]["error"] == "invalid_cycle_id"


def test_post_advisory_400_bad_cycle_id_simple() -> None:
    app = _make_app(portfolio=_fake_portfolio())
    # Unambiguous invalid cycle_id: contains a dot (outside the [a-zA-Z0-9_-] charset)
    r = TestClient(app).post("/api/advisory/bad.id")
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_cycle_id"


# ---------------- GET tests --------------------------------------------


def test_get_advisory_200(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Redirect ADVISORY_DIR to tmp_path for isolation
    monkeypatch.setattr(
        "alphaswarm.web.routes.advisory.ADVISORY_DIR", tmp_path,
    )
    payload = {
        "cycle_id": "cycle_01",
        "generated_at": "2026-04-19T22:00:00+00:00",
        "portfolio_outlook": "Mildly bullish.",
        "items": [],
        "total_holdings": 3,
        "affected_holdings": 0,
    }
    (tmp_path / "cycle_01_advisory.json").write_text(json.dumps(payload))

    app = _make_app(portfolio=_fake_portfolio())
    r = TestClient(app).get("/api/advisory/cycle_01")
    assert r.status_code == 200
    assert r.json() == payload


def test_get_advisory_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "alphaswarm.web.routes.advisory.ADVISORY_DIR", tmp_path,
    )
    app = _make_app(portfolio=_fake_portfolio())
    r = TestClient(app).get("/api/advisory/cycle_missing")
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "advisory_not_found"


def test_get_advisory_500_after_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "alphaswarm.web.routes.advisory.ADVISORY_DIR", tmp_path,
    )
    app = _make_app(
        portfolio=_fake_portfolio(),
        advisory_error={
            "cycle_01": {
                "error": "advisory_generation_failed",
                "message": "boom",
            },
        },
    )
    r = TestClient(app).get("/api/advisory/cycle_01")
    assert r.status_code == 500
    detail = r.json()["detail"]
    assert detail["error"] == "advisory_generation_failed"
    assert detail["message"] == "boom"
    assert detail["cycle_id"] == "cycle_01"


def test_get_advisory_400_bad_cycle_id() -> None:
    app = _make_app(portfolio=_fake_portfolio())
    r = TestClient(app).get("/api/advisory/bad.id")
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_cycle_id"


# ---------------- Report auto-trigger chain (quick-260611-rlx) -----------


async def _drain_report_chain() -> None:
    """Await + clear any chain tasks the done-callback scheduled."""
    for task in list(_report_chain_tasks):
        try:
            await task
        except Exception:  # pragma: no cover - defensive in teardown
            pass
    _report_chain_tasks.clear()


async def test_advisory_done_success_schedules_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SUCCESS branch (not cancelled, no exception) schedules _auto_trigger_report
    via asyncio.create_task with a strong module-level reference."""
    app = _make_app(portfolio=_fake_portfolio())
    fake_trigger = AsyncMock()
    monkeypatch.setattr(advisory_module, "_auto_trigger_report", fake_trigger)

    task = MagicMock(spec=asyncio.Task)
    task.cancelled.return_value = False
    task.exception.return_value = None

    _on_advisory_task_done(task, "cycle_01", app)
    # Let the scheduled chain task start + run to completion.
    await asyncio.sleep(0)
    await _drain_report_chain()

    fake_trigger.assert_awaited_once_with(app, "cycle_01")


async def test_advisory_done_failure_no_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILURE branch (exception present) does NOT schedule a report task."""
    app = _make_app(portfolio=_fake_portfolio())
    fake_trigger = AsyncMock()
    monkeypatch.setattr(advisory_module, "_auto_trigger_report", fake_trigger)

    task = MagicMock(spec=asyncio.Task)
    task.cancelled.return_value = False
    task.exception.return_value = RuntimeError("synthesis blew up")

    _on_advisory_task_done(task, "cycle_01", app)
    await asyncio.sleep(0)
    await _drain_report_chain()

    fake_trigger.assert_not_called()


async def test_advisory_done_cancelled_no_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CANCEL branch does NOT schedule a report task."""
    app = _make_app(portfolio=_fake_portfolio())
    fake_trigger = AsyncMock()
    monkeypatch.setattr(advisory_module, "_auto_trigger_report", fake_trigger)

    task = MagicMock(spec=asyncio.Task)
    task.cancelled.return_value = True

    _on_advisory_task_done(task, "cycle_01", app)
    await asyncio.sleep(0)
    await _drain_report_chain()

    fake_trigger.assert_not_called()


# ------ Cloud-advisory guard (docs/DECISIONS.md#adr-advisory-pipeline) ------


def _cloud_cfg(*, opt_in: bool) -> InferenceConfig:
    role = RoleConfig(
        provider=ProviderType.ANTHROPIC, model="claude-fictional", api_key="sk-fictional-3333"
    )
    return InferenceConfig(orchestrator=role, worker=role, allow_cloud_advisory=opt_in)


def test_post_advisory_409_for_a_cloud_orchestrator_without_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        advisory_module, "load_inference_config", lambda _s: _cloud_cfg(opt_in=False)
    )
    app = _make_app(portfolio=_fake_portfolio())

    r = TestClient(app).post("/api/advisory/cycle_01")

    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "cloud_advisory_disabled"
    assert app.state.advisory_task is None


def test_the_cloud_guard_runs_before_the_holdings_are_touched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        advisory_module, "load_inference_config", lambda _s: _cloud_cfg(opt_in=False)
    )
    reloads: list[Any] = []
    monkeypatch.setattr(
        "alphaswarm.web.routes.holdings.load_portfolio_snapshot", lambda p: reloads.append(p)
    )
    app = _make_app(portfolio=None)

    r = TestClient(app).post("/api/advisory/cycle_01")

    assert r.json()["detail"]["error"] == "cloud_advisory_disabled"
    assert reloads == []


def test_post_advisory_202_for_a_cloud_orchestrator_with_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        advisory_module, "load_inference_config", lambda _s: _cloud_cfg(opt_in=True)
    )
    app = _make_app(portfolio=_fake_portfolio())

    assert TestClient(app).post("/api/advisory/cycle_01").status_code == 202


def _ollama_cfg(model: str, *, opt_in: bool) -> InferenceConfig:
    role = RoleConfig(provider=ProviderType.OLLAMA, model=model)
    return InferenceConfig(orchestrator=role, worker=role, allow_cloud_advisory=opt_in)


def _with_ollama_host(app: FastAPI, base_url: str) -> FastAPI:
    """Point the shared OllamaClient at *base_url*. The settings keep their local
    default, so these tests also show the guard reads the client's real host."""
    app.state.app_state.ollama_client = SimpleNamespace(base_url=base_url)
    return app


@pytest.mark.parametrize(
    ("model", "ollama_host"),
    [
        ("gpt-oss:120b-cloud", "http://localhost:11434"),
        ("glm-4.6:cloud", "http://localhost:11434"),
        ("alphaswarm-orchestrator", "http://192.168.1.20:11434"),
        ("alphaswarm-orchestrator", "https://ollama.com"),
    ],
    ids=["cloud-model-dash", "cloud-model-colon", "lan-host", "ollama-com"],
)
@pytest.mark.parametrize("opt_in", [False, True], ids=["no-opt-in", "opted-in"])
def test_a_cloud_or_remote_ollama_orchestrator_needs_the_opt_in(
    monkeypatch: pytest.MonkeyPatch, model: str, ollama_host: str, opt_in: bool
) -> None:
    monkeypatch.setattr(
        advisory_module, "load_inference_config", lambda _s: _ollama_cfg(model, opt_in=opt_in)
    )
    app = _with_ollama_host(_make_app(portfolio=_fake_portfolio()), ollama_host)

    r = TestClient(app).post("/api/advisory/cycle_01")

    if opt_in:
        assert r.status_code == 202
    else:
        assert r.status_code == 409
        assert r.json()["detail"]["error"] == "cloud_advisory_disabled"
        assert "remote" in r.json()["detail"]["message"]
        assert app.state.advisory_task is None


def test_a_local_ollama_orchestrator_needs_no_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        advisory_module,
        "load_inference_config",
        lambda _s: _ollama_cfg("alphaswarm-orchestrator", opt_in=False),
    )
    app = _with_ollama_host(_make_app(portfolio=_fake_portfolio()), "http://127.0.0.1:11434")

    assert TestClient(app).post("/api/advisory/cycle_01").status_code == 202


@pytest.mark.parametrize(
    "error",
    [ValueError("Failed to parse inference config"), PermissionError("permission denied")],
    ids=["corrupt", "no-permission"],
)
def test_an_unreadable_inference_config_fails_closed(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    def _broken(_settings: Any) -> InferenceConfig:
        raise error

    monkeypatch.setattr(advisory_module, "load_inference_config", _broken)
    app = _make_app(portfolio=_fake_portfolio())

    r = TestClient(app).post("/api/advisory/cycle_01")

    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "cloud_advisory_disabled"


def test_a_refused_post_is_recorded_so_get_stops_reporting_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """GET answers 404 ("still generating" in the UI) when nothing is recorded, so a
    cloud refusal is recorded like a refused job and GET returns its code."""
    monkeypatch.setattr(
        advisory_module, "load_inference_config", lambda _s: _cloud_cfg(opt_in=False)
    )
    monkeypatch.setattr("alphaswarm.web.routes.advisory.ADVISORY_DIR", tmp_path)
    client = TestClient(_make_app(portfolio=_fake_portfolio()))

    assert client.post("/api/advisory/cycle_01").status_code == 409
    r = client.get("/api/advisory/cycle_01")

    assert r.status_code == 500
    assert r.json()["detail"]["error"] == "cloud_advisory_disabled"
