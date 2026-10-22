"""Report endpoints: GET serves the markdown, POST starts a background generation.

POST gates on durable cycle state (complete, no simulation running) and on the
orchestrator slot; GET answers 409 while that cycle's job runs, 500 after a
recorded failure and 404 when no report exists. Writes are atomic
(docs/DECISIONS.md#adr-background-tasks).
"""

from __future__ import annotations

import asyncio
import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiofiles
import aiofiles.os
import structlog
from fastapi import APIRouter, FastAPI, Request, status
from pydantic import BaseModel

from alphaswarm.config import load_inference_config
from alphaswarm.inference.factory import build_providers
from alphaswarm.report import (
    ReportAssembler,
    ReportEngine,
    ToolObservation,
    write_report,
    write_sentinel,
)
from alphaswarm.state import JobStatus
from alphaswarm.web.errors import ApiError
from alphaswarm.web.guards import (
    job_config_error,
    require_complete_cycle,
    require_no_simulation,
    require_orchestrator_free,
    running_job_cycle,
)
from alphaswarm.web.params import CycleId

if TYPE_CHECKING:
    from alphaswarm.app import AppState

log = structlog.get_logger(component="web.report")

router = APIRouter()

class ReportResponse(BaseModel):
    """Response body for GET /api/report/{cycle_id} (D-05)."""

    cycle_id: str
    content: str
    generated_at: str  # ISO-8601 UTC from file mtime


class GenerateResponse(BaseModel):
    """Response body for POST /api/report/{cycle_id}/generate (D-01)."""

    status: str
    cycle_id: str


def reports_dir(app_state: AppState) -> Path:
    """Absolute report directory: settings.reports_dir anchored at the project root."""
    return app_state.settings.resolve_path(app_state.settings.reports_dir)


@router.get("/report/{cycle_id}", response_model=ReportResponse)
async def get_report(cycle_id: CycleId, request: Request) -> ReportResponse:
    """200 with the file; 409 while this cycle's job runs; 500 after a recorded
    failure; 404 when no report exists. File probes use aiofiles.os
    (docs/DECISIONS.md#t-36-14)."""
    app_state = request.app.state.app_state
    if running_job_cycle(app_state, "report") == cycle_id:
        raise ApiError(
            409,
            "report_generation_in_progress",
            "The report for this cycle is being generated",
            extra={"cycle_id": cycle_id},
        )
    report_path = reports_dir(app_state) / f"{cycle_id}_report.md"
    if not await aiofiles.os.path.exists(report_path):
        errors: dict[str, dict[str, str]] = (
            getattr(request.app.state, "report_generation_error", {}) or {}
        )
        recorded = errors.get(cycle_id)
        if recorded is not None:
            raise ApiError(
                500,
                recorded.get("error", "report_generation_failed"),
                recorded.get("message", "Report generation failed"),
                extra={"cycle_id": cycle_id},
            )
        raise ApiError(404, "report_not_found", f"No report exists for cycle {cycle_id}")

    async with aiofiles.open(report_path, encoding="utf-8") as f:
        content = await f.read()
    statres = await aiofiles.os.stat(report_path)
    generated_at = datetime.datetime.fromtimestamp(statres.st_mtime, tz=datetime.UTC).isoformat()
    log.info("report_served", cycle_id=cycle_id, size=len(content))
    return ReportResponse(cycle_id=cycle_id, content=content, generated_at=generated_at)


@router.post(
    "/report/{cycle_id}/generate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=GenerateResponse,
)
async def generate_report(cycle_id: CycleId, request: Request) -> GenerateResponse:
    """Start a report for a complete cycle (any cycle, not just the last run)."""
    app_state = request.app.state.app_state
    sim_manager = request.app.state.sim_manager
    await require_complete_cycle(app_state, sim_manager, cycle_id)
    # Again after the await, with none before the job starts: a run may have started.
    require_no_simulation(sim_manager)
    require_orchestrator_free(app_state)
    start_report_job(request.app, cycle_id)
    log.info("report_generation_started", cycle_id=cycle_id)
    return GenerateResponse(status="accepted", cycle_id=cycle_id)


def start_report_job(app: FastAPI, cycle_id: str) -> asyncio.Task[None]:
    """Start report generation as a tracked task and mark the report job running.

    Shared by POST /api/report/{id}/generate and the post-run pipeline; callers
    have already checked the cycle and the orchestrator slot.
    """
    app_state: AppState = app.state.app_state
    errors = getattr(app.state, "report_generation_error", None)
    if errors is None:
        errors = {}
        app.state.report_generation_error = errors
    errors.pop(cycle_id, None)
    task: asyncio.Task[None] = asyncio.create_task(
        _run_report_generation(app_state, cycle_id), name=f"report_{cycle_id}",
    )
    app.state.report_task = task
    app_state.state_store.set_job_status("report", JobStatus("running", cycle_id))
    task.add_done_callback(lambda t: _on_report_task_done(t, cycle_id, app))
    return task


def _record_report_failure(app: FastAPI, cycle_id: str, message: str) -> None:
    errors = getattr(app.state, "report_generation_error", None)
    if errors is None:
        errors = {}
        app.state.report_generation_error = errors
    errors[cycle_id] = {"error": "report_generation_failed", "message": message}


def _set_report_status(app: FastAPI, job_status: JobStatus) -> None:
    app_state = getattr(app.state, "app_state", None)
    if app_state is not None:
        app_state.state_store.set_job_status("report", job_status)


