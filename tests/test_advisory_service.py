"""AdvisoryService: gate, re-check under the lock, atomic owner-only write, prune."""

from __future__ import annotations

import asyncio
import json
import os
import stat
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

import alphaswarm.services.advisory as advisory_service_module
from alphaswarm.advisory import synthesize
from alphaswarm.advisory.sector_map import SectorMap
from alphaswarm.errors import StructuredOutputError
from alphaswarm.holdings.types import Holding, PortfolioSnapshot
from alphaswarm.inference.budget import BudgetMeter
from alphaswarm.inference.config import InferenceConfig, ProviderType, RoleConfig
from alphaswarm.inference.factory import BuiltProviders
from alphaswarm.inference.types import InferenceResult, ProviderRole
from alphaswarm.services.advisory import (
    CLOUD_ADVISORY_MESSAGE,
    MODEL_CHECK_FAILED_MESSAGE,
    AdvisoryNotAllowedError,
    AdvisoryService,
)
from alphaswarm.services.jobs import JobRunner
from alphaswarm.services.runtime import InferenceRuntime
from alphaswarm.state import JobStatus, StateStore
from tests.inference.fakes import FakeInferenceProvider
from tests.support.web_app import CYCLE_A

LOCAL = InferenceConfig(
    orchestrator=RoleConfig(provider=ProviderType.OLLAMA, model="alphaswarm-orchestrator"),
    worker=RoleConfig(provider=ProviderType.OLLAMA, model="alphaswarm-worker"),
)
CLOUD = InferenceConfig(
    orchestrator=RoleConfig(provider=ProviderType.ANTHROPIC, model="claude-test", api_key="sk-x"),
    worker=RoleConfig(provider=ProviderType.OLLAMA, model="alphaswarm-worker"),
)
REPLY = json.dumps(
    {
        "portfolio_outlook": "Constructive.",
        "items": [{"ticker": "ZZZT", "signal": "BUY", "confidence": 0.8, "rationale": "Accretive."}],
    }
)


def _portfolio(*tickers: str) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        holdings=tuple(Holding(ticker=t, qty=Decimal("12.3456"), cost_basis=Decimal("1234.56")) for t in tickers),
        as_of=datetime(2026, 9, 30, tzinfo=UTC),
        account_number_hash="cafebabe",
    )


class _Graph:
    async def read_consensus_summary(self, cycle_id: str) -> dict[str, Any]:
        return {"buy_count": 1, "sell_count": 0, "hold_count": 0, "parse_error_count": 0, "total": 1}

    async def read_round_timeline(self, cycle_id: str) -> list[dict[str, Any]]:
        return []

    async def read_bracket_narratives(self, cycle_id: str) -> list[dict[str, Any]]:
        return []

    async def read_entity_impact(self, cycle_id: str) -> list[dict[str, Any]]:
        return []

    async def read_cycle_seed(self, cycle_id: str) -> str:
        return "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."


class FakeOllamaClient:
    """The shared OllamaClient as the advisory gate sees it: its host and /api/show."""

    def __init__(self, base_url: str = "http://127.0.0.1:11434", *, remote: bool | Exception = False) -> None:
        self.base_url = base_url
        self.remote = remote
        self.checked: list[str] = []

    async def is_remote_model(self, model: str) -> bool:
        self.checked.append(model)
        if isinstance(self.remote, Exception):
            raise self.remote
        return self.remote


class FakeInference:
    def __init__(self, cfg: InferenceConfig, contents: list[str], *, client: FakeOllamaClient | None = None) -> None:
        self.cfg = cfg
        self.operations: list[str] = []
        self.ollama_client: FakeOllamaClient | None = client if client is not None else FakeOllamaClient()
        self.orchestrator = FakeInferenceProvider(
            ProviderRole.ORCHESTRATOR,
            "fake-orch",
            scripted=[InferenceResult(content=c, model="fake-orch") for c in contents],
        )

    async def config(self) -> InferenceConfig:
        return self.cfg

    async def open_operation(self, name: str) -> BuiltProviders:
        self.operations.append(name)
        return BuiltProviders(
            orchestrator=self.orchestrator,
            worker=FakeInferenceProvider(ProviderRole.WORKER, "fake-worker", scripted=[]),
            budget_meter=BudgetMeter(None, {}),
        )


