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
import httpx
import structlog
from fastapi import APIRouter, FastAPI, HTTPException, Request, status
from pydantic import BaseModel

from alphaswarm.advisory import synthesize
from alphaswarm.config import load_inference_config
from alphaswarm.inference.factory import build_providers
from alphaswarm.types import SimulationPhase
from alphaswarm.web.routes.report import _validate_cycle_id  # single-source-of-truth regex guard

if TYPE_CHECKING:
    from alphaswarm.app import AppState
    from alphaswarm.holdings.types import PortfolioSnapshot

log = structlog.get_logger(component="web.advisory")

router = APIRouter()

ADVISORY_DIR = Path("advisory")

# Strong references to chained report-generation tasks. The advisory done-callback
# is SYNC and only receives (cycle_id, app) — no `self` — so the ref set cannot
# live on an instance. The event loop holds only WEAK refs to bare tasks, so
# without this set a chained task could be GC'd before it runs. Mirrors the
# `_bg_tasks` rationale in SimulationManager.
_report_chain_tasks: set[asyncio.Task[Any]] = set()


async def _auto_trigger_report(app: FastAPI, cycle_id: str) -> None:
    """POST /api/report/{cycle_id}/generate in-process after a successful advisory.

    Mirrors _auto_trigger_advisory in simulation_manager.py: uses
    httpx.ASGITransport to call the FastAPI ASGI app directly — no network
    socket, no port assumption — so all report-route guards (409, 503) are
    re-used. Non-202 responses are swallowed with scalar-only logs:
      202 -> accepted; 409 -> skipped_conflict (the report route's bidirectional
      orchestrator-serialization guard stays authoritative and is tolerated
      here); 503 -> skipped_unavailable; else -> unexpected_status. Any
      network-level exception is logged and swallowed so it never surfaces.

    Loop-safety: report.py contains no advisory trigger, so report -> advisory
    recursion is impossible; the only chain is advisory-success -> report.
    """
    try:
        transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post(f"/api/report/{cycle_id}/generate")
        if resp.status_code == 202:
            log.info("auto_report_trigger_accepted", cycle_id=cycle_id)
        elif resp.status_code == 409:
            log.info("auto_report_trigger_skipped_conflict", cycle_id=cycle_id)
        elif resp.status_code == 503:
            log.warning("auto_report_trigger_skipped_unavailable", cycle_id=cycle_id)
        else:
            log.warning(
                "auto_report_trigger_unexpected_status",
                cycle_id=cycle_id,
                status=resp.status_code,
            )
    except Exception:
        log.exception("auto_report_trigger_failed", cycle_id=cycle_id)


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
        # Lazy reload: if the startup load failed (CSV missing at boot, race
        # condition, transient FS error) AND the file is now readable, try
        # loading it on the fly so a stale backend doesn't permanently block
        # auto-advisory. This makes the auto-trigger path resilient across
        # the "backend started before CSV existed" failure mode that produced
        # consecutive cycles with no advisory file.
        try:
            from alphaswarm.web.routes.holdings import load_portfolio_snapshot

            reloaded = await asyncio.to_thread(
                load_portfolio_snapshot, app_state.settings.holdings_csv_path,
            )
            if reloaded is not None:
                request.app.state.portfolio_snapshot = reloaded
                app_state.portfolio_snapshot = reloaded
                portfolio = reloaded
                log.info(
                    "portfolio_snapshot_lazy_reloaded",
                    holdings_count=len(reloaded.holdings),
                    cycle_id=cycle_id,
                )
        except Exception:
            log.exception("portfolio_snapshot_lazy_reload_failed", cycle_id=cycle_id)
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

    async with aiofiles.open(path, encoding="utf-8") as f:
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
        # SUCCESS branch only: the orchestrator is warm and the cycle is COMPLETE,
        # so chain report generation off the same cycle. Hold a strong ref (the
        # loop keeps only weak refs to bare tasks). MUST NOT raise — the callback
        # body is swallowed by the loop, so wrap defensively like the other branches.
        try:
            chain = asyncio.create_task(
                _auto_trigger_report(app, cycle_id),
                name=f"auto_report_{cycle_id}",
            )
            _report_chain_tasks.add(chain)
            chain.add_done_callback(_report_chain_tasks.discard)
        except Exception:  # defensive — never let the done-callback raise
            log.error("auto_report_chain_schedule_failed", cycle_id=cycle_id)
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
    """Background task: prepare provider -> synthesize -> write file -> teardown in finally.

    D-08: orchestrator lifecycle in try/finally. Matches report pattern.
    Pitfall 1: log only scalar metadata — never the portfolio.

    Uses build_providers(load_inference_config(...)) so cloud configs are honoured
    and the provider is budget-capped.  LOCAL mode returns a plain OllamaProvider
    with identical behaviour to before.  The budget_meter here is per-operation
    (fresh per advisory run) which bounds each advisory to its own spend cap.
    """
    gm = app_state.graph_manager
    ollama_client = app_state.ollama_client
    model_manager = app_state.model_manager
    assert gm is not None
    assert ollama_client is not None
    assert model_manager is not None

    cfg = await asyncio.to_thread(load_inference_config, app_state.settings)
    built = build_providers(
        cfg,
        ollama_client=ollama_client,
        ollama_model_manager=model_manager,
    )
    provider = built.orchestrator

    try:
        await provider.prepare()

        report_obj = await synthesize(
            cycle_id=cycle_id,
            portfolio=portfolio,
            graph_manager=gm,
            provider=provider,
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
            await provider.teardown()
            await provider.aclose()
        except Exception:
            log.warning("orchestrator_unload_failed_after_advisory", cycle_id=cycle_id)
