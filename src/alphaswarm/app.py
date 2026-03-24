"""AppState container -- central dependency holder initialized once at startup."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from alphaswarm.config import AppSettings
from alphaswarm.governor import ResourceGovernor
from alphaswarm.logging import configure_logging, get_logger
from alphaswarm.state import StateStore
from alphaswarm.types import AgentPersona


@dataclass
class AppState:
    """Central application state container. Initialized once at startup.

    Passed to all subsystems as a dependency to prevent circular imports
    and scattered globals. Per user decision: AppState container pattern
    preferred over scattered global singletons.
    """

    settings: AppSettings
    logger: structlog.stdlib.BoundLogger
    governor: ResourceGovernor
    state_store: StateStore
    personas: list[AgentPersona]
    # neo4j_driver: AsyncDriver  # Added in Phase 4
    # ollama_client: AsyncClient  # Added in Phase 2


def create_app_state(settings: AppSettings, personas: list[AgentPersona]) -> AppState:
    """Factory to create AppState with proper initialization order.

    1. Configure logging first (so all subsequent logs are structured)
    2. Create logger
    3. Create stubs (governor, state_store)
    4. Bundle into AppState
    """
    configure_logging(
        log_level=settings.log_level,
        json_output=not settings.debug,
    )
    logger = get_logger(component="app")
    governor = ResourceGovernor(
        baseline_parallel=settings.governor.baseline_parallel,
    )
    state_store = StateStore()

    return AppState(
        settings=settings,
        logger=logger,
        governor=governor,
        state_store=state_store,
        personas=personas,
    )
