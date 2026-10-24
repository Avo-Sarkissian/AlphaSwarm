"""POST/GET /api/advisory/{cycle_id} over AdvisoryService + JobRunner (docs/DECISIONS.md#adr-background-tasks)."""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import alphaswarm.services.runtime as runtime_module
import alphaswarm.web.routes.advisory as advisory_module
from alphaswarm.advisory import AdvisoryItem, AdvisoryReport
from alphaswarm.errors import InferenceConfigError, Neo4jUnavailableError
from alphaswarm.holdings.types import Holding, PortfolioSnapshot
from alphaswarm.inference.config import InferenceConfig, ProviderType, RoleConfig, save_inference_config
from alphaswarm.services.advisory import (
    CLOUD_ADVISORY_MESSAGE,
    MODEL_CHECK_FAILED_MESSAGE,
    AdvisoryNotAllowedError,
    AdvisoryService,
)
from alphaswarm.state import JobStatus, StateStore
from alphaswarm.web.routes.advisory import router as advisory_router
from tests.support.log_capture import RenderedLog
from tests.support.web_app import (
    CYCLE_A,
    CYCLE_B,
    CYCLE_UNKNOWN,
    FakeCycleGraph,
    StaticPortfolioCache,
    block_service_jobs,
    make_route_app,
    offline_runtime,
    route_test_settings,
)


def _portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        holdings=(Holding(ticker="ZZZT", qty=Decimal("12.3456"), cost_basis=Decimal("1234.56")),),
        as_of=datetime.now(UTC),
        account_number_hash="cafebabe",
    )


def _stored_report() -> AdvisoryReport:
    return AdvisoryReport(
        cycle_id=CYCLE_A,
        generated_at=datetime(2026, 10, 3, 12, 0, tzinfo=UTC),
        portfolio_outlook="Fictional outlook for the test portfolio.",
        items=(
            AdvisoryItem(
                ticker="ZZZT",
                consensus_signal="BUY",
                confidence=0.7,
                rationale_summary="Fictional summary.",
                cost_basis_exposure=Decimal("1234.56"),
            ),
        ),
        total_holdings=1,
        affected_holdings=1,
    )


def _unreadable_contents() -> list[str]:
    valid = json.loads(_stored_report().model_dump_json())
    return [
        json.dumps({"cycle_id": CYCLE_A, "items": []}),
        "not json at all",
        json.dumps({**valid, "unexpected": 1}),
    ]


@pytest.fixture(autouse=True)
def _blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    block_service_jobs(monkeypatch)


def _no_job_started(app: FastAPI) -> bool:
    return _store(app).job_statuses().advisory.state != "running"


def _use_ollama_client(app: FastAPI, client: object) -> None:
    """Swap the OllamaClient the advisory gate reads its host from (the shared runtime's)."""
    app.state.runtime.inference._ollama_client = client


def _app(
    tmp_path: Path,
    *,
    graph: FakeCycleGraph | None = None,
    portfolio: object | None = None,
) -> FastAPI:
    return make_route_app(
        advisory_router,
        settings=route_test_settings(tmp_path),
        graph=graph if graph is not None else FakeCycleGraph({CYCLE_A: "complete"}),
        portfolio=portfolio,
    )


def _store(app: FastAPI) -> StateStore:
    store: StateStore = app.state.app_state.state_store
    return store


def test_post_202_for_complete_cycle_while_phase_is_idle(tmp_path: Path) -> None:
    app = _app(tmp_path, portfolio=_portfolio())
    with TestClient(app) as client:
        r = client.post(f"/api/advisory/{CYCLE_A}")
        assert r.status_code == 202
        assert r.json() == {"status": "accepted", "cycle_id": CYCLE_A}
        assert _store(app).job_statuses().advisory == JobStatus("running", CYCLE_A)


def test_post_404_for_unknown_cycle_starts_nothing(tmp_path: Path) -> None:
    app = _app(tmp_path, portfolio=_portfolio())
    with TestClient(app) as client:
        r = client.post(f"/api/advisory/{CYCLE_UNKNOWN}")
        assert r.status_code == 404
        assert r.json()["detail"]["error"] == "cycle_not_found"
        assert _no_job_started(app)


