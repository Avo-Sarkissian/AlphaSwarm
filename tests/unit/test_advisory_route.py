"""POST/GET /api/advisory/{cycle_id} (docs/DECISIONS.md#adr-background-tasks)."""

from __future__ import annotations

import asyncio
import json
import os
import stat
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import alphaswarm.web.guards as guards_module
import alphaswarm.web.routes.advisory as advisory_module
from alphaswarm.advisory import AdvisoryItem, AdvisoryReport
from alphaswarm.config import InferenceConfig, ProviderType, RoleConfig, save_inference_config
from alphaswarm.errors import InferenceConfigError, Neo4jUnavailableError
from alphaswarm.holdings.types import Holding, PortfolioSnapshot
from alphaswarm.inference.budget import BudgetMeter
from alphaswarm.inference.factory import BuiltProviders
from alphaswarm.state import JobStatus, StateStore
from alphaswarm.web.routes.advisory import router as advisory_router
from tests.support.log_capture import RenderedLog
from tests.support.web_app import (
    CYCLE_A,
    CYCLE_B,
    CYCLE_UNKNOWN,
    FakeCycleGraph,
    StaticPortfolioCache,
    make_route_app,
    route_test_settings,
)

_REAL_SYNTHESIS = advisory_module._run_advisory_synthesis


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
                position_exposure=Decimal("1234.56"),
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
def _blocked_synthesis(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _blocked(app_state: Any, cycle_id: str, portfolio: Any) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(advisory_module, "_run_advisory_synthesis", _blocked)


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
        assert isinstance(app.state.advisory_task, asyncio.Task)


def test_post_404_for_unknown_cycle_starts_nothing(tmp_path: Path) -> None:
    app = _app(tmp_path, portfolio=_portfolio())
    with TestClient(app) as client:
        r = client.post(f"/api/advisory/{CYCLE_UNKNOWN}")
        assert r.status_code == 404
        assert r.json()["detail"]["error"] == "cycle_not_found"
        assert app.state.advisory_task is None


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


class _RunStartsDuringHoldingsRead(StaticPortfolioCache):
    """POST /api/simulate/start lands while the route awaits the holdings.

    The run's start() probe passes because no job is marked running yet, so
    the route must check again before it starts the job.
    """

    def __init__(self, snapshot: object, sim_manager: Any) -> None:
        super().__init__(snapshot)
        self._sim_manager = sim_manager

    async def get(self) -> object | None:
        self._sim_manager._is_running = True
        return await super().get()


def test_post_409_when_a_run_starts_during_the_holdings_read(tmp_path: Path) -> None:
    app = _app(tmp_path, portfolio=_portfolio())
    with TestClient(app) as client:
        app.state.portfolio_cache = _RunStartsDuringHoldingsRead(
            _portfolio(), app.state.sim_manager,
        )
        r = client.post(f"/api/advisory/{CYCLE_A}")
        assert r.status_code == 409
        assert r.json()["detail"]["error"] == "simulation_running"
        assert app.state.advisory_task is None
        assert _store(app).job_statuses().advisory == JobStatus()


def test_post_503_without_holdings(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, portfolio=None)) as client:
        r = client.post(f"/api/advisory/{CYCLE_A}")
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "holdings_unavailable"


def _cloud_app(tmp_path: Path, *, opt_in: bool, portfolio: object | None) -> FastAPI:
    """App whose stored config uses a cloud orchestrator, with the opt-in flag set or not."""
    settings = route_test_settings(tmp_path)
    cloud = InferenceConfig(
        orchestrator=RoleConfig(
            provider=ProviderType.ANTHROPIC, model="claude-test", api_key="sk-x",
        ),
        worker=RoleConfig(provider=ProviderType.OLLAMA, model="alphaswarm-worker"),
        allow_cloud_advisory=opt_in,
    )
    save_inference_config(cloud, settings.inference_config_path)
    return make_route_app(
        advisory_router, settings=settings,
        graph=FakeCycleGraph({CYCLE_A: "complete"}), portfolio=portfolio,
    )


