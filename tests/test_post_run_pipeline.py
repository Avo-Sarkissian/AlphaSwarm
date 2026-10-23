"""PostRunPipeline order and failure branches (docs/DECISIONS.md#adr-advisory-pipeline)."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

import alphaswarm.services.post_run as post_run_module
from alphaswarm.errors import AuthError, BudgetExceededError
from alphaswarm.services.jobs import JobInProgressError
from alphaswarm.services.post_run import (
    AdvisoryGate,
    PostRunOutcome,
    PostRunPipeline,
)

CYCLE = "00000000-0000-4000-8000-0000000000a1"


class FakeJobs:
    def __init__(
        self,
        gate: AdvisoryGate = "run",
        *,
        gate_exc: BaseException | None = None,
        advisory_exc: BaseException | None = None,
        report_exc: BaseException | None = None,
    ) -> None:
        self.gate = gate
        self.gate_exc = gate_exc
        self.advisory_exc = advisory_exc
        self.report_exc = report_exc
        self.calls: list[str] = []

    async def advisory_gate(self, cycle_id: str) -> AdvisoryGate:
        self.calls.append("gate")
        if self.gate_exc is not None:
            raise self.gate_exc
        return self.gate

    async def run_advisory(self, cycle_id: str) -> None:
        self.calls.append("advisory")
        if self.advisory_exc is not None:
            raise self.advisory_exc

    async def run_report(self, cycle_id: str) -> None:
        self.calls.append("report")
        if self.report_exc is not None:
            raise self.report_exc


@pytest.fixture()
def recorder(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    fake_log = MagicMock()
    monkeypatch.setattr(post_run_module, "log", fake_log)
    return fake_log


async def test_runs_advisory_then_report(recorder: MagicMock) -> None:
    jobs = FakeJobs()
    outcome = await PostRunPipeline(jobs=jobs).on_complete(CYCLE)
    assert outcome == PostRunOutcome(cycle_id=CYCLE, advisory="ran", report="ran")
    assert jobs.calls == ["gate", "advisory", "report"]
    recorder.info.assert_any_call(
        "post_run_pipeline_completed",
        cycle_id=CYCLE,
        advisory="ran",
        report="ran",
    )


@pytest.mark.parametrize(
    ("gate", "expected", "event"),
    [
        ("no_portfolio", "skipped_no_portfolio", "auto_advisory_skipped_no_portfolio"),
        (
            "cloud_advisory_disabled",
            "skipped_cloud_advisory_disabled",
            "auto_advisory_skipped_cloud",
        ),
    ],
)
async def test_skipped_advisory_still_runs_the_report(
    recorder: MagicMock,
    gate: AdvisoryGate,
    expected: str,
    event: str,
) -> None:
    jobs = FakeJobs(gate)
    outcome = await PostRunPipeline(jobs=jobs).on_complete(CYCLE)
    assert (outcome.advisory, outcome.report) == (expected, "ran")
    assert jobs.calls == ["gate", "report"]
    recorder.info.assert_any_call(event, cycle_id=CYCLE)


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("synthesis broke"),
        AuthError("bad key", provider="anthropic", model="claude-test"),
        BudgetExceededError(Decimal("2"), Decimal("1")),
    ],
)
async def test_failed_advisory_is_logged_and_the_report_still_runs(
    recorder: MagicMock,
    exc: BaseException,
) -> None:
    jobs = FakeJobs(advisory_exc=exc)
    outcome = await PostRunPipeline(jobs=jobs).on_complete(CYCLE)
    assert (outcome.advisory, outcome.report) == ("failed", "ran")
    assert jobs.calls == ["gate", "advisory", "report"]
    recorder.error.assert_any_call("auto_advisory_failed", cycle_id=CYCLE, exc_info=True)


async def test_gate_failure_counts_as_failed_advisory(recorder: MagicMock) -> None:
    jobs = FakeJobs(gate_exc=ValueError("config unreadable"))
    outcome = await PostRunPipeline(jobs=jobs).on_complete(CYCLE)
    assert (outcome.advisory, outcome.report) == ("failed", "ran")


async def test_busy_slots_are_skipped(recorder: MagicMock) -> None:
    jobs = FakeJobs(advisory_exc=JobInProgressError("report"), report_exc=JobInProgressError("advisory"))
    outcome = await PostRunPipeline(jobs=jobs).on_complete(CYCLE)
    assert (outcome.advisory, outcome.report) == ("skipped_busy", "skipped_busy")


async def test_report_failure_is_reported_not_raised(recorder: MagicMock) -> None:
    jobs = FakeJobs(report_exc=RuntimeError("react loop broke"))
    outcome = await PostRunPipeline(jobs=jobs).on_complete(CYCLE)
    assert (outcome.advisory, outcome.report) == ("ran", "failed")
    recorder.error.assert_any_call("auto_report_failed", cycle_id=CYCLE, exc_info=True)


async def test_cancellation_propagates_and_skips_the_report(recorder: MagicMock) -> None:
    jobs = FakeJobs(advisory_exc=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await PostRunPipeline(jobs=jobs).on_complete(CYCLE)
    assert jobs.calls == ["gate", "advisory"]