def test_post_422_for_unfinished_cycle(tmp_path: Path) -> None:
    graph = FakeCycleGraph({CYCLE_A: "running"})
    with TestClient(_app(tmp_path, graph=graph, portfolio=_portfolio())) as client:
        r = client.post(f"/api/advisory/{CYCLE_A}")
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "cycle_not_ready"


def test_post_409_while_a_simulation_runs(tmp_path: Path) -> None:
    app = _app(tmp_path, portfolio=_portfolio())
    with TestClient(app) as client:
        app.state.sim_manager._is_running = True
        r = client.post(f"/api/advisory/{CYCLE_A}")
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "simulation_running"


def test_post_409_when_a_run_starts_during_the_gate(tmp_path: Path) -> None:
    """POST /api/simulate/start lands while the route awaits the gate (config, holdings).

    The run's start() probe passes because no job is marked running yet, so the
    route must check again before it starts the job.
    """
    app = _app(tmp_path, portfolio=_portfolio())
    with TestClient(app) as client:
        service = app.state.advisory_service
        real_gate = service.gate

        async def _gate(cycle_id: str) -> Any:
            app.state.sim_manager._is_running = True
            return await real_gate(cycle_id)

        service.gate = _gate
        r = client.post(f"/api/advisory/{CYCLE_A}")
        assert r.status_code == 409
        assert r.json()["detail"]["error"] == "simulation_running"
        assert _store(app).job_statuses().advisory == JobStatus()


@pytest.mark.parametrize("empty", [False, True], ids=["no-file", "no-holdings"])
def test_post_503_without_holdings(tmp_path: Path, empty: bool) -> None:
    portfolio = (
        PortfolioSnapshot(holdings=(), as_of=datetime.now(UTC), account_number_hash="cafebabe") if empty else None
    )
    with TestClient(_app(tmp_path, portfolio=portfolio)) as client:
        r = client.post(f"/api/advisory/{CYCLE_A}")
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "holdings_unavailable"


def _cloud_app(tmp_path: Path, *, opt_in: bool, portfolio: object | None) -> FastAPI:
    """App whose stored config uses a cloud orchestrator, with the opt-in flag set or not."""
    settings = route_test_settings(tmp_path)
    cloud = InferenceConfig(
        orchestrator=RoleConfig(
            provider=ProviderType.ANTHROPIC,
            model="claude-test",
            api_key="sk-x",
        ),
        worker=RoleConfig(provider=ProviderType.OLLAMA, model="alphaswarm-worker"),
        allow_cloud_advisory=opt_in,
    )
    save_inference_config(cloud, settings.inference_config_path)
    return make_route_app(
        advisory_router,
        settings=settings,
        graph=FakeCycleGraph({CYCLE_A: "complete"}),
        portfolio=portfolio,
    )


def test_post_409_for_cloud_orchestrator_without_opt_in(tmp_path: Path) -> None:
    app = _cloud_app(tmp_path, opt_in=False, portfolio=_portfolio())
    with TestClient(app) as client:
        r = client.post(f"/api/advisory/{CYCLE_A}")
        assert r.status_code == 409
        assert r.json()["detail"]["error"] == "cloud_advisory_disabled"
        assert _no_job_started(app)


def test_cloud_guard_runs_before_the_holdings_are_touched(tmp_path: Path) -> None:
    """Refuse before reading the holdings (docs/DECISIONS.md#adr-advisory-pipeline)."""
    app = _cloud_app(tmp_path, opt_in=False, portfolio=None)
    with TestClient(app) as client:
        r = client.post(f"/api/advisory/{CYCLE_A}")
        assert r.json()["detail"]["error"] == "cloud_advisory_disabled"
        assert app.state.portfolio_cache.get_calls == 0


def test_post_202_for_cloud_orchestrator_with_opt_in(tmp_path: Path) -> None:
    app = _cloud_app(tmp_path, opt_in=True, portfolio=_portfolio())
    with TestClient(app) as client:
        assert client.post(f"/api/advisory/{CYCLE_A}").status_code == 202


