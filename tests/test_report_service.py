"""ReportService: lock -> open operation -> generate_report -> teardown."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

import alphaswarm.services.report as report_service_module
import alphaswarm.services.runtime as runtime_module
from alphaswarm.graph import GraphStateManager
from alphaswarm.inference.budget import BudgetMeter
from alphaswarm.inference.factory import BuiltProviders
from alphaswarm.inference.types import InferenceResult, ProviderRole
from alphaswarm.services.jobs import JobInProgressError, JobRunner
from alphaswarm.services.report import ReportService
from alphaswarm.services.runtime import InferenceRuntime, close_operation
from alphaswarm.state import JobStatus, StateStore
from tests.inference.fakes import FakeInferenceProvider
from tests.support.report_fakes import REPORT_CYCLE, FakeReportGraph

NARRATIVE = json.dumps({"summary": "Consensus ended BUY.", "moments": [], "dissent": [], "followups": []})


class RecordingProvider(FakeInferenceProvider):
    def __init__(self, role: ProviderRole, events: list[str], contents: list[str]) -> None:
        super().__init__(
            role,
            f"fake-{role.value}",
            scripted=[InferenceResult(content=c, model="fake") for c in contents],
        )
        self.events = events

    async def prepare(self) -> None:
        self.events.append(f"{self.role.value}:prepare")

    async def teardown(self) -> None:
        self.events.append(f"{self.role.value}:teardown")

    async def aclose(self) -> None:
        self.events.append(f"{self.role.value}:aclose")


class FakeInference:
    def __init__(self, contents: list[str]) -> None:
        self.events: list[str] = []
        self.operations: list[str] = []
        self._contents = contents

    async def open_operation(self, name: str) -> BuiltProviders:
        self.operations.append(name)
        return BuiltProviders(
            orchestrator=RecordingProvider(ProviderRole.ORCHESTRATOR, self.events, self._contents),
            worker=RecordingProvider(ProviderRole.WORKER, self.events, []),
            budget_meter=BudgetMeter(None, {}),
        )


def _service(tmp_path: Path, inference: FakeInference, graph: Any = None) -> tuple[ReportService, JobRunner]:
    jobs = JobRunner(StateStore())
    service = ReportService(
        graph=cast(GraphStateManager, graph if graph is not None else FakeReportGraph()),
        inference=cast(InferenceRuntime, inference),
        jobs=jobs,
        reports_dir=tmp_path / "reports",
    )
    return service, jobs


async def test_generate_runs_one_operation_and_closes_everything(tmp_path: Path) -> None:
    inference = FakeInference([NARRATIVE])
    service, _ = _service(tmp_path, inference)
    result = await service.generate(REPORT_CYCLE)
    assert inference.operations == ["report"]
    assert inference.events == [
        "orchestrator:prepare",
        "orchestrator:teardown",
        "orchestrator:aclose",
        "worker:aclose",
    ]
    assert result.path == tmp_path / "reports" / f"{REPORT_CYCLE}_report.md"
    assert result.path.is_file() and result.path.with_suffix(".json").is_file()
    assert service.reports_dir == tmp_path / "reports"


async def test_generate_tears_down_on_failure(tmp_path: Path) -> None:
    class BrokenGraph(FakeReportGraph):
        async def read_round_timeline(self, cycle_id: str) -> Any:
            raise RuntimeError("graph down")

    inference = FakeInference([NARRATIVE])
    service, _ = _service(tmp_path, inference, graph=BrokenGraph())
    with pytest.raises(RuntimeError, match="graph down"):
        await service.generate(REPORT_CYCLE)
    assert inference.events[-3:] == ["orchestrator:teardown", "orchestrator:aclose", "worker:aclose"]


async def test_generate_failure_is_logged_with_its_traceback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenGraph(FakeReportGraph):
        async def read_round_timeline(self, cycle_id: str) -> Any:
            raise RuntimeError("graph down")

    fake_log = MagicMock()
    monkeypatch.setattr(report_service_module, "log", fake_log)
    service, _ = _service(tmp_path, FakeInference([NARRATIVE]), graph=BrokenGraph())
    with pytest.raises(RuntimeError):
        await service.generate(REPORT_CYCLE)
    fake_log.error.assert_called_once_with(
        "report_generation_failed", cycle_id=REPORT_CYCLE, error_type="RuntimeError", exc_info=True
    )


async def test_generate_waits_for_the_orchestrator_lock(tmp_path: Path) -> None:
    inference = FakeInference([NARRATIVE])
    service, jobs = _service(tmp_path, inference)
    async with jobs.orchestrator_lock:
        task = asyncio.create_task(service.generate(REPORT_CYCLE))
        await asyncio.sleep(0)
        assert inference.operations == []
    await task
    assert inference.operations == ["report"]


async def test_start_is_a_report_job(tmp_path: Path) -> None:
    service, jobs = _service(tmp_path, FakeInference([NARRATIVE]))
    task = service.start(REPORT_CYCLE)
    assert jobs.status("report") == JobStatus("running", REPORT_CYCLE)
    with pytest.raises(JobInProgressError):
        service.start(REPORT_CYCLE)
    await task
    assert jobs.status("report") == JobStatus("idle", REPORT_CYCLE)


class _FailingProvider(FakeInferenceProvider):
    """Raises from teardown and aclose; records that each was attempted."""

    def __init__(self, role: ProviderRole, events: list[str]) -> None:
        super().__init__(role, f"fake-{role.value}", scripted=[])
        self.events = events

    async def teardown(self) -> None:
        self.events.append(f"{self.role.value}:teardown")
        raise RuntimeError("unload failed")

    async def aclose(self) -> None:
        self.events.append(f"{self.role.value}:aclose")
        raise RuntimeError("close failed")


@pytest.mark.parametrize(
    ("teardown", "expected"),
    [
        (True, ["orchestrator:teardown", "orchestrator:aclose", "worker:aclose"]),
        (False, ["orchestrator:aclose", "worker:aclose"]),
    ],
)
async def test_close_operation_logs_failures_and_never_raises(
    monkeypatch: pytest.MonkeyPatch, teardown: bool, expected: list[str]
) -> None:
    fake_log = MagicMock()
    monkeypatch.setattr(runtime_module, "log", fake_log)
    events: list[str] = []
    built = BuiltProviders(
        orchestrator=_FailingProvider(ProviderRole.ORCHESTRATOR, events),
        worker=_FailingProvider(ProviderRole.WORKER, events),
        budget_meter=BudgetMeter(None, {}),
    )
    await close_operation(built, teardown=teardown)
    assert events == expected
    names = [call.args[0] for call in fake_log.warning.call_args_list]
    assert names == (["orchestrator_teardown_failed"] if teardown else []) + ["provider_close_failed"] * 2
