"""Orchestrator job status kept in the StateStore (docs/DECISIONS.md#adr-background-tasks)."""

from __future__ import annotations

from alphaswarm.state import JobsSnapshot, JobStatus, StateStore
from alphaswarm.types import SimulationPhase


def test_job_statuses_default_to_idle() -> None:
    assert StateStore().job_statuses() == JobsSnapshot(advisory=JobStatus(), report=JobStatus())


def test_set_job_status_is_per_kind() -> None:
    store = StateStore()
    store.set_job_status("report", JobStatus(state="running", cycle_id="c1"))
    jobs = store.job_statuses()
    assert jobs.report == JobStatus(state="running", cycle_id="c1", error_code=None)
    assert jobs.advisory == JobStatus()


def test_failed_status_keeps_cycle_and_code() -> None:
    store = StateStore()
    store.set_job_status("advisory", JobStatus("failed", "c1", "advisory_generation_failed"))
    assert store.job_statuses().advisory.error_code == "advisory_generation_failed"


async def test_job_status_survives_a_new_run() -> None:
    store = StateStore()
    store.set_job_status("report", JobStatus("failed", "c1", "report_generation_failed"))
    await store.set_phase(SimulationPhase.SEEDING)
    assert store.job_statuses().report.state == "failed"
