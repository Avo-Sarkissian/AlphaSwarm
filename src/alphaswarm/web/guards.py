"""Guards shared by the job routes (report, advisory, interview) and Settings.

They turn a missing graph, cycle state and an unreadable inference config into
ApiErrors with stable codes, so every route reports the same condition the same
way (docs/DECISIONS.md#adr-background-tasks). Orchestrator contention is the
JobRunner's (services.jobs.JobInProgressError, web.deps.job_conflict).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from alphaswarm.inference.config import InferenceConfig, load_inference_config
from alphaswarm.web.errors import ApiError

if TYPE_CHECKING:
    from alphaswarm.app import AppState
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.web.simulation_manager import SimulationManager


def require_graph(app_state: AppState) -> GraphStateManager:
    """Return the graph manager; 503 when this server was built without Neo4j."""
    graph = app_state.graph_manager
    if graph is None:
        raise ApiError(503, "graph_unavailable", "Neo4j is not configured for this server")
    return graph


def require_no_simulation(sim_manager: SimulationManager) -> None:
    """409 ``simulation_running`` while a run is in progress.

    A job route calls it again after its last await, right before it starts the
    job: a run started during those awaits passed start()'s orchestrator probe
    because no job was marked running yet, and the orchestrator must not load
    while the rounds run (docs/DECISIONS.md#adr-sequential-model-lifecycle).
    """
    if sim_manager.is_running:
        raise ApiError(409, "simulation_running", "A simulation is running; retry when it finishes")


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
    require_no_simulation(sim_manager)
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


# Settings cannot open an invalid file, so the message names the file's setting
# rather than Settings. It says to move the file aside, not to delete it: the
# file holds the stored API keys (docs/DECISIONS.md#adr-local-first-inference).
STORED_CONFIG_INVALID_MESSAGE: Final = (
    "The stored inference config is invalid, so Settings cannot open it. Fix or "
    "move aside the file named by ALPHASWARM_INFERENCE_CONFIG_PATH (the health check "
    "lists the rejected keys); without it the local defaults apply."
)


async def load_inference_config_or_422(app_state: AppState) -> InferenceConfig:
    """Load the stored inference config off the loop; 422 (no path) when it is invalid.

    An unreadable file (OSError, e.g. no read permission) counts as invalid, so
    callers that gate on the config fail closed. The Settings routes use this
    guard too (STORED_CONFIG_INVALID_MESSAGE).
    """
    try:
        return await asyncio.to_thread(load_inference_config, app_state.settings)
    except (ValueError, OSError) as exc:
        raise ApiError(422, "inference_config_invalid", STORED_CONFIG_INVALID_MESSAGE) from exc