def test_unreadable_inference_config_fails_closed_without_path(tmp_path: Path) -> None:
    settings = route_test_settings(tmp_path)
    settings.inference_config_path.write_text("{not json", encoding="utf-8")
    app = make_route_app(
        advisory_router,
        settings=settings,
        graph=FakeCycleGraph({CYCLE_A: "complete"}),
        portfolio=_portfolio(),
    )
    with TestClient(app) as client:
        r = client.post(f"/api/advisory/{CYCLE_A}")
        assert r.status_code == 422
        assert r.json()["detail"]["error"] == "inference_config_invalid"
        assert str(tmp_path) not in r.text
        assert _no_job_started(app)
        assert app.state.portfolio_cache.get_calls == 0


@pytest.mark.parametrize(
    ("kind", "code"),
    [("report", "report_generation_in_progress"), ("advisory", "advisory_generation_in_progress")],
)
def test_post_409_when_the_orchestrator_is_busy(tmp_path: Path, kind: str, code: str) -> None:
    app = _app(tmp_path, portfolio=_portfolio())
    with TestClient(app) as client:
        _store(app).set_job_status(kind, JobStatus("running", CYCLE_B))  # type: ignore[arg-type]
        r = client.post(f"/api/advisory/{CYCLE_A}")
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == code


def test_post_503_when_neo4j_is_down(tmp_path: Path) -> None:
    graph = FakeCycleGraph(error=Neo4jUnavailableError("down", op="read_cycle_status"))
    with TestClient(_app(tmp_path, graph=graph, portfolio=_portfolio())) as client:
        r = client.post(f"/api/advisory/{CYCLE_A}")
    assert r.status_code == 503


@pytest.mark.parametrize("bad", ["cycle_01", "bad.id", f"{CYCLE_A}%0A"])
def test_malformed_ids_are_422(tmp_path: Path, bad: str) -> None:
    with TestClient(_app(tmp_path, portfolio=_portfolio())) as client:
        assert client.post(f"/api/advisory/{bad}").status_code == 422
        assert client.get(f"/api/advisory/{bad}").status_code == 422


def test_get_200_reads_from_settings_dir_not_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "advisory").mkdir()
    stored = _stored_report()
    (tmp_path / "advisory" / f"{CYCLE_A}_advisory.json").write_text(stored.model_dump_json())
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    with TestClient(_app(tmp_path)) as client:
        r = client.get(f"/api/advisory/{CYCLE_A}")
    assert r.status_code == 200
    assert r.json() == json.loads(stored.model_dump_json())


