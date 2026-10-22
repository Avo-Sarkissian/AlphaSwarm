"""WebPostRunJobs + PostRunPipeline over the real job starters.

Pins docs/DECISIONS.md#adr-advisory-pipeline: the advisory runs when it is
allowed, and the report runs after every completed simulation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI

import alphaswarm.web.routes.advisory as advisory_module
import alphaswarm.web.routes.report as report_module
from alphaswarm.app import create_app_state
from alphaswarm.config import (
    InferenceConfig,
    ProviderType,
    RoleConfig,
    generate_personas,
    load_bracket_configs,
    save_inference_config,
)
from alphaswarm.state import JobStatus
from alphaswarm.web.app import WebPostRunJobs
from alphaswarm.web.post_run import PostRunPipeline
from tests.support.web_app import CYCLE_A, CYCLE_B, StaticPortfolioCache, route_test_settings


def _app(tmp_path: Path, portfolio: object | None) -> FastAPI:
    settings = route_test_settings(tmp_path)
    app = FastAPI()
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


async def test_report_runs_when_cloud_advisory_not_opted_in(
    tmp_path: Path,
    calls: list[str],
) -> None:
    app = _app(tmp_path, portfolio=object())
    cloud = InferenceConfig(
        orchestrator=RoleConfig(
            provider=ProviderType.ANTHROPIC, model="claude-test", api_key="sk-x"
        ),
        worker=RoleConfig(provider=ProviderType.OLLAMA, model="alphaswarm-worker"),
    )
    save_inference_config(cloud, app.state.app_state.settings.inference_config_path)
    outcome = await PostRunPipeline(jobs=WebPostRunJobs(app)).on_complete(CYCLE_A)
    assert (outcome.advisory, outcome.report) == ("skipped_cloud_advisory_disabled", "ran")
    assert calls == [f"report:{CYCLE_A}"]


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