def _service(
    tmp_path: Path,
    inference: FakeInference,
    portfolio: PortfolioSnapshot | None,
    *,
    keep_last: int = 20,
    sector_map_path: Path | None = None,
) -> AdvisoryService:
    async def _get() -> PortfolioSnapshot | None:
        return portfolio

    return AdvisoryService(
        graph=_Graph(),  # type: ignore[arg-type]
        inference=cast(InferenceRuntime, inference),
        jobs=JobRunner(StateStore()),
        advisory_dir=tmp_path / "advisory",
        portfolio=_get,
        keep_last=keep_last,
        sector_map_path=sector_map_path,
    )


@pytest.mark.parametrize(
    ("cfg", "portfolio", "expected"),
    [
        (LOCAL, None, "no_portfolio"),
        (LOCAL, _portfolio(), "no_portfolio"),
        (CLOUD, _portfolio("ZZZT"), "cloud_advisory_disabled"),
        (CLOUD.model_copy(update={"allow_cloud_advisory": True}), _portfolio("ZZZT"), "run"),
        (LOCAL, _portfolio("ZZZT"), "run"),
    ],
)
async def test_gate(tmp_path: Path, cfg: InferenceConfig, portfolio: PortfolioSnapshot | None, expected: str) -> None:
    assert await _service(tmp_path, FakeInference(cfg, []), portfolio).gate(CYCLE_A) == expected


async def test_gate_checks_the_orchestrator_before_touching_the_holdings(tmp_path: Path) -> None:
    calls: list[str] = []

    async def _get() -> PortfolioSnapshot | None:
        calls.append("get")
        return None

    service = AdvisoryService(
        graph=_Graph(),  # type: ignore[arg-type]
        inference=cast(InferenceRuntime, FakeInference(CLOUD, [])),
        jobs=JobRunner(StateStore()),
        advisory_dir=tmp_path / "advisory",
        portfolio=_get,
    )
    assert await service.gate(CYCLE_A) == "cloud_advisory_disabled"
    assert calls == []


@pytest.mark.parametrize(
    "client",
    [None, FakeOllamaClient("http://192.0.2.10:11434")],
    ids=["no_client", "remote_host"],
)
async def test_gate_fails_closed_without_a_local_ollama_host(tmp_path: Path, client: FakeOllamaClient | None) -> None:
    inference = FakeInference(LOCAL, [])
    inference.ollama_client = client
    assert await _service(tmp_path, inference, _portfolio("ZZZT")).gate(CYCLE_A) == "cloud_advisory_disabled"


async def test_generate_writes_owner_only_json_and_prunes(tmp_path: Path) -> None:
    advisory_dir = tmp_path / "advisory"
    advisory_dir.mkdir()
    for index in range(3):
        old = advisory_dir / f"00000000-0000-4000-8000-00000000000{index}_advisory.json"
        old.write_text("{}", encoding="utf-8")
        os.utime(old, (1_000_000 + index, 1_000_000 + index))
    inference = FakeInference(LOCAL, [REPLY])
    service = _service(tmp_path, inference, _portfolio("ZZZT"), keep_last=2)
    report = await service.generate(CYCLE_A)
    out = advisory_dir / f"{CYCLE_A}_advisory.json"
    assert json.loads(out.read_text(encoding="utf-8"))["items"][0]["ticker"] == "ZZZT"
    assert report.holdings_as_of is not None
    assert len(list(advisory_dir.glob("*_advisory.json"))) == 2
    assert inference.operations == ["advisory"]
    assert service.advisory_dir == advisory_dir
    if os.name == "posix":
        assert stat.S_IMODE(out.stat().st_mode) == 0o600


