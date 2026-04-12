"""Tests for StateStore and AgentState."""

from __future__ import annotations

import pytest

from alphaswarm.state import (
    AgentState,
    BracketSummary,
    GovernorMetrics,
    RationaleEntry,
    ReplayStore,
    StateSnapshot,
    StateStore,
)
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


# ---------------------------------------------------------------------------
# Task 1 Tests: RationaleEntry, TPS accumulation, BracketSummary storage
# ---------------------------------------------------------------------------


def test_rationale_entry_frozen() -> None:
    """RationaleEntry is an immutable frozen dataclass."""
    entry = RationaleEntry(
        agent_id="A_42",
        signal=SignalType.BUY,
        rationale="Strong earnings beat expectations",
        round_num=1,
    )
    assert entry.agent_id == "A_42"
    assert entry.signal == SignalType.BUY
    assert entry.rationale == "Strong earnings beat expectations"
    assert entry.round_num == 1
    with pytest.raises(AttributeError):
        entry.agent_id = "A_99"  # type: ignore[misc]


async def test_rationale_queue_drain() -> None:
    """Push 7 entries; snapshot drains 5 first call, 2 second call."""
    store = StateStore()
    for i in range(7):
        await store.push_rationale(
            RationaleEntry(agent_id=f"A_{i}", signal=SignalType.BUY, rationale="test", round_num=1)
        )
    snap1 = store.snapshot()
    assert len(snap1.rationale_entries) == 5
    snap2 = store.snapshot()
    assert len(snap2.rationale_entries) == 2


async def test_rationale_queue_empty_drain() -> None:
    """No entries pushed; snapshot rationale_entries is empty tuple."""
    store = StateStore()
    snap = store.snapshot()
    assert snap.rationale_entries == ()


async def test_rationale_queue_full_drops_oldest() -> None:
    """Pushing 51 entries to maxsize=50 queue drops oldest; newest entry survives."""
    store = StateStore()
    # Push 50 entries (fills queue)
    for i in range(50):
        await store.push_rationale(
            RationaleEntry(agent_id=f"OLD_{i}", signal=SignalType.SELL, rationale="old", round_num=1)
        )
    # Push one more (should drop oldest, keep this new one)
    await store.push_rationale(
        RationaleEntry(agent_id="NEWEST", signal=SignalType.BUY, rationale="newest", round_num=2)
    )
    # Drain all entries (maxsize=50 so drain 5 per snapshot, need 10 calls)
    all_entries: list[RationaleEntry] = []
    for _ in range(11):  # 10 * 5 = 50 entries
        snap = store.snapshot()
        all_entries.extend(snap.rationale_entries)
        if not snap.rationale_entries:
            break
    agent_ids = [e.agent_id for e in all_entries]
    assert "NEWEST" in agent_ids


async def test_update_tps_single() -> None:
    """update_tps(100, 1_000_000_000) results in tps == 100.0."""
    store = StateStore()
    store.update_tps(eval_count=100, eval_duration_ns=1_000_000_000)
    snap = store.snapshot()
    assert snap.tps == pytest.approx(100.0)


async def test_update_tps_accumulates() -> None:
    """Two update_tps calls accumulate correctly: (100+200) / ((1e9+2e9)/1e9) = 100.0."""
    store = StateStore()
    store.update_tps(eval_count=100, eval_duration_ns=1_000_000_000)
    store.update_tps(eval_count=200, eval_duration_ns=2_000_000_000)
    snap = store.snapshot()
    expected_tps = 300 / 3.0  # 300 tokens / 3 seconds
    assert snap.tps == pytest.approx(expected_tps)


async def test_tps_default_zero() -> None:
    """No update_tps calls; snapshot tps is 0.0."""
    store = StateStore()
    snap = store.snapshot()
    assert snap.tps == 0.0


