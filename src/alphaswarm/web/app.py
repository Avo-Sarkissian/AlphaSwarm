"""FastAPI application factory with lifespan-managed state."""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Final

import structlog
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles

from alphaswarm.manifest import current_git_revision
from alphaswarm.personas import load_bracket_configs
from alphaswarm.readiness import DIST_FIX
from alphaswarm.services.advisory import AdvisoryService, PortfolioSource
from alphaswarm.services.post_run import PostRunPipeline, ServicePostRunJobs
from alphaswarm.services.report import ReportService
from alphaswarm.services.runtime import Runtime, RuntimeFactory, open_runtime
from alphaswarm.settings import PROJECT_ROOT, AppSettings, legacy_origin_settings
from alphaswarm.web.broadcaster import start_broadcaster
from alphaswarm.web.connection_manager import ConnectionManager
from alphaswarm.web.errors import install_error_handlers
from alphaswarm.web.origin_guard import install_origin_guard, normalized_trusted_hosts
from alphaswarm.web.replay_manager import ReplayManager
from alphaswarm.web.routes.advisory import router as advisory_router
from alphaswarm.web.routes.agents import router as agents_router
from alphaswarm.web.routes.edges import router as edges_router
from alphaswarm.web.routes.health import router as health_router
from alphaswarm.web.routes.holdings import PortfolioCache
from alphaswarm.web.routes.holdings import router as holdings_router
from alphaswarm.web.routes.interview import router as interview_router
from alphaswarm.web.routes.replay import router as replay_router
from alphaswarm.web.routes.report import router as report_router
from alphaswarm.web.routes.settings import router as settings_router
from alphaswarm.web.routes.simulation import router as simulation_router
from alphaswarm.web.routes.websocket import router as ws_router
from alphaswarm.web.simulation_manager import SimulationManager

log = structlog.get_logger(component="web.app")