def test_post_409_for_cloud_orchestrator_without_opt_in(tmp_path: Path) -> None:
    app = _cloud_app(tmp_path, opt_in=False, portfolio=_portfolio())
    with TestClient(app) as client:
        r = client.post(f"/api/advisory/{CYCLE_A}")
        assert r.status_code == 409
        assert r.json()["detail"]["error"] == "cloud_advisory_disabled"
        assert app.state.advisory_task is None


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
        advisory_router, settings=settings,
        graph=FakeCycleGraph({CYCLE_A: "complete"}), portfolio=_portfolio(),
    )
    with TestClient(app) as client:
        r = client.post(f"/api/advisory/{CYCLE_A}")
        assert r.status_code == 422
        assert r.json()["detail"]["error"] == "inference_config_invalid"
        assert str(tmp_path) not in r.text
        assert app.state.advisory_task is None
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
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
        assert client.get(f"/api/advisory/{CYCLE_A}").json()["detail"]["error"] == (
            "advisory_not_found"
        )
        app.state.advisory_generation_error = {
            CYCLE_A: {
                "error": "advisory_generation_failed",
                "message": "Advisory generation failed",
            },
        }
        failed = client.get(f"/api/advisory/{CYCLE_A}")
        assert failed.status_code == 500
        assert failed.json()["detail"]["cycle_id"] == CYCLE_A
        _store(app).set_job_status("advisory", JobStatus("running", CYCLE_A))
        running = client.get(f"/api/advisory/{CYCLE_A}")
        assert running.status_code == 409
        assert running.json()["detail"]["error"] == "advisory_generation_in_progress"


async def test_done_callback_failure_records_class_name_only() -> None:
    app = FastAPI()
    app.state.app_state = SimpleNamespace(state_store=StateStore())
    app.state.advisory_generation_error = {}

    async def _fail() -> None:
        raise ValueError("ZZZT leaked into an exception message")

    task = asyncio.create_task(_fail())
    with pytest.raises(ValueError):
        await task
    advisory_module._on_advisory_task_done(task, CYCLE_A, app)
    assert app.state.advisory_generation_error[CYCLE_A] == {
        "error": "advisory_generation_failed",
        "message": "Advisory generation failed (ValueError)",
    }
    assert app.state.app_state.state_store.job_statuses().advisory == JobStatus(
        "failed", CYCLE_A, "advisory_generation_failed",
    )