async def test_set_bracket_summaries() -> None:
    """set_bracket_summaries stores and snapshot returns them."""
    store = StateStore()
    summaries = (
        BracketSummary(
            bracket="quants",
            display_name="Quantitative",
            buy_count=5,
            sell_count=3,
            hold_count=2,
            total=10,
            avg_confidence=0.75,
            avg_sentiment=0.3,
        ),
    )
    await store.set_bracket_summaries(summaries)
    snap = store.snapshot()
    assert snap.bracket_summaries == summaries
    assert snap.bracket_summaries[0].bracket == "quants"


async def test_state_snapshot_new_defaults() -> None:
    """StateSnapshot() has tps=0.0, rationale_entries=(), bracket_summaries=()."""
    snap = StateSnapshot()
    assert snap.tps == 0.0
    assert snap.rationale_entries == ()
    assert snap.bracket_summaries == ()


async def test_snapshot_drain_queue_twice() -> None:
    """Calling snapshot() twice drains queue only for entries present at call time."""
    store = StateStore()
    await store.push_rationale(
        RationaleEntry(agent_id="A_0", signal=SignalType.HOLD, rationale="hold signal", round_num=3)
    )
    snap1 = store.snapshot()
    assert len(snap1.rationale_entries) == 1
    # Second call gets empty -- no new entries pushed
    snap2 = store.snapshot()
    assert snap2.rationale_entries == ()


def test_bracket_summary_frozen() -> None:
    """BracketSummary is an immutable frozen dataclass (now in state.py)."""
    bs = BracketSummary(
        bracket="degens",
        display_name="Degenerate Traders",
        buy_count=10,
        sell_count=5,
        hold_count=5,
        total=20,
        avg_confidence=0.6,
        avg_sentiment=0.2,
    )
    with pytest.raises(AttributeError):
        bs.bracket = "quants"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Task 2 Tests: Integration data flow tests
# ---------------------------------------------------------------------------


async def test_tps_from_worker_path() -> None:
    """StateStore.update_tps with realistic values produces correct tps in snapshot."""
    store = StateStore()
    # Simulate 500 tokens in 2 seconds (2e9 nanoseconds)
    store.update_tps(eval_count=500, eval_duration_ns=2_000_000_000)
    snap = store.snapshot()
    assert snap.tps == pytest.approx(250.0)


async def test_push_top_rationales_sorts_by_influence() -> None:
    """_push_top_rationales selects highest-influence agents first."""
    from alphaswarm.simulation import _push_top_rationales
    from alphaswarm.types import AgentDecision, SignalType

    store = StateStore()
    decisions: list[tuple[str, AgentDecision]] = [
        ("low_agent", AgentDecision(signal=SignalType.SELL, confidence=0.9, rationale="sell rationale")),
        ("high_agent", AgentDecision(signal=SignalType.BUY, confidence=0.5, rationale="buy rationale")),
        ("mid_agent", AgentDecision(signal=SignalType.HOLD, confidence=0.7, rationale="hold rationale")),
    ]
    influence_weights = {"high_agent": 0.9, "mid_agent": 0.5, "low_agent": 0.1}

    await _push_top_rationales(decisions, 1, store, influence_weights=influence_weights, limit=2)
    snap = store.snapshot()

    # Should have pushed at most 2 entries (limit=2)
    assert len(snap.rationale_entries) == 2
    # First entry should be high_agent (highest influence)
    assert snap.rationale_entries[0].agent_id == "high_agent"


async def test_push_top_rationales_skips_parse_errors() -> None:
    """_push_top_rationales skips PARSE_ERROR agents."""
    from alphaswarm.simulation import _push_top_rationales
    from alphaswarm.types import AgentDecision, SignalType

    store = StateStore()
    decisions: list[tuple[str, AgentDecision]] = [
        ("error_agent", AgentDecision(signal=SignalType.PARSE_ERROR, confidence=0.0, rationale="")),
        ("good_agent", AgentDecision(signal=SignalType.BUY, confidence=0.8, rationale="solid analysis")),
    ]

    await _push_top_rationales(decisions, 2, store)
    snap = store.snapshot()

    # Only good_agent should be in the queue
    assert len(snap.rationale_entries) == 1
    assert snap.rationale_entries[0].agent_id == "good_agent"


