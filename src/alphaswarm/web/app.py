"""FastAPI application factory with lifespan-managed state."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from starlette.staticfiles import StaticFiles

from alphaswarm.app import create_app_state
from alphaswarm.config import AppSettings, generate_personas, load_bracket_configs
from alphaswarm.web.broadcaster import start_broadcaster
from alphaswarm.web.connection_manager import ConnectionManager
from alphaswarm.web.routes.edges import router as edges_router
from alphaswarm.web.routes.health import router as health_router
from alphaswarm.web.routes.interview import router as interview_router
from alphaswarm.web.routes.replay import router as replay_router
from alphaswarm.web.routes.report import router as report_router
from alphaswarm.web.routes.simulation import router as simulation_router
from alphaswarm.web.routes.websocket import router as ws_router
from alphaswarm.web.replay_manager import ReplayManager
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
    # Per D-06 and review consensus: sessions stored as {agent_id: {"engine": InterviewEngine, "lock": asyncio.Lock}}
    # Initialized before SimulationManager so the on_start lambda can reference app.state.interview_sessions.
    app.state.interview_sessions = {}
    # Phase 36 D-02: single task handle for in-progress report generation detection.
    app.state.report_task = None
    # Phase 36 T-36-15: per-cycle error capture from the background task's done_callback.
    # Keys are cycle_id strings; values are {"error": ..., "message": ...} dicts.
    # GET /api/report/{cycle_id} reads this to surface 500 so the frontend can stop polling.
    app.state.report_generation_error = {}
    # ReplayManager must be constructed BEFORE SimulationManager so the latter
    # can hold a reference for the B4 replay-active guard in start().
    replay_manager = ReplayManager(app_state)
    sim_manager = SimulationManager(
        app_state,
        brackets,
        on_start=lambda: app.state.interview_sessions.clear(),
        replay_manager=replay_manager,
    )
    connection_manager = ConnectionManager()

    app.state.app_state = app_state
    app.state.sim_manager = sim_manager
    app.state.replay_manager = replay_manager
    app.state.connection_manager = connection_manager

    # Object identity: start_broadcaster receives the same `connection_manager` stored on
    # app.state.connection_manager above. ws_state reads websocket.app.state.connection_manager
    # at request time — both paths reference the same object, ensuring broadcasts reach clients.
    broadcaster_task = start_broadcaster(app_state.state_store, connection_manager, replay_manager)
    app.state.broadcaster_task = broadcaster_task

    log.info("lifespan_started", phase="idle")

    yield

    # Teardown — cancel broadcaster BEFORE closing graph_manager, because the broadcaster
    # loop calls state_store.snapshot() which may reference state that graph_manager
    # teardown would invalidate.
    broadcaster_task.cancel()
    try:
        await broadcaster_task
    except asyncio.CancelledError:
        pass

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
    app.include_router(simulation_router, prefix="/api")
    app.include_router(edges_router, prefix="/api")
    app.include_router(replay_router, prefix="/api")
    app.include_router(interview_router, prefix="/api")
    app.include_router(report_router, prefix="/api")
    app.include_router(ws_router)  # No prefix — /ws/state is the full WebSocket path (D-08)

    # Serve Vue SPA production build as static files (D-02).
    # Must be LAST mount — html=True serves index.html as fallback for all non-API paths,
    # enabling Vue Router history mode. Only mounted when dist/ exists (production build).
    frontend_dist = os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "dist")
    if os.path.isdir(frontend_dist):
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app
