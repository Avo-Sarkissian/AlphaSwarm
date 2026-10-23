"""StateStore: mutable state container bridging the simulation and the web UI.

Simulation writes per-agent decisions and phase transitions. The WebSocket
broadcaster reads an immutable StateSnapshot every 200 ms.
"""

from __future__ import annotations

import asyncio
import itertools
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Final, Literal, Protocol

from alphaswarm.data_audit import DataSourceAuditBuffer, DataSourceAuditEntry
from alphaswarm.errors import RunError
from alphaswarm.types import SignalType, SimulationPhase

# Live TPS window (docs/DECISIONS.md#p10-d-05): tokens completed in the last
# TPS_WINDOW_SECONDS of wall-clock time, summed over every parallel call.
TPS_WINDOW_SECONDS: Final = 10.0

# One process-wide counter: every StateStore/ReplayStore mutation takes the next
# value, so a version is never reused, not even by a newer store; the
# broadcaster keys its frames on it (docs/DECISIONS.md#adr-ws-broadcaster).
_VERSIONS: Final = itertools.count(1)


@dataclass(frozen=True)
class GovernorMetrics:
    """Metrics emitted by ResourceGovernor on state transitions.

    Added in Phase 3 Plan 01 for governor -> StateStore metric wiring (D-09, D-11).
    """

    current_slots: int
    active_count: int
    pressure_level: str
    memory_percent: float
    governor_state: str
    timestamp: float


@dataclass(frozen=True)
class BracketSummary:
    """Per-bracket signal distribution and confidence for a single round (D-07, D-08).

    Moved from simulation.py to state.py in Phase 10 Plan 01 to avoid circular
    import: StateSnapshot needs BracketSummary, simulation.py imports StateStore.
    """

    bracket: str  # BracketType.value
    display_name: str
    buy_count: int
    sell_count: int
    hold_count: int
    total: int
    avg_confidence: float
    avg_sentiment: float


@dataclass(frozen=True)
class RationaleEntry:
    """Single agent rationale entry for the UI rationale feed (docs/DECISIONS.md#p10-d-03).

    In a live run, batch_dispatcher produces one for each decision except
    PARSE_ERROR as the agent resolves, and pushes it into StateStore's 50-entry
    sliding window (docs/DECISIONS.md#p10-d-02); replay builds them from stored
    decisions.
    Agent ID is the persona id (e.g. "quants_07"). The live producer truncates
    the rationale to 50 chars.
    """

    agent_id: str  # persona id, e.g. "quants_07"
    signal: SignalType  # BUY, SELL, HOLD for color-coding
    rationale: str  # truncated at 50 chars by producer
    round_num: int  # which round this came from
    # Stamped by StateStore.push_rationale: a process-lifetime monotonic sequence
    # and the wall-clock time. Replay numbers entries 1..n per round with ts 0.0.
    seq: int = 0
    ts: float = 0.0


@dataclass(frozen=True)
class AgentState:
    """Per-agent state for the live agent graph. Signal + confidence only."""

    signal: SignalType | None = None
    confidence: float = 0.0


JobKind = Literal["advisory", "report"]


@dataclass(frozen=True)
class JobStatus:
    """Status of one orchestrator job kind; idle/failed keep the last cycle id.

    The single source of truth for "is a report/advisory running" used by the
    route cross-guards and SimulationManager (docs/DECISIONS.md#adr-background-tasks).
    """

    state: Literal["idle", "running", "failed"] = "idle"
    cycle_id: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class JobsSnapshot:
    """Both job statuses at one instant."""

    advisory: JobStatus
    report: JobStatus


@dataclass(frozen=True)
class AppliedShock:
    """A shock that entered the prompts, and the round it was first applied before."""

    text: str
    round_num: int


_ROUND_OF_PHASE: Final[dict[SimulationPhase, int]] = {
    SimulationPhase.ROUND_1: 1,
    SimulationPhase.ROUND_2: 2,
    SimulationPhase.ROUND_3: 3,
}


