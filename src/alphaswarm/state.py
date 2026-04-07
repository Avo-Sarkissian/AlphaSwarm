"""StateStore: mutable state container for simulation -> TUI bridge.

Simulation writes per-agent decisions and phase transitions.
TUI reads immutable StateSnapshot on 200ms timer.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from alphaswarm.types import SignalType, SimulationPhase


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

    bracket: str          # BracketType.value
    display_name: str
    buy_count: int
    sell_count: int
    hold_count: int
    total: int
    avg_confidence: float
    avg_sentiment: float


@dataclass(frozen=True)
class TickerConsensus:
    """Per-ticker consensus aggregation for TUI display (Phase 19, D-05).

    majority_pct is stored as a fraction 0.0-1.0 (not 0-100 percentage).
    The display layer converts to percentage for rendering.
    """

    ticker: str
    round_num: int
    weighted_signal: str      # "BUY" / "SELL" / "HOLD"
    weighted_score: float     # 0.0-1.0 (normalized weighted sum for winning direction)
    majority_signal: str      # "BUY" / "SELL" / "HOLD"
    majority_pct: float       # 0.0-1.0 (fraction of valid votes for majority signal)
    bracket_breakdown: tuple[BracketSummary, ...]


@dataclass(frozen=True)
class RationaleEntry:
    """Single agent rationale entry for the TUI rationale sidebar (D-03, D-04, TUI-03).

    Produced by simulation.py after each round and pushed to StateStore queue.
    Agent ID is a short identifier (e.g. "A_42"). Rationale is truncated to
    50 chars by the producer per D-03.
    """

    agent_id: str        # e.g. "A_42" -- short agent ID
    signal: SignalType   # BUY, SELL, HOLD for color-coding
    rationale: str       # truncated at 50 chars by producer
    round_num: int       # which round this came from


@dataclass(frozen=True)
class AgentState:
    """Per-agent state for TUI grid rendering. Signal + confidence only."""

    signal: SignalType | None = None
    confidence: float = 0.0


@dataclass(frozen=True)
class StateSnapshot:
    """Immutable snapshot for TUI consumption."""

    phase: SimulationPhase = SimulationPhase.IDLE
    round_num: int = 0
    agent_count: int = 100
    agent_states: dict[str, AgentState] = field(default_factory=dict)
    elapsed_seconds: float = 0.0
    governor_metrics: GovernorMetrics | None = None
    tps: float = 0.0
    rationale_entries: tuple[RationaleEntry, ...] = ()
    bracket_summaries: tuple[BracketSummary, ...] = ()
    ticker_consensus: tuple[TickerConsensus, ...] = ()


class StateStore:
    """Mutable state container. Simulation writes, TUI reads snapshots.

    Per D-02: per-agent writes happen immediately after each agent resolves.
    asyncio.Lock guards structural consistency (defensive, not strictly
    necessary for single-loop architecture but prevents future surprises).

    Phase 10 additions (TUI-03, TUI-04, TUI-05):
    - _rationale_queue: asyncio.Queue[RationaleEntry] for rationale sidebar
    - _cumulative_tokens/_cumulative_eval_ns: TPS accumulation from Ollama metadata
    - _bracket_summaries: latest round's bracket distribution for bracket panel
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._agent_states: dict[str, AgentState] = {}
        self._phase: SimulationPhase = SimulationPhase.IDLE
        self._round_num: int = 0
        self._start_time: float | None = None
        self._final_elapsed: float | None = None
        self._latest_governor_metrics: GovernorMetrics | None = None
        # Phase 10: TUI-03 rationale sidebar queue (maxsize=50, drops oldest on overflow)
        self._rationale_queue: asyncio.Queue[RationaleEntry] = asyncio.Queue(maxsize=50)
        # Phase 10: TUI-04 TPS accumulation from Ollama response metadata
        self._cumulative_tokens: int = 0
        self._cumulative_eval_ns: int = 0
        # Phase 10: TUI-05 bracket summaries storage
        self._bracket_summaries: tuple[BracketSummary, ...] = ()
        # Phase 19: Per-ticker consensus storage
        self._ticker_consensus: tuple[TickerConsensus, ...] = ()

    async def update_agent_state(
        self,
        agent_id: str,
        signal: SignalType,
        confidence: float,
    ) -> None:
        """Write a single agent's decision. Called per-agent, not per-round (D-02)."""
        async with self._lock:
            self._agent_states[agent_id] = AgentState(signal=signal, confidence=confidence)

    async def set_phase(self, phase: SimulationPhase) -> None:
        """Update simulation phase. Resets agent states on round transitions (D-05)."""
        async with self._lock:
            self._phase = phase
            # Reset agent states to pending at each round start for clean visual slate
            if phase in (
                SimulationPhase.ROUND_1,
                SimulationPhase.ROUND_2,
                SimulationPhase.ROUND_3,
            ):
                self._agent_states.clear()
            # Start elapsed timer on first non-IDLE phase
            if self._start_time is None and phase != SimulationPhase.IDLE:
                self._start_time = time.monotonic()
            # Freeze elapsed timer on COMPLETE
            if phase == SimulationPhase.COMPLETE and self._start_time is not None:
                self._final_elapsed = time.monotonic() - self._start_time

    async def set_round(self, round_num: int) -> None:
        """Update the current round number."""
        async with self._lock:
            self._round_num = round_num

    async def push_rationale(self, entry: RationaleEntry) -> None:
        """Push rationale entry to queue. Drops oldest if full (non-blocking).

        Queue maxsize=50. When full, the oldest entry is discarded to make room
        for the newest. Single-consumer pattern: TUI drains via snapshot().
        """
        try:
            self._rationale_queue.put_nowait(entry)
        except asyncio.QueueFull:
            try:
                self._rationale_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._rationale_queue.put_nowait(entry)

    def update_tps(self, eval_count: int, eval_duration_ns: int) -> None:
        """Accumulate TPS from Ollama response metadata (D-05, TUI-04).

        Called by AgentWorker.infer() after each successful inference.
        GIL protects int addition -- no asyncio.Lock needed for this hot-path call.

        Args:
            eval_count: Number of tokens evaluated (response.eval_count).
            eval_duration_ns: Evaluation duration in nanoseconds (response.eval_duration).
        """
        self._cumulative_tokens += eval_count
        self._cumulative_eval_ns += eval_duration_ns

    async def set_bracket_summaries(self, summaries: tuple[BracketSummary, ...]) -> None:
        """Store bracket summaries after each round completes (D-08, TUI-05).

        Called by simulation.py after compute_bracket_summaries() for each round.
        """
        async with self._lock:
            self._bracket_summaries = summaries

    async def set_ticker_consensus(self, consensus: tuple[TickerConsensus, ...]) -> None:
        """Store ticker consensus after each round completes (Phase 19, D-07)."""
        async with self._lock:
            self._ticker_consensus = consensus

    def _compute_tps(self) -> float:
        """Compute running tokens-per-second from accumulated values."""
        if self._cumulative_eval_ns <= 0:
            return 0.0
        return self._cumulative_tokens / (self._cumulative_eval_ns / 1e9)

    def snapshot(self) -> StateSnapshot:
        """Return immutable snapshot of current state.

        No lock needed for read -- dict copy is atomic enough at 200ms polling granularity.

        Side effect: drains up to 5 rationale entries from the queue per call.
        This is intentional -- the TUI consumes entries in batches of 5 per 200ms tick.
        Documented side effect per Phase 10 decision D-04.
        """
        entries: list[RationaleEntry] = []
        for _ in range(5):
            try:
                entries.append(self._rationale_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return StateSnapshot(
            phase=self._phase,
            round_num=self._round_num,
            agent_count=100,
            agent_states=dict(self._agent_states),
            elapsed_seconds=(
                self._final_elapsed
                if self._final_elapsed is not None
                else (time.monotonic() - self._start_time if self._start_time else 0.0)
            ),
            governor_metrics=self._latest_governor_metrics,
            tps=self._compute_tps(),
            rationale_entries=tuple(entries),
            bracket_summaries=self._bracket_summaries,
            ticker_consensus=self._ticker_consensus,
        )

    @property
    def governor_metrics(self) -> GovernorMetrics | None:
        """Return the latest governor metrics, or None if never emitted."""
        return self._latest_governor_metrics

    def update_governor_metrics(self, metrics: GovernorMetrics) -> None:
        """Store latest governor metrics."""
        self._latest_governor_metrics = metrics