DIST_HINT_HTML: Final = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>AlphaSwarm</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 40rem; margin: 4rem auto; line-height: 1.5">
<h1>AlphaSwarm API is running</h1>
<p>The web UI has not been built, so there is nothing to show at <code>/</code> yet.</p>
<p>Build it once: <code>cd frontend &amp;&amp; npm ci &amp;&amp; npm run build</code>, then reload.</p>
<p>For development: <code>npm --prefix frontend run dev</code> and open
<a href="http://localhost:5173">http://localhost:5173</a>.</p>
<p>Check the whole setup with <code>uv run alphaswarm doctor</code>.</p>
</body></html>
"""


def mount_frontend(app: FastAPI, dist_dir: Path) -> None:
    """Serve the built SPA at / (must be the last mount), or a build hint.

    html=True serves index.html as the fallback for every non-API path, so
    client-side routes resolve (docs/DECISIONS.md#p31-d-02). Without a build, /
    used to return a bare JSON 404 (docs/DECISIONS.md#adr-web-lifespan).
    """
    if (dist_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=dist_dir, html=True), name="frontend")
        return
    log.warning("frontend_dist_missing", dist_dir=str(dist_dir), hint=DIST_FIX)

    @app.get("/", include_in_schema=False)
    async def frontend_build_hint() -> HTMLResponse:
        return HTMLResponse(DIST_HINT_HTML)


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
        close_tasks: set[asyncio.Task[None]] = getattr(app.state, "_interview_close_tasks", set())
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


async def close_interview_sessions(app: FastAPI) -> None:
    """Close every interview provider and await pending close tasks (lifespan teardown)."""
    sessions: dict[tuple[str, str], dict[str, object]] = getattr(app.state, "interview_sessions", {})
    closers: list[Callable[[], Awaitable[object]]] = []
    for session in sessions.values():
        aclose = getattr(session.get("provider"), "aclose", None)  # getattr(None, ...) -> None
        if callable(aclose):
            closers.append(aclose)
    results = await asyncio.gather(*(close() for close in closers), return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            log.warning("interview_provider_close_failed", exc_type=type(result).__name__)
    sessions.clear()
    pending: set[asyncio.Task[None]] = getattr(app.state, "_interview_close_tasks", set())
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    log.info("interview_sessions_closed", count=len(closers))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Enter the runtime, wire the web state, and unwind both through one exit stack.

    Everything with asyncio primitives is created here, never at import time.
    A failure anywhere after the runtime opened still closes it. Teardown
    order: broadcaster, simulation (and the post-run task), interview
    providers, then the runtime (jobs, Ollama pool, Neo4j driver)
    (docs/DECISIONS.md#adr-web-lifespan).
    """
    # create_app() stores the settings; the lifespan never builds AppSettings() itself,
    # so tests and launchers control configuration explicitly (docs/DECISIONS.md#adr-web-lifespan).
    settings: AppSettings = app.state.settings
    factory: RuntimeFactory = app.state.runtime_factory
    async with AsyncExitStack() as stack:
        runtime = await stack.enter_async_context(factory(settings))
        # Holdings are loaded eagerly (docs/DECISIONS.md#p39-d-07) and reloaded when the
        # CSV's mtime changes; the cache stays on app.state, never on AppState.
        portfolio_cache = PortfolioCache(settings.resolve_path(settings.holdings_csv_path))
        await portfolio_cache.get()
        await wire_web_state(app, runtime, stack, portfolio=portfolio_cache)
        log.info("lifespan_started", phase="idle", neo4j_ready=runtime.neo4j_ready)
        yield
    log.info("lifespan_stopped")


async def _cancel_and_wait(task: asyncio.Task[None]) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def wire_web_state(
    app: FastAPI,
    runtime: Runtime,
    stack: AsyncExitStack,
    *,
    portfolio: PortfolioSource,
) -> None:
    """Build the web-specific objects on top of *runtime*; register their teardown on *stack*.

    Shared by the production lifespan and the route-test app builder, so every
    route test runs the production wiring (docs/DECISIONS.md#adr-web-lifespan).
    *portfolio* is passed through as a PortfolioSource: this module never
    imports ``alphaswarm.holdings`` (docs/DECISIONS.md#adr-holdings-isolation).
    """
    settings = runtime.settings
    app_state = runtime.app_state
    app.state.runtime = runtime
    app.state.app_state = app_state
    app.state.neo4j_ready = runtime.neo4j_ready
    app.state.portfolio_cache = portfolio
    # (timestamp, components) cache for GET /api/health; None until the first probe.
    app.state.health_components = None
    # Interview sessions keyed (cycle_id, agent_id) -> {"engine", "lock", "provider"}
    # (docs/DECISIONS.md#p35-d-06).
    app.state.interview_sessions = {}
    stack.push_async_callback(close_interview_sessions, app)
    # Pin run provenance to the code this process loaded: cycles stamp this
    # revision even if HEAD moves before the first run (docs/DECISIONS.md#adr-cycle-metrics).
    await asyncio.to_thread(current_git_revision)

    graph = app_state.graph_manager
    report_service: ReportService | None = None
    advisory_service: AdvisoryService | None = None
    pipeline: PostRunPipeline | None = None
    if graph is not None:
        report_service = ReportService(
            graph=graph,
            inference=runtime.inference,
            jobs=runtime.jobs,
            reports_dir=settings.resolve_path(settings.reports_dir),
        )
        advisory_service = AdvisoryService(
            graph=graph,
            inference=runtime.inference,
            jobs=runtime.jobs,
            advisory_dir=settings.resolve_path(settings.advisory_dir),
            portfolio=portfolio.get,
            keep_last=settings.advisory_keep_last,
            sector_map_path=settings.resolve_path(settings.sector_map_path),
        )
        # docs/DECISIONS.md#adr-sequential-model-lifecycle: advisory (when allowed), then
        # the report, always; direct calls, no in-process HTTP.
        pipeline = PostRunPipeline(
            jobs=ServicePostRunJobs(report=report_service, advisory=advisory_service),
        )
    app.state.report_service = report_service
    app.state.advisory_service = advisory_service
    app.state.post_run_pipeline = pipeline

    # ReplayManager is built first so SimulationManager can refuse a start during a replay.
    replay_manager = ReplayManager(app_state)
    sim_manager = SimulationManager(
        app_state,
        load_bracket_configs(),
        on_start=make_session_clearer(app),
        replay_manager=replay_manager,
        on_complete=pipeline.on_complete if pipeline is not None else None,
        orchestrator_busy=runtime.jobs.is_busy,
        inference=runtime.inference,
    )
    # Bidirectional replay/sim exclusion: ReplayManager.start() re-checks for a
    # live simulation under its own lock.
    replay_manager.set_sim_running_check(lambda: sim_manager.is_running)
    stack.push_async_callback(sim_manager.shutdown)
    connection_manager = ConnectionManager()
    app.state.sim_manager = sim_manager
    app.state.replay_manager = replay_manager
    app.state.connection_manager = connection_manager

    # Object identity: the broadcaster gets the same ConnectionManager the WS route reads.
    broadcaster_task = start_broadcaster(app_state.state_store, connection_manager, replay_manager)
    app.state.broadcaster_task = broadcaster_task
    stack.push_async_callback(_cancel_and_wait, broadcaster_task)


def _warn_legacy_origin_settings(settings: AppSettings) -> None:
    """Log once when a removed per-channel origin variable is still configured."""
    env_file = settings.model_config.get("env_file")
    env_path = Path(env_file) if isinstance(env_file, (str, Path)) else None
    names = legacy_origin_settings(os.environ, env_path)
    if names:
        log.warning("legacy_origin_settings_ignored", names=names, use="ALPHASWARM_ALLOWED_ORIGINS")


def create_app(
    settings: AppSettings | None = None,
    *,
    runtime_factory: RuntimeFactory | None = None,
) -> FastAPI:
    """Create and configure the AlphaSwarm FastAPI application.

    ``settings`` is stored on ``app.state.settings`` and the lifespan reads it;
    ``None`` reads the environment plus ``.env``. ``runtime_factory`` defaults to
    ``open_runtime`` (Ollama + Neo4j); tests pass an offline factory. The single
    launcher is ``alphaswarm web``; nothing is constructed at import time.
    """
    resolved = settings if settings is not None else AppSettings()
    app = FastAPI(title="AlphaSwarm", lifespan=lifespan)
    app.state.settings = resolved
    app.state.runtime_factory = runtime_factory if runtime_factory is not None else open_runtime
    install_error_handlers(app)

    # CSRF guard (CWE-352): the API is unauthenticated and localhost-only, so
    # every mutating route runs with the operator's authority. One middleware
    # in front of the whole app rejects non-GET requests carrying a foreign
    # Origin/Referer, covering all routers below plus any added later.
    # Header-less callers (curl, scripts/) are unaffected — see web/origin_guard.py.
    install_origin_guard(app, resolved.allowed_origins)
    # DNS-rebinding guard (docs/DECISIONS.md#adr-security-2026-08): a page that
    # re-points its own name at 127.0.0.1 still sends that name as Host, so only
    # the Host values in settings.trusted_hosts reach any route or the WebSocket.
    # Added after the origin guard so it is the outermost middleware. A malformed
    # entry raises ValueError here, at startup.
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=normalized_trusted_hosts(resolved.trusted_hosts),
        www_redirect=False,
    )
    _warn_legacy_origin_settings(resolved)

    app.include_router(health_router, prefix="/api")
    app.include_router(simulation_router, prefix="/api")
    app.include_router(edges_router, prefix="/api")
    app.include_router(replay_router, prefix="/api")
    app.include_router(interview_router, prefix="/api")
    app.include_router(holdings_router, prefix="/api")
    app.include_router(report_router, prefix="/api")
    app.include_router(advisory_router, prefix="/api")
    app.include_router(agents_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    app.include_router(ws_router)  # No prefix — /ws/state is the full WebSocket path (D-08)

    # Built SPA at / when present, otherwise a page that says how to build it
    # (docs/DECISIONS.md#adr-web-lifespan). Must stay the last mount.
    mount_frontend(app, PROJECT_ROOT / "frontend" / "dist")

    return app