@dataclass(frozen=True)
class StateSnapshot:
    """Immutable snapshot serialized by the WebSocket broadcaster."""

    phase: SimulationPhase = SimulationPhase.IDLE
    round_num: int = 0
    agent_count: int = 0  # len(roster); begin_run installs it at SEEDING
    agent_states: dict[str, AgentState] = field(default_factory=dict)
    elapsed_seconds: float = 0.0
    governor_metrics: GovernorMetrics | None = None
    tps: float = 0.0
    rationale_entries: tuple[RationaleEntry, ...] = ()
    bracket_summaries: tuple[BracketSummary, ...] = ()
    # ITEM 5 of quick task 260512-jqn — DataSourceAudit buffer surface.
    # Each entry is one provider call (yfinance / FRED / RSS / …). The
    # frontend SignalWire ticker reads this slice instead of the prior
    # DEV-only mock seed.
    data_source_audit: tuple[DataSourceAuditEntry, ...] = ()
    # Typed, UI-safe description of the last failed run; cleared when a new
    # run starts (docs/DECISIONS.md#adr-taskgroup-dispatch).
    last_error: RunError | None = None
    # Shock state; mapped onto the wire by web/wire.py:build_frame.
    pending_shock: str | None = None
    applied_shocks: tuple[AppliedShock, ...] = ()
    shock_window_open: bool = False
    # Run identity for the wire frame (docs/DECISIONS.md#adr-ws-broadcaster).
    cycle_id: str | None = None
    num_rounds: int = 3
    edges_version: int = 0
    jobs: JobsSnapshot = field(default_factory=lambda: JobsSnapshot(advisory=JobStatus(), report=JobStatus()))


