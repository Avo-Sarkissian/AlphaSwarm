"""Guards shared by the job routes (report, advisory, interview).

They turn a missing graph, cycle state and orchestrator contention into
ApiErrors with stable codes, so every route reports the same condition the same
way (docs/DECISIONS.md#adr-background-tasks).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from alphaswarm.config import InferenceConfig, load_inference_config
from alphaswarm.web.errors import ApiError

if TYPE_CHECKING:
    from alphaswarm.app import AppState
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.state import JobKind
    from alphaswarm.web.simulation_manager import SimulationManager


def require_graph(app_state: AppState) -> GraphStateManager:
    """Return the graph manager; 503 when this server was built without Neo4j."""
    graph = app_state.graph_manager
    if graph is None:
        raise ApiError(503, "graph_unavailable", "Neo4j is not configured for this server")
    return graph


def running_job_cycle(app_state: AppState, kind: JobKind) -> str | None:
    """Cycle id of the running *kind* job, or None when that job is not running."""
    jobs = app_state.state_store.job_statuses()
    status = jobs.advisory if kind == "advisory" else jobs.report
    return status.cycle_id if status.state == "running" else None


def orchestrator_job_running(app_state: AppState) -> bool:
    """True while a report or advisory job holds the orchestrator."""
    jobs = app_state.state_store.job_statuses()
    return jobs.advisory.state == "running" or jobs.report.state == "running"


def require_orchestrator_free(app_state: AppState) -> None:
    """409 while either orchestrator job runs (report/advisory never overlap)."""
    jobs = app_state.state_store.job_statuses()
    if jobs.report.state == "running":
        raise ApiError(
            409,
            "report_generation_in_progress",
            "A report generation is already running; retry when it completes",
        )
    if jobs.advisory.state == "running":
        raise ApiError(
            409,
            "advisory_generation_in_progress",
            "An advisory generation is already running; retry when it completes",
        )


async def require_complete_cycle(
    app_state: AppState,
    sim_manager: SimulationManager,
    cycle_id: str,
) -> None:
    """Gate a job on durable cycle state instead of the in-memory phase.

    409 ``simulation_running`` while a run is in progress (checked first, without
    touching Neo4j), 404 ``cycle_not_found`` for an unknown id, 422
    ``cycle_not_ready`` for a running, failed or cancelled cycle.
    """
    if sim_manager.is_running:
        raise ApiError(409, "simulation_running", "A simulation is running; retry when it finishes")
    status = await require_graph(app_state).read_cycle_status(cycle_id)
    if status is None:
        raise ApiError(404, "cycle_not_found", f"No cycle {cycle_id}")
    if status != "complete":
        raise ApiError(
            422,
            "cycle_not_ready",
            f"Cycle {cycle_id} is {status}; only complete cycles can be used",
            extra={"cycle_status": status},
        )


async def load_inference_config_or_422(app_state: AppState) -> InferenceConfig:
    """Load the stored inference config off the loop; 422 (no path) when it is invalid."""
    try:
        return await asyncio.to_thread(load_inference_config, app_state.settings)
    except ValueError as exc:
        raise ApiError(
            422,
            "inference_config_invalid",
            "The stored inference config is invalid; fix it in Settings or remove the stored file",
        ) from exc