def _on_report_task_done(task: asyncio.Task[Any], cycle_id: str, app: FastAPI) -> None:
    """Record the outcome for GET and the job status. Must never raise."""
    try:
        if task.cancelled():
            _record_report_failure(app, cycle_id, "Report generation was cancelled")
            _set_report_status(app, JobStatus("failed", cycle_id, "report_generation_failed"))
            log.warning("report_task_cancelled", cycle_id=cycle_id)
            return
        exc = task.exception()
        if exc is None:
            _set_report_status(app, JobStatus("idle", cycle_id))
            log.info("report_task_completed", cycle_id=cycle_id)
            return
        _record_report_failure(
            app, cycle_id, f"Report generation failed ({exc.__class__.__name__})",
        )
        _set_report_status(app, JobStatus("failed", cycle_id, "report_generation_failed"))
        # Event name and exc_info are pinned by tests/test_task_failure_logging.py.
        log.error(
            "report_task_exception_recorded",
            cycle_id=cycle_id,
            exc_type=exc.__class__.__name__,
            exc_info=exc,
        )
    except Exception:  # a done-callback must never raise
        log.exception("report_task_done_callback_failed", cycle_id=cycle_id)


async def _run_report_generation(app_state: AppState, cycle_id: str) -> None:
    """Background task mirroring cli.py's _handle_report sequence (docs/DECISIONS.md#p36-d-03).

    Sequence: provider.prepare -> ReportEngine.run -> ReportAssembler.assemble ->
    write_report -> write_sentinel. provider.teardown/aclose happens in finally
    even when generation raises (prevents leaked model lock / cloud client leak).

    Started by POST /api/report/{id}/generate and by the post-run pipeline; the
    lifespan always builds graph_manager, ollama_client and model_manager, so the
    asserts below only narrow their types.

    Uses build_providers(load_inference_config(...)) so cloud configs are honoured
    and the provider is budget-capped.  LOCAL mode returns a plain OllamaProvider
    with identical behaviour to before.  The budget_meter is per-operation (fresh
    per report run) which bounds each report generation to its own spend cap. An
    invalid config fails the job with a fixed InferenceConfigError (job_config_error).

    write_report replaces the file atomically, so GET never reads a partial report
    (docs/DECISIONS.md#adr-background-tasks).
    """
    model_manager = app_state.model_manager
    gm = app_state.graph_manager
    ollama_client = app_state.ollama_client
    assert model_manager is not None, "model_manager must be set (the lifespan builds it)"
    assert gm is not None, "graph_manager must be set (the lifespan builds it)"
    assert ollama_client is not None, "ollama_client must be set (the lifespan builds it)"

    try:
        cfg = await asyncio.to_thread(load_inference_config, app_state.settings)
    except (ValueError, OSError) as exc:
        raise job_config_error(exc, job="report", cycle_id=cycle_id) from None
    built = build_providers(
        cfg,
        ollama_client=ollama_client,
        ollama_model_manager=model_manager,
    )
    provider = built.orchestrator

    try:
        await provider.prepare()

        # Exact tool registry from cli.py:716-725 (D-03: mirror CLI behavior).
        tools: dict[str, object] = {
            "bracket_summary": lambda **kw: gm.read_consensus_summary(
                kw.get("cycle_id", cycle_id),
            ),
            "round_timeline": lambda **kw: gm.read_round_timeline(
                kw.get("cycle_id", cycle_id),
            ),
            "bracket_narratives": lambda **kw: gm.read_bracket_narratives(
                kw.get("cycle_id", cycle_id),
            ),
            "key_dissenters": lambda **kw: gm.read_key_dissenters(
                kw.get("cycle_id", cycle_id),
            ),
            "influence_leaders": lambda **kw: gm.read_influence_leaders(
                kw.get("cycle_id", cycle_id),
            ),
            "signal_flip_analysis": lambda **kw: gm.read_signal_flips(
                kw.get("cycle_id", cycle_id),
            ),
            "entity_impact": lambda **kw: gm.read_entity_impact(
                kw.get("cycle_id", cycle_id),
            ),
            "social_post_reach": lambda **kw: gm.read_social_post_reach(
                kw.get("cycle_id", cycle_id),
            ),
        }

        # Phase 27 pre-seed: include shock_impact observation if a ShockEvent exists
        # (mirrors cli.py:727-731).
        shock_event = await gm.read_shock_event(cycle_id)
        pre_seeded: list[ToolObservation] | None = None
        if shock_event is not None:
            shock_impact = await gm.read_shock_impact(cycle_id)
            pre_seeded = [
                ToolObservation(
                    tool_name="shock_impact",
                    tool_input={"cycle_id": cycle_id},
                    result=shock_impact,
                ),
            ]

        engine = ReportEngine(
            provider=provider,
            tools=tools,  # type: ignore[arg-type]
            pre_seeded_observations=pre_seeded,
        )
        observations = await engine.run(cycle_id)

        assembler = ReportAssembler()
        content = assembler.assemble(observations, cycle_id)

        output_path = reports_dir(app_state) / f"{cycle_id}_report.md"
        await write_report(output_path, content)
        await write_sentinel(cycle_id, str(output_path))

        log.info(
            "report_generation_complete",
            cycle_id=cycle_id,
            output=str(output_path),
        )
    except Exception as exc:
        log.error("report_generation_failed", cycle_id=cycle_id, error=str(exc))
        raise
    finally:
        try:
            await provider.teardown()
            await provider.aclose()
        except Exception:
            log.warning("orchestrator_unload_failed", cycle_id=cycle_id)
