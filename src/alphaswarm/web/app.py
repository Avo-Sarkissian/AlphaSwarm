"""FastAPI application factory with lifespan-managed state."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from alphaswarm.app import create_app_state
from alphaswarm.config import AppSettings, generate_personas, load_bracket_configs
from alphaswarm.web.connection_manager import ConnectionManager
from alphaswarm.web.routes.health import router as health_router
from alphaswarm.web.simulation_manager import SimulationManager

log = structlog.get_logger(component="web.app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan: create all stateful objects inside the event loop.

    All objects that use asyncio primitives (ResourceGovernor's Queue,
    SimulationManager's Lock, ConnectionManager's queues) must be created
    here — never at module import time — to avoid the
    "Future attached to a different loop" error class.
    """
    settings = AppSettings()
    brackets = load_bracket_configs()
    personas = generate_personas(brackets)
    app_state = create_app_state(settings, personas, with_ollama=True, with_neo4j=True)
    sim_manager = SimulationManager(app_state)
    connection_manager = ConnectionManager()

    app.state.app_state = app_state
    app.state.sim_manager = sim_manager
    app.state.connection_manager = connection_manager

    log.info("lifespan_started", phase="idle")

    yield

    # Teardown
    if app_state.graph_manager is not None:
        await app_state.graph_manager.close()

    log.info("lifespan_stopped")


def create_app() -> FastAPI:
    """Create and configure the AlphaSwarm FastAPI application.

    All stateful objects are created inside the lifespan function,
    never at module import time.
    """
    app = FastAPI(title="AlphaSwarm", lifespan=lifespan)
    app.include_router(health_router, prefix="/api")
    return app
