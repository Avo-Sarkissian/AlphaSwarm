"""Advisory endpoints (ADVIS-02): POST starts an advisory job, GET serves the JSON.

POST: 404/422/409 from the cycle gate; then the AdvisoryService gate, which
checks the orchestrator before the holdings (docs/DECISIONS.md#adr-advisory-pipeline):
422 ``inference_config_invalid`` for an unreadable config (fails closed), 409
``cloud_advisory_disabled`` for a cloud or remote orchestrator without the
opt-in, 503 ``holdings_unavailable`` without holdings; 409 ``simulation_running``
if a run started during those awaits; 409 while the orchestrator is busy
(JobRunner). Both refusals are recorded, so GET answers with their code instead
of a 404 the UI shows as pending.

GET mirrors the report semantics with advisory_* codes and validates the file
into AdvisoryReport; files written before ``stats``/``source`` existed still
validate. File probes use aiofiles.os (docs/DECISIONS.md#t-36-14). Synthesis
and the owner-only write live in alphaswarm.services.advisory; this module
never touches holdings (docs/DECISIONS.md#adr-holdings-isolation).
"""

from __future__ import annotations

from typing import Final

import aiofiles
import aiofiles.os
import structlog
from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ValidationError

from alphaswarm.advisory import AdvisoryReport
from alphaswarm.errors import InferenceConfigError
from alphaswarm.services.advisory import CLOUD_ADVISORY_MESSAGE
from alphaswarm.services.jobs import INFERENCE_CONFIG_FAILURE_CODE, JobInProgressError
from alphaswarm.web.deps import get_advisory_service, get_runtime, job_conflict
from alphaswarm.web.errors import ApiError
from alphaswarm.web.guards import (
    STORED_CONFIG_INVALID_MESSAGE,
    require_complete_cycle,
    require_no_simulation,
)
from alphaswarm.web.params import CycleId

log = structlog.get_logger(component="web.advisory")

router = APIRouter()

# Fixed text per recorded failure code; never exception text, which can echo tickers.
_FAILURE_MESSAGES: Final[dict[str, str]] = {
    "cloud_advisory_disabled": CLOUD_ADVISORY_MESSAGE,
    INFERENCE_CONFIG_FAILURE_CODE: STORED_CONFIG_INVALID_MESSAGE,
}
_FAILED_MESSAGE: Final = "Advisory generation failed; see the server log"


class GenerateAdvisoryResponse(BaseModel):
    """Response body for POST /api/advisory/{cycle_id}."""

    status: str
    cycle_id: str


@router.post(
    "/advisory/{cycle_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=GenerateAdvisoryResponse,
)
async def generate_advisory(cycle_id: CycleId, request: Request) -> GenerateAdvisoryResponse:
    """Start advisory synthesis for a complete cycle."""
    sim_manager = request.app.state.sim_manager
    await require_complete_cycle(request.app.state.app_state, sim_manager, cycle_id)
    service = get_advisory_service(request)
    jobs = get_runtime(request).jobs
    try:
        gate = await service.gate(cycle_id)
    except InferenceConfigError:
        # Logged by type only in InferenceRuntime: the load error can quote keys.
        jobs.record_refusal("advisory", cycle_id, INFERENCE_CONFIG_FAILURE_CODE)
        raise ApiError(422, INFERENCE_CONFIG_FAILURE_CODE, STORED_CONFIG_INVALID_MESSAGE) from None
    if gate == "cloud_advisory_disabled":
        jobs.record_refusal("advisory", cycle_id, gate)
        raise ApiError(409, gate, CLOUD_ADVISORY_MESSAGE)
    if gate == "no_portfolio":
        raise ApiError(503, "holdings_unavailable", "Holdings file could not be loaded; see the server log")
    # Again after the awaits, with none before the job starts: a run may have started.
    require_no_simulation(sim_manager)
    try:
        service.start(cycle_id)
    except JobInProgressError as exc:
        raise job_conflict(exc) from exc
    log.info("advisory_generation_started", cycle_id=cycle_id)
    return GenerateAdvisoryResponse(status="accepted", cycle_id=cycle_id)


@router.get("/advisory/{cycle_id}", response_model=AdvisoryReport)
async def get_advisory(cycle_id: CycleId, request: Request) -> AdvisoryReport:
    """200 with the validated advisory; 409 while this cycle's job runs; 500 after a
    recorded failure or for an unreadable file; 404 when no advisory exists."""
    runtime = get_runtime(request)
    job = runtime.jobs.status("advisory")
    if job.state == "running" and job.cycle_id == cycle_id:
        raise ApiError(
            409,
            "advisory_generation_in_progress",
            "The advisory for this cycle is being generated",
            extra={"cycle_id": cycle_id},
        )
    settings = runtime.settings
    path = settings.resolve_path(settings.advisory_dir) / f"{cycle_id}_advisory.json"
    if not await aiofiles.os.path.exists(path):
        code = runtime.jobs.error_for("advisory", cycle_id)
        if code is not None:
            message = _FAILURE_MESSAGES.get(code, _FAILED_MESSAGE)
            raise ApiError(500, code, message, extra={"cycle_id": cycle_id})
        raise ApiError(404, "advisory_not_found", f"No advisory exists for cycle {cycle_id}")
    async with aiofiles.open(path, encoding="utf-8") as handle:
        content = await handle.read()
    try:
        report = AdvisoryReport.model_validate_json(content)
    except ValidationError as exc:
        # The file holds portfolio data: log the error count only, never the content.
        log.warning("advisory_file_invalid", cycle_id=cycle_id, error_count=exc.error_count())
        raise ApiError(
            500,
            "advisory_generation_failed",
            "The stored advisory for this cycle is unreadable; generate it again",
            extra={"cycle_id": cycle_id},
        ) from None
    log.info("advisory_served", cycle_id=cycle_id, bytes=len(content))
    return report