def test_get_404_500_and_409(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        assert client.get(f"/api/advisory/{CYCLE_A}").json()["detail"]["error"] == ("advisory_not_found")
        app.state.runtime.jobs.record_refusal("advisory", CYCLE_A, "advisory_generation_failed")
        failed = client.get(f"/api/advisory/{CYCLE_A}")
        assert failed.status_code == 500
        assert failed.json()["detail"]["cycle_id"] == CYCLE_A
        _store(app).set_job_status("advisory", JobStatus("running", CYCLE_A))
        running = client.get(f"/api/advisory/{CYCLE_A}")
        assert running.status_code == 409
        assert running.json()["detail"]["error"] == "advisory_generation_in_progress"


async def test_get_500_after_a_failed_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed job is recorded per cycle; GET answers its code with fixed text only."""

    async def _fail(self: AdvisoryService, cycle_id: str) -> None:
        raise ValueError("ZZZT leaked into an exception message")

    monkeypatch.setattr(AdvisoryService, "generate", _fail)
    app = _app(tmp_path, portfolio=_portfolio())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            assert (await client.post(f"/api/advisory/{CYCLE_A}")).status_code == 202
            task = next(t for t in asyncio.all_tasks() if t.get_name() == f"advisory_{CYCLE_A}")
            with contextlib.suppress(ValueError):
                await task
            response = await client.get(f"/api/advisory/{CYCLE_A}")
    assert response.status_code == 500
    assert response.json()["detail"] == {
        "error": "advisory_generation_failed",
        "message": "Advisory generation failed; see the server log",
        "cycle_id": CYCLE_A,
    }
    assert "ZZZT" not in response.text
    assert _store(app).job_statuses().advisory == JobStatus("failed", CYCLE_A, "advisory_generation_failed")


async def test_synthesis_fails_with_a_fixed_error_on_an_invalid_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The config error's text quotes raw values, keys included, so the job logs only
    its type and raises a fixed InferenceConfigError from None."""
    canary = "".join(["sk-", "fictional", "-ADVISORY-CANARY"])  # never in this source
    settings = route_test_settings(tmp_path)
    roles = {
        "orchestrator": {"provider": "anthropic", "api_key": canary},
        "worker": {"provider": "ollama", "model": "alphaswarm-worker"},
    }
    settings.inference_config_path.write_text(json.dumps(roles), encoding="utf-8")
    monkeypatch.undo()  # the real generate, not block_service_jobs' stand-in
    rendered = RenderedLog()
    monkeypatch.setattr(runtime_module, "log", rendered)
    runtime = offline_runtime(settings, graph=FakeCycleGraph({CYCLE_A: "complete"}))
    graph: Any = runtime.app_state.graph_manager
    portfolio = StaticPortfolioCache(_portfolio())
    service = AdvisoryService(
        graph=graph,
        inference=runtime.inference,
        jobs=runtime.jobs,
        advisory_dir=tmp_path / "advisory",
        portfolio=portfolio.get,  # type: ignore[arg-type]
    )
    with pytest.raises(InferenceConfigError) as exc_info:
        await service.generate(CYCLE_A)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True
    assert canary not in str(exc_info.value)
    assert rendered.events == ["inference_config_invalid"]
    assert canary not in rendered.text
    assert '"error_type": "InferenceConfigFileError"' in rendered.text
    assert portfolio.get_calls == 0


# ------ Cloud-advisory guard: host and model checks at the route ------
# (docs/DECISIONS.md#adr-advisory-pipeline)


def _ollama_cfg_app(tmp_path: Path, model: str, *, opt_in: bool) -> FastAPI:
    settings = route_test_settings(tmp_path)
    role = RoleConfig(provider=ProviderType.OLLAMA, model=model)
    cfg = InferenceConfig(orchestrator=role, worker=role, allow_cloud_advisory=opt_in)
    save_inference_config(cfg, settings.inference_config_path)
    return make_route_app(
        advisory_router,
        settings=settings,
        graph=FakeCycleGraph({CYCLE_A: "complete"}),
        portfolio=_portfolio(),
    )


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
    tmp_path: Path,
    model: str,
    ollama_host: str,
    opt_in: bool,
) -> None:
    """The guard reads the host the shared OllamaClient really connects to."""
    app = _ollama_cfg_app(tmp_path, model, opt_in=opt_in)
    with TestClient(app) as client:
        _use_ollama_client(app, SimpleNamespace(base_url=ollama_host))
        r = client.post(f"/api/advisory/{CYCLE_A}")
        if opt_in:
            assert r.status_code == 202
        else:
            assert r.status_code == 409
            assert r.json()["detail"]["error"] == "cloud_advisory_disabled"
            assert "remote" in r.json()["detail"]["message"]
            assert _no_job_started(app)


def test_no_ollama_client_fails_closed(tmp_path: Path) -> None:
    app = _app(tmp_path, portfolio=_portfolio())
    with TestClient(app) as client:
        _use_ollama_client(app, None)
        r = client.post(f"/api/advisory/{CYCLE_A}")
        assert r.status_code == 409
        assert r.json()["detail"]["error"] == "cloud_advisory_disabled"
        assert app.state.portfolio_cache.get_calls == 0


def test_a_permission_denied_config_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _denied(_settings: Any) -> InferenceConfig:
        raise PermissionError("permission denied")

    monkeypatch.setattr("alphaswarm.inference.config.load_inference_config", _denied)
    app = _app(tmp_path, portfolio=_portfolio())
    with TestClient(app) as client:
        r = client.post(f"/api/advisory/{CYCLE_A}")
        assert r.status_code == 422
        assert r.json()["detail"]["error"] == "inference_config_invalid"
        assert _no_job_started(app)
        assert app.state.portfolio_cache.get_calls == 0


def test_a_refused_post_is_recorded_so_get_stops_reporting_pending(tmp_path: Path) -> None:
    """GET answers 404 (shown as "still generating") when nothing is recorded, so a
    refusal is recorded like a refused job and GET returns its code."""
    app = _cloud_app(tmp_path, opt_in=False, portfolio=_portfolio())
    with TestClient(app) as client:
        assert client.post(f"/api/advisory/{CYCLE_A}").status_code == 409
        r = client.get(f"/api/advisory/{CYCLE_A}")
    assert r.status_code == 500
    assert r.json()["detail"]["error"] == "cloud_advisory_disabled"
    assert r.json()["detail"]["message"] == CLOUD_ADVISORY_MESSAGE


