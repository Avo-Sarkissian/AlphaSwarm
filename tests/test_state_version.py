"""StateStore/ReplayStore version counters and the run-scoped audit log."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from types import FunctionType

import pytest

from alphaswarm.state import (
    AgentState,
    GovernorMetrics,
    JobStatus,
    RationaleEntry,
    ReplayStore,
    StateStore,
)
from alphaswarm.types import SignalType, SimulationPhase

CYCLE_A = "00000000-0000-4000-8000-0000000000a1"
SHOCK = "ZZZT Holdings raises its offer for QQQX Robotics to $4.6B in cash."

Call = Callable[[StateStore], object]

# Every public StateStore method that changes what snapshot() or job_statuses() returns.
MUTATOR_CALLS: dict[str, Call] = {
    "update_agent_state": lambda s: s.update_agent_state("quants_01", SignalType.BUY, 0.8),
    "set_phase": lambda s: s.set_phase(SimulationPhase.ROUND_1),
    "set_round": lambda s: s.set_round(2),
    "push_rationale": lambda s: s.push_rationale(
        RationaleEntry(agent_id="quants_01", signal=SignalType.BUY, rationale="ZZZT deal", round_num=1)
    ),
    "record_tokens": lambda s: s.record_tokens(150),
    "set_bracket_summaries": lambda s: s.set_bracket_summaries(()),
    "update_governor_metrics": lambda s: s.update_governor_metrics(
        GovernorMetrics(
            current_slots=8,
            active_count=0,
            pressure_level="green",
            memory_percent=50.0,
            governor_state="running",
            timestamp=0.0,
        )
    ),
    "record_data_source": lambda s: s.record_data_source("rss", "ZZZT Holdings", "ok"),
    "set_last_error": lambda s: s.set_last_error(None),
    "set_job_status": lambda s: s.set_job_status("report", JobStatus("running", CYCLE_A)),
    "set_num_rounds": lambda s: s.set_num_rounds(2),
    "set_pending_shock": lambda s: s.set_pending_shock(SHOCK),
    "record_applied_shock": lambda s: s.record_applied_shock(SHOCK, 2),
    "set_cycle": lambda s: s.set_cycle(CYCLE_A),
    "bump_edges_version": lambda s: s.bump_edges_version(),
    "begin_run": lambda s: s.begin_run(["quants_01", "quants_02"]),
}
READERS = frozenset(
    {
        "snapshot",
        "peek_rationales",
        "governor_metrics",
        "peek_data_source_audit",
        "last_error",
        "job_statuses",
        "shock_window_open",
        "version",
    }
)
REPLAY_MUTATORS = frozenset({"set_round", "set_bracket_summaries", "set_rationale_entries"})
REPLAY_READERS = frozenset({"snapshot", "cycle_id", "version"})


def _public_members(cls: type) -> set[str]:
    return {
        name
        for name in dir(cls)
        if not name.startswith("_") and isinstance(inspect.getattr_static(cls, name), (FunctionType, property))
    }


async def _apply(call: Call, store: StateStore) -> None:
    result = call(store)
    if inspect.isawaitable(result):
        await result


def test_every_public_member_is_classified() -> None:
    # A new StateStore method fails here until it is listed as a mutator (and
    # bumps the version) or as a reader.
    assert _public_members(StateStore) == set(MUTATOR_CALLS) | READERS
    assert _public_members(ReplayStore) == REPLAY_MUTATORS | REPLAY_READERS


@pytest.mark.parametrize("name", sorted(MUTATOR_CALLS))
async def test_every_mutator_bumps_the_version(name: str) -> None:
    store = StateStore()
    before = store.version
    await _apply(MUTATOR_CALLS[name], store)
    assert store.version > before


def test_readers_leave_the_version_alone() -> None:
    store = StateStore()
    before = store.version
    store.snapshot()
    store.peek_rationales()
    store.peek_data_source_audit()
    store.job_statuses()
    store.shock_window_open()
    assert (store.governor_metrics, store.last_error) == (None, None)
    assert store.version == before


def test_versions_are_never_reused_across_stores() -> None:
    live = StateStore()
    replay = ReplayStore(CYCLE_A, {("quants_01", 1): AgentState(SignalType.BUY, 0.8)})
    seen = {live.version, replay.version}
    replay.set_round(1)
    live.record_tokens(10)
    seen |= {live.version, replay.version}
    assert len(seen) == 4


def test_replay_setters_bump_the_version() -> None:
    replay = ReplayStore(CYCLE_A, {})
    versions = [replay.version]
    replay.set_round(1)
    versions.append(replay.version)
    replay.set_bracket_summaries(())
    versions.append(replay.version)
    replay.set_rationale_entries(())
    versions.append(replay.version)
    assert versions == sorted(set(versions))


async def test_seeding_clears_the_audit_buffer() -> None:
    store = StateStore()
    store.record_data_source("rss", "ZZZT Holdings", "ok", used=True)
    assert len(store.snapshot().data_source_audit) == 1
    await store.set_phase(SimulationPhase.SEEDING)
    assert store.snapshot().data_source_audit == ()
