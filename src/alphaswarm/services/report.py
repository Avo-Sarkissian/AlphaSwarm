"""ReportService: one report at a time through the orchestrator.

Takes the orchestrator lock, opens a "report" operation (fresh budget meter),
prepares the orchestrator, runs ``report.generate_report`` and always tears
down and closes the providers (docs/DECISIONS.md#p15-d-12). Shared by the CLI
``report`` subcommand, the POST route and the post-run pipeline.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from alphaswarm.report import ReportResult, generate_report
from alphaswarm.services.runtime import close_operation

if TYPE_CHECKING:
    from pathlib import Path

    from alphaswarm.graph import GraphStateManager
    from alphaswarm.services.jobs import JobRunner
    from alphaswarm.services.runtime import InferenceRuntime

log = structlog.get_logger(component="services.report")


class ReportService:
    """Generates reports into ``reports_dir``."""

    def __init__(
        self,
        *,
        graph: GraphStateManager,
        inference: InferenceRuntime,
        jobs: JobRunner,
        reports_dir: Path,
    ) -> None:
        self._graph = graph
        self._inference = inference
        self._jobs = jobs
        self._reports_dir = reports_dir

    @property
    def reports_dir(self) -> Path:
        return self._reports_dir

    async def generate(self, cycle_id: str) -> ReportResult:
        """Generate and write the report for *cycle_id*; waits for the orchestrator lock.

        An unusable inference config raises the fixed InferenceConfigError
        (logged by type only, in InferenceRuntime). Any other failure is logged
        here with its traceback and re-raised: report data holds no holdings.
        """
        async with self._jobs.orchestrator_lock:
            built = await self._inference.open_operation("report")
            try:
                await built.orchestrator.prepare()
                result = await generate_report(
                    gm=self._graph,
                    provider=built.orchestrator,
                    cycle_id=cycle_id,
                    reports_dir=self._reports_dir,
                )
            except Exception as exc:
                log.error(
                    "report_generation_failed",
                    cycle_id=cycle_id,
                    error_type=type(exc).__name__,
                    exc_info=True,
                )
                raise
            finally:
                await close_operation(built, teardown=True)
        log.info("report_service_completed", cycle_id=cycle_id, output=str(result.path))
        return result

    def start(self, cycle_id: str) -> asyncio.Task[None]:
        """Run ``generate`` as the background report job (JobInProgressError when busy)."""

        async def _job() -> None:
            await self.generate(cycle_id)

        return self._jobs.start("report", cycle_id, _job)
