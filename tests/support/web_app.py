"""Helpers for web route tests: fixed cycle ids and a fake graph.

Every value here is fictional.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import APIRouter, FastAPI

from alphaswarm.app import AppState
from alphaswarm.errors import AgentNotFoundError
from alphaswarm.services.advisory import AdvisoryService
from alphaswarm.services.jobs import JobRunner
from alphaswarm.services.report import ReportService
from alphaswarm.services.runtime import InferenceRuntime, Runtime, RuntimeFactory, build_runtime
from alphaswarm.settings import AppSettings
from alphaswarm.web.app import wire_web_state
from alphaswarm.web.errors import install_error_handlers

CYCLE_A: Final = "00000000-0000-4000-8000-0000000000a1"
CYCLE_B: Final = "00000000-0000-4000-8000-0000000000b2"
CYCLE_UNKNOWN: Final = "00000000-0000-4000-8000-0000000000ff"


class FakeCycleGraph:
    """Minimal GraphStateManager stand-in for the gating reads."""

    def __init__(
        self,
        statuses: Mapping[str, str] | None = None,
        *,
        latest: str | None = None,
        error: BaseException | None = None,
        signals: Mapping[str, Mapping[tuple[str, int], object]] | None = None,
        contexts: Mapping[tuple[str, str], object] | None = None,
        cycles: Sequence[Mapping[str, object]] = (),
        decisions: Mapping[tuple[str, str], Sequence[Mapping[str, object]]] | None = None,
    ) -> None:
        self.statuses: dict[str, str] = dict(statuses or {})
        self.latest = latest
        self.error = error
        self.signals = {k: dict(v) for k, v in (signals or {}).items()}
        self.contexts = dict(contexts or {})
        self.status_calls: list[str] = []
        self.context_calls: list[tuple[str, str]] = []
        self.cycles: list[dict[str, object]] = [dict(c) for c in cycles]
        self.cycle_calls: list[tuple[int, datetime | None]] = []
        self.decisions = {key: [dict(r) for r in rows] for key, rows in (decisions or {}).items()}
        self.decision_calls: list[tuple[str, str]] = []

    async def read_cycle_status(self, cycle_id: str) -> str | None:
        self.status_calls.append(cycle_id)
        if self.error is not None:
            raise self.error
        return self.statuses.get(cycle_id)

    async def cycle_exists(self, cycle_id: str) -> bool:
        return await self.read_cycle_status(cycle_id) is not None

    async def read_latest_cycle_id(self, *, statuses: Sequence[str] = ("complete",)) -> str | None:
        if self.error is not None:
            raise self.error
        return self.latest

    async def read_full_cycle_signals(self, cycle_id: str) -> dict[tuple[str, int], object]:
        return dict(self.signals.get(cycle_id, {}))

    async def read_bracket_narratives_for_round(
        self,
        cycle_id: str,
        round_num: int,
    ) -> list[dict[str, object]]:
        return []

    async def read_rationale_entries_for_round(
        self,
        cycle_id: str,
        round_num: int,
    ) -> list[dict[str, object]]:
        return []

    async def read_influence_edges(self, cycle_id: str, round_num: int) -> list[dict[str, object]]:
        return []

    async def read_completed_cycles(
        self,
        limit: int = 20,
        *,
        before: datetime | None = None,
    ) -> list[dict[str, object]]:
        """The *cycles* page older than *before*; falls back to *latest* when no cycles are set."""
        self.cycle_calls.append((limit, before))
        rows = self.cycles or ([{"cycle_id": self.latest}] if self.latest else [])
        if before is not None:
            cursor = before if before.tzinfo is not None else before.replace(tzinfo=UTC)
            rows = [r for r in rows if datetime.fromisoformat(str(r["created_at"])) < cursor]
        return rows[:limit]

    async def read_agent_interview_context(self, agent_id: str, cycle_id: str) -> object:
        """The stored context for (cycle, agent); AgentNotFoundError for an unknown agent."""
        self.context_calls.append((cycle_id, agent_id))
        context = self.contexts.get((cycle_id, agent_id))
        if context is None:
            raise AgentNotFoundError(agent_id, cycle_id)
        return context

    async def read_agent_decisions(self, cycle_id: str, agent_id: str) -> list[dict[str, object]]:
        self.decision_calls.append((cycle_id, agent_id))
        return list(self.decisions.get((cycle_id, agent_id), []))

    async def close(self) -> None:
        return None


class StaticPortfolioCache:
    """Stand-in for PortfolioCache that always returns one snapshot (or None)."""

    def __init__(self, snapshot: object | None) -> None:
        self.snapshot = snapshot
        self.get_calls = 0  # lets tests prove the holdings were never touched

    async def get(self) -> object | None:
        self.get_calls += 1
        return self.snapshot

    @property
    def holdings_as_of(self) -> object | None:
        return getattr(self.snapshot, "as_of", None)


def route_test_settings(tmp_path: Path, **overrides: Any) -> AppSettings:
    """AppSettings whose output and input paths all live under *tmp_path*."""
    values: dict[str, Any] = {
        "reports_dir": tmp_path / "reports",
        "advisory_dir": tmp_path / "advisory",
        "inference_config_path": tmp_path / "inference.json",
        "holdings_csv_path": tmp_path / "holdings.csv",
        "sector_map_path": tmp_path / "sector_map.json",
    }
    values.update(overrides)
    return AppSettings(_env_file=None, **values)  # type: ignore[call-arg]


def runtime_for(app_state: AppState) -> Runtime:
    """A Runtime around an AppState a test built by hand (for custom test lifespans)."""
    return Runtime(
        settings=app_state.settings,
        app_state=app_state,
        inference=InferenceRuntime(
            app_state.settings,
            ollama_client=app_state.ollama_client,
            model_manager=app_state.model_manager,
        ),
        jobs=JobRunner(app_state.state_store),
        neo4j_ready=app_state.graph_manager is not None,
    )


def offline_runtime(settings: AppSettings, *, graph: object | None = None) -> Runtime:
    """build_runtime without Ollama or Neo4j; *graph* (a fake) becomes the graph manager."""
    runtime = build_runtime(settings, with_ollama=False, with_neo4j=False)
    runtime.app_state.graph_manager = graph  # type: ignore[assignment]
    return runtime_for(runtime.app_state)


def offline_runtime_factory(
    *,
    graph: object | None = None,
    events: list[str] | None = None,
) -> RuntimeFactory:
    """A RuntimeFactory for create_app(settings, runtime_factory=...) tests."""

    @asynccontextmanager
    async def _factory(settings: AppSettings) -> AsyncIterator[Runtime]:
        runtime = offline_runtime(settings, graph=graph)
        if events is not None:
            events.append("runtime_open")
        try:
            yield runtime
        finally:
            await runtime.jobs.shutdown()
            if events is not None:
                events.append("runtime_close")

    return _factory


def advisory_service_for(
    settings: AppSettings,
    *,
    portfolio: object | None,
    graph: object | None = None,
    ollama_client: object | None = None,
) -> AdvisoryService:
    """An AdvisoryService over an offline runtime, wired like the web app.

    The default Ollama client is a loopback host whose model runs locally, so the
    advisory's cloud guards pass; *portfolio* sits behind StaticPortfolioCache.
    """
    app_state = offline_runtime(settings, graph=graph if graph is not None else object()).app_state
    app_state.ollama_client = (  # type: ignore[assignment]
        ollama_client
        if ollama_client is not None
        else SimpleNamespace(base_url="http://127.0.0.1:11434", is_remote_model=AsyncMock(return_value=False))
    )
    runtime = runtime_for(app_state)
    service_graph: Any = app_state.graph_manager
    return AdvisoryService(
        graph=service_graph,
        inference=runtime.inference,
        jobs=runtime.jobs,
        advisory_dir=settings.resolve_path(settings.advisory_dir),
        portfolio=StaticPortfolioCache(portfolio).get,  # type: ignore[arg-type]
        keep_last=settings.advisory_keep_last,
        sector_map_path=settings.resolve_path(settings.sector_map_path),
    )


def block_service_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ReportService/AdvisoryService.generate wait forever (route tests never run a job)."""

    async def _blocked(self: object, cycle_id: str) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(ReportService, "generate", _blocked)
    monkeypatch.setattr(AdvisoryService, "generate", _blocked)


def make_route_app(
    *routers: APIRouter,
    settings: AppSettings,
    graph: object | None = None,
    portfolio: object | None = None,
) -> FastAPI:
    """App with *routers* and the error handlers, wired by the production wire_web_state.

    Runs offline (no Ollama, no Neo4j driver): *graph* is a fake and *portfolio*
    a fixed snapshot behind StaticPortfolioCache, so every route test exercises
    the production wiring.
    """

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            app_state = offline_runtime(settings, graph=graph).app_state
            # A loopback host, so the advisory's cloud guard sees a local Ollama server;
            # no route test call reaches the client or the model manager.
            app_state.ollama_client = MagicMock(base_url="http://127.0.0.1:11434")
            app_state.model_manager = MagicMock()
            runtime = runtime_for(app_state)
            stack.push_async_callback(runtime.jobs.shutdown)
            await wire_web_state(app, runtime, stack, portfolio=StaticPortfolioCache(portfolio))  # type: ignore[arg-type]
            yield

    app = FastAPI(lifespan=_lifespan)
    app.state.settings = settings
    install_error_handlers(app)
    for router in routers:
        app.include_router(router, prefix="/api")
    return app
