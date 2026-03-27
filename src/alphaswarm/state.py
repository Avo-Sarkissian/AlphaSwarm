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


class StateStore:
    """Mutable state container. Simulation writes, TUI reads snapshots.

    Per D-02: per-agent writes happen immediately after each agent resolves.
    asyncio.Lock guards structural consistency (defensive, not strictly
    necessary for single-loop architecture but prevents future surprises).
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._agent_states: dict[str, AgentState] = {}
        self._phase: SimulationPhase = SimulationPhase.IDLE
        self._round_num: int = 0
        self._start_time: float | None = None
        self._latest_governor_metrics: GovernorMetrics | None = None

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

    async def set_round(self, round_num: int) -> None:
        """Update the current round number."""
        async with self._lock:
            self._round_num = round_num

    def snapshot(self) -> StateSnapshot:
        """Return immutable snapshot of current state.

        No lock needed for read -- dict copy is atomic enough at 200ms polling granularity.
        """
        return StateSnapshot(
            phase=self._phase,
            round_num=self._round_num,
            agent_count=100,
            agent_states=dict(self._agent_states),
            elapsed_seconds=time.monotonic() - self._start_time if self._start_time else 0.0,
            governor_metrics=self._latest_governor_metrics,
        )

    @property
    def governor_metrics(self) -> GovernorMetrics | None:
        """Return the latest governor metrics, or None if never emitted."""
        return self._latest_governor_metrics

    def update_governor_metrics(self, metrics: GovernorMetrics) -> None:
        """Store latest governor metrics."""
        self._latest_governor_metrics = metrics
