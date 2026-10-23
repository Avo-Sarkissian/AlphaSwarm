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
    assert snap.agent_count == 0
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


async def test_set_phase_preserves_agent_keys_resets_signals() -> None:
    """Setting phase to a round preserves agent dict keys but resets signals to None.

    New contract (supersedes the original D-05 "clean visual slate"): the WS
    broadcaster reads agent_states on every snapshot tick during the 14-18min
    round dispatch. Clearing the dict produced empty WS frames for the entire
    round. Now we keep the keys (so the frontend renders dim/pulsing "thinking"
    dots) and let streaming per-agent writes overwrite them as inference
    resolves.
    """
    store = StateStore()
    await store.update_agent_state("quants_01", SignalType.BUY, 0.9)
    await store.update_agent_state("degens_01", SignalType.SELL, 0.7)
    assert len(store.snapshot().agent_states) == 2

    await store.set_phase(SimulationPhase.ROUND_2)
    snap = store.snapshot()
    # Keys preserved
    assert set(snap.agent_states.keys()) == {"quants_01", "degens_01"}
    # Signals reset to "thinking" placeholder (signal=None, confidence=0.0)
    assert snap.agent_states["quants_01"].signal is None
    assert snap.agent_states["quants_01"].confidence == 0.0
    assert snap.agent_states["degens_01"].signal is None
    assert snap.agent_states["degens_01"].confidence == 0.0
    assert snap.phase == SimulationPhase.ROUND_2


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


def test_governor_metrics_includes_slots_for_ws_frame() -> None:
    """ITEM 3 of quick task 260512-jqn — GovernorMetrics MUST carry
    both `current_slots` (budget) and `active_count` (in-flight)
    so the WS frame can surface PARALLEL SLOTS as numerator/denominator.

    Closes KR-41.1-05: previously slotsMax was a frontend stub of 8.
    Frontend frame.ts now reads governor_metrics.active_count and
    governor_metrics.current_slots directly; this test fixes the
    backend contract that the adapter depends on.
    """
    from alphaswarm.web.wire import build_frame

    store = StateStore()
    metrics = GovernorMetrics(
        current_slots=16,
        active_count=12,
        pressure_level="NORMAL",
        memory_percent=45.0,
        governor_state="RUNNING",
        timestamp=1000.0,
    )
    store.update_governor_metrics(metrics)
    snap = store.snapshot()

    # Both fields surface on the snapshot for the broadcaster.
    assert snap.governor_metrics is not None
    assert snap.governor_metrics.current_slots == 16
    assert snap.governor_metrics.active_count == 12

    # build_frame is the StateFrame mapper the broadcaster serializes; its JSON keeps both.
    frame = build_frame(snap, jobs=store.job_statuses(), memory_percent=45.0)
    gm = frame.model_dump(mode="json")["governor_metrics"]
    assert gm["current_slots"] == 16
    assert gm["active_count"] == 12


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


async def test_rationale_window_appends_and_caps_at_50() -> None:
    """ITEM 4 of 260512-jqn — sliding window caps at 50, drops oldest on overflow."""
    store = StateStore()
    for i in range(60):
        await store.push_rationale(
            RationaleEntry(agent_id=f"A_{i}", signal=SignalType.BUY, rationale="test", round_num=1)
        )
    snap = store.snapshot()
    # The deque keeps the most-recent 50 entries; oldest 10 are dropped.
    assert len(snap.rationale_entries) == 50
    assert snap.rationale_entries[0].agent_id == "A_10"  # A_0..A_9 dropped
    assert snap.rationale_entries[-1].agent_id == "A_59"  # newest preserved


async def test_rationale_window_peek_non_destructive() -> None:
    """Snapshot can be called repeatedly without losing rationale entries.

    Previously drain_rationales drained the queue per consumer; the new
    sliding window is peek-only so the WS broadcaster, TUI, and any
    reconnecting client all see the same data.
    """
    store = StateStore()
    await store.push_rationale(RationaleEntry(agent_id="A_0", signal=SignalType.BUY, rationale="test", round_num=1))
    snap1 = store.snapshot()
    snap2 = store.snapshot()
    # Both snapshots carry the entry — no drain.
    assert len(snap1.rationale_entries) == 1
    assert len(snap2.rationale_entries) == 1
    assert snap1.rationale_entries[0].agent_id == "A_0"
    assert snap2.rationale_entries[0].agent_id == "A_0"


async def test_rationale_window_empty_initially() -> None:
    """No entries pushed; snapshot.rationale_entries is empty tuple."""
    store = StateStore()
    snap = store.snapshot()
    assert snap.rationale_entries == ()


async def test_peek_rationales_returns_full_window() -> None:
    """ITEM 4 — peek_rationales returns the full window without draining."""
    store = StateStore()
    for i in range(3):
        await store.push_rationale(
            RationaleEntry(agent_id=f"A_{i}", signal=SignalType.HOLD, rationale="hold", round_num=1)
        )
    peeked = store.peek_rationales()
    assert len(peeked) == 3
    assert all(e.signal == SignalType.HOLD for e in peeked)
    # Calling again returns the same data — peek is idempotent.
    again = store.peek_rationales()
    assert again == peeked


