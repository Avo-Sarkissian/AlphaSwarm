"""WebPostRunJobs + PostRunPipeline over the real job starters.

Pins docs/DECISIONS.md#adr-advisory-pipeline: the advisory runs when it is
allowed, and the report runs after every completed simulation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI

import alphaswarm.services.post_run as post_run_module
import alphaswarm.web.guards as guards_module
import alphaswarm.web.routes.advisory as advisory_module
import alphaswarm.web.routes.report as report_module
from alphaswarm.app import create_app_state
from alphaswarm.inference.config import InferenceConfig, ProviderType, RoleConfig, save_inference_config
from alphaswarm.personas import generate_personas, load_bracket_configs
from alphaswarm.services.post_run import PostRunPipeline
from alphaswarm.state import JobStatus
from alphaswarm.web.app import WebPostRunJobs
from alphaswarm.web.errors import install_error_handlers
from alphaswarm.web.routes.advisory import router as advisory_router
from tests.support.log_capture import RenderedLog
from tests.support.web_app import CYCLE_A, CYCLE_B, StaticPortfolioCache, route_test_settings


def _app(tmp_path: Path, portfolio: object | None) -> FastAPI:
    settings = route_test_settings(tmp_path)
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(advisory_router, prefix="/api")
    app.state.app_state = create_app_state(
        settings,
        generate_personas(load_bracket_configs()),
        with_ollama=False,
        with_neo4j=False,
    )
    # A loopback host, so the advisory's cloud guard sees a local Ollama server.
    app.state.app_state.ollama_client = MagicMock(base_url="http://127.0.0.1:11434")
    app.state.portfolio_cache = StaticPortfolioCache(portfolio)
    app.state.report_task = None
    app.state.advisory_task = None
    app.state.report_generation_error = {}
    app.state.advisory_generation_error = {}
    return app


def _save_cloud_config(app: FastAPI) -> None:
    """A cloud orchestrator without the allow_cloud_advisory opt-in."""
    cloud = InferenceConfig(
        orchestrator=RoleConfig(provider=ProviderType.ANTHROPIC, model="claude-test", api_key="sk-x"),
        worker=RoleConfig(provider=ProviderType.OLLAMA, model="alphaswarm-worker"),
    )
    save_inference_config(cloud, app.state.app_state.settings.inference_config_path)


async def _get_advisory(app: FastAPI, cycle_id: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(f"/api/advisory/{cycle_id}")


@pytest.fixture()
def calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    async def _advisory(app_state: Any, cycle_id: str, portfolio: Any) -> None:
        seen.append(f"advisory:{cycle_id}")

    async def _report(app_state: Any, cycle_id: str) -> None:
        seen.append(f"report:{cycle_id}")

    monkeypatch.setattr(advisory_module, "_run_advisory_synthesis", _advisory)
    monkeypatch.setattr(report_module, "_run_report_generation", _report)
    return seen


async def test_advisory_then_report_when_holdings_are_loaded(
    tmp_path: Path,
    calls: list[str],
) -> None:
    app = _app(tmp_path, portfolio=object())
    outcome = await PostRunPipeline(jobs=WebPostRunJobs(app)).on_complete(CYCLE_A)
    assert (outcome.advisory, outcome.report) == ("ran", "ran")
    assert calls == [f"advisory:{CYCLE_A}", f"report:{CYCLE_A}"]
    jobs = app.state.app_state.state_store.job_statuses()
    assert jobs.advisory == JobStatus("idle", CYCLE_A)
    assert jobs.report == JobStatus("idle", CYCLE_A)


async def test_report_runs_without_holdings(tmp_path: Path, calls: list[str]) -> None:
    app = _app(tmp_path, portfolio=None)
    outcome = await PostRunPipeline(jobs=WebPostRunJobs(app)).on_complete(CYCLE_A)
    assert (outcome.advisory, outcome.report) == ("skipped_no_portfolio", "ran")
    assert calls == [f"report:{CYCLE_A}"]
    # Nothing is recorded without holdings: no advisory exists for the cycle.
    r = await _get_advisory(app, CYCLE_A)
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "advisory_not_found"


async def test_report_runs_when_cloud_advisory_not_opted_in(
    tmp_path: Path,
    calls: list[str],
) -> None:
    app = _app(tmp_path, portfolio=object())
    _save_cloud_config(app)
    outcome = await PostRunPipeline(jobs=WebPostRunJobs(app)).on_complete(CYCLE_A)
    assert (outcome.advisory, outcome.report) == ("skipped_cloud_advisory_disabled", "ran")
    assert calls == [f"report:{CYCLE_A}"]


async def test_a_cloud_refusal_is_recorded_so_get_stops_reporting_pending(
    tmp_path: Path,
    calls: list[str],
) -> None:
    """GET answers 404 (shown as "still generating") when nothing is recorded, so the
    pipeline records the refusal like the POST route and GET returns its code."""
    app = _app(tmp_path, portfolio=object())
    _save_cloud_config(app)
    await PostRunPipeline(jobs=WebPostRunJobs(app)).on_complete(CYCLE_A)
    r = await _get_advisory(app, CYCLE_A)
    assert r.status_code == 500
    assert r.json()["detail"]["error"] == "cloud_advisory_disabled"
    assert r.json()["detail"]["message"] == advisory_module._CLOUD_ADVISORY_MESSAGE
    assert app.state.portfolio_cache.get_calls == 0  # refused before the holdings


async def test_no_ollama_client_fails_closed_and_the_report_still_runs(
    tmp_path: Path,
    calls: list[str],
) -> None:
    app = _app(tmp_path, portfolio=object())
    app.state.app_state.ollama_client = None
    outcome = await PostRunPipeline(jobs=WebPostRunJobs(app)).on_complete(CYCLE_A)
    assert (outcome.advisory, outcome.report) == ("skipped_cloud_advisory_disabled", "ran")
    assert calls == [f"report:{CYCLE_A}"]
    r = await _get_advisory(app, CYCLE_A)
    assert (r.status_code, r.json()["detail"]["error"]) == (500, "cloud_advisory_disabled")


async def test_an_unreadable_config_fails_closed_and_is_recorded(
    tmp_path: Path,
    calls: list[str],
) -> None:
    """Like the POST route: the advisory is refused before the holdings are read,
    GET returns inference_config_invalid, and the report still runs."""
    app = _app(tmp_path, portfolio=object())
    app.state.app_state.settings.inference_config_path.write_text("{not json", encoding="utf-8")
    outcome = await PostRunPipeline(jobs=WebPostRunJobs(app)).on_complete(CYCLE_A)
    assert (outcome.advisory, outcome.report) == ("skipped_cloud_advisory_disabled", "ran")
    assert calls == [f"report:{CYCLE_A}"]
    assert app.state.portfolio_cache.get_calls == 0
    r = await _get_advisory(app, CYCLE_A)
    assert (r.status_code, r.json()["detail"]["error"]) == (500, "inference_config_invalid")
    assert str(tmp_path) not in r.text


async def test_the_config_error_text_never_reaches_the_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An invalid config's error text quotes the file path and raw values, API keys
    included: the gate, the real report job and its done-callback log only error
    types and a fixed InferenceConfigError (docs/DECISIONS.md#adr-local-first-inference)."""
    canary = "".join(["sk-", "fictional", "-PIPELINE-CANARY"])  # never in this source
    app = _app(tmp_path, portfolio=object())
    app.state.app_state.graph_manager = MagicMock()
    app.state.app_state.model_manager = MagicMock()
    # No orchestrator model: pydantic quotes the whole role, key included.
    roles = {
        "orchestrator": {"provider": "anthropic", "api_key": canary},
        "worker": {"provider": "ollama", "model": "alphaswarm-worker"},
    }
    config_path = app.state.app_state.settings.inference_config_path
    config_path.write_text(json.dumps(roles), encoding="utf-8")
    rendered = RenderedLog()
    for module in (post_run_module, guards_module, advisory_module, report_module):
        monkeypatch.setattr(module, "log", rendered, raising=False)

    outcome = await PostRunPipeline(jobs=WebPostRunJobs(app)).on_complete(CYCLE_A)

    assert (outcome.advisory, outcome.report) == ("skipped_cloud_advisory_disabled", "failed")
    assert app.state.report_generation_error[CYCLE_A]["message"] == ("Report generation failed (InferenceConfigError)")
    # Positive control: the report failure was rendered with its traceback.
    assert "report_task_exception_recorded" in rendered.events
    assert '"exc_type": "InferenceConfigError"' in rendered.text
    assert canary not in rendered.text
    assert str(config_path) not in rendered.text


async def test_report_runs_after_advisory_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    calls: list[str],
) -> None:
    async def _broken(app_state: Any, cycle_id: str, portfolio: Any) -> None:
        raise RuntimeError("synthesis broke")

    monkeypatch.setattr(advisory_module, "_run_advisory_synthesis", _broken)
    app = _app(tmp_path, portfolio=object())
    outcome = await PostRunPipeline(jobs=WebPostRunJobs(app)).on_complete(CYCLE_A)
    assert (outcome.advisory, outcome.report) == ("failed", "ran")
    assert calls == [f"report:{CYCLE_A}"]
    assert app.state.app_state.state_store.job_statuses().advisory.state == "failed"


async def test_busy_slot_skips_both_jobs(tmp_path: Path, calls: list[str]) -> None:
    app = _app(tmp_path, portfolio=object())
    app.state.app_state.state_store.set_job_status("report", JobStatus("running", CYCLE_B))
    outcome = await PostRunPipeline(jobs=WebPostRunJobs(app)).on_complete(CYCLE_A)
    assert (outcome.advisory, outcome.report) == ("skipped_busy", "skipped_busy")
    assert calls == []