async def test_a_refused_job_is_reported_with_its_fixed_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A job refused under the lock (Settings switched to a cloud orchestrator) keeps
    the cloud_advisory_disabled code and its fixed message for GET."""

    async def _refused(self: AdvisoryService, cycle_id: str) -> None:
        raise AdvisoryNotAllowedError("cloud_advisory_disabled", MODEL_CHECK_FAILED_MESSAGE)

    monkeypatch.setattr(AdvisoryService, "generate", _refused)
    app = _app(tmp_path, portfolio=_portfolio())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            assert (await client.post(f"/api/advisory/{CYCLE_A}")).status_code == 202
            task = next(t for t in asyncio.all_tasks() if t.get_name() == f"advisory_{CYCLE_A}")
            with contextlib.suppress(AdvisoryNotAllowedError):
                await task
            response = await client.get(f"/api/advisory/{CYCLE_A}")
    assert response.status_code == 500
    assert response.json()["detail"]["error"] == "cloud_advisory_disabled"
    assert response.json()["detail"]["message"] == CLOUD_ADVISORY_MESSAGE
    assert _store(app).job_statuses().advisory == JobStatus("failed", CYCLE_A, "cloud_advisory_disabled")


def test_get_legacy_advisory_file_is_200(tmp_path: Path) -> None:
    """Files written before ``stats``/``source`` existed still validate."""
    legacy = {
        "cycle_id": CYCLE_A,
        "generated_at": "2026-09-01T12:00:00+00:00",
        "portfolio_outlook": "Old.",
        "items": [
            {
                "ticker": "ZZZT",
                "consensus_signal": "BUY",
                "confidence": 0.8,
                "rationale_summary": "Old.",
                "position_exposure": "1234.56",
            }
        ],
        "total_holdings": 1,
        "affected_holdings": 1,
    }
    (tmp_path / "advisory").mkdir()
    (tmp_path / "advisory" / f"{CYCLE_A}_advisory.json").write_text(json.dumps(legacy))
    with TestClient(_app(tmp_path)) as client:
        response = client.get(f"/api/advisory/{CYCLE_A}")
    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["source"] == "swarm"
    assert body["stats"] is None and body["holdings_as_of"] is None
    # The legacy key maps onto cost_basis_exposure; swarm fields take their defaults
    # (docs/DECISIONS.md#adr-grounded-advisory).
    item = body["items"][0]
    assert item["cost_basis_exposure"] == "1234.56" and "position_exposure" not in item
    assert (item["swarm_support"], item["swarm_signal"], item["llm_signal"], item["divergent"]) == (
        0,
        None,
        None,
        False,
    )
    assert item["evidence_agent_ids"] == []


@pytest.mark.parametrize("content", _unreadable_contents(), ids=["older-shape", "not-json", "extra-field"])
def test_get_500_when_the_stored_advisory_is_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    (tmp_path / "advisory").mkdir()
    (tmp_path / "advisory" / f"{CYCLE_A}_advisory.json").write_text(content)
    recorder = MagicMock()
    monkeypatch.setattr(advisory_module, "log", recorder)
    with TestClient(_app(tmp_path)) as client:
        r = client.get(f"/api/advisory/{CYCLE_A}")
    assert r.status_code == 500
    assert r.json()["detail"]["error"] == "advisory_generation_failed"
    assert r.json()["detail"]["cycle_id"] == CYCLE_A
    assert "ZZZT" not in r.text and "1234.56" not in r.text
    recorder.warning.assert_called_once()
    assert recorder.warning.call_args.args == ("advisory_file_invalid",)
    assert set(recorder.warning.call_args.kwargs) == {"cycle_id", "error_count"}
    assert "ZZZT" not in repr(recorder.mock_calls) and "1234.56" not in repr(recorder.mock_calls)


def test_openapi_declares_the_advisory_report_response(tmp_path: Path) -> None:
    schema = _app(tmp_path).openapi()
    ok = schema["paths"]["/api/advisory/{cycle_id}"]["get"]["responses"]["200"]
    assert ok["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/AdvisoryReport"}
    declared = schema["components"]["schemas"]["AdvisoryReport"]["properties"]
    assert set(declared) == set(AdvisoryReport.model_fields)
