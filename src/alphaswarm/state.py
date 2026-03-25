"""StateStore stub for Phase 1. Full implementation in Phase 9."""

from __future__ import annotations

from dataclasses import dataclass, field

from alphaswarm.types import SimulationPhase


@dataclass(frozen=True)
class StateSnapshot:
    """Immutable snapshot for TUI consumption. Full fields added in Phase 9."""

    phase: SimulationPhase = SimulationPhase.IDLE
    round_num: int = 0
    agent_count: int = 100


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


class StateStore:
    """Stub StateStore for Phase 1. Full implementation in Phase 9.

    In Phase 9, this will hold mutable state with asyncio.Lock guarded writes.
    TUI reads immutable StateSnapshot on 200ms timer.
    """

    def __init__(self) -> None:
        self._latest_governor_metrics: GovernorMetrics | None = None

    def snapshot(self) -> StateSnapshot:
        """Return immutable snapshot of current state."""
        return StateSnapshot()

    def update_governor_metrics(self, metrics: GovernorMetrics) -> None:
        """Store latest governor metrics. Full implementation in Phase 9."""
        self._latest_governor_metrics = metrics
