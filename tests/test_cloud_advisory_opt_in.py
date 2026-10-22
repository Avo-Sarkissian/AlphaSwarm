"""No advisory provider is built for a cloud orchestrator without the opt-in.

A cloud orchestrator with allow_cloud_advisory=False must not receive a single
advisory call, whether the advisory is requested by POST or by the post-run
pipeline; with the opt-in the same pipeline does build it (positive control).
Values are fictional; ZZZT is one of the reserved tickers in
tests/invariants/test_fictional_fixtures.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import alphaswarm.web.routes.advisory as advisory_module
import alphaswarm.web.routes.report as report_module
from alphaswarm.app import create_app_state
from alphaswarm.config import (
    AppSettings,
    InferenceConfig,
    ProviderType,
    RoleConfig,
    generate_personas,
    load_bracket_configs,
    save_inference_config,
)
from alphaswarm.holdings.types import Holding, PortfolioSnapshot
from alphaswarm.inference.budget import BudgetMeter
from alphaswarm.inference.factory import BuiltProviders
from alphaswarm.inference.types import ProviderRole
from alphaswarm.web.app import WebPostRunJobs
from alphaswarm.web.post_run import PostRunPipeline
from alphaswarm.web.routes.advisory import router as advisory_router
from tests.inference.fakes import FakeInferenceProvider
from tests.support.web_app import (
    CYCLE_A,
    FakeCycleGraph,
    StaticPortfolioCache,
    make_route_app,
    route_test_settings,
)


def _portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        holdings=(Holding(ticker="ZZZT", qty=Decimal("12.3456"), cost_basis=Decimal("1234.56")),),
        as_of=datetime.now(UTC),
        account_number_hash="cafebabe",
    )


def _cloud_settings(tmp_path: Path, *, opt_in: bool) -> AppSettings:
    settings = route_test_settings(tmp_path)
    cfg = InferenceConfig(
        orchestrator=RoleConfig(
            provider=ProviderType.ANTHROPIC,
            model="claude-test",
            api_key="sk-fictional-0000",
        ),
        worker=RoleConfig(provider=ProviderType.OLLAMA, model="alphaswarm-worker"),
        allow_cloud_advisory=opt_in,
    )
    save_inference_config(cfg, settings.inference_config_path)
    return settings


class _FakeReport:
    affected_holdings = 0

    def model_dump_json(self, *, indent: int) -> str:
        return f'{{"cycle_id": "{CYCLE_A}", "items": []}}'


@pytest.fixture()
def ledger(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace build_providers and synthesize; count every provider build."""
    provider = FakeInferenceProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="claude-test",
        scripted=[],
        is_local=False,
    )
    state: dict[str, Any] = {"builds": 0, "provider": provider}

    def _build(*_args: Any, **_kwargs: Any) -> BuiltProviders:
        state["builds"] += 1
        return BuiltProviders(
            orchestrator=provider,  # type: ignore[arg-type]
            worker=provider,  # type: ignore[arg-type]
            budget_meter=BudgetMeter(None, {}),
        )

    async def _synthesize(**_kwargs: Any) -> _FakeReport:
        return _FakeReport()

    monkeypatch.setattr(advisory_module, "build_providers", _build)
    monkeypatch.setattr(advisory_module, "synthesize", _synthesize)
    return state


@pytest.fixture()
def report_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    async def _report(app_state: Any, cycle_id: str) -> None:
        calls.append(cycle_id)

    monkeypatch.setattr(report_module, "_run_report_generation", _report)
    return calls


def _pipeline_app(settings: AppSettings) -> FastAPI:
    app = FastAPI()
    app_state = create_app_state(
        settings,
        generate_personas(load_bracket_configs()),
        with_ollama=False,
        with_neo4j=False,
    )
    app_state.graph_manager = MagicMock()  # type: ignore[assignment]
    app_state.ollama_client = MagicMock()  # type: ignore[assignment]
    app_state.model_manager = MagicMock()  # type: ignore[assignment]
    app.state.app_state = app_state
    app.state.portfolio_cache = StaticPortfolioCache(_portfolio())
    app.state.report_task = None
    app.state.advisory_task = None
    app.state.report_generation_error = {}
    app.state.advisory_generation_error = {}
    return app


def test_post_without_opt_in_never_builds_a_provider(
    tmp_path: Path,
    ledger: dict[str, Any],
) -> None:
    app = make_route_app(
        advisory_router,
        settings=_cloud_settings(tmp_path, opt_in=False),
        graph=FakeCycleGraph({CYCLE_A: "complete"}),
        portfolio=_portfolio(),
    )
    with TestClient(app) as client:
        r = client.post(f"/api/advisory/{CYCLE_A}")
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "cloud_advisory_disabled"
    assert ledger["builds"] == 0
    assert ledger["provider"].calls == []


def test_refusal_names_the_settings_checkbox_and_the_config_key(
    tmp_path: Path,
    ledger: dict[str, Any],
) -> None:
    """The 409 says where to opt in: the Settings checkbox, or the config key when
    the checkbox is not shown (the UI cannot see an alias of a cloud model)."""
    app = make_route_app(
        advisory_router,
        settings=_cloud_settings(tmp_path, opt_in=False),
        graph=FakeCycleGraph({CYCLE_A: "complete"}),
        portfolio=_portfolio(),
    )
    with TestClient(app) as client:
        message = client.post(f"/api/advisory/{CYCLE_A}").json()["detail"]["message"]
    assert "tick 'Allow cloud advisory' in Settings > Model" in message
    assert "set allow_cloud_advisory to true in the inference config" in message


async def test_pipeline_without_opt_in_never_builds_a_provider(
    tmp_path: Path,
    ledger: dict[str, Any],
    report_calls: list[str],
) -> None:
    app = _pipeline_app(_cloud_settings(tmp_path, opt_in=False))
    outcome = await PostRunPipeline(jobs=WebPostRunJobs(app)).on_complete(CYCLE_A)
    assert (outcome.advisory, outcome.report) == ("skipped_cloud_advisory_disabled", "ran")
    assert report_calls == [CYCLE_A]
    assert ledger["builds"] == 0
    assert ledger["provider"].calls == []


async def test_pipeline_with_opt_in_builds_the_provider_once(
    tmp_path: Path,
    ledger: dict[str, Any],
    report_calls: list[str],
) -> None:
    """Positive control: after the opt-in the same path does reach the provider."""
    app = _pipeline_app(_cloud_settings(tmp_path, opt_in=True))
    outcome = await PostRunPipeline(jobs=WebPostRunJobs(app)).on_complete(CYCLE_A)
    assert (outcome.advisory, outcome.report) == ("ran", "ran")
    assert ledger["builds"] == 1
    assert report_calls == [CYCLE_A]
