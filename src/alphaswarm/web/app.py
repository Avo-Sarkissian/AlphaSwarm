"""FastAPI application factory with lifespan-managed state."""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import structlog
from fastapi import FastAPI
from neo4j.exceptions import AuthError as Neo4jAuthError
from neo4j.exceptions import DriverError, Neo4jError
from starlette.staticfiles import StaticFiles

from alphaswarm.app import create_app_state
from alphaswarm.config import AppSettings, generate_personas, load_bracket_configs
from alphaswarm.ingestion import RSSNewsProvider, YFinanceMarketDataProvider
from alphaswarm.manifest import current_git_revision
from alphaswarm.readiness import NEO4J_AUTH_FIX, NEO4J_FIX
from alphaswarm.web.broadcaster import start_broadcaster
from alphaswarm.web.connection_manager import ConnectionManager
from alphaswarm.web.errors import install_error_handlers
from alphaswarm.web.guards import orchestrator_job_running
from alphaswarm.web.origin_guard import install_origin_guard
from alphaswarm.web.post_run import AdvisoryGate, PostRunJobBusyError, PostRunPipeline
from alphaswarm.web.replay_manager import ReplayManager
from alphaswarm.web.routes.advisory import advisory_refusal, start_advisory_job
from alphaswarm.web.routes.advisory import router as advisory_router
from alphaswarm.web.routes.edges import router as edges_router
from alphaswarm.web.routes.health import router as health_router
from alphaswarm.web.routes.holdings import PortfolioCache
from alphaswarm.web.routes.holdings import router as holdings_router
from alphaswarm.web.routes.interview import router as interview_router
from alphaswarm.web.routes.replay import router as replay_router
from alphaswarm.web.routes.report import router as report_router
from alphaswarm.web.routes.report import start_report_job
from alphaswarm.web.routes.settings import router as settings_router
from alphaswarm.web.routes.simulation import router as simulation_router
from alphaswarm.web.routes.websocket import router as ws_router
from alphaswarm.web.simulation_manager import SimulationManager

if TYPE_CHECKING:
    from alphaswarm.graph import GraphStateManager

log = structlog.get_logger(component="web.app")


async def _prepare_neo4j(graph_manager: GraphStateManager | None) -> bool:
    """Verify Neo4j, then apply the idempotent schema; return readiness.

    ensure_schema() also seeds the 100 Agent nodes every write MATCHes, so a
    fresh database persists nothing until it has run (docs/DECISIONS.md#p4-d-05).
    A down or misconfigured database must not stop the server from starting,
    so driver and auth errors are logged (with the fix for that failure, the
    same text /api/health shows) and reported as not ready. Once the database
    answers, /api/health applies the schema.
    """
    if graph_manager is None:
        return False
    try:
        await graph_manager.verify_connectivity()
        await graph_manager.ensure_schema()
    except (DriverError, Neo4jError) as exc:
        fix = NEO4J_AUTH_FIX if isinstance(exc, Neo4jAuthError) else NEO4J_FIX
        log.warning(
            "neo4j_unavailable_at_startup",
            error_type=type(exc).__name__,
            error=str(exc),
            fix=fix,
        )
        return False
    log.info("neo4j_schema_ready")
    return True


def make_session_clearer(app: FastAPI) -> Callable[[], None]:
    """Return a synchronous on_start callback that closes interview providers before clearing.

    Extracted as a module-level factory so tests can import and verify the
    behaviour without standing up the full lifespan.  The returned callable is
    safe to call from a sync context (SimulationManager.start does NOT await
    on_start).  Each provider.aclose() is scheduled as a tracked
    asyncio.create_task; strong references live on app.state._interview_close_tasks
    so the GC cannot collect them before the event loop executes them.
    OllamaProvider.aclose is a documented no-op — the close is harmless for the
    local path.
    """
    def _clear_interview_sessions() -> None:
        sessions: dict[tuple[str, str], dict[str, object]] = app.state.interview_sessions
        close_tasks: set[asyncio.Task[None]] = getattr(
            app.state, "_interview_close_tasks", set()
        )
        app.state._interview_close_tasks = close_tasks

        async def _safe_close(provider: object) -> None:
            try:
                aclose = getattr(provider, "aclose", None)
                if callable(aclose):
                    await aclose()
            except Exception:
                log.warning("interview_provider_close_failed", provider=repr(provider))

        for session in sessions.values():
            provider = session.get("provider") if isinstance(session, dict) else None
            if provider is not None:
                task: asyncio.Task[None] = asyncio.create_task(
                    _safe_close(provider),
                    name="interview_provider_close",
                )
                close_tasks.add(task)
                task.add_done_callback(close_tasks.discard)

        sessions.clear()
        log.info("interview_sessions_cleared")

    return _clear_interview_sessions


