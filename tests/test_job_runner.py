"""JobRunner: one orchestrator job at a time, per-cycle failures, clean shutdown."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
import structlog
from pydantic import BaseModel, ValidationError

import alphaswarm.services.jobs as jobs_module
from alphaswarm.errors import AlphaSwarmError, InferenceConfigError
from alphaswarm.services.jobs import JOB_FAILURE_CODES, JobInProgressError, JobRunner
from alphaswarm.state import JobStatus, StateStore
from tests.support.web_app import CYCLE_A, CYCLE_B


async def _ok() -> None:
    return None


async def _blocked() -> None:
    await asyncio.Event().wait()


async def test_success_marks_running_then_idle() -> None:
    store = StateStore()
    runner = JobRunner(store)
    task = runner.start("report", CYCLE_A, _ok)
    assert store.job_statuses().report == JobStatus("running", CYCLE_A)
    assert runner.is_busy() and runner.running() == "report"
    await task
    assert store.job_statuses().report == JobStatus("idle", CYCLE_A)
    assert runner.error_for("report", CYCLE_A) is None and not runner.is_busy()


async def test_failure_records_the_kind_code_per_cycle() -> None:
    store = StateStore()
    runner = JobRunner(store)

    async def _fail() -> None:
        raise RuntimeError("boom")

    task = runner.start("advisory", CYCLE_A, _fail)
    with pytest.raises(RuntimeError):
        await task
    assert runner.error_for("advisory", CYCLE_A) == "advisory_generation_failed"
    assert runner.error_for("advisory", CYCLE_B) is None
    assert store.job_statuses().advisory == JobStatus("failed", CYCLE_A, "advisory_generation_failed")


async def test_restart_clears_that_cycles_old_error() -> None:
    runner = JobRunner(StateStore())

    async def _fail() -> None:
        raise ValueError("x")

    with pytest.raises(ValueError):
        await runner.start("report", CYCLE_A, _fail)
    await runner.start("report", CYCLE_A, _ok)
    assert runner.error_for("report", CYCLE_A) is None


async def test_second_job_conflicts_with_the_running_kind() -> None:
    runner = JobRunner(StateStore())
    runner.start("report", CYCLE_A, _blocked)
    with pytest.raises(JobInProgressError) as exc:
        runner.start("advisory", CYCLE_B, _ok)
    assert exc.value.kind == "report"
    assert exc.value.code == "report_generation_in_progress"
    await runner.shutdown()


async def test_busy_reads_the_store_as_the_single_source_of_truth() -> None:
    store = StateStore()
    runner = JobRunner(store)
    store.set_job_status("advisory", JobStatus("running", CYCLE_A))
    assert runner.is_busy() and runner.running() == "advisory"
    with pytest.raises(JobInProgressError):
        runner.start("report", CYCLE_B, _ok)


async def test_shutdown_cancels_and_records_failure() -> None:
    store = StateStore()
    runner = JobRunner(store)
    task = runner.start("report", CYCLE_A, _blocked)
    await asyncio.sleep(0)
    await runner.shutdown()
    assert task.cancelled()
    assert store.job_statuses().report == JobStatus("failed", CYCLE_A, "report_generation_failed")
    assert not runner.is_busy()


async def test_advisory_failures_never_log_the_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_log = MagicMock()
    monkeypatch.setattr(jobs_module, "log", fake_log)
    runner = JobRunner(StateStore())

    async def _fail() -> None:
        raise ValueError("ZZZT 12.3456 1234.56")

    with pytest.raises(ValueError):
        await runner.start("advisory", CYCLE_A, _fail)
    args, kwargs = fake_log.error.call_args
    assert args == ("job_failed",)
    assert kwargs == {"kind": "advisory", "cycle_id": CYCLE_A, "exc_type": "ValueError"}


async def test_advisory_validation_failures_log_a_summary_only(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_log = MagicMock()
    monkeypatch.setattr(jobs_module, "log", fake_log)
    runner = JobRunner(StateStore())

    class _Row(BaseModel):
        ticker: int

    async def _fail() -> None:
        _Row.model_validate({"ticker": "ZZZT"})

    with pytest.raises(ValidationError):
        await runner.start("advisory", CYCLE_A, _fail)
    kwargs = fake_log.error.call_args.kwargs
    assert "exc_info" not in kwargs
    assert kwargs["exc_type"] == "ValidationError"
    assert kwargs["error_count"] == 1 and kwargs["error_locations"] == ["ticker"]
    assert "ZZZT" not in repr(fake_log.mock_calls)


async def test_report_failures_log_the_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_log = MagicMock()
    monkeypatch.setattr(jobs_module, "log", fake_log)
    runner = JobRunner(StateStore())

    async def _fail() -> None:
        raise RuntimeError("report broke")

    with pytest.raises(RuntimeError):
        await runner.start("report", CYCLE_A, _fail)
    assert "exc_info" in fake_log.error.call_args.kwargs


async def test_orchestrator_lock_is_one_lock() -> None:
    runner = JobRunner(StateStore())
    assert runner.orchestrator_lock is runner.orchestrator_lock


async def test_job_binds_its_log_context_inside_the_task_only() -> None:
    runner = JobRunner(StateStore())
    seen: dict[str, object] = {}

    async def _capture() -> None:
        seen.update(structlog.contextvars.get_contextvars())

    structlog.contextvars.clear_contextvars()
    await runner.start("advisory", CYCLE_A, _capture)
    assert seen == {"cycle_id": CYCLE_A, "job": "advisory"}
    assert structlog.contextvars.get_contextvars() == {}


async def test_inference_config_failures_record_the_config_code() -> None:
    store = StateStore()
    runner = JobRunner(store)

    async def _fail() -> None:
        raise InferenceConfigError("fixed text")

    with pytest.raises(InferenceConfigError):
        await runner.start("report", CYCLE_A, _fail)
    assert runner.error_for("report", CYCLE_A) == "inference_config_invalid"
    assert store.job_statuses().report == JobStatus("failed", CYCLE_A, "inference_config_invalid")


async def test_a_refusal_with_its_own_code_is_recorded_under_that_code() -> None:
    runner = JobRunner(StateStore())

    class _RefusedError(AlphaSwarmError):
        job_failure_code = "cloud_advisory_disabled"

    async def _fail() -> None:
        raise _RefusedError("refused")

    with pytest.raises(_RefusedError):
        await runner.start("advisory", CYCLE_A, _fail)
    assert runner.error_for("advisory", CYCLE_A) == "cloud_advisory_disabled"


async def test_record_refusal_marks_the_cycle_failed_without_a_task() -> None:
    store = StateStore()
    runner = JobRunner(store)
    runner.record_refusal("advisory", CYCLE_A, "no_portfolio")
    assert runner.error_for("advisory", CYCLE_A) == "no_portfolio"
    assert store.job_statuses().advisory == JobStatus("failed", CYCLE_A, "no_portfolio")
    assert not runner.is_busy()
    await runner.start("advisory", CYCLE_A, _ok)
    assert runner.error_for("advisory", CYCLE_A) is None


async def test_record_refusal_never_overwrites_a_running_status() -> None:
    store = StateStore()
    runner = JobRunner(store)
    runner.start("advisory", CYCLE_A, _blocked)
    runner.record_refusal("advisory", CYCLE_B, "cloud_advisory_disabled")
    assert store.job_statuses().advisory == JobStatus("running", CYCLE_A)
    assert runner.error_for("advisory", CYCLE_B) == "cloud_advisory_disabled"
    await runner.shutdown()


def test_failure_codes_cover_both_kinds() -> None:
    assert JOB_FAILURE_CODES == {"report": "report_generation_failed", "advisory": "advisory_generation_failed"}
