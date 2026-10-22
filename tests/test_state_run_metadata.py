"""Run identity and ordering in StateStore snapshots (docs/DECISIONS.md#adr-ws-broadcaster)."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

import alphaswarm.state as state_module
from alphaswarm.state import (
    AgentState,
    JobsSnapshot,
    JobStatus,
    RationaleEntry,
    ReplayStore,
    StateSnapshot,
    StateStore,
)
from alphaswarm.types import SignalType, SimulationPhase

CYCLE_A = "00000000-0000-4000-8000-0000000000a1"
CYCLE_B = "00000000-0000-4000-8000-0000000000b2"


def _entry(agent_id: str = "quants_01", round_num: int = 1) -> RationaleEntry:
    return RationaleEntry(agent_id, SignalType.BUY, "fictional rationale", round_num)


def test_snapshot_defaults_for_new_fields() -> None:
    snap = StateSnapshot()
    assert snap.cycle_id is None
    assert snap.num_rounds == 3
    assert snap.edges_version == 0
    assert snap.jobs == JobsSnapshot(advisory=JobStatus(), report=JobStatus())
    assert (_entry().seq, _entry().ts) == (0, 0.0)


async def test_set_cycle_and_bump_edges_version_reach_the_snapshot() -> None:
    store = StateStore()
    await store.set_cycle(CYCLE_A)
    store.bump_edges_version()
    store.bump_edges_version()
    snap = store.snapshot()
    assert snap.cycle_id == CYCLE_A
    assert snap.edges_version == 2


async def test_seeding_starts_a_new_run_identity() -> None:
    store = StateStore()
    await store.set_cycle(CYCLE_A)
    store.bump_edges_version()
    await store.set_phase(SimulationPhase.COMPLETE)
    assert store.snapshot().cycle_id == CYCLE_A  # the finished cycle stays on screen

    await store.set_phase(SimulationPhase.SEEDING)
    snap = store.snapshot()
    assert (snap.cycle_id, snap.edges_version) == (None, 0)


async def test_round_and_finalizing_phases_keep_the_run_identity() -> None:
    store = StateStore()
    await store.set_phase(SimulationPhase.SEEDING)
    await store.set_cycle(CYCLE_A)
    for phase in (
        SimulationPhase.ROUND_1,
        SimulationPhase.ROUND_2,
        SimulationPhase.FINALIZING,
        SimulationPhase.COMPLETE,
        SimulationPhase.IDLE,
    ):
        await store.set_phase(phase)
        assert store.snapshot().cycle_id == CYCLE_A, phase


def test_num_rounds_reaches_the_snapshot() -> None:
    store = StateStore()
    store.set_num_rounds(2)
    assert store.snapshot().num_rounds == 2


def test_snapshot_carries_job_statuses() -> None:
    store = StateStore()
    store.set_job_status("report", JobStatus("running", CYCLE_A))
    assert store.snapshot().jobs.report == JobStatus("running", CYCLE_A)


async def test_push_rationale_stamps_monotonic_seq_and_wall_clock_ts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    times = iter([1_790_000_000.0, 1_790_000_001.5, 1_790_000_003.0])
    fake_time = SimpleNamespace(time=lambda: next(times), monotonic=time.monotonic)
    monkeypatch.setattr(state_module, "time", fake_time)
    store = StateStore()
    await store.push_rationale(_entry("quants_01"))
    await store.push_rationale(_entry("degens_02"))
    await store.set_phase(SimulationPhase.SEEDING)  # new run: window cleared, seq keeps growing
    await store.push_rationale(_entry("macro_03"))
    entries = store.snapshot().rationale_entries
    assert [(e.agent_id, e.seq, e.ts) for e in entries] == [("macro_03", 3, 1_790_000_003.0)]


async def test_seq_stays_unique_when_the_window_drops_old_entries() -> None:
    store = StateStore()
    for i in range(60):
        await store.push_rationale(_entry(f"quants_{i:02d}"))
    seqs = [e.seq for e in store.snapshot().rationale_entries]
    assert seqs == list(range(11, 61))


def test_replay_store_reports_cycle_rounds_and_edges_version() -> None:
    signals = {
        ("quants_01", 1): AgentState(SignalType.BUY, 0.8),
        ("quants_01", 2): AgentState(SignalType.SELL, 0.6),
    }
    store = ReplayStore(CYCLE_B, signals, num_rounds=2)
    assert store.cycle_id == CYCLE_B
    store.set_round(1)
    first = store.snapshot()
    assert (first.cycle_id, first.num_rounds, first.edges_version) == (CYCLE_B, 2, 0)
    store.set_round(2)
    assert store.snapshot().edges_version == 1


def test_replay_store_defaults_to_three_rounds() -> None:
    assert ReplayStore(CYCLE_B, {}).snapshot().num_rounds == 3
