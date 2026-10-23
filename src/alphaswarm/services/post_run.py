"""Post-run pipeline: the advisory when it is allowed, then the report, always.

Replaces the in-process HTTP self-calls that chained run completion -> POST
advisory -> (on success only) POST report. The deliberate advisory -> report
order is kept (docs/DECISIONS.md#adr-advisory-pipeline); only the no-holdings,
cloud-without-opt-in and failure branches change: the report now runs in every
case. The jobs are injected (PostRunJobs); ServicePostRunJobs implements them
over ReportService, AdvisoryService and JobRunner
(docs/DECISIONS.md#adr-sequential-model-lifecycle).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, Protocol

import structlog

from alphaswarm.errors import InferenceConfigError
from alphaswarm.logging import validation_error_summary
from alphaswarm.services.jobs import INFERENCE_CONFIG_FAILURE_CODE, JobInProgressError

if TYPE_CHECKING:
    from alphaswarm.services.advisory import AdvisoryService
    from alphaswarm.services.report import ReportService

log = structlog.get_logger(component="services.post_run")

AdvisoryGate = Literal["run", "no_portfolio", "cloud_advisory_disabled"]
AdvisoryOutcome = Literal[
    "ran",
    "skipped_no_portfolio",
    "skipped_cloud_advisory_disabled",
    "skipped_busy",
    "failed",
]
ReportOutcome = Literal["ran", "skipped_busy", "failed"]

_SKIPPED_BY_GATE: Final[dict[str, tuple[AdvisoryOutcome, str]]] = {
    "no_portfolio": ("skipped_no_portfolio", "auto_advisory_skipped_no_portfolio"),
    "cloud_advisory_disabled": ("skipped_cloud_advisory_disabled", "auto_advisory_skipped_cloud"),
}


class PostRunJobs(Protocol):
    """The three operations the pipeline needs; each run_* awaits completion."""

    async def advisory_gate(self, cycle_id: str) -> AdvisoryGate: ...
    async def run_advisory(self, cycle_id: str) -> None: ...
    async def run_report(self, cycle_id: str) -> None: ...


@dataclass(frozen=True)
class PostRunOutcome:
    """What happened to each job for one completed cycle."""

    cycle_id: str
    advisory: AdvisoryOutcome
    report: ReportOutcome


class PostRunPipeline:
    """Runs after every completed simulation (SimulationManager.on_complete)."""

    def __init__(self, *, jobs: PostRunJobs) -> None:
        self._jobs = jobs

    async def on_complete(self, cycle_id: str) -> PostRunOutcome:
        """Advisory (if the gate says run), then the report; never raises except on cancel."""
        advisory = await self._advisory(cycle_id)
        report = await self._report(cycle_id)
        log.info("post_run_pipeline_completed", cycle_id=cycle_id, advisory=advisory, report=report)
        return PostRunOutcome(cycle_id=cycle_id, advisory=advisory, report=report)

    async def _advisory(self, cycle_id: str) -> AdvisoryOutcome:
        try:
            gate = await self._jobs.advisory_gate(cycle_id)
        except Exception:
            log.error("auto_advisory_gate_failed", cycle_id=cycle_id, exc_info=True)
            return "failed"
        skipped = _SKIPPED_BY_GATE.get(gate)
        if skipped is not None:
            outcome, event = skipped
            log.info(event, cycle_id=cycle_id)
            return outcome
        try:
            await self._jobs.run_advisory(cycle_id)
        except JobInProgressError:
            log.warning("auto_advisory_skipped_busy", cycle_id=cycle_id)
            return "skipped_busy"
        except Exception as exc:
            # Includes AuthError/BudgetExceededError: logged with the traceback and
            # recorded as the job's failure, never silently dropped. A ValidationError
            # is logged as a summary without the traceback, whose text echoes the
            # model's input (docs/DECISIONS.md#adr-holdings-isolation).
            summary = validation_error_summary(exc)
            if summary:
                log.error(
                    "auto_advisory_failed",
                    cycle_id=cycle_id,
                    exc_type=exc.__class__.__name__,
                    **summary,
                )
            else:
                log.error("auto_advisory_failed", cycle_id=cycle_id, exc_info=True)
            return "failed"
        return "ran"

    async def _report(self, cycle_id: str) -> ReportOutcome:
        try:
            await self._jobs.run_report(cycle_id)
        except JobInProgressError:
            log.warning("auto_report_skipped_busy", cycle_id=cycle_id)
            return "skipped_busy"
        except Exception:
            log.error("auto_report_failed", cycle_id=cycle_id, exc_info=True)
            return "failed"
        return "ran"


class ServicePostRunJobs:
    """PostRunJobs over the services: each run_* starts the JobRunner job and awaits it.

    A busy orchestrator raises JobInProgressError synchronously from ``start``
    (the pipeline records ``skipped_busy``); a failed job re-raises from the
    awaited task (the pipeline records ``failed``, the JobRunner records the
    per-cycle code for GET). A refused gate (cloud orchestrator without the
    opt-in, unreadable inference config) is recorded too, so GET answers with
    its code instead of a 404 the UI shows as pending
    (docs/DECISIONS.md#adr-advisory-pipeline).
    """

    def __init__(self, *, report: ReportService, advisory: AdvisoryService) -> None:
        self._report = report
        self._advisory = advisory

    async def advisory_gate(self, cycle_id: str) -> AdvisoryGate:
        jobs = self._advisory.jobs
        try:
            gate = await self._advisory.gate(cycle_id)
        except InferenceConfigError:
            jobs.record_refusal("advisory", cycle_id, INFERENCE_CONFIG_FAILURE_CODE)
            raise
        if gate == "cloud_advisory_disabled":
            jobs.record_refusal("advisory", cycle_id, gate)
        return gate

    async def run_advisory(self, cycle_id: str) -> None:
        await self._advisory.start(cycle_id)

    async def run_report(self, cycle_id: str) -> None:
        await self._report.start(cycle_id)
