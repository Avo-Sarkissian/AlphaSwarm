"""The 5 Hz broadcaster sends a validated StateFrame (docs/DECISIONS.md#adr-ws-broadcaster)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from alphaswarm.state import AgentState, JobStatus, ReplayStore, StateStore
from alphaswarm.types import SignalType, SimulationPhase
from alphaswarm.web.broadcaster import snapshot_to_json
from alphaswarm.web.wire import SCHEMA_VERSION, StateFrame

CYCLE = "00000000-0000-4000-8000-0000000000d4"


@pytest.fixture(autouse=True)
def _host_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("alphaswarm.web.broadcaster.psutil.virtual_memory", lambda: SimpleNamespace(percent=50.0))


async def test_live_json_validates_as_a_state_frame() -> None:
    store = StateStore()
    await store.set_phase(SimulationPhase.SEEDING)
    await store.set_cycle(CYCLE)
    frame = StateFrame.model_validate_json(snapshot_to_json(store))
    assert (frame.schema_version, frame.mode, frame.phase, frame.cycle_id) == (
        SCHEMA_VERSION,
        "live",
        "seeding",
        CYCLE,
    )
    assert frame.governor_metrics.memory_percent == 50.0


def test_idle_frame_has_mode_idle_and_no_cycle() -> None:
    frame = StateFrame.model_validate_json(snapshot_to_json(StateStore()))
    assert (frame.mode, frame.cycle_id, frame.edges_version, frame.num_rounds) == (
        "idle",
        None,
        0,
        3,
    )


def test_replay_frame_shows_the_replayed_cycle_with_live_jobs() -> None:
    live = StateStore()
    live.set_job_status("advisory", JobStatus("running", CYCLE))
    replay = ReplayStore(CYCLE, {("quants_01", 2): AgentState(SignalType.HOLD, 0.5)}, num_rounds=2)
    replay.set_round(2)
    manager = SimpleNamespace(has_store=True, store=replay)
    frame = StateFrame.model_validate_json(snapshot_to_json(live, manager))  # type: ignore[arg-type]
    assert (frame.mode, frame.cycle_id, frame.num_rounds, frame.edges_version) == (
        "replay",
        CYCLE,
        2,
        1,
    )
    assert frame.jobs.advisory.state == "running"


def test_replay_start_up_window_still_serves_the_live_frame() -> None:
    # is_active is already True while ReplayManager.start() awaits Neo4j, but no store
    # is committed yet (docs/DECISIONS.md#f-24).
    manager = SimpleNamespace(is_active=True, has_store=False)
    frame = StateFrame.model_validate_json(snapshot_to_json(StateStore(), manager))  # type: ignore[arg-type]
    assert frame.mode == "idle"
