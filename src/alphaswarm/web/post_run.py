"""Post-run pipeline: the advisory when it is allowed, then the report, always.

Replaces the in-process HTTP self-calls that chained run completion -> POST
advisory -> (on success only) POST report. The deliberate advisory -> report
order is kept (docs/DECISIONS.md#adr-advisory-pipeline); only the no-holdings,
cloud-without-opt-in and failure branches change: the report now runs in every
case. The jobs themselves are injected (PostRunJobs), so this module has no web
or holdings imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, Protocol

import structlog

from alphaswarm.errors import AlphaSwarmError
from alphaswarm.logging import validation_error_summary

log = structlog.get_logger(component="web.post_run")

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


class PostRunJobBusyError(AlphaSwarmError):
    """Raised by PostRunJobs.run_* when another orchestrator job holds the slot."""

    def __init__(self, kind: Literal["advisory", "report"]) -> None:
        super().__init__(f"{kind} skipped: another orchestrator job is running")
        self.kind = kind


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
        except PostRunJobBusyError:
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
        except PostRunJobBusyError:
            log.warning("auto_report_skipped_busy", cycle_id=cycle_id)
            return "skipped_busy"
        except Exception:
            log.error("auto_report_failed", cycle_id=cycle_id, exc_info=True)
            return "failed"
        return "ran"