async def test_rationale_window_survives_round_transitions() -> None:
    """ITEM 4: rationales must NOT be cleared when set_phase advances rounds.

    Without this, a WS client that reconnects mid-R2 would see an empty
    feed because set_phase(ROUND_2) used to clear agent_states (which is
    still expected) but NOT the rationale window.
    """
    store = StateStore()
    await store.push_rationale(RationaleEntry(agent_id="R1_AGENT", signal=SignalType.BUY, rationale="r1", round_num=1))
    await store.set_phase(SimulationPhase.ROUND_2)
    snap = store.snapshot()
    assert len(snap.rationale_entries) == 1
    assert snap.rationale_entries[0].agent_id == "R1_AGENT"


async def test_tps_default_zero() -> None:
    """No record_tokens calls; snapshot tps is 0.0."""
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


async def test_snapshot_peek_window_repeatable() -> None:
    """ITEM 4: snapshot() is non-destructive AND carries the rationale window
    so repeated snapshots return identical data (peek semantics).

    Previously snapshot returned () and a destructive drain popped entries;
    this test asserts that repeated snapshots contain the same entry.
    """
    store = StateStore()
    await store.push_rationale(
        RationaleEntry(agent_id="A_0", signal=SignalType.HOLD, rationale="hold signal", round_num=3)
    )
    snap1 = store.snapshot()
    snap2 = store.snapshot()
    # Both snapshots carry the rationale — peek semantics.
    assert len(snap1.rationale_entries) == 1
    assert snap1.rationale_entries[0].agent_id == "A_0"
    assert snap1.rationale_entries == snap2.rationale_entries
    assert len(store.snapshot().rationale_entries) == 1


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


async def test_last_error_defaults_to_none_and_round_trips() -> None:
    from alphaswarm.errors import RoundFailedError, run_error_from_exception

    store = StateStore()
    assert store.last_error is None
    assert store.snapshot().last_error is None

    err = run_error_from_exception(RoundFailedError(2, 80, 100, 50.0), round_num=2)
    await store.set_last_error(err)
    assert store.last_error == err
    assert store.snapshot().last_error == err

    await store.set_last_error(None)
    assert store.snapshot().last_error is None


def test_replay_snapshot_has_no_last_error() -> None:
    assert ReplayStore("c1", {}).snapshot().last_error is None


async def test_finalizing_keeps_agent_signals() -> None:
    store = StateStore()
    await store.set_phase(SimulationPhase.ROUND_3)
    await store.update_agent_state("quants_01", SignalType.SELL, 0.7)
    await store.set_phase(SimulationPhase.FINALIZING)
    snap = store.snapshot()
    assert snap.phase is SimulationPhase.FINALIZING
    assert snap.agent_states["quants_01"] == AgentState(signal=SignalType.SELL, confidence=0.7)


# ---------------------------------------------------------------------------
# Canonical roster (docs/DECISIONS.md#adr-streaming-state)
# ---------------------------------------------------------------------------


async def test_begin_run_installs_ordered_pending_roster() -> None:
    store = StateStore()
    await store.update_agent_state("stale_99", SignalType.BUY, 0.9)
    await store.begin_run(["quants_01", "degens_01", "macro_01"])
    snap = store.snapshot()
    assert list(snap.agent_states) == ["quants_01", "degens_01", "macro_01"]
    assert set(snap.agent_states.values()) == {AgentState(signal=None, confidence=0.0)}
    assert snap.agent_count == 3


async def test_begin_run_keeps_the_first_position_of_a_duplicate() -> None:
    store = StateStore()
    await store.begin_run(["algos_01", "macro_01", "algos_01"])
    assert list(store.snapshot().agent_states) == ["algos_01", "macro_01"]


async def test_roster_order_survives_streaming_and_round_entry() -> None:
    store = StateStore()
    await store.begin_run(["quants_01", "degens_01", "macro_01"])
    await store.update_agent_state("macro_01", SignalType.SELL, 0.7)
    await store.update_agent_state("quants_01", SignalType.BUY, 0.6)
    await store.set_phase(SimulationPhase.ROUND_2)
    snap = store.snapshot()
    assert list(snap.agent_states) == ["quants_01", "degens_01", "macro_01"]
    assert snap.agent_states["macro_01"].signal is None


def test_agent_count_is_zero_before_any_run() -> None:
    assert StateStore().snapshot().agent_count == 0


def test_replay_agent_count_counts_the_active_round() -> None:
    signals: dict[tuple[str, int], AgentState] = {
        ("quants_01", 1): AgentState(signal=SignalType.BUY, confidence=0.9),
        ("degens_01", 1): AgentState(signal=SignalType.SELL, confidence=0.4),
        ("quants_01", 2): AgentState(signal=SignalType.HOLD, confidence=0.5),
    }
    store = ReplayStore(cycle_id="00000000-0000-4000-8000-000000000001", signals=signals)
    store.set_round(1)
    assert store.snapshot().agent_count == 2
    store.set_round(2)
    assert store.snapshot().agent_count == 1
