"""Report endpoints: GET serves the markdown and its sections, POST starts a report job.

POST gates on durable cycle state (complete, no simulation running) and on the
orchestrator slot (JobRunner); GET answers 409 while that cycle's job runs, 500
after a recorded failure and 404 when no report exists. Generation lives in
alphaswarm.services.report (docs/DECISIONS.md#adr-background-tasks,
docs/DECISIONS.md#adr-report-react). File probes use aiofiles.os so the event
loop never blocks (docs/DECISIONS.md#t-36-14).
"""

from __future__ import annotations

import datetime
from pathlib import Path

import aiofiles
import aiofiles.os
import structlog
from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ValidationError

from alphaswarm.services.jobs import JobInProgressError
from alphaswarm.web.deps import get_report_service, get_runtime, job_conflict
from alphaswarm.web.errors import ApiError
from alphaswarm.web.guards import require_complete_cycle, require_no_simulation
from alphaswarm.web.params import CycleId

log = structlog.get_logger(component="web.report")

router = APIRouter()

_FAILED_MESSAGE = "Report generation failed; see the server log"


class ConvergenceRowOut(BaseModel):
    round_num: int
    buy_count: int
    sell_count: int
    hold_count: int
    parse_error_count: int
    total: int


class InfluenceRowOut(BaseModel):
    agent_id: str
    name: str
    bracket: str
    citation_count: int
    influence_share: float


class ReportSectionsOut(BaseModel):
    """Wire mirror of ``report.ReportSections``.

    A pydantic copy because pydantic cannot validate the ``typing.TypedDict``
    rows of ``alphaswarm.graph`` on Python 3.11.
    """

    summary: str
    convergence: list[ConvergenceRowOut]
    influence: list[InfluenceRowOut]
    moments: list[str]
    dissent: list[str]
    followups: list[str]


class ReportResponse(BaseModel):
    """GET /api/report/{cycle_id}; ``sections`` is null for reports written before sections existed."""

    cycle_id: str
    content: str
    generated_at: str  # ISO-8601 UTC from the file mtime
    sections: ReportSectionsOut | None = None


class GenerateResponse(BaseModel):
    """Response body for POST /api/report/{cycle_id}/generate."""

    status: str
    cycle_id: str


def _reports_dir(request: Request) -> Path:
    settings = get_runtime(request).settings
    return settings.resolve_path(settings.reports_dir)


async def _read_sections(path: Path, cycle_id: str) -> ReportSectionsOut | None:
    if not await aiofiles.os.path.exists(path):
        return None
    async with aiofiles.open(path, encoding="utf-8") as handle:
        raw = await handle.read()
    try:
        return ReportSectionsOut.model_validate_json(raw)
    except ValidationError:
        log.warning("report_sections_invalid", cycle_id=cycle_id)
        return None


@router.get("/report/{cycle_id}", response_model=ReportResponse)
async def get_report(cycle_id: CycleId, request: Request) -> ReportResponse:
    """200 with markdown and sections; 409 while this cycle's job runs; 500 after a
    recorded failure; 404 when no report exists."""
    jobs = get_runtime(request).jobs
    job = jobs.status("report")
    if job.state == "running" and job.cycle_id == cycle_id:
        raise ApiError(
            409,
            "report_generation_in_progress",
            "The report for this cycle is being generated",
            extra={"cycle_id": cycle_id},
        )
    report_path = _reports_dir(request) / f"{cycle_id}_report.md"
    if not await aiofiles.os.path.exists(report_path):
        code = jobs.error_for("report", cycle_id)
        if code is not None:
            raise ApiError(500, code, _FAILED_MESSAGE, extra={"cycle_id": cycle_id})
        raise ApiError(404, "report_not_found", f"No report exists for cycle {cycle_id}")
    async with aiofiles.open(report_path, encoding="utf-8") as handle:
        content = await handle.read()
    statres = await aiofiles.os.stat(report_path)
    generated_at = datetime.datetime.fromtimestamp(statres.st_mtime, tz=datetime.UTC).isoformat()
    sections = await _read_sections(report_path.with_suffix(".json"), cycle_id)
    log.info("report_served", cycle_id=cycle_id, size=len(content), sections=sections is not None)
    return ReportResponse(cycle_id=cycle_id, content=content, generated_at=generated_at, sections=sections)


@router.post(
    "/report/{cycle_id}/generate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=GenerateResponse,
)
async def generate_report(cycle_id: CycleId, request: Request) -> GenerateResponse:
    """Start a report for a complete cycle (any cycle, not just the last run)."""
    sim_manager = request.app.state.sim_manager
    await require_complete_cycle(request.app.state.app_state, sim_manager, cycle_id)
    # Again after the await, with none before the job starts: a run may have started.
    require_no_simulation(sim_manager)
    service = get_report_service(request)
    try:
        service.start(cycle_id)
    except JobInProgressError as exc:
        raise job_conflict(exc) from exc
    log.info("report_generation_started", cycle_id=cycle_id)
    return GenerateResponse(status="accepted", cycle_id=cycle_id)
