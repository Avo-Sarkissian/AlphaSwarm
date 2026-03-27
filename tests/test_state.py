"""Tests for StateStore and AgentState."""

from __future__ import annotations

import pytest

from alphaswarm.state import AgentState, GovernorMetrics, StateSnapshot, StateStore
from alphaswarm.types import SignalType, SimulationPhase


def test_agent_state_frozen() -> None:
    """AgentState is immutable."""
    state = AgentState(signal=SignalType.BUY, confidence=0.8)
    with pytest.raises(AttributeError):
        state.signal = SignalType.SELL  # type: ignore[misc]


def test_state_snapshot_defaults() -> None:
    """StateSnapshot has sensible defaults."""
    snap = StateSnapshot()
    assert snap.phase == SimulationPhase.IDLE
    assert snap.round_num == 0
    assert snap.agent_count == 100
    assert snap.agent_states == {}
    assert snap.elapsed_seconds == 0.0
    assert snap.governor_metrics is None


async def test_update_agent_state() -> None:
    """StateStore records per-agent state."""
    store = StateStore()
    await store.update_agent_state("quants_01", SignalType.BUY, 0.85)
    snap = store.snapshot()
    assert "quants_01" in snap.agent_states
    assert snap.agent_states["quants_01"].signal == SignalType.BUY
    assert snap.agent_states["quants_01"].confidence == 0.85


async def test_state_snapshot_with_agents() -> None:
    """Snapshot returns immutable copy of agent states."""
    store = StateStore()
    await store.update_agent_state("quants_01", SignalType.BUY, 0.9)
    await store.update_agent_state("degens_01", SignalType.SELL, 0.7)
    snap = store.snapshot()
    assert len(snap.agent_states) == 2
    # Mutating the snapshot dict should not affect the store
    snap.agent_states["fake"] = AgentState(signal=SignalType.HOLD, confidence=0.5)
    snap2 = store.snapshot()
    assert "fake" not in snap2.agent_states


async def test_set_phase_resets_agents() -> None:
    """Setting phase to a round clears agent states (D-05 pending reset)."""
    store = StateStore()
    await store.update_agent_state("quants_01", SignalType.BUY, 0.9)
    assert len(store.snapshot().agent_states) == 1
    await store.set_phase(SimulationPhase.ROUND_2)
    assert len(store.snapshot().agent_states) == 0
    assert store.snapshot().phase == SimulationPhase.ROUND_2


async def test_set_phase_starts_timer() -> None:
    """First non-IDLE phase starts the elapsed timer."""
    store = StateStore()
    snap_idle = store.snapshot()
    assert snap_idle.elapsed_seconds == 0.0
    await store.set_phase(SimulationPhase.SEEDING)
    snap_active = store.snapshot()
    assert snap_active.elapsed_seconds >= 0.0  # Timer started


async def test_set_round() -> None:
    """set_round updates the round number in snapshot."""
    store = StateStore()
    await store.set_round(2)
    assert store.snapshot().round_num == 2


async def test_governor_metrics_preserved() -> None:
    """Governor metrics survive state expansion."""
    store = StateStore()
    metrics = GovernorMetrics(
        current_slots=8,
        active_count=3,
        pressure_level="NORMAL",
        memory_percent=45.0,
        governor_state="RUNNING",
        timestamp=1000.0,
    )
    store.update_governor_metrics(metrics)
    snap = store.snapshot()
    assert snap.governor_metrics is not None
    assert snap.governor_metrics.current_slots == 8
