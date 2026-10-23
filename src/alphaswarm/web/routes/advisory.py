"""Advisory endpoints (Phase 41, ADVIS-02).

Mirrors web/routes/report.py line-for-line:
  - T-36-14 equivalent: use aiofiles.os (never Path.exists/stat on the event loop)
  - T-36-15 equivalent: done_callback records failures into
    app.state.advisory_generation_error[cycle_id] so GET returns 500 and the
    frontend can stop polling instead of waiting out the 10-minute cap.
  - Writes are atomic (fsutil.atomic_write_text, owner-only).

The report/advisory cross-guard lives in web/guards.require_orchestrator_free.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import aiofiles
import aiofiles.os
import structlog
from fastapi import APIRouter, FastAPI, Request, status
from pydantic import BaseModel, ValidationError

from alphaswarm.advisory import AdvisoryReport, synthesize
from alphaswarm.config import ProviderType, load_inference_config
from alphaswarm.fsutil import atomic_write_text
from alphaswarm.inference.factory import advisory_block_reason, build_providers
from alphaswarm.state import JobStatus
from alphaswarm.web.errors import ApiError
from alphaswarm.web.guards import (
    job_config_error,
    load_inference_config_or_422,
    require_complete_cycle,
    require_no_simulation,
    require_orchestrator_free,
    running_job_cycle,
)
from alphaswarm.web.params import CycleId

if TYPE_CHECKING:
    from pathlib import Path

    from alphaswarm.app import AppState
    from alphaswarm.config import InferenceConfig
    from alphaswarm.holdings.types import PortfolioSnapshot

log = structlog.get_logger(component="web.advisory")

router = APIRouter()


class CloudAdvisoryDisabledError(Exception):
    """The orchestrator is cloud or remote and allow_cloud_advisory is off."""


_CLOUD_ADVISORY_MESSAGE = (
    "Advisory is disabled while the orchestrator is a cloud or remote model (a cloud "
    "provider, an Ollama cloud model, or an Ollama server off this machine: check the "
    "Ollama base URL, OLLAMA_HOST, and the orchestrator's base_url in the inference "
    "config), so the portfolio stays on this machine. Switch the orchestrator to a local "
    "Ollama model on localhost, or opt in: tick 'Allow cloud advisory' in Settings > Model, "
    "or set allow_cloud_advisory to true in the inference config when the checkbox is not "
    "shown."
)

_MODEL_CHECK_FAILED_MESSAGE = (
    "Advisory is disabled because the Ollama server could not confirm that the "
    "orchestrator model runs on this machine (its /api/show request failed). Make sure "
    "Ollama is running and the model exists, or set allow_cloud_advisory to true in the "
    "inference config to opt in."
)


def _orchestrator_block_reason(cfg: InferenceConfig, app_state: AppState) -> str | None:
    """advisory_block_reason() against the host the shared OllamaClient connects to.

    The host is read from the client itself, not rebuilt from the settings, so
    the check and the connection cannot disagree. No client fails closed.
    """
    client = app_state.ollama_client
    if client is None:
        return "ollama_client_missing"
    return advisory_block_reason(cfg, ollama_base_url=client.base_url)


async def _refuse_remote_ollama_model(cfg: InferenceConfig, app_state: AppState, cycle_id: str) -> None:
    """Ask the Ollama server whether the orchestrator model runs remotely.

    A name check cannot see an alias whose Modelfile is ``FROM`` a cloud model
    (the default ``alphaswarm-orchestrator`` is such an alias), so without the
    opt-in the job asks ``/api/show``. Any failure refuses
    (docs/DECISIONS.md#adr-advisory-pipeline).
    """
    if cfg.allow_cloud_advisory or cfg.orchestrator.provider != ProviderType.OLLAMA:
        return
    client = app_state.ollama_client
    assert client is not None
    try:
        remote = await client.is_remote_model(cfg.orchestrator.model)
    except Exception as exc:
        log.warning(
            "advisory_blocked_model_check_failed",
            cycle_id=cycle_id,
            error_type=type(exc).__name__,
        )
        raise CloudAdvisoryDisabledError(_MODEL_CHECK_FAILED_MESSAGE) from exc
    if remote:
        log.warning("advisory_blocked_cloud_disabled", cycle_id=cycle_id, reason="remote_model")
        raise CloudAdvisoryDisabledError(_CLOUD_ADVISORY_MESSAGE)


class GenerateAdvisoryResponse(BaseModel):
    """Response body for POST /api/advisory/{cycle_id} (D-09)."""

    status: str
    cycle_id: str


def advisory_dir(app_state: AppState) -> Path:
    """Absolute advisory directory: settings.advisory_dir anchored at the project root."""
    return app_state.settings.resolve_path(app_state.settings.advisory_dir)


async def advisory_refusal(app: FastAPI, cycle_id: str) -> ApiError | None:
    """The recorded refusal when the advisory for *cycle_id* may not run, else None.

    Shared by POST /api/advisory/{id} and the post-run pipeline, and checked
    before the holdings are touched (docs/DECISIONS.md#adr-advisory-pipeline):
    an unreadable inference config fails closed (422 inference_config_invalid)
    and a cloud or remote orchestrator without the opt-in is refused (409
    cloud_advisory_disabled). The refusal is recorded like a refused job, so GET
    answers with its code: with nothing recorded GET answers 404, which the UI
    shows as "still generating" until its poll times out. Only the type of a
    config error is logged, because its text can quote API keys.
    """
    app_state: AppState = app.state.app_state
    try:
        cfg = await load_inference_config_or_422(app_state)
    except ApiError as exc:
        log.warning(
            "advisory_blocked_config_unreadable",
            cycle_id=cycle_id,
            error_type=type(exc.__cause__).__name__,
        )
        refusal = exc
    else:
        reason = _orchestrator_block_reason(cfg, app_state)
        if reason is None:
            return None
        log.warning("advisory_blocked_cloud_disabled", cycle_id=cycle_id, reason=reason)
        refusal = ApiError(409, "cloud_advisory_disabled", _CLOUD_ADVISORY_MESSAGE)
    _record_advisory_failure(app, cycle_id, refusal.code, refusal.message)
    return refusal


@router.post(
    "/advisory/{cycle_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=GenerateAdvisoryResponse,
)
async def generate_advisory(cycle_id: CycleId, request: Request) -> GenerateAdvisoryResponse:
    """Start advisory synthesis for a complete cycle (ADVIS-02).

    In order: 404/422/409 from the cycle gate; 422 inference_config_invalid
    (fails closed) or 409 cloud_advisory_disabled for a cloud or remote
    orchestrator without the opt-in, both before the holdings are touched
    (advisory_refusal); 503 without holdings; 409 simulation_running if a run
    started during those awaits; 409 while the orchestrator slot is taken.
    """
    app_state: AppState = request.app.state.app_state
    sim_manager = request.app.state.sim_manager
    await require_complete_cycle(app_state, sim_manager, cycle_id)
    refusal = await advisory_refusal(request.app, cycle_id)
    if refusal is not None:
        raise refusal
    portfolio: PortfolioSnapshot | None = await request.app.state.portfolio_cache.get()
    if portfolio is None:
        raise ApiError(
            503,
            "holdings_unavailable",
            "Holdings file could not be loaded; see the server log",
        )
    # Again after the awaits, with none before the job starts: a run may have started.
    require_no_simulation(sim_manager)
    require_orchestrator_free(app_state)
    start_advisory_job(request.app, cycle_id, portfolio)
    log.info(
        "advisory_generation_started",
        cycle_id=cycle_id,
        holdings_count=len(portfolio.holdings),
    )
    return GenerateAdvisoryResponse(status="accepted", cycle_id=cycle_id)


@router.get("/advisory/{cycle_id}", response_model=AdvisoryReport)
async def get_advisory(cycle_id: CycleId, request: Request) -> AdvisoryReport:
    """200 with the AdvisoryReport; 409 while this cycle's job runs; 500 after a
    recorded failure or when the stored file no longer parses; 404 when no advisory exists."""
    app_state = request.app.state.app_state
    if running_job_cycle(app_state, "advisory") == cycle_id:
        raise ApiError(
            409,
            "advisory_generation_in_progress",
            "The advisory for this cycle is being generated",
            extra={"cycle_id": cycle_id},
        )
    path = advisory_dir(app_state) / f"{cycle_id}_advisory.json"
    if not await aiofiles.os.path.exists(path):
        recorded = _advisory_errors(request.app).get(cycle_id)
        if recorded is not None:
            raise ApiError(
                500,
                recorded.get("error", "advisory_generation_failed"),
                recorded.get("message", "Advisory generation failed"),
                extra={"cycle_id": cycle_id},
            )
        raise ApiError(404, "advisory_not_found", f"No advisory exists for cycle {cycle_id}")
    async with aiofiles.open(path, encoding="utf-8") as f:
        content = await f.read()
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


def start_advisory_job(
    app: FastAPI,
    cycle_id: str,
    portfolio: PortfolioSnapshot,
) -> asyncio.Task[None]:
    """Start advisory synthesis as a tracked task and mark the advisory job running.

    Shared by POST /api/advisory/{id} and the post-run pipeline; callers have
    already checked the cycle, the holdings, the cloud opt-in and the slot.
    """
    app_state: AppState = app.state.app_state
    _advisory_errors(app).pop(cycle_id, None)
    task: asyncio.Task[None] = asyncio.create_task(
        _run_advisory_synthesis(app_state, cycle_id, portfolio),
        name=f"advisory_{cycle_id}",
    )
    app.state.advisory_task = task
    app_state.state_store.set_job_status("advisory", JobStatus("running", cycle_id))
    task.add_done_callback(lambda t: _on_advisory_task_done(t, cycle_id, app))
    return task


def _advisory_errors(app: FastAPI) -> dict[str, dict[str, str]]:
    """The per-cycle failure records GET reads, created on first use."""
    errors: dict[str, dict[str, str]] | None = getattr(
        app.state,
        "advisory_generation_error",
        None,
    )
    if errors is None:
        errors = {}
        app.state.advisory_generation_error = errors
    return errors


def _record_advisory_failure(app: FastAPI, cycle_id: str, code: str, message: str) -> None:
    _advisory_errors(app)[cycle_id] = {"error": code, "message": message}


def _set_advisory_status(app: FastAPI, job_status: JobStatus) -> None:
    app_state = getattr(app.state, "app_state", None)
    if app_state is not None:
        app_state.state_store.set_job_status("advisory", job_status)


def _on_advisory_task_done(task: asyncio.Task[Any], cycle_id: str, app: FastAPI) -> None:
    """Record the outcome for GET and the job status. Must never raise.

    Messages carry the exception class only, or the fixed sentence of a
    CloudAdvisoryDisabledError: advisory exceptions can mention tickers, which
    must not reach HTTP responses (docs/DECISIONS.md#adr-holdings-isolation).
    """
    try:
        if task.cancelled():
            _record_advisory_failure(
                app,
                cycle_id,
                "advisory_generation_failed",
                "Advisory generation was cancelled",
            )
            _set_advisory_status(app, JobStatus("failed", cycle_id, "advisory_generation_failed"))
            log.warning("advisory_task_cancelled", cycle_id=cycle_id)
            return
        exc = task.exception()
        if exc is None:
            _set_advisory_status(app, JobStatus("idle", cycle_id))
            log.info("advisory_task_completed", cycle_id=cycle_id)
            return
        if isinstance(exc, CloudAdvisoryDisabledError):
            # The job re-checked the config or asked the server and refused; its
            # messages are fixed module constants, so they are safe to return.
            code, message = "cloud_advisory_disabled", str(exc) or _CLOUD_ADVISORY_MESSAGE
        else:
            code = "advisory_generation_failed"
            message = f"Advisory generation failed ({exc.__class__.__name__})"
        _record_advisory_failure(app, cycle_id, code, message)
        _set_advisory_status(app, JobStatus("failed", cycle_id, code))
        # Event name and exc_info are pinned by tests/test_task_failure_logging.py.
        log.error(
            "advisory_task_exception_recorded",
            cycle_id=cycle_id,
            exc_type=exc.__class__.__name__,
            exc_info=exc,
        )
    except Exception:  # a done-callback must never raise
        log.exception("advisory_task_done_callback_failed", cycle_id=cycle_id)


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

    try:
        cfg = await asyncio.to_thread(load_inference_config, app_state.settings)
    except (ValueError, OSError) as exc:
        raise job_config_error(exc, job="advisory", cycle_id=cycle_id) from None
    reason = _orchestrator_block_reason(cfg, app_state)
    if reason is not None:
        # The config can change between the POST and this task starting.
        log.warning("advisory_blocked_cloud_disabled", cycle_id=cycle_id, reason=reason)
        raise CloudAdvisoryDisabledError(_CLOUD_ADVISORY_MESSAGE)
    await _refuse_remote_ollama_model(cfg, app_state, cycle_id)
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

        output_path = advisory_dir(app_state) / f"{cycle_id}_advisory.json"
        await asyncio.to_thread(
            atomic_write_text,
            output_path,
            report_obj.model_dump_json(indent=2),
        )

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
