"""StateStore stub for Phase 1. Full implementation in Phase 9."""

from __future__ import annotations

from dataclasses import dataclass

from alphaswarm.types import SimulationPhase


@dataclass(frozen=True)
class StateSnapshot:
    """Immutable snapshot for TUI consumption. Full fields added in Phase 9."""

    phase: SimulationPhase = SimulationPhase.IDLE
    round_num: int = 0
    agent_count: int = 100


class StateStore:
    """Stub StateStore for Phase 1. Full implementation in Phase 9.

    In Phase 9, this will hold mutable state with asyncio.Lock guarded writes.
    TUI reads immutable StateSnapshot on 200ms timer.
    """

    def snapshot(self) -> StateSnapshot:
        """Return immutable snapshot of current state."""
        return StateSnapshot()
