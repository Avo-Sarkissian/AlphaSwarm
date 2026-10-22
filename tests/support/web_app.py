"""Helpers for web route tests: fixed cycle ids and a fake graph.

Every value here is fictional.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Final
from unittest.mock import MagicMock

from fastapi import APIRouter, FastAPI

from alphaswarm.app import create_app_state
from alphaswarm.config import AppSettings, generate_personas, load_bracket_configs
from alphaswarm.web.app import make_session_clearer
from alphaswarm.web.connection_manager import ConnectionManager
from alphaswarm.web.errors import install_error_handlers
from alphaswarm.web.guards import orchestrator_job_running
from alphaswarm.web.replay_manager import ReplayManager
from alphaswarm.web.simulation_manager import SimulationManager

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
    ) -> None:
        self.statuses: dict[str, str] = dict(statuses or {})
        self.latest = latest
        self.error = error
        self.signals = {k: dict(v) for k, v in (signals or {}).items()}
        self.status_calls: list[str] = []

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

    async def read_completed_cycles(self, limit: int = 10) -> list[dict[str, object]]:
        return []

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
    }
    values.update(overrides)
    return AppSettings(_env_file=None, **values)  # type: ignore[call-arg]


def make_route_app(
    *routers: APIRouter,
    settings: AppSettings,
    graph: object | None = None,
    portfolio: object | None = None,
) -> FastAPI:
    """App with *routers*, the error handlers and an offline AppState (no Neo4j/Ollama).

    Mirrors the app.state slots the production lifespan creates. Job tasks still
    running at shutdown are cancelled, like the real lifespan teardown.
    """

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        brackets = load_bracket_configs()
        app_state = create_app_state(
            settings,
            generate_personas(brackets),
            with_ollama=False,
            with_neo4j=False,
        )
        app_state.graph_manager = graph  # type: ignore[assignment]
        # A loopback host, so the advisory's cloud guard sees a local Ollama server.
        app_state.ollama_client = MagicMock(base_url="http://127.0.0.1:11434")
        app_state.model_manager = MagicMock()
        app.state.interview_sessions = {}
        app.state.report_task = None
        app.state.advisory_task = None
        app.state.report_generation_error = {}
        app.state.advisory_generation_error = {}
        app.state.portfolio_cache = StaticPortfolioCache(portfolio)
        replay_manager = ReplayManager(app_state)
        sim_manager = SimulationManager(
            app_state,
            brackets,
            on_start=make_session_clearer(app),
            replay_manager=replay_manager,
            orchestrator_busy=lambda: orchestrator_job_running(app_state),
        )
        replay_manager.set_sim_running_check(lambda: sim_manager.is_running)
        app.state.app_state = app_state
        app.state.sim_manager = sim_manager
        app.state.replay_manager = replay_manager
        app.state.connection_manager = ConnectionManager()
        yield
        for attr in ("report_task", "advisory_task"):
            task = getattr(app.state, attr, None)
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    app = FastAPI(lifespan=_lifespan)
    install_error_handlers(app)
    for router in routers:
        app.include_router(router, prefix="/api")
    return app