class StateStore:
    """Mutable state container. Simulation writes, the broadcaster reads snapshots.

    Per D-02: per-agent writes happen immediately after each agent resolves.
    asyncio.Lock guards structural consistency (defensive, not strictly
    necessary for single-loop architecture but prevents future surprises).

    Phase 10 additions (docs/DECISIONS.md#p10-d-02, #p10-d-05, #p10-d-08):
    - _rationale_window: 50-entry sliding window for the rationale feed
    - _token_window: completion tokens finished in the last TPS_WINDOW_SECONDS (live TPS)
    - _bracket_summaries: latest round's bracket distribution for the bracket panel
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._agent_states: dict[str, AgentState] = {}
        self._phase: SimulationPhase = SimulationPhase.IDLE
        self._round_num: int = 0
        self._start_time: float | None = None
        self._final_elapsed: float | None = None
        self._latest_governor_metrics: GovernorMetrics | None = None
        # ITEM 4 of quick task 260512-jqn: rationale sliding window.
        # Replaces the prior asyncio.Queue (drain semantics) with a
        # bounded deque (peek semantics). Every snapshot() carries the
        # full window so the frontend feed populates progressively
        # during a round AND survives WS client reconnect (no drain,
        # no per-consumer race).
        self._rationale_window: deque[RationaleEntry] = deque(maxlen=50)
        # ITEM 5 of quick task 260512-jqn: data-provider audit buffer.
        # Replaces the SignalWire DEV mock seed with live provider calls.
        self._data_source_audit: DataSourceAuditBuffer = DataSourceAuditBuffer(
            max_entries=100,
        )
        # (monotonic time, completion tokens) for each finished call, kept for
        # TPS_WINDOW_SECONDS (docs/DECISIONS.md#p10-d-05).
        self._token_window: deque[tuple[float, int]] = deque()
        # Latest bracket summaries (docs/DECISIONS.md#p10-d-08)
        self._bracket_summaries: tuple[BracketSummary, ...] = ()
        self._last_error: RunError | None = None
        # Orchestrator job status (report/advisory). Not run-scoped: survives SEEDING.
        self._jobs: dict[JobKind, JobStatus] = {
            "advisory": JobStatus(),
            "report": JobStatus(),
        }
        # Shock state: num_rounds bounds the shock window and must be set before
        # SEEDING, which keeps it; applied shocks are run-scoped.
        self._num_rounds: int = 3
        self._pending_shock: str | None = None
        self._applied_shocks: list[AppliedShock] = []
        # Run identity (reset on SEEDING) and the rationale sequence (never reset).
        self._cycle_id: str | None = None
        self._edges_version: int = 0
        self._rationale_seq: int = 0
        self._version = next(_VERSIONS)

    @property
    def version(self) -> int:
        """Grows on every mutation; never reused by another store."""
        return self._version

    def _bump(self) -> None:
        self._version = next(_VERSIONS)

    async def update_agent_state(
        self,
        agent_id: str,
        signal: SignalType,
        confidence: float,
    ) -> None:
        """Write a single agent's decision. Called per-agent, not per-round (D-02)."""
        async with self._lock:
            self._agent_states[agent_id] = AgentState(signal=signal, confidence=confidence)
            self._bump()

    async def begin_run(self, agent_ids: Sequence[str]) -> None:
        """Install the canonical roster for a new run, in config order, all pending.

        Called by run_simulation right after set_phase(SEEDING). From then on
        every snapshot carries the same agents in the same order, each with
        signal=None until its first decision streams in, so the UI shows a
        stable, complete set of nodes from the first frame of a run
        (docs/DECISIONS.md#adr-streaming-state). Ids from a previous run that
        are not in the roster disappear; a duplicate id keeps its first position.
        """
        async with self._lock:
            self._agent_states = {
                agent_id: AgentState(signal=None, confidence=0.0) for agent_id in dict.fromkeys(agent_ids)
            }
            self._bump()

    async def set_phase(self, phase: SimulationPhase) -> None:
        """Update simulation phase. Resets agent signals to "thinking" on round transitions.

        Per WS broadcaster contract: keys MUST persist across round entries so the
        frontend renders dim/pulsing dots (signal=None) during the dispatch window
        instead of an empty graph. Streaming per-agent writes from
        batch_dispatcher._safe_agent_inference overwrite each placeholder as that
        agent's inference resolves. Supersedes the original D-05 "clean visual
        slate" intent which produced empty WS frames during 14-18min round
        dispatch on M1 Max.
        """
        async with self._lock:
            self._phase = phase
            # SEEDING marks the start of a NEW run: clear all run-scoped state
            # so a second simulation starts from a clean slate. Without this,
            # _final_elapsed from run 1 freezes the elapsed clock for every
            # subsequent run, TPS averages across runs, and the rationale feed
            # / bracket bars show stale run-1 data during run 2's first round.
            # Run-scoped: elapsed clock, TPS window, bracket summaries,
            # rationale window, cycle id, edges version, applied shocks, agent
            # signals, the data-source audit log.
            if phase == SimulationPhase.SEEDING:
                self._start_time = time.monotonic()
                self._final_elapsed = None
                self._token_window.clear()
                self._bracket_summaries = ()
                self._rationale_window.clear()
                self._data_source_audit.clear()
                self._cycle_id = None
                self._edges_version = 0
                self._applied_shocks.clear()
                # Not _num_rounds: it must be set before SEEDING, and a reset here
                # would reopen the shock window in the last round of a 2-round run.
                self._agent_states = {aid: AgentState(signal=None, confidence=0.0) for aid in self._agent_states}
            # Reset signals to "thinking" placeholder on round entry while preserving
            # dict keys so broadcaster snapshots stay non-empty during dispatch.
            if phase in (
                SimulationPhase.ROUND_1,
                SimulationPhase.ROUND_2,
                SimulationPhase.ROUND_3,
            ):
                self._agent_states = {aid: AgentState(signal=None, confidence=0.0) for aid in self._agent_states}
            # Start elapsed timer on first live phase. REPLAY is excluded: merely
            # viewing a replay must not start (or corrupt) the live-run clock.
            if self._start_time is None and phase not in (
                SimulationPhase.IDLE,
                SimulationPhase.REPLAY,
            ):
                self._start_time = time.monotonic()
            # Freeze elapsed timer on COMPLETE
            if phase == SimulationPhase.COMPLETE and self._start_time is not None:
                self._final_elapsed = time.monotonic() - self._start_time
            self._bump()

    async def set_round(self, round_num: int) -> None:
        """Update the current round number."""
        async with self._lock:
            self._round_num = round_num
            self._bump()

    async def set_cycle(self, cycle_id: str | None) -> None:
        """Record the cycle being simulated (called right after inject_seed)."""
        async with self._lock:
            self._cycle_id = cycle_id
            self._bump()

    def bump_edges_version(self) -> None:
        """Count one finished influence-edge step for the current cycle."""
        self._edges_version += 1
        self._bump()

    async def push_rationale(self, entry: RationaleEntry) -> None:
        """Append a rationale entry, stamped with ``seq`` and ``ts``, to the window (maxlen=50).

        ITEM 4 of quick task 260512-jqn: replaced drain semantics with peek
        semantics. The deque silently drops the oldest entry when full, so
        every snapshot() — and therefore every WS broadcast — carries the
        most recent 50 entries. Multiple consumers (WS broadcaster,
        reconnecting clients) all see the same window without racing each
        other for queue items.

        Method stays async to preserve the existing call-site signature in
        simulation.py / batch_dispatcher.py; deque.append is O(1) and the
        GIL keeps it consistent under the StateStore's single-loop usage.
        """
        self._rationale_seq += 1
        self._rationale_window.append(replace(entry, seq=self._rationale_seq, ts=time.time()))
        self._bump()

    def record_tokens(self, completion_tokens: int, *, now: float | None = None) -> None:
        """Count one finished call's completion tokens for the live TPS tile.

        TPS is the tokens finished in the last TPS_WINDOW_SECONDS divided by the
        window, so four parallel streams show four times one stream's rate
        (docs/DECISIONS.md#p10-d-05). ``now`` (monotonic seconds) is for tests.
        """
        if completion_tokens <= 0:
            return
        stamp = time.monotonic() if now is None else now
        self._token_window.append((stamp, completion_tokens))
        self._prune_token_window(stamp)
        self._bump()

    def _prune_token_window(self, now: float) -> None:
        cutoff = now - TPS_WINDOW_SECONDS
        while self._token_window and self._token_window[0][0] <= cutoff:
            self._token_window.popleft()

    async def set_bracket_summaries(self, summaries: tuple[BracketSummary, ...]) -> None:
        """Store bracket summaries after each round completes (docs/DECISIONS.md#p10-d-08).

        Called by rounds.run_round after compute_bracket_summaries() for each round.
        """
        async with self._lock:
            self._bracket_summaries = summaries
            self._bump()

    async def set_last_error(self, err: RunError | None) -> None:
        """Record (or clear, with None) the error that ended the last run."""
        async with self._lock:
            self._last_error = err
            self._bump()

    @property
    def last_error(self) -> RunError | None:
        """The error that ended the last run, or None."""
        return self._last_error

    def _compute_tps(self) -> float:
        """Tokens per second over the sliding window (0.0 when idle)."""
        self._prune_token_window(time.monotonic())
        return round(sum(tokens for _, tokens in self._token_window) / TPS_WINDOW_SECONDS, 1)

    def snapshot(self) -> StateSnapshot:
        """Return immutable snapshot of current state.

        No lock needed for read -- dict copy is atomic enough at 200ms polling granularity.

        ITEM 4 of quick task 260512-jqn: snapshot now carries the full
        rationale sliding window (peek, no drain) so every WS frame
        contains the latest 50 entries.
        """
        return StateSnapshot(
            phase=self._phase,
            round_num=self._round_num,
            agent_count=len(self._agent_states),
            agent_states=dict(self._agent_states),
            elapsed_seconds=(
                self._final_elapsed
                if self._final_elapsed is not None
                else (time.monotonic() - self._start_time if self._start_time else 0.0)
            ),
            governor_metrics=self._latest_governor_metrics,
            tps=self._compute_tps(),
            rationale_entries=tuple(self._rationale_window),
            bracket_summaries=self._bracket_summaries,
            data_source_audit=self._data_source_audit.snapshot(),
            last_error=self._last_error,
            pending_shock=self._pending_shock,
            applied_shocks=tuple(self._applied_shocks),
            shock_window_open=self.shock_window_open(),
            cycle_id=self._cycle_id,
            num_rounds=self._num_rounds,
            edges_version=self._edges_version,
            jobs=self.job_statuses(),
        )

    def peek_rationales(self) -> tuple[RationaleEntry, ...]:
        """Return the full rationale sliding window (peek, no drain).

        ITEM 4 of 260512-jqn: replaces the prior drain_rationales(limit)
        destructive read. Same data is also embedded directly in the
        StateSnapshot returned by snapshot().
        """
        return tuple(self._rationale_window)

    @property
    def governor_metrics(self) -> GovernorMetrics | None:
        """Return the latest governor metrics, or None if never emitted."""
        return self._latest_governor_metrics

    def update_governor_metrics(self, metrics: GovernorMetrics) -> None:
        """Store latest governor metrics."""
        self._latest_governor_metrics = metrics
        self._bump()

    def set_job_status(self, kind: JobKind, status: JobStatus) -> None:
        """Record the advisory or report job status (sync: called from done-callbacks)."""
        self._jobs[kind] = status
        self._bump()

    def job_statuses(self) -> JobsSnapshot:
        """Return both job statuses."""
        return JobsSnapshot(advisory=self._jobs["advisory"], report=self._jobs["report"])

    def set_num_rounds(self, n: int) -> None:
        """Record the run's round count, which bounds the shock window.

        Call it before SEEDING; SEEDING keeps it. Until it is called the window
        assumes 3 rounds.
        """
        self._num_rounds = n
        self._bump()

    def set_pending_shock(self, text: str | None) -> None:
        """Record the shock queued for the next round, or None when none is queued.

        The store does not watch the shock queue: pending_shock shows only what
        the queue's owner last passed here.
        """
        self._pending_shock = text
        self._bump()

    def record_applied_shock(self, text: str, round_num: int) -> None:
        """Record a shock that was applied before *round_num*."""
        self._applied_shocks.append(AppliedShock(text=text, round_num=round_num))
        self._bump()

    def shock_window_open(self) -> bool:
        """True while a queued shock can still reach a later round.

        Open during SEEDING and during ROUND_k while k < num_rounds; closed once
        the last gated round has started, and in FINALIZING, COMPLETE, IDLE and
        REPLAY. The phase number, not round_num, is used so the window closes at
        the same instant the runner moves to the last round.
        """
        if self._phase == SimulationPhase.SEEDING:
            return True
        current = _ROUND_OF_PHASE.get(self._phase)
        return current is not None and current < self._num_rounds

    # ------------------------------------------------------------------
    # ITEM 5 of quick task 260512-jqn — data-provider audit pass-through
    # ------------------------------------------------------------------

    def record_data_source(
        self,
        source: str,
        query: str,
        result: str,
        used: bool = False,
    ) -> None:
        """Record one data-provider call into the audit buffer.

        Cheap O(1) call, safe from any context (sync or async). Provider
        modules invoke this after each yfinance/FRED/RSS fetch so the WS
        SignalWire ticker scrolls live activity.
        """
        self._data_source_audit.record(
            source=source,
            query=query,
            result=result,
            used=used,
        )
        self._bump()

    def peek_data_source_audit(self) -> tuple[DataSourceAuditEntry, ...]:
        """Return the full audit buffer (peek, no drain)."""
        return self._data_source_audit.snapshot()


