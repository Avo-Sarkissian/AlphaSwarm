"""Report endpoints for post-simulation markdown viewer (Phase 36).

Revision round 1 (reviews mode): fixes two MEDIUM concerns from the cross-AI review.
- Codex MEDIUM (T-36-14): replace synchronous Path.exists()/Path.stat() with
  aiofiles.os equivalents so the async event loop stays responsive
  (CLAUDE.md Hard Constraint 1).
- Codex MEDIUM (T-36-15): attach a done_callback to the generation Task that
  captures failures into app.state.report_generation_error[cycle_id], so the
  GET endpoint can return 500 and the frontend can stop polling instead of
  waiting for the 10-minute timeout.

Accepted risk (T-36-16, both reviewers LOW): the atomic file-write race on
write_report. Window is milliseconds; poll cadence is 3 s; actual collisions
are extremely rare at the 5-10 KB file size. Noted — no code change.
"""

from __future__ import annotations

import asyncio
import datetime
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiofiles  # type: ignore[import-untyped]
import aiofiles.os  # type: ignore[import-untyped]
import structlog
from fastapi import APIRouter, FastAPI, HTTPException, Request, status
from pydantic import BaseModel

from alphaswarm.report import (
    ReportAssembler,
    ReportEngine,
    ToolObservation,
    write_report,
    write_sentinel,
)
from alphaswarm.types import SimulationPhase

if TYPE_CHECKING:
    from alphaswarm.app import AppState

log = structlog.get_logger(component="web.report")

router = APIRouter()

REPORTS_DIR = Path("reports")

# T-36-01: path traversal guard. Regex allows only the charset used in cycle UUIDs.
_CYCLE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


class ReportResponse(BaseModel):
    """Response body for GET /api/report/{cycle_id} (D-05)."""

    cycle_id: str
    content: str
    generated_at: str  # ISO-8601 UTC from file mtime


class GenerateResponse(BaseModel):
    """Response body for POST /api/report/{cycle_id}/generate (D-01)."""

    status: str
    cycle_id: str


def _validate_cycle_id(cycle_id: str) -> None:
    """Raise 400 if cycle_id contains characters outside the allowed charset (T-36-01)."""
    if not _CYCLE_ID_RE.match(cycle_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_cycle_id",
                "message": "cycle_id must match ^[a-zA-Z0-9_-]+$",
            },
        )


@router.get("/report/{cycle_id}", response_model=ReportResponse)
async def get_report(cycle_id: str, request: Request) -> ReportResponse:
    """Read the generated report file from disk (D-05).

    Returns 200 with {cycle_id, content, generated_at} when the file exists.
    Returns 404 'report_not_found' when reports/{cycle_id}_report.md is absent AND
      no failure has been recorded for this cycle.
    Returns 500 'report_generation_failed' when app.state.report_generation_error
      contains an entry for cycle_id (T-36-15). The frontend uses this to stop
      polling.
    Returns 400 'invalid_cycle_id' when cycle_id fails the regex guard (T-36-01).

    Uses aiofiles.os.path.exists and aiofiles.os.stat (NOT Path.exists / Path.stat)
    so the event loop is never blocked — CLAUDE.md Hard Constraint 1, T-36-14.
    """
    _validate_cycle_id(cycle_id)

    report_path = REPORTS_DIR / f"{cycle_id}_report.md"

    # Async filesystem probe — does not hold the event loop (T-36-14).
    exists = await aiofiles.os.path.exists(report_path)

    if not exists:
        # Before returning 404, surface any recorded failure so the frontend
        # can stop polling instead of timing out after 10 minutes (T-36-15).
        errors: dict[str, dict[str, str]] = (
            getattr(request.app.state, "report_generation_error", {}) or {}
        )
        recorded = errors.get(cycle_id)
        if recorded is not None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": recorded.get("error", "report_generation_failed"),
                    "message": recorded.get("message", "Report generation failed"),
                    "cycle_id": cycle_id,
                },
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "report_not_found",
                "message": f"No report exists for cycle {cycle_id}",
            },
        )

    async with aiofiles.open(report_path, "r", encoding="utf-8") as f:
        content = await f.read()

    # Async stat — returns os.stat_result with st_mtime (T-36-14).
    statres = await aiofiles.os.stat(report_path)
    generated_at = datetime.datetime.fromtimestamp(
        statres.st_mtime, tz=datetime.timezone.utc,
    ).isoformat()

    log.info("report_served", cycle_id=cycle_id, size=len(content))
    return ReportResponse(
        cycle_id=cycle_id, content=content, generated_at=generated_at,
    )