async def test_generate_rechecks_cloud_opt_in_under_the_lock(tmp_path: Path) -> None:
    inference = FakeInference(LOCAL, [REPLY])
    service = _service(tmp_path, inference, _portfolio("ZZZT"))
    assert await service.gate(CYCLE_A) == "run"
    jobs = service._jobs
    async with jobs.orchestrator_lock:
        task = asyncio.create_task(service.generate(CYCLE_A))
        await asyncio.sleep(0)
        inference.cfg = CLOUD  # Settings saved while the job waited for the orchestrator
    with pytest.raises(AdvisoryNotAllowedError) as exc:
        await task
    assert exc.value.gate == "cloud_advisory_disabled"
    assert str(exc.value) == CLOUD_ADVISORY_MESSAGE
    assert inference.operations == [] and inference.orchestrator.calls == []
    assert not (tmp_path / "advisory").exists()


async def test_portfolio_removed_before_generate(tmp_path: Path) -> None:
    with pytest.raises(AdvisoryNotAllowedError) as exc:
        await _service(tmp_path, FakeInference(LOCAL, [REPLY]), None).generate(CYCLE_A)
    assert exc.value.gate == "no_portfolio"
    assert exc.value.job_failure_code == "no_portfolio"


@pytest.mark.parametrize(
    ("remote", "message"),
    [(True, CLOUD_ADVISORY_MESSAGE), (OSError("connection refused"), MODEL_CHECK_FAILED_MESSAGE)],
    ids=["remote_model", "check_failed"],
)
async def test_generate_refuses_a_remote_ollama_model(
    tmp_path: Path, remote: bool | Exception, message: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_log = MagicMock()
    monkeypatch.setattr(advisory_service_module, "log", fake_log)
    client = FakeOllamaClient(remote=remote)
    inference = FakeInference(LOCAL, [REPLY], client=client)
    with pytest.raises(AdvisoryNotAllowedError) as exc:
        await _service(tmp_path, inference, _portfolio("ZZZT")).generate(CYCLE_A)
    assert exc.value.gate == "cloud_advisory_disabled"
    assert exc.value.job_failure_code == "cloud_advisory_disabled"
    assert str(exc.value) == message
    assert client.checked == ["alphaswarm-orchestrator"]
    assert inference.operations == []
    assert "connection refused" not in repr(fake_log.mock_calls)


async def test_opt_in_skips_the_remote_model_check(tmp_path: Path) -> None:
    client = FakeOllamaClient(remote=True)
    cfg = LOCAL.model_copy(update={"allow_cloud_advisory": True})
    inference = FakeInference(cfg, [REPLY], client=client)
    await _service(tmp_path, inference, _portfolio("ZZZT")).generate(CYCLE_A)
    assert client.checked == []
    assert inference.operations == ["advisory"]


async def test_generate_loads_the_sector_map_per_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    loaded: list[Path] = []
    seen: list[SectorMap | None] = []
    sentinel_map = MagicMock(spec=SectorMap)

    def _load(path: Path) -> SectorMap:
        loaded.append(path)
        return sentinel_map

    async def _synthesize(**kwargs: Any) -> Any:
        seen.append(kwargs.pop("sector_map"))
        return await synthesize(**kwargs)

    monkeypatch.setattr(advisory_service_module, "load_sector_map", _load)
    monkeypatch.setattr(advisory_service_module, "synthesize", _synthesize)
    path = tmp_path / "sector_map.local.json"
    await _service(tmp_path, FakeInference(LOCAL, [REPLY]), _portfolio("ZZZT"), sector_map_path=path).generate(CYCLE_A)
    assert loaded == [path] and seen == [sentinel_map]


async def test_a_failed_prune_keeps_the_written_advisory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _prune(*_args: Any, **_kwargs: Any) -> list[Path]:
        raise PermissionError("/secret/path")

    fake_log = MagicMock()
    monkeypatch.setattr(advisory_service_module, "log", fake_log)
    monkeypatch.setattr(advisory_service_module, "prune_old_files", _prune)
    await _service(tmp_path, FakeInference(LOCAL, [REPLY]), _portfolio("ZZZT")).generate(CYCLE_A)
    assert (tmp_path / "advisory" / f"{CYCLE_A}_advisory.json").is_file()
    fake_log.warning.assert_any_call("advisory_prune_failed", cycle_id=CYCLE_A, error_type="PermissionError")
    assert "/secret/path" not in repr(fake_log.mock_calls)


async def test_two_invalid_replies_write_nothing(tmp_path: Path) -> None:
    inference = FakeInference(LOCAL, ["prose", "more prose"])
    with pytest.raises(StructuredOutputError):
        await _service(tmp_path, inference, _portfolio("ZZZT")).generate(CYCLE_A)
    assert not (tmp_path / "advisory" / f"{CYCLE_A}_advisory.json").exists()


async def test_failure_log_carries_the_class_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_log = MagicMock()
    monkeypatch.setattr(advisory_service_module, "log", fake_log)
    inference = FakeInference(LOCAL, ["prose ZZZT 12.3456", "more prose ZZZT 1234.56"])
    with pytest.raises(StructuredOutputError):
        await _service(tmp_path, inference, _portfolio("ZZZT")).generate(CYCLE_A)
    (call,) = fake_log.error.call_args_list
    assert call.args == ("advisory_generation_failed",)
    assert call.kwargs["exc_type"] == "StructuredOutputError"
    assert "exc_info" not in call.kwargs
    logged = repr(fake_log.mock_calls)
    assert "12.3456" not in logged and "1234.56" not in logged


async def test_service_logs_carry_no_holdings_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_log = MagicMock()
    monkeypatch.setattr(advisory_service_module, "log", fake_log)
    await _service(tmp_path, FakeInference(LOCAL, [REPLY]), _portfolio("ZZZT")).generate(CYCLE_A)
    logged = repr(fake_log.mock_calls)
    assert "advisory_written" in logged  # positive control: the service did log
    assert "12.3456" not in logged and "1234.56" not in logged and "cafebabe" not in logged


async def test_start_records_a_refused_gate_as_the_job_failure(tmp_path: Path) -> None:
    service = _service(tmp_path, FakeInference(LOCAL, [REPLY]), None)
    task = service.start(CYCLE_A)
    with pytest.raises(AdvisoryNotAllowedError):
        await task
    await asyncio.sleep(0)
    jobs = service._jobs
    assert jobs.error_for("advisory", CYCLE_A) == "no_portfolio"
    assert jobs.status("advisory") == JobStatus("failed", CYCLE_A, "no_portfolio")


async def test_start_is_an_advisory_job(tmp_path: Path) -> None:
    service = _service(tmp_path, FakeInference(LOCAL, [REPLY]), _portfolio("ZZZT"))
    task = service.start(CYCLE_A)
    jobs = service._jobs
    assert jobs.status("advisory") == JobStatus("running", CYCLE_A)
    await task
    assert jobs.status("advisory") == JobStatus("idle", CYCLE_A)


class _RecordingProvider(FakeInferenceProvider):
    """Records prepare/teardown/aclose so the test can assert the provider lifecycle."""

    def __init__(self, events: list[str], contents: list[str]) -> None:
        super().__init__(
            ProviderRole.ORCHESTRATOR,
            "fake-orch",
            scripted=[InferenceResult(content=c, model="fake-orch") for c in contents],
        )
        self.events = events

    async def prepare(self) -> None:
        self.events.append("prepare")

    async def teardown(self) -> None:
        self.events.append("teardown")

    async def aclose(self) -> None:
        self.events.append("aclose")


@pytest.mark.parametrize(("replies", "fails"), [([REPLY], False), (["prose", "more prose"], True)])
async def test_generate_always_tears_down_and_closes_the_orchestrator(
    tmp_path: Path,
    replies: list[str],
    fails: bool,
) -> None:
    events: list[str] = []
    inference = FakeInference(LOCAL, [])
    inference.orchestrator = _RecordingProvider(events, replies)
    service = _service(tmp_path, inference, _portfolio("ZZZT"))
    if fails:
        with pytest.raises(StructuredOutputError):
            await service.generate(CYCLE_A)
    else:
        await service.generate(CYCLE_A)
    assert events == ["prepare", "teardown", "aclose"]
