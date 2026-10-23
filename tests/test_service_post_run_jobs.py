"""ServicePostRunJobs + PostRunPipeline over the real services and JobRunner."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from alphaswarm.errors import InferenceConfigError
from alphaswarm.services.advisory import AdvisoryNotAllowedError, AdvisoryService
from alphaswarm.services.jobs import JobRunner
from alphaswarm.services.post_run import PostRunPipeline, ServicePostRunJobs
from alphaswarm.services.report import ReportService
from alphaswarm.services.runtime import InferenceRuntime
from alphaswarm.state import JobStatus, StateStore
from tests.support.web_app import CYCLE_A, CYCLE_B


def _wire(
    tmp_path: Path,
    calls: list[str],
    *,
    gate: str = "run",
    gate_exc: BaseException | None = None,
    advisory_exc: BaseException | None = None,
) -> tuple[PostRunPipeline, StateStore, JobRunner]:
    store = StateStore()
    jobs = JobRunner(store)

    async def _no_portfolio() -> None:
        return None

    report = ReportService(
        graph=cast(Any, object()),
        inference=cast(InferenceRuntime, object()),
        jobs=jobs,
        reports_dir=tmp_path,
    )
    advisory = AdvisoryService(
        graph=cast(Any, object()),
        inference=cast(InferenceRuntime, object()),
        jobs=jobs,
        advisory_dir=tmp_path,
        portfolio=_no_portfolio,
    )

    async def _gate(cycle_id: str) -> Any:
        calls.append(f"gate:{cycle_id}")
        if gate_exc is not None:
            raise gate_exc
        return gate

    async def _advisory(cycle_id: str) -> Any:
        calls.append(f"advisory:{cycle_id}")
        if advisory_exc is not None:
            raise advisory_exc

    async def _report(cycle_id: str) -> Any:
        calls.append(f"report:{cycle_id}")

    object.__setattr__(advisory, "gate", _gate)
    object.__setattr__(advisory, "generate", _advisory)
    object.__setattr__(report, "generate", _report)
    pipeline = PostRunPipeline(jobs=ServicePostRunJobs(report=report, advisory=advisory))
    return pipeline, store, jobs


async def test_advisory_then_report(tmp_path: Path) -> None:
    calls: list[str] = []
    pipeline, store, _ = _wire(tmp_path, calls)
    outcome = await pipeline.on_complete(CYCLE_A)
    assert (outcome.advisory, outcome.report) == ("ran", "ran")
    assert calls == [f"gate:{CYCLE_A}", f"advisory:{CYCLE_A}", f"report:{CYCLE_A}"]
    jobs = store.job_statuses()
    assert (jobs.advisory, jobs.report) == (JobStatus("idle", CYCLE_A), JobStatus("idle", CYCLE_A))


async def test_no_portfolio_still_runs_the_report(tmp_path: Path) -> None:
    calls: list[str] = []
    pipeline, _, jobs = _wire(tmp_path, calls, gate="no_portfolio")
    outcome = await pipeline.on_complete(CYCLE_A)
    assert (outcome.advisory, outcome.report) == ("skipped_no_portfolio", "ran")
    assert calls == [f"gate:{CYCLE_A}", f"report:{CYCLE_A}"]
    assert jobs.error_for("advisory", CYCLE_A) is None


async def test_cloud_gate_is_recorded_for_get_and_the_report_runs(tmp_path: Path) -> None:
    """A refused gate is recorded, so GET answers its code instead of a pending 404."""
    calls: list[str] = []
    pipeline, store, jobs = _wire(tmp_path, calls, gate="cloud_advisory_disabled")
    outcome = await pipeline.on_complete(CYCLE_A)
    assert (outcome.advisory, outcome.report) == ("skipped_cloud_advisory_disabled", "ran")
    assert jobs.error_for("advisory", CYCLE_A) == "cloud_advisory_disabled"
    assert store.job_statuses().advisory.state == "failed"


async def test_unreadable_config_is_recorded_and_the_report_runs(tmp_path: Path) -> None:
    calls: list[str] = []
    pipeline, _, jobs = _wire(tmp_path, calls, gate_exc=InferenceConfigError("bad"))
    outcome = await pipeline.on_complete(CYCLE_A)
    assert (outcome.advisory, outcome.report) == ("failed", "ran")
    assert jobs.error_for("advisory", CYCLE_A) == "inference_config_invalid"


async def test_cloud_switch_after_gate_still_runs_report(tmp_path: Path) -> None:
    calls: list[str] = []
    pipeline, store, jobs = _wire(
        tmp_path,
        calls,
        advisory_exc=AdvisoryNotAllowedError("cloud_advisory_disabled"),
    )
    outcome = await pipeline.on_complete(CYCLE_A)
    assert (outcome.advisory, outcome.report) == ("failed", "ran")
    assert store.job_statuses().advisory.state == "failed"
    assert jobs.error_for("advisory", CYCLE_A) == "cloud_advisory_disabled"


async def test_busy_orchestrator_skips_both(tmp_path: Path) -> None:
    calls: list[str] = []
    pipeline, store, _ = _wire(tmp_path, calls)
    store.set_job_status("report", JobStatus("running", CYCLE_B))
    outcome = await pipeline.on_complete(CYCLE_A)
    assert (outcome.advisory, outcome.report) == ("skipped_busy", "skipped_busy")
    assert calls == [f"gate:{CYCLE_A}"]


def test_post_run_jobs_busy_error_is_gone() -> None:
    import alphaswarm.services.post_run as post_run_module

    assert not hasattr(post_run_module, "PostRunJobBusyError")
    with pytest.raises(ImportError):
        __import__("alphaswarm.web.post_run")