class WebPostRunJobs:
    """PostRunJobs over the route-level job starters.

    The pipeline, the POST routes and the job status therefore share one code
    path. ``app.state.portfolio_cache`` is passed through untyped: this module
    must not import ``alphaswarm.holdings`` (docs/DECISIONS.md#adr-holdings-isolation).
    """

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    async def advisory_gate(self, cycle_id: str) -> AdvisoryGate:
        # The POST route's check, before the holdings are touched: an unreadable
        # config fails closed and a cloud or remote orchestrator without the opt-in
        # is refused. Both refusals are recorded, so GET answers with their code
        # instead of a 404 the UI shows as pending (docs/DECISIONS.md#adr-advisory-pipeline).
        if await advisory_refusal(self._app, cycle_id) is not None:
            return "cloud_advisory_disabled"
        if await self._app.state.portfolio_cache.get() is None:
            return "no_portfolio"
        return "run"

    async def run_advisory(self, cycle_id: str) -> None:
        if orchestrator_job_running(self._app.state.app_state):
            raise PostRunJobBusyError("advisory")
        portfolio = await self._app.state.portfolio_cache.get()
        if portfolio is None:
            raise RuntimeError("holdings disappeared before the advisory started")
        # The job's done-callback (which resets the job status) was registered
        # before this await, so it runs before we resume and run_report sees the
        # slot free.
        await start_advisory_job(self._app, cycle_id, portfolio)

    async def run_report(self, cycle_id: str) -> None:
        if orchestrator_job_running(self._app.state.app_state):
            raise PostRunJobBusyError("report")
        await start_report_job(self._app, cycle_id)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan: create all stateful objects inside the event loop.

    All objects that use asyncio primitives (ResourceGovernor's Queue,
    SimulationManager's Lock, ConnectionManager's queues) must be created
    here — never at module import time — to avoid the
    "Future attached to a different loop" error class.
    """
    # create_app() stores the settings; the lifespan never builds AppSettings() itself,
    # so tests and launchers control configuration explicitly (docs/DECISIONS.md#adr-web-lifespan).
    settings: AppSettings = app.state.settings
    brackets = load_bracket_configs()
    personas = generate_personas(brackets)
    app_state = create_app_state(settings, personas, with_ollama=True, with_neo4j=True)
    # Interview sessions keyed (cycle_id, agent_id) -> {"engine", "lock", "provider"}; created
    # before SimulationManager so on_start can clear them (docs/DECISIONS.md#p35-d-06).
    app.state.interview_sessions = {}
    # Phase 36 D-02: single task handle for in-progress report generation detection.
    app.state.report_task = None
    # Phase 36 T-36-15: per-cycle error capture from the background task's done_callback.
    # Keys are cycle_id strings; values are {"error": ..., "message": ...} dicts.
    # GET /api/report/{cycle_id} reads this to surface 500 so the frontend can stop polling.
    app.state.report_generation_error = {}
    # Phase 41 D-08 / D-13: advisory task slot + per-cycle error capture,
    # mirrors the report pattern so GET /api/advisory/{cycle_id} can surface
    # 500 on failure without the frontend polling to the 10-minute cap.
    app.state.advisory_task = None
    app.state.advisory_generation_error = {}
    # ReplayManager must be constructed BEFORE SimulationManager so the latter
    # can hold a reference for the B4 replay-active guard in start().
    replay_manager = ReplayManager(app_state)
    # docs/DECISIONS.md#adr-sequential-model-lifecycle: advisory (when allowed), then the
    # report, always; direct calls, no in-process HTTP.
    post_run_pipeline = PostRunPipeline(jobs=WebPostRunJobs(app))
    app.state.post_run_pipeline = post_run_pipeline
    sim_manager = SimulationManager(
        app_state,
        brackets,
        on_start=make_session_clearer(app),
        replay_manager=replay_manager,
        on_complete=post_run_pipeline.on_complete,
        orchestrator_busy=lambda: orchestrator_job_running(app_state),
    )
    # Bidirectional replay/sim exclusion: ReplayManager.start() re-checks for a
    # live simulation under its own lock (closes the TOCTOU window between the
    # route-level is_running check and the awaited Neo4j loads in start()).
    replay_manager.set_sim_running_check(lambda: sim_manager.is_running)
    connection_manager = ConnectionManager()

    app.state.app_state = app_state
    app.state.sim_manager = sim_manager
    app.state.replay_manager = replay_manager
    app.state.connection_manager = connection_manager
    app.state.neo4j_ready = await _prepare_neo4j(app_state.graph_manager)
    # (timestamp, components) cache for GET /api/health; None until the first probe.
    app.state.health_components = None
    # Pin run provenance to the code this process loaded: cycles stamp this
    # revision even if HEAD moves before the first run (docs/DECISIONS.md#adr-cycle-metrics).
    await asyncio.to_thread(current_git_revision)

    # Holdings are loaded eagerly (docs/DECISIONS.md#p39-d-07) and reloaded when the
    # CSV's mtime changes; the cache stays on app.state, never on AppState.
    portfolio_cache = PortfolioCache(settings.resolve_path(settings.holdings_csv_path))
    await portfolio_cache.get()
    app.state.portfolio_cache = portfolio_cache

    # Phase 40 D-10: construct Yahoo Finance + RSS providers once at startup.
    # Both __init__ methods are synchronous and do no network I/O (lazy fetch).
    # Providers are stored on BOTH app.state (request-handler convenience) and
    # app_state (subsystem convenience for SimulationManager) — same instance.
    market_provider = YFinanceMarketDataProvider()
    news_provider = RSSNewsProvider()
    # ITEM 5 of quick task 260512-jqn: attach the state_store as the audit
    # sink so each yfinance/RSS fetch surfaces on the WS SignalWire ticker.
    # Providers swallow record_data_source failures (non-fatal).
    market_provider.attach_audit_sink(app_state.state_store)
    news_provider.attach_audit_sink(app_state.state_store)
    app.state.market_provider = market_provider
    app.state.news_provider = news_provider
    app_state.market_provider = market_provider
    app_state.news_provider = news_provider
    log.info("providers_wired", market="yfinance", news="rss", audit_sink="state_store")

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
    with contextlib.suppress(asyncio.CancelledError):
        await broadcaster_task

    # Cancel and await any running simulation + report/advisory background
    # tasks BEFORE closing graph_manager, so no orphaned task is left
    # mid-Neo4j-write ("Task was destroyed but it is pending" at shutdown).
    await sim_manager.shutdown()
    for task_attr in ("report_task", "advisory_task"):
        bg_task = getattr(app.state, task_attr, None)
        if bg_task is not None and not bg_task.done():
            bg_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await bg_task

    if app_state.graph_manager is not None:
        await app_state.graph_manager.close()

    log.info("lifespan_stopped")


def create_app(settings: AppSettings | None = None) -> FastAPI:
    """Create and configure the AlphaSwarm FastAPI application.

    ``settings`` is stored on ``app.state.settings`` and the lifespan reads it.
    ``None`` keeps today's behaviour (environment plus ``.env``). All stateful
    objects are still created inside the lifespan, never at import time.
    """
    resolved = settings if settings is not None else AppSettings()
    app = FastAPI(title="AlphaSwarm", lifespan=lifespan)
    app.state.settings = resolved
    install_error_handlers(app)

    # CSRF guard (CWE-352): the API is unauthenticated and localhost-only, so
    # every mutating route runs with the operator's authority. One middleware
    # in front of the whole app rejects non-GET requests carrying a foreign
    # Origin/Referer, covering all routers below plus any added later.
    # Header-less callers (curl, scripts/) are unaffected — see web/origin_guard.py.
    install_origin_guard(app, resolved.http_allowed_origins)

    app.include_router(health_router, prefix="/api")
    app.include_router(simulation_router, prefix="/api")
    app.include_router(edges_router, prefix="/api")
    app.include_router(replay_router, prefix="/api")
    app.include_router(interview_router, prefix="/api")
    app.include_router(holdings_router, prefix="/api")
    app.include_router(report_router, prefix="/api")
    app.include_router(advisory_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    app.include_router(ws_router)  # No prefix — /ws/state is the full WebSocket path (D-08)

    # Serve the React SPA production build as static files (docs/DECISIONS.md#p31-d-02).
    # Must be LAST mount — html=True serves index.html as fallback for all non-API paths,
    # so client-side routes resolve. Only mounted when dist/ exists (production build).
    frontend_dist = os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "dist")
    if os.path.isdir(frontend_dist):
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app


def __getattr__(name: str) -> FastAPI:
    """Build the module-level ``app`` on first access (``uvicorn alphaswarm.web.app:app``).

    Not at import: every ``alphaswarm.web`` import loads this module, and pytest
    imports it while collecting, before its hermetic fixture runs. An app built
    then would keep the operator's settings for its lifespan
    (docs/DECISIONS.md#adr-web-lifespan).
    """
    if name != "app":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    built = create_app()
    globals()["app"] = built  # later lookups find it directly and skip this hook
    return built
