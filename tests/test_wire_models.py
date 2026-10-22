"""StateFrame models and the snapshot-to-frame mapper (docs/DECISIONS.md#adr-ws-broadcaster)."""

from __future__ import annotations

import dataclasses

import pytest
from pydantic import BaseModel, ValidationError

from alphaswarm.data_audit import DataSourceAuditEntry
from alphaswarm.errors import RunError
from alphaswarm.state import (
    AgentState,
    AppliedShock,
    BracketSummary,
    GovernorMetrics,
    JobsSnapshot,
    JobStatus,
    RationaleEntry,
    StateSnapshot,
)
from alphaswarm.types import SignalType, SimulationPhase
from alphaswarm.web import wire

IDLE_JOBS = JobsSnapshot(advisory=JobStatus(), report=JobStatus())


@pytest.mark.parametrize(
    ("model", "source"),
    [
        (wire.WireAgentState, AgentState),
        (wire.WireGovernorMetrics, GovernorMetrics),
        (wire.WireRationaleEntry, RationaleEntry),
        (wire.WireBracketSummary, BracketSummary),
        (wire.WireDataSourceAuditEntry, DataSourceAuditEntry),
        (wire.WireRunError, RunError),
        (wire.WireJobStatus, JobStatus),
        (wire.WireAppliedShock, AppliedShock),
    ],
)
def test_wire_models_mirror_their_dataclasses(model: type[BaseModel], source: type) -> None:
    assert set(model.model_fields) == {f.name for f in dataclasses.fields(source)}


def test_frame_maps_every_snapshot_field_plus_schema_version_and_mode() -> None:
    snapshot_fields = {f.name for f in dataclasses.fields(StateSnapshot)}
    assert set(wire.StateFrame.model_fields) == snapshot_fields | {"schema_version", "mode"}


@pytest.mark.parametrize(
    ("phase", "mode"),
    [
        (SimulationPhase.IDLE, "idle"),
        (SimulationPhase.SEEDING, "live"),
        (SimulationPhase.ROUND_1, "live"),
        (SimulationPhase.ROUND_2, "live"),
        (SimulationPhase.ROUND_3, "live"),
        (SimulationPhase.FINALIZING, "live"),
        (SimulationPhase.COMPLETE, "live"),
        (SimulationPhase.REPLAY, "replay"),
    ],
)
def test_mode_is_a_pure_function_of_phase(phase: SimulationPhase, mode: str) -> None:
    frame = wire.build_frame(StateSnapshot(phase=phase), jobs=IDLE_JOBS, memory_percent=1.0)
    assert (frame.mode, frame.phase) == (mode, phase.value)


def test_every_simulation_phase_has_a_wire_value() -> None:
    assert {p.value for p in SimulationPhase} == set(wire._PHASES.values())


def test_idle_frame_synthesizes_governor_metrics_with_live_memory() -> None:
    frame = wire.build_frame(StateSnapshot(), jobs=IDLE_JOBS, memory_percent=42.5)
    assert frame.schema_version == wire.SCHEMA_VERSION == 1
    assert frame.governor_metrics == wire.WireGovernorMetrics(
        current_slots=0,
        active_count=0,
        pressure_level="green",
        memory_percent=42.5,
        governor_state="idle",
        timestamp=0.0,
    )


def test_live_memory_overrides_the_governor_reading_only() -> None:
    gm = GovernorMetrics(12, 5, "yellow", 11.1, "throttled", 999.0)
    frame = wire.build_frame(
        StateSnapshot(governor_metrics=gm), jobs=IDLE_JOBS, memory_percent=88.8
    )
    assert frame.governor_metrics.model_dump() == {
        "current_slots": 12,
        "active_count": 5,
        "pressure_level": "yellow",
        "memory_percent": 88.8,
        "governor_state": "throttled",
        "timestamp": 999.0,
    }


def test_signals_map_to_lowercase_wire_values_and_null_means_thinking() -> None:
    snap = StateSnapshot(
        agent_states={
            "quants_01": AgentState(SignalType.BUY, 0.8),
            "degens_02": AgentState(SignalType.PARSE_ERROR, 0.0),
            "macro_03": AgentState(None, 0.0),
        },
        rationale_entries=(RationaleEntry("quants_01", SignalType.SELL, "x", 2, 7, 1.5),),
    )
    frame = wire.build_frame(snap, jobs=IDLE_JOBS, memory_percent=1.0)
    assert {k: v.signal for k, v in frame.agent_states.items()} == {
        "quants_01": "buy",
        "degens_02": "parse_error",
        "macro_03": None,
    }
    assert frame.rationale_entries[0].model_dump() == {
        "seq": 7,
        "ts": 1.5,
        "agent_id": "quants_01",
        "signal": "sell",
        "rationale": "x",
        "round_num": 2,
    }


def test_agent_order_is_preserved() -> None:
    ids = ["shorts_07", "institutions_01", "macro_03"]
    snap = StateSnapshot(agent_states={i: AgentState(None, 0.0) for i in ids})
    frame = wire.build_frame(snap, jobs=IDLE_JOBS, memory_percent=1.0)
    assert list(frame.agent_states) == ids


def test_jobs_come_from_the_argument_not_the_snapshot() -> None:
    running = JobsSnapshot(advisory=JobStatus(), report=JobStatus("running", "c1"))
    frame = wire.build_frame(
        StateSnapshot(phase=SimulationPhase.REPLAY), jobs=running, memory_percent=1.0
    )
    assert frame.jobs.report == wire.WireJobStatus(state="running", cycle_id="c1", error_code=None)


def test_last_error_and_shocks_are_mapped() -> None:
    err = RunError(code="round_failed", message="Round 2 failed", round_num=2, ts=3.5)
    snap = StateSnapshot(
        last_error=err,
        pending_shock="next shock",
        applied_shocks=(AppliedShock("first shock", 2),),
        shock_window_open=True,
    )
    frame = wire.build_frame(snap, jobs=IDLE_JOBS, memory_percent=1.0)
    assert frame.last_error == wire.WireRunError(
        code="round_failed", message="Round 2 failed", round_num=2, ts=3.5
    )
    assert frame.pending_shock == "next shock"
    assert frame.applied_shocks == [wire.WireAppliedShock(text="first shock", round_num=2)]
    assert frame.shock_window_open is True


def test_build_frame_is_pure() -> None:
    snap = StateSnapshot(phase=SimulationPhase.ROUND_1, round_num=1, cycle_id="c1")
    first = wire.build_frame(snap, jobs=IDLE_JOBS, memory_percent=5.0)
    second = wire.build_frame(snap, jobs=IDLE_JOBS, memory_percent=5.0)
    assert first.model_dump_json() == second.model_dump_json()


def test_frame_models_are_strict() -> None:
    frame = wire.build_frame(StateSnapshot(), jobs=IDLE_JOBS, memory_percent=1.0)
    with pytest.raises(ValidationError, match="extra"):
        wire.StateFrame.model_validate({**frame.model_dump(), "surprise": 1})
    with pytest.raises(ValidationError):
        frame.tps = 2.0  # type: ignore[misc]


def test_unknown_signal_fails_loudly() -> None:
    snap = StateSnapshot(rationale_entries=(RationaleEntry("q", "BULLISH", "x", 1),))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="BULLISH"):
        wire.build_frame(snap, jobs=IDLE_JOBS, memory_percent=1.0)
