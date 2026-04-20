"""Unit tests for POST/GET /api/advisory/{cycle_id} (ADVIS-02)."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from alphaswarm.holdings.types import Holding, PortfolioSnapshot
from alphaswarm.types import SimulationPhase
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
    settings = SimpleNamespace(
        ollama=SimpleNamespace(orchestrator_model_alias="alphaswarm-orchestrator"),
    )
    app_state = SimpleNamespace(
        settings=settings,
        state_store=state_store,
        graph_manager=object() if services_available else None,
        ollama_client=object() if services_available else None,
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