@router.post(
    "/report/{cycle_id}/generate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=GenerateResponse,
)
async def generate_report(cycle_id: str, request: Request) -> GenerateResponse:
    """Spawn ReACT + assembler as a background task (D-01, D-02).

    Guards:
    - 400 if cycle_id fails regex (T-36-01)
    - 503 if graph_manager / ollama_client / model_manager is None
    - 409 if snapshot.phase != SimulationPhase.COMPLETE (D-01)
    - 409 if app.state.report_task exists and is not .done() (D-02)

    On successful spawn:
    - Clears app.state.report_generation_error[cycle_id] so a previous failure
      does not poison the new run (related to T-36-15).
    - Attaches _on_report_task_done as a done_callback so unhandled exceptions
      are captured into app.state.report_generation_error[cycle_id] (T-36-15).

    Returns 202 immediately with the cycle_id; the background task writes
    reports/{cycle_id}_report.md, updates .alphaswarm/last_report.json, and
    unloads the orchestrator model in a finally block.
    """
    _validate_cycle_id(cycle_id)

    app_state = request.app.state.app_state
    graph_manager = app_state.graph_manager
    ollama_client = app_state.ollama_client
    model_manager = app_state.model_manager

    if graph_manager is None or ollama_client is None or model_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "services_unavailable",
                "message": "Neo4j, Ollama, or ModelManager is not connected",
            },
        )

    # D-01 phase guard.
    snap = app_state.state_store.snapshot()
    if snap.phase != SimulationPhase.COMPLETE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "report_unavailable",
                "message": "Reports can only be generated after a simulation completes",
                "current_phase": snap.phase.value,
            },
        )

    # D-02 in-progress guard.
    existing = getattr(request.app.state, "report_task", None)
    if existing is not None and not existing.done():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "report_generation_in_progress",
                "message": "A report generation is already running",
            },
        )

    # Ensure the error dict exists and clear any stale entry for this cycle so
    # prior failures do not poison the new run (T-36-15).
    if (
        not hasattr(request.app.state, "report_generation_error")
        or request.app.state.report_generation_error is None
    ):
        request.app.state.report_generation_error = {}
    errors: dict[str, dict[str, str]] = request.app.state.report_generation_error
    if cycle_id in errors:
        errors.pop(cycle_id, None)

    task = asyncio.create_task(_run_report_generation(app_state, cycle_id))
    request.app.state.report_task = task

    # T-36-15: capture background exceptions instead of letting asyncio log
    # "Task exception was never retrieved" while the frontend polls to timeout.
    app_ref = request.app
    task.add_done_callback(
        lambda t: _on_report_task_done(t, cycle_id, app_ref),
    )

    log.info("report_generation_started", cycle_id=cycle_id)
    return GenerateResponse(status="accepted", cycle_id=cycle_id)


def _on_report_task_done(
    task: "asyncio.Task[Any]", cycle_id: str, app: FastAPI,
) -> None:
    """Done-callback for the background generation task (T-36-15).

    On failure: records {error, message} into
    app.state.report_generation_error[cycle_id] so the GET endpoint can surface
    500 instead of the frontend polling to timeout.

    On success: no-op (file on disk is the success signal for GET).

    Must be safe to call on CancelledError (treat as failure with message 'cancelled').
    The callback itself must never raise (FastAPI's asyncio loop would swallow
    the exception and log "Task exception was never retrieved").
    """
    if task.cancelled():
        try:
            errors = getattr(app.state, "report_generation_error", None)
            if errors is None:
                app.state.report_generation_error = {}
                errors = app.state.report_generation_error
            errors[cycle_id] = {
                "error": "report_generation_failed",
                "message": "cancelled",
            }
            log.warning("report_task_cancelled", cycle_id=cycle_id)
        except Exception:  # defensive — callback must never raise
            pass
        return

    exc = task.exception()
    if exc is None:
        # Success — leave app.state.report_generation_error untouched for this cycle.
        log.info("report_task_completed", cycle_id=cycle_id)
        return

    # Failure — record a machine-parseable error for the GET endpoint to surface.
    try:
        errors = getattr(app.state, "report_generation_error", None)
        if errors is None:
            app.state.report_generation_error = {}
            errors = app.state.report_generation_error
        errors[cycle_id] = {
            "error": "report_generation_failed",
            "message": str(exc) or exc.__class__.__name__,
        }
        log.error(
            "report_task_exception_recorded",
            cycle_id=cycle_id,
            error=str(exc),
            exc_type=exc.__class__.__name__,
        )
    except Exception:  # defensive — callback must never raise
        log.error("report_task_exception_record_failed", cycle_id=cycle_id)


async def _run_report_generation(app_state: "AppState", cycle_id: str) -> None:
    """Background task — mirrors cli.py _handle_report sequence exactly (D-03).

    Sequence: load_model -> ReportEngine.run -> ReportAssembler.assemble ->
    write_report -> write_sentinel. Orchestrator unload happens in finally
    even when generation raises (prevents leaked model lock).

    Preconditions: the POST handler has already validated that graph_manager,
    ollama_client, and model_manager are non-None, so the narrowing asserts
    below are always safe when this coroutine is scheduled from the route.

    Accepted risk (T-36-16, both reviewers LOW): write_report is not atomic.
    The window between open('w') truncation and write completion is milliseconds
    and the poll cadence is 3 s, so collisions are extremely rare at the typical
    5-10 KB report size. If observed in practice, Phase 15's write_report can
    be enhanced with a .tmp + os.rename pattern in a follow-up quick task.
    """
    orchestrator = app_state.settings.ollama.orchestrator_model_alias
    model_manager = app_state.model_manager
    gm = app_state.graph_manager
    ollama_client = app_state.ollama_client
    assert model_manager is not None, "model_manager must be set (POST guard enforces this)"
    assert gm is not None, "graph_manager must be set (POST guard enforces this)"
    assert ollama_client is not None, "ollama_client must be set (POST guard enforces this)"

    try:
        await model_manager.load_model(orchestrator)

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
            ollama_client=ollama_client,
            model=orchestrator,
            tools=tools,  # type: ignore[arg-type]
            pre_seeded_observations=pre_seeded,
        )
        observations = await engine.run(cycle_id)

        assembler = ReportAssembler()
        content = assembler.assemble(observations, cycle_id)

        output_path = REPORTS_DIR / f"{cycle_id}_report.md"
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
            await model_manager.unload_model(orchestrator)
        except Exception:
            log.warning("orchestrator_unload_failed", cycle_id=cycle_id)