class _FakeProvider:
    role = "orchestrator"
    model = "fake-orch"

    async def prepare(self) -> None:
        return None

    async def teardown(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


class _FakeReport:
    affected_holdings = 1

    def model_dump_json(self, *, indent: int) -> str:
        return json.dumps({"cycle_id": CYCLE_A, "items": []}, indent=indent)


async def test_synthesis_writes_atomically_into_advisory_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _FakeProvider()
    built = BuiltProviders(
        orchestrator=provider,  # type: ignore[arg-type]
        worker=provider,  # type: ignore[arg-type]
        budget_meter=BudgetMeter(None, {}),
    )

    async def _synthesize(**_: Any) -> _FakeReport:
        return _FakeReport()

    # load_inference_config is not patched: route_test_settings points it at a missing
    # file, so the job's cloud re-check sees the local default config.
    monkeypatch.setattr(advisory_module, "build_providers", lambda *a, **k: built)
    monkeypatch.setattr(advisory_module, "synthesize", _synthesize)
    # The job asks the shared client for its host and whether the model runs remotely.
    client = SimpleNamespace(
        base_url="http://127.0.0.1:11434", is_remote_model=AsyncMock(return_value=False),
    )
    app_state = SimpleNamespace(
        settings=route_test_settings(tmp_path),
        graph_manager=object(),
        ollama_client=client,
        model_manager=object(),
    )
    await _REAL_SYNTHESIS(app_state, CYCLE_A, _portfolio())  # type: ignore[arg-type]
    out = tmp_path / "advisory" / f"{CYCLE_A}_advisory.json"
    assert json.loads(out.read_text(encoding="utf-8"))["cycle_id"] == CYCLE_A
    assert sorted(p.name for p in out.parent.iterdir()) == [out.name]
    if os.name == "posix":
        assert stat.S_IMODE(out.stat().st_mode) == 0o600


async def test_synthesis_fails_with_a_fixed_error_on_an_invalid_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
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
    rendered = RenderedLog()
    monkeypatch.setattr(advisory_module, "log", rendered)
    monkeypatch.setattr(guards_module, "log", rendered, raising=False)
    client = SimpleNamespace(
        base_url="http://127.0.0.1:11434", is_remote_model=AsyncMock(return_value=False),
    )
    app_state = SimpleNamespace(
        settings=settings, graph_manager=object(), ollama_client=client, model_manager=object(),
    )
    with pytest.raises(InferenceConfigError) as exc_info:
        await _REAL_SYNTHESIS(app_state, CYCLE_A, _portfolio())  # type: ignore[arg-type]
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True
    assert canary not in str(exc_info.value)
    assert rendered.events == ["job_inference_config_invalid"]
    assert canary not in rendered.text
    assert '"error_type": "ValueError"' in rendered.text


# ------ Cloud-advisory guard: host and model checks at the route ------
# (docs/DECISIONS.md#adr-advisory-pipeline)


def _ollama_cfg_app(tmp_path: Path, model: str, *, opt_in: bool) -> FastAPI:
    settings = route_test_settings(tmp_path)
    role = RoleConfig(provider=ProviderType.OLLAMA, model=model)
    cfg = InferenceConfig(orchestrator=role, worker=role, allow_cloud_advisory=opt_in)
    save_inference_config(cfg, settings.inference_config_path)
    return make_route_app(
        advisory_router, settings=settings,
        graph=FakeCycleGraph({CYCLE_A: "complete"}), portfolio=_portfolio(),
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
    tmp_path: Path, model: str, ollama_host: str, opt_in: bool,
) -> None:
    """The guard reads the host the shared OllamaClient really connects to."""
    app = _ollama_cfg_app(tmp_path, model, opt_in=opt_in)
    with TestClient(app) as client:
        app.state.app_state.ollama_client = SimpleNamespace(base_url=ollama_host)
        r = client.post(f"/api/advisory/{CYCLE_A}")
        if opt_in:
            assert r.status_code == 202
        else:
            assert r.status_code == 409
            assert r.json()["detail"]["error"] == "cloud_advisory_disabled"
            assert "remote" in r.json()["detail"]["message"]
            assert app.state.advisory_task is None


def test_no_ollama_client_fails_closed(tmp_path: Path) -> None:
    app = _app(tmp_path, portfolio=_portfolio())
    with TestClient(app) as client:
        app.state.app_state.ollama_client = None
        r = client.post(f"/api/advisory/{CYCLE_A}")
        assert r.status_code == 409
        assert r.json()["detail"]["error"] == "cloud_advisory_disabled"
        assert app.state.portfolio_cache.get_calls == 0


def test_a_permission_denied_config_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _denied(_settings: Any) -> InferenceConfig:
        raise PermissionError("permission denied")

    monkeypatch.setattr("alphaswarm.web.guards.load_inference_config", _denied)
    app = _app(tmp_path, portfolio=_portfolio())
    with TestClient(app) as client:
        r = client.post(f"/api/advisory/{CYCLE_A}")
        assert r.status_code == 422
        assert r.json()["detail"]["error"] == "inference_config_invalid"
        assert app.state.advisory_task is None
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


async def test_a_refused_job_keeps_its_own_fixed_message() -> None:
    """A job refused by the /api/show check keeps that check's message, not the generic one."""
    app = FastAPI()
    app.state.app_state = SimpleNamespace(state_store=StateStore())

    async def _refused() -> None:
        raise advisory_module.CloudAdvisoryDisabledError(
            advisory_module._MODEL_CHECK_FAILED_MESSAGE,
        )

    task = asyncio.create_task(_refused())
    with pytest.raises(advisory_module.CloudAdvisoryDisabledError):
        await task
    advisory_module._on_advisory_task_done(task, CYCLE_A, app)
    assert app.state.advisory_generation_error[CYCLE_A] == {
        "error": "cloud_advisory_disabled",
        "message": advisory_module._MODEL_CHECK_FAILED_MESSAGE,
    }
    assert app.state.app_state.state_store.job_statuses().advisory == JobStatus(
        "failed", CYCLE_A, "cloud_advisory_disabled",
    )


@pytest.mark.parametrize(
    "content", _unreadable_contents(), ids=["older-shape", "not-json", "extra-field"]
)
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
    assert ok["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AdvisoryReport"
    }
    declared = schema["components"]["schemas"]["AdvisoryReport"]["properties"]
    assert set(declared) == set(AdvisoryReport.model_fields)