class ReplayStore:
    """Read-only store for replay mode. Feeds StateSnapshot to the broadcaster.

    snapshot() has no side effects, as in StateStore. Rationale entries and
    bracket summaries are set once per round transition, not accumulated over
    time.
    """

    def __init__(
        self,
        cycle_id: str,
        signals: dict[tuple[str, int], AgentState],
        *,
        num_rounds: int = 3,
    ) -> None:
        self._cycle_id = cycle_id
        self._num_rounds = num_rounds
        self._signals = signals
        self._current_round: int = 0
        self._bracket_summaries: tuple[BracketSummary, ...] = ()
        self._rationale_entries: tuple[RationaleEntry, ...] = ()
        self._version = next(_VERSIONS)

    @property
    def version(self) -> int:
        """Grows on every setter call; never reused by another store."""
        return self._version

    def _bump(self) -> None:
        self._version = next(_VERSIONS)

    @property
    def cycle_id(self) -> str:
        """The cycle being replayed."""
        return self._cycle_id

    def set_round(self, round_num: int) -> None:
        """Set the active round for snapshot filtering."""
        self._current_round = round_num
        self._bump()

    def set_bracket_summaries(self, summaries: tuple[BracketSummary, ...]) -> None:
        """Replace bracket summaries (called once per round transition)."""
        self._bracket_summaries = summaries
        self._bump()

    def set_rationale_entries(self, entries: tuple[RationaleEntry, ...]) -> None:
        """Replace rationale entries (called once per round transition, no drain)."""
        self._rationale_entries = entries
        self._bump()

    def snapshot(self) -> StateSnapshot:
        """Return immutable snapshot for the active round.

        No side effects -- calling snapshot() twice returns identical data
        (StateStore keeps a sliding window instead; neither store drains).
        """
        agent_states = {
            agent_id: state for (agent_id, rnd), state in self._signals.items() if rnd == self._current_round
        }
        return StateSnapshot(
            phase=SimulationPhase.REPLAY,
            round_num=self._current_round,
            agent_count=len(agent_states),
            agent_states=agent_states,
            elapsed_seconds=0.0,
            governor_metrics=None,
            tps=0.0,
            rationale_entries=self._rationale_entries,
            bracket_summaries=self._bracket_summaries,
            data_source_audit=(),
            cycle_id=self._cycle_id,
            num_rounds=self._num_rounds,
            # A replayed cycle is complete, so round r's edges exist once r >= 2.
            edges_version=max(0, self._current_round - 1),
        )


