"""ReplayManager: one replay session at a time over a ReplayStore.

A round is read from Neo4j first and then shown in one synchronous step, so the
5 Hz broadcaster never streams a half-loaded round
(docs/DECISIONS.md#adr-replaystore-separate).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from alphaswarm.personas import DEFAULT_BRACKETS
from alphaswarm.state import BracketSummary, RationaleEntry, ReplayStore
from alphaswarm.types import SignalType

if TYPE_CHECKING:
    from alphaswarm.app import AppState
    from alphaswarm.graph import BracketRoundRow, GraphStateManager, RationaleRoundRow
    from alphaswarm.state import AgentState

log = structlog.get_logger(component="web.replay_manager")


class ReplayAlreadyActiveError(Exception):
    """Raised when start() is called while a replay is already active."""


class NoReplayActiveError(Exception):
    """Raised when advance/stop called with no active replay."""


class SimulationActiveError(Exception):
    """Raised when start() is called while a live simulation is running.

    Closes the TOCTOU window between the route-level sim_manager.is_running
    check and the actual replay start: the route check happens before an
    awaited Neo4j read, during which a simulation could start.
    """


def _empty_or_row_summary(
    bracket: str,
    display_name: str,
    row: BracketRoundRow | None,
) -> BracketSummary:
    if row is None:
        return BracketSummary(
            bracket=bracket,
            display_name=display_name,
            buy_count=0,
            sell_count=0,
            hold_count=0,
            total=0,
            avg_confidence=0.0,
            avg_sentiment=0.0,
        )
    return BracketSummary(
        bracket=bracket,
        display_name=display_name,
        buy_count=row["buy_count"],
        sell_count=row["sell_count"],
        hold_count=row["hold_count"],
        total=row["total"],
        avg_confidence=row["avg_confidence"],
        avg_sentiment=row["avg_sentiment"],
    )


def _bracket_summaries_from_rows(rows: Sequence[BracketRoundRow]) -> tuple[BracketSummary, ...]:
    """Every configured bracket in config order, like the live frame.

    Brackets that are not in DEFAULT_BRACKETS (pre-v2 cycles) are appended
    with their raw key as the display name, so no decisions disappear.
    """
    by_key = {row["bracket"]: row for row in rows}
    summaries = [
        _empty_or_row_summary(
            b.bracket_type.value,
            b.display_name,
            by_key.pop(b.bracket_type.value, None),
        )
        for b in DEFAULT_BRACKETS
    ]
    summaries.extend(_empty_or_row_summary(key, key, by_key[key]) for key in sorted(by_key))
    return tuple(summaries)


def _rationale_entries_from_rows(rows: Sequence[RationaleRoundRow]) -> tuple[RationaleEntry, ...]:
    """Typed entries for one replayed round, numbered 1..n; replay has no wall-clock time."""
    return tuple(
        RationaleEntry(
            agent_id=row["agent_id"],
            signal=SignalType(row["signal"]),
            rationale=row["rationale"],
            round_num=row["round_num"],
            seq=seq,
            ts=0.0,
        )
        for seq, row in enumerate(rows, start=1)
    )


@dataclass(frozen=True)
class _RoundRows:
    """One replay round's panels, read before anything on screen changes."""

    bracket_summaries: tuple[BracketSummary, ...]
    rationale_entries: tuple[RationaleEntry, ...]


async def _load_round(graph_manager: GraphStateManager, cycle_id: str, round_num: int) -> _RoundRows:
    """Read round *round_num* of *cycle_id*. Raises on a failed read and changes nothing.

    The reads run one after the other: a TaskGroup would wrap a
    Neo4jUnavailableError in an ExceptionGroup, so the API's 503 mapping would
    no longer apply.
    """
    brackets = await graph_manager.read_bracket_narratives_for_round(cycle_id, round_num)
    rationales = await graph_manager.read_rationale_entries_for_round(cycle_id, round_num)
    return _RoundRows(
        bracket_summaries=_bracket_summaries_from_rows(brackets),
        rationale_entries=_rationale_entries_from_rows(rationales),
    )


