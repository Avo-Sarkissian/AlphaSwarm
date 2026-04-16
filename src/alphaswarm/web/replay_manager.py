"""ReplayManager: stateful wrapper for replay lifecycle (D-07)."""

from __future__ import annotations

import asyncio
import dataclasses
import json
from typing import TYPE_CHECKING

import structlog

from alphaswarm.state import BracketSummary, RationaleEntry, ReplayStore
from alphaswarm.types import SimulationPhase

if TYPE_CHECKING:
    from alphaswarm.app import AppState
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.state import AgentState
    from alphaswarm.web.connection_manager import ConnectionManager

log = structlog.get_logger(component="web.replay_manager")


class ReplayAlreadyActiveError(Exception):
    """Raised when start() is called while a replay is already active."""


class NoReplayActiveError(Exception):
    """Raised when advance/stop called with no active replay."""


class ReplayManager:
    """Thin wrapper enforcing single-replay concurrency via asyncio.Lock.

    Created inside FastAPI lifespan. Holds the active ReplayStore,
    cycle_id, and round_num for the duration of a replay session.
    """

    def __init__(self, app_state: AppState) -> None:
        self._app_state = app_state
        self._lock = asyncio.Lock()
        self._store: ReplayStore | None = None
        self._cycle_id: str | None = None
        self._round_num: int = 0
        self._seed_rumor: str = ""

    @property
    def is_active(self) -> bool:
        """True when a replay session is currently active."""
        return self._store is not None

    @property
    def store(self) -> ReplayStore:
        """Return the active ReplayStore. Raises if no replay is active."""
        if self._store is None:
            raise NoReplayActiveError("No replay active")
        return self._store

    @property
    def round_num(self) -> int:
        """Current round number (0 when inactive)."""
        return self._round_num

    @property
    def cycle_id(self) -> str | None:
        """Active cycle ID, or None when inactive."""
        return self._cycle_id

    @property
    def seed_rumor(self) -> str:
        """Seed rumor for the active replay."""
        return self._seed_rumor

    async def start(
        self,
        cycle_id: str,
        signals: dict[tuple[str, int], AgentState],
        connection_manager: ConnectionManager,
        graph_manager: GraphStateManager,
    ) -> None:
        """Start replay: construct ReplayStore, load round 1, broadcast (D-08)."""
        async with self._lock:
            if self.is_active:
                raise ReplayAlreadyActiveError("Replay already active")
            self._store = ReplayStore(cycle_id, signals)
            self._cycle_id = cycle_id
            self._round_num = 1
            self._store.set_round(1)
            # Load bracket summaries and rationale entries for round 1
            brackets = await graph_manager.read_bracket_narratives_for_round(cycle_id, 1)
            bracket_summaries = tuple(
                BracketSummary(
                    bracket=b["bracket"],
                    display_name=b.get("display_name", b["bracket"]),
                    buy_count=b.get("buy_count", 0),
                    sell_count=b.get("sell_count", 0),
                    hold_count=b.get("hold_count", 0),
                    total=b.get("total", 0),
                    avg_confidence=b.get("avg_confidence", 0.0),
                    avg_sentiment=b.get("avg_sentiment", 0.0),
                )
                for b in brackets
            )
            self._store.set_bracket_summaries(bracket_summaries)
            rationales_raw = await graph_manager.read_rationale_entries_for_round(cycle_id, 1)
            rationale_entries = tuple(
                RationaleEntry(
                    agent_id=r["agent_id"],
                    signal=r["signal"],
                    rationale=r["rationale"],
                    round_num=r["round_num"],
                )
                for r in rationales_raw
            )
            self._store.set_rationale_entries(rationale_entries)
            # Set phase on state_store so broadcaster sees REPLAY
            await self._app_state.state_store.set_phase(SimulationPhase.REPLAY)
            # Broadcast round-1 snapshot immediately
            snap = self._store.snapshot()
            d = dataclasses.asdict(snap)
            connection_manager.broadcast(json.dumps(d))
            log.info("replay_started", cycle_id=cycle_id, round_num=1)

    async def advance(
        self,
        connection_manager: ConnectionManager,
        graph_manager: GraphStateManager,
    ) -> int:
        """Advance to next round (max 3), broadcast new snapshot (D-09).

        B9: body is serialized behind self._lock to match start() and
        prevent concurrent mutation of _store / _round_num / _cycle_id.
        None of the awaited callees re-enter self._lock, so this is
        deadlock-safe.
        """
        async with self._lock:
            if not self.is_active or self._store is None:
                raise NoReplayActiveError("No replay active")
            if self._round_num >= 3:
                return self._round_num  # Already at max
            self._round_num += 1
            self._store.set_round(self._round_num)
            # Load bracket summaries and rationale entries for new round
            assert self._cycle_id is not None
            brackets = await graph_manager.read_bracket_narratives_for_round(self._cycle_id, self._round_num)
            bracket_summaries = tuple(
                BracketSummary(
                    bracket=b["bracket"],
                    display_name=b.get("display_name", b["bracket"]),
                    buy_count=b.get("buy_count", 0),
                    sell_count=b.get("sell_count", 0),
                    hold_count=b.get("hold_count", 0),
                    total=b.get("total", 0),
                    avg_confidence=b.get("avg_confidence", 0.0),
                    avg_sentiment=b.get("avg_sentiment", 0.0),
                )
                for b in brackets
            )
            self._store.set_bracket_summaries(bracket_summaries)
            rationales_raw = await graph_manager.read_rationale_entries_for_round(self._cycle_id, self._round_num)
            rationale_entries = tuple(
                RationaleEntry(
                    agent_id=r["agent_id"],
                    signal=r["signal"],
                    rationale=r["rationale"],
                    round_num=r["round_num"],
                )
                for r in rationales_raw
            )
            self._store.set_rationale_entries(rationale_entries)
            snap = self._store.snapshot()
            d = dataclasses.asdict(snap)
            connection_manager.broadcast(json.dumps(d))
            log.info("replay_advanced", cycle_id=self._cycle_id, round_num=self._round_num)
            return self._round_num

    async def stop(self) -> None:
        """Stop replay, reset to IDLE (D-10).

        B9: body is serialized behind self._lock to match start() and
        prevent races between concurrent stop() and advance() calls.
        state_store.set_phase uses its own internal lock, not ours, so
        this is deadlock-safe.
        """
        async with self._lock:
            self._store = None
            self._cycle_id = None
            self._round_num = 0
            self._seed_rumor = ""
            await self._app_state.state_store.set_phase(SimulationPhase.IDLE)
            log.info("replay_stopped")