# ---------------------------------------------------------------------------
# Phase 28 Task 1 Tests: ReplayStore + SimulationPhase.REPLAY
# ---------------------------------------------------------------------------


def test_simulation_phase_replay() -> None:
    """SimulationPhase.REPLAY exists and has value 'replay'."""
    assert SimulationPhase.REPLAY.value == "replay"


def test_replay_store_snapshot() -> None:
    """ReplayStore with pre-loaded signals for round 1 returns correct StateSnapshot."""
    signals: dict[tuple[str, int], AgentState] = {
        ("quants_01", 1): AgentState(signal=SignalType.BUY, confidence=0.9),
        ("degens_01", 1): AgentState(signal=SignalType.SELL, confidence=0.7),
    }
    store = ReplayStore(cycle_id="test-cycle-123", signals=signals)
    store.set_round(1)
    snap = store.snapshot()

    assert snap.phase == SimulationPhase.REPLAY
    assert snap.round_num == 1
    assert snap.agent_states == {
        "quants_01": AgentState(signal=SignalType.BUY, confidence=0.9),
        "degens_01": AgentState(signal=SignalType.SELL, confidence=0.7),
    }
    assert snap.governor_metrics is None
    assert snap.tps == 0.0
    assert snap.elapsed_seconds == 0.0


def test_replay_store_round_advance() -> None:
    """set_round(2) changes snapshot round_num and filters agent_states to round 2."""
    signals: dict[tuple[str, int], AgentState] = {
        ("quants_01", 1): AgentState(signal=SignalType.BUY, confidence=0.9),
        ("quants_01", 2): AgentState(signal=SignalType.SELL, confidence=0.6),
    }
    store = ReplayStore(cycle_id="test-cycle-123", signals=signals)

    store.set_round(1)
    assert store.snapshot().agent_states["quants_01"].signal == SignalType.BUY

    store.set_round(2)
    assert store.snapshot().round_num == 2
    assert store.snapshot().agent_states["quants_01"].signal == SignalType.SELL


def test_replay_store_set_bracket_summaries() -> None:
    """set_bracket_summaries stores summaries returned in next snapshot."""
    store = ReplayStore(cycle_id="test-cycle-123", signals={})
    summary = BracketSummary(
        bracket="quants",
        display_name="Quants",
        buy_count=5,
        sell_count=3,
        hold_count=2,
        total=10,
        avg_confidence=0.7,
        avg_sentiment=0.3,
    )
    store.set_bracket_summaries((summary,))
    assert store.snapshot().bracket_summaries == (summary,)


def test_replay_store_set_rationale_entries() -> None:
    """set_rationale_entries stores entries returned in next snapshot."""
    store = ReplayStore(cycle_id="test-cycle-123", signals={})
    entry = RationaleEntry(
        agent_id="quants_01",
        signal=SignalType.BUY,
        rationale="test rationale",
        round_num=1,
    )
    store.set_rationale_entries((entry,))
    assert store.snapshot().rationale_entries == (entry,)


def test_replay_store_no_drain() -> None:
    """snapshot() does NOT drain rationale_entries -- same tuple returned every call."""
    store = ReplayStore(cycle_id="test-cycle-123", signals={})
    entry = RationaleEntry(
        agent_id="quants_01",
        signal=SignalType.BUY,
        rationale="no drain test",
        round_num=1,
    )
    store.set_rationale_entries((entry,))

    snap1 = store.snapshot()
    snap2 = store.snapshot()
    assert snap1.rationale_entries == snap2.rationale_entries
    assert len(snap1.rationale_entries) == 1