class StateSink(Protocol):
    """What the engine writes to live state (docs/DECISIONS.md#adr-round-runner).

    Exactly the StateStore methods run_simulation, run_round, dispatch_wave and
    AgentWorker call. Web-side calls (set_last_error, set_pending_shock,
    set_job_status) are deliberately not part of it; a plan that adds an
    engine -> store call extends this protocol.
    """

    async def set_phase(self, phase: SimulationPhase) -> None: ...

    async def set_round(self, round_num: int) -> None: ...

    async def update_agent_state(self, agent_id: str, signal: SignalType, confidence: float) -> None: ...

    async def push_rationale(self, entry: RationaleEntry) -> None: ...

    async def set_bracket_summaries(self, summaries: tuple[BracketSummary, ...]) -> None: ...

    def record_tokens(self, completion_tokens: int, *, now: float | None = None) -> None: ...

    async def set_cycle(self, cycle_id: str | None) -> None: ...

    def set_num_rounds(self, n: int) -> None: ...

    def bump_edges_version(self) -> None: ...

    async def begin_run(self, agent_ids: Sequence[str]) -> None: ...

    def record_applied_shock(self, text: str, round_num: int) -> None: ...


if TYPE_CHECKING:

    def _store_is_a_sink(store: StateStore) -> StateSink:
        return store  # mypy proves StateStore satisfies StateSink