class ReplayManager:
    """One replay session at a time, serialised by an asyncio.Lock.

    Created in the FastAPI lifespan (docs/DECISIONS.md#p34-d-07). Holds the
    active ReplayStore, its cycle id and the round on screen.
    """

    def __init__(self, app_state: AppState) -> None:
        self._app_state = app_state
        self._lock = asyncio.Lock()
        self._store: ReplayStore | None = None
        self._cycle_id: str | None = None
        self._round_num: int = 0
        self._max_rounds: int = 3
        self._starting: bool = False
        # Set by the lifespan once SimulationManager exists, so start() can
        # re-check for a live run under its own lock.
        self._sim_running_check: Callable[[], bool] | None = None

    def set_sim_running_check(self, check: Callable[[], bool]) -> None:
        """Wire the SimulationManager.is_running probe (called from lifespan)."""
        self._sim_running_check = check

    @property
    def is_active(self) -> bool:
        """True when a replay session is active OR mid-start.

        _starting counts as active so SimulationManager's replay-active guard
        blocks a live-sim start during the awaited Neo4j loads inside start().
        """
        return self._store is not None or self._starting

    @property
    def has_store(self) -> bool:
        """True only when the ReplayStore is committed and queryable.

        Distinct from is_active, which is True during the _starting window
        (before _store is committed). The broadcaster must gate on this, not
        is_active, or it calls store.snapshot() while _store is still None and
        raises NoReplayActiveError on every tick during replay start-up (docs/DECISIONS.md#f-24).
        """
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

    @staticmethod
    def _show(store: ReplayStore, round_num: int, rows: _RoundRows) -> None:
        """Switch *store* to a fully read round. Synchronous, so no frame interleaves."""
        store.set_round(round_num)
        store.set_bracket_summaries(rows.bracket_summaries)
        store.set_rationale_entries(rows.rationale_entries)

    async def start(
        self,
        cycle_id: str,
        signals: dict[tuple[str, int], AgentState],
        graph_manager: GraphStateManager,
    ) -> None:
        """Start a replay of *cycle_id* on round 1 (docs/DECISIONS.md#p34-d-08).

        Round 1 is read before anything is committed, so a failed read leaves
        the manager inactive. While the read is pending, ``_starting`` keeps
        ``is_active`` true so a live simulation cannot start
        (docs/DECISIONS.md#b4). The broadcaster shows the store on its next
        tick; the live phase is left alone (docs/DECISIONS.md#adr-replaystore-separate).
        """
        async with self._lock:
            if self.is_active:
                raise ReplayAlreadyActiveError("Replay already active")
            if self._sim_running_check is not None and self._sim_running_check():
                raise SimulationActiveError("Cannot start replay while a simulation is running")
            self._starting = True
            try:
                rows = await _load_round(graph_manager, cycle_id, 1)
                # Signals are keyed (agent_id, round); a 2-round cycle never
                # advances to an empty round 3 (docs/DECISIONS.md#f-12).
                max_rounds = max((rnd for (_, rnd) in signals), default=1)
                store = ReplayStore(cycle_id, signals, num_rounds=max_rounds)
                self._show(store, 1, rows)
                self._store = store
                self._cycle_id = cycle_id
                self._round_num = 1
                self._max_rounds = max_rounds
            finally:
                self._starting = False
        log.info("replay_started", cycle_id=cycle_id, round_num=1)

    async def advance(self, graph_manager: GraphStateManager) -> int:
        """Show the next round and return its number (docs/DECISIONS.md#p34-d-09).

        The next round is read first and committed in one synchronous step, so
        frames never mix two rounds and a failed read leaves the current round
        on screen; calling advance again retries the same round. Serialised with
        start() and stop() by the lock (docs/DECISIONS.md#b9).
        """
        async with self._lock:
            store, cycle_id = self._store, self._cycle_id
            if store is None or cycle_id is None:
                raise NoReplayActiveError("No replay active")
            if self._round_num >= self._max_rounds:
                return self._round_num
            next_round = self._round_num + 1
            rows = await _load_round(graph_manager, cycle_id, next_round)
            self._show(store, next_round, rows)
            self._round_num = next_round
        log.info("replay_advanced", cycle_id=cycle_id, round_num=next_round)
        return next_round

    async def stop(self) -> None:
        """End the replay; the live phase is untouched (docs/DECISIONS.md#p34-d-10)."""
        async with self._lock:
            self._store = None
            self._cycle_id = None
            self._round_num = 0
            self._max_rounds = 3
        log.info("replay_stopped")
