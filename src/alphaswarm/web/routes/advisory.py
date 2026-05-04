"""Advisory endpoints (Phase 41, ADVIS-02).

Mirrors web/routes/report.py line-for-line:
  - T-36-14 equivalent: use aiofiles.os (never Path.exists/stat on the event loop)
  - T-36-15 equivalent: done_callback records failures into
    app.state.advisory_generation_error[cycle_id] so GET returns 500 and the
    Vue client can stop polling instead of waiting out the 10-minute cap.
  - T-36-16 equivalent (accepted LOW): write_truncation window on rewrite.

Pitfall 4 (Phase 41 RESEARCH): 409 CONFLICT when either report_task or
advisory_task is in flight, preventing orchestrator-model starvation.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiofiles  # type: ignore[import-untyped]
import aiofiles.os  # type: ignore[import-untyped]
import structlog
from fastapi import APIRouter, FastAPI, HTTPException, Request, status
from pydantic import BaseModel

from alphaswarm.advisory import synthesize
from alphaswarm.types import SimulationPhase
from alphaswarm.web.routes.report import _validate_cycle_id  # single-source-of-truth regex guard

if TYPE_CHECKING:
    from alphaswarm.app import AppState
    from alphaswarm.holdings.types import PortfolioSnapshot

log = structlog.get_logger(component="web.advisory")

router = APIRouter()

ADVISORY_DIR = Path("advisory")


class GenerateAdvisoryResponse(BaseModel):
    """Response body for POST /api/advisory/{cycle_id} (D-09)."""

    status: str
    cycle_id: str


@router.post(
    "/advisory/{cycle_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=GenerateAdvisoryResponse,
)
async def generate_advisory(cycle_id: str, request: Request) -> GenerateAdvisoryResponse:
    """Spawn advisory synthesis as a background task (ADVIS-02, D-09).

    Guards (in order):
      400: invalid cycle_id (D-12)
      503: graph_manager / ollama_client / model_manager is None
      503: portfolio_snapshot is None (holdings CSV unavailable — RESEARCH OQ-3)
      409: phase != COMPLETE
      409: report_task or advisory_task in flight (D-08, Pitfall 4)
    """
    _validate_cycle_id(cycle_id)

    app_state: AppState = request.app.state.app_state
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

    portfolio: PortfolioSnapshot | None = getattr(
        request.app.state, "portfolio_snapshot", None,
    )
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "holdings_unavailable",
                "message": "Portfolio snapshot was not loaded — check holdings CSV path",
            },
        )

    snap = app_state.state_store.snapshot()
    if snap.phase != SimulationPhase.COMPLETE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "advisory_unavailable",
                "message": "Advisories can only be generated after a simulation completes",
                "current_phase": snap.phase.value,
            },
        )

    # Pitfall 4: serialize orchestrator model consumers.
    existing_report = getattr(request.app.state, "report_task", None)
    if existing_report is not None and not existing_report.done():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "report_generation_in_progress",
                "message": "A report generation is already running — retry when it completes",
            },
        )
    existing_advisory = getattr(request.app.state, "advisory_task", None)
    if existing_advisory is not None and not existing_advisory.done():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "advisory_generation_in_progress",
                "message": "An advisory generation is already running",
            },
        )

    # Ensure error dict exists; clear any stale entry for this cycle (D-13).
    if (
        not hasattr(request.app.state, "advisory_generation_error")
        or request.app.state.advisory_generation_error is None
    ):
        request.app.state.advisory_generation_error = {}
    errors: dict[str, dict[str, str]] = request.app.state.advisory_generation_error
    errors.pop(cycle_id, None)

    task = asyncio.create_task(_run_advisory_synthesis(app_state, cycle_id, portfolio))
    request.app.state.advisory_task = task
    app_ref = request.app
    task.add_done_callback(lambda t: _on_advisory_task_done(t, cycle_id, app_ref))

    log.info(
        "advisory_generation_started",
        cycle_id=cycle_id,
        holdings_count=len(portfolio.holdings),
    )
    return GenerateAdvisoryResponse(status="accepted", cycle_id=cycle_id)


@router.get("/advisory/{cycle_id}")
async def get_advisory(cycle_id: str, request: Request) -> dict[str, Any]:
    """Return the advisory JSON payload for a cycle (D-10).

      200: file exists -> parsed JSON body
      404: file absent AND no recorded error
      500: app.state.advisory_generation_error[cycle_id] present (done_callback captured)
      400: invalid cycle_id (D-12)
    """
    _validate_cycle_id(cycle_id)

    path = ADVISORY_DIR / f"{cycle_id}_advisory.json"
    exists = await aiofiles.os.path.exists(path)

    if not exists:
        errors: dict[str, dict[str, str]] = (
            getattr(request.app.state, "advisory_generation_error", {}) or {}
        )
        recorded = errors.get(cycle_id)
        if recorded is not None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": recorded.get("error", "advisory_generation_failed"),
                    "message": recorded.get("message", "Advisory generation failed"),
                    "cycle_id": cycle_id,
                },
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "advisory_not_found",
                "message": f"No advisory exists for cycle {cycle_id}",
            },
        )

    async with aiofiles.open(path, "r", encoding="utf-8") as f:
        content = await f.read()

    payload: dict[str, Any] = json.loads(content)
    log.info("advisory_served", cycle_id=cycle_id, bytes=len(content))
    return payload


def _on_advisory_task_done(
    task: asyncio.Task[Any], cycle_id: str, app: FastAPI,
) -> None:
    """Done-callback mirroring _on_report_task_done (D-13, T-36-15 pattern).

    MUST NOT raise — FastAPI's loop would swallow it.
    """
    if task.cancelled():
        try:
            errors = getattr(app.state, "advisory_generation_error", None)
            if errors is None:
                app.state.advisory_generation_error = {}
                errors = app.state.advisory_generation_error
            errors[cycle_id] = {
                "error": "advisory_generation_failed",
                "message": "cancelled",
            }
            log.warning("advisory_task_cancelled", cycle_id=cycle_id)
        except Exception:  # defensive
            pass
        return

    exc = task.exception()
    if exc is None:
        log.info("advisory_task_completed", cycle_id=cycle_id)
        return

    try:
        errors = getattr(app.state, "advisory_generation_error", None)
        if errors is None:
            app.state.advisory_generation_error = {}
            errors = app.state.advisory_generation_error
        errors[cycle_id] = {
            "error": "advisory_generation_failed",
            "message": str(exc) or exc.__class__.__name__,
        }
        log.error(
            "advisory_task_exception_recorded",
            cycle_id=cycle_id,
            error=str(exc),
            exc_type=exc.__class__.__name__,
        )
    except Exception:
        log.error("advisory_task_exception_record_failed", cycle_id=cycle_id)


async def _run_advisory_synthesis(
    app_state: AppState,
    cycle_id: str,
    portfolio: PortfolioSnapshot,
) -> None:
    """Background task: load orchestrator -> synthesize -> write file -> unload in finally.

    D-08: orchestrator lifecycle in try/finally. Matches report pattern.
    Pitfall 1: log only scalar metadata — never the portfolio.
    """
    orchestrator = app_state.settings.ollama.orchestrator_model_alias
    model_manager = app_state.model_manager
    gm = app_state.graph_manager
    ollama_client = app_state.ollama_client
    assert model_manager is not None
    assert gm is not None
    assert ollama_client is not None

    try:
        await model_manager.load_model(orchestrator)

        report_obj = await synthesize(
            cycle_id=cycle_id,
            portfolio=portfolio,
            graph_manager=gm,
            ollama_client=ollama_client,
            orchestrator_model=orchestrator,
        )

        await aiofiles.os.makedirs(ADVISORY_DIR, exist_ok=True)
        output_path = ADVISORY_DIR / f"{cycle_id}_advisory.json"
        async with aiofiles.open(output_path, "w", encoding="utf-8") as f:
            await f.write(report_obj.model_dump_json(indent=2))

        log.info(
            "advisory_generation_complete",
            cycle_id=cycle_id,
            output=str(output_path),
            affected=report_obj.affected_holdings,
        )
    except Exception as exc:
        log.error("advisory_generation_failed", cycle_id=cycle_id, error=str(exc))
        raise
    finally:
        try:
            await model_manager.unload_model(orchestrator)
        except Exception:
            log.warning("orchestrator_unload_failed_after_advisory", cycle_id=cycle_id)
