"""AppState container -- central dependency holder initialized once at startup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from alphaswarm.config import AppSettings
from alphaswarm.errors import Neo4jConnectionError
from alphaswarm.governor import ResourceGovernor
from alphaswarm.graph import GraphStateManager
from alphaswarm.logging import configure_logging, get_logger
from alphaswarm.ollama_client import OllamaClient
from alphaswarm.ollama_models import OllamaModelManager
from alphaswarm.state import StateStore
from alphaswarm.types import AgentPersona

if TYPE_CHECKING:
    from neo4j import AsyncDriver


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
    ollama_client: OllamaClient | None = None  # Wired in Phase 2, None if offline
    model_manager: OllamaModelManager | None = None  # Wired in Phase 2, None if offline
    graph_manager: GraphStateManager | None = None  # Wired in Phase 4, None if offline


def create_app_state(
    settings: AppSettings,
    personas: list[AgentPersona],
    *,
    with_ollama: bool = False,
    with_neo4j: bool = False,
) -> AppState:
    """Factory to create AppState with proper initialization order.

    1. Configure logging first (so all subsequent logs are structured)
    2. Create logger
    3. Create stubs (governor, state_store)
    4. Optionally create OllamaClient and OllamaModelManager
    5. Optionally create Neo4j driver and GraphStateManager
    6. Bundle into AppState

    Args:
        settings: Application settings.
        personas: Generated agent personas.
        with_ollama: If True, create OllamaClient and OllamaModelManager.
                     If False, both are None. Allows startup without Ollama running.
        with_neo4j: If True, create Neo4j driver and GraphStateManager.
                    If False, graph_manager is None. Fast-fails if Neo4j unreachable.
    """
    configure_logging(
        log_level=settings.log_level,
        json_output=not settings.debug,
    )
    logger = get_logger(component="app")
    state_store = StateStore()
    governor = ResourceGovernor(
        settings.governor,
        state_store=state_store,
    )

    ollama_client: OllamaClient | None = None
    model_manager: OllamaModelManager | None = None
    if with_ollama:
        ollama_client = OllamaClient(base_url=settings.ollama.base_url)
        model_manager = OllamaModelManager(
            client=ollama_client,
            configured_aliases={
                settings.ollama.orchestrator_model_alias,
                settings.ollama.worker_model_alias,
            },
        )

    graph_manager: GraphStateManager | None = None
    if with_neo4j:
        import asyncio

        from neo4j import AsyncGraphDatabase
        from neo4j.exceptions import Neo4jError as _Neo4jError

        driver = AsyncGraphDatabase.driver(
            settings.neo4j.uri,
            auth=(settings.neo4j.username, settings.neo4j.password),
            max_connection_pool_size=50,
        )
        # Fast-fail: verify Neo4j is reachable before proceeding.
        # Addresses review concern: immediate feedback if container is not running.
        try:
            asyncio.get_event_loop().run_until_complete(driver.verify_connectivity())
        except _Neo4jError as exc:
            raise Neo4jConnectionError(
                f"Cannot connect to Neo4j at {settings.neo4j.uri}. "
                "Ensure the container is running: docker compose up -d",
                original_error=exc,
            ) from exc
        except OSError as exc:
            raise Neo4jConnectionError(
                f"Cannot connect to Neo4j at {settings.neo4j.uri}. "
                "Ensure the container is running: docker compose up -d",
                original_error=exc,
            ) from exc

        graph_manager = GraphStateManager(
            driver=driver,
            personas=personas,
            database=settings.neo4j.database,
        )

    return AppState(
        settings=settings,
        logger=logger,
        governor=governor,
        state_store=state_store,
        personas=personas,
        ollama_client=ollama_client,
        model_manager=model_manager,
        graph_manager=graph_manager,
    )
