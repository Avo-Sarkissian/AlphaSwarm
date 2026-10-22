"""WebSocket wire contract: the StateFrame carried by every /ws/state message.

The broadcaster never serialises internal dataclasses directly. ``build_frame``
maps a ``StateSnapshot`` onto these models field by field, so renaming an internal
field fails a test instead of silently changing what the UI receives
(docs/DECISIONS.md#adr-ws-broadcaster). The TypeScript mirror lives in
``frontend/src/types.ts``; ``tests/test_wire_contract.py`` writes the golden frames
the frontend tests read.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

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

SCHEMA_VERSION: Final = 1

WireSignal = Literal["buy", "sell", "hold", "parse_error"]
WirePhase = Literal[
    "idle", "seeding", "round_1", "round_2", "round_3", "finalizing", "complete", "replay"
]
FrameMode = Literal["live", "replay", "idle"]

_SIGNALS: Final[Mapping[SignalType, WireSignal]] = {
    SignalType.BUY: "buy",
    SignalType.SELL: "sell",
    SignalType.HOLD: "hold",
    SignalType.PARSE_ERROR: "parse_error",
}
_PHASES: Final[Mapping[SimulationPhase, WirePhase]] = {
    SimulationPhase.IDLE: "idle",
    SimulationPhase.SEEDING: "seeding",
    SimulationPhase.ROUND_1: "round_1",
    SimulationPhase.ROUND_2: "round_2",
    SimulationPhase.ROUND_3: "round_3",
    SimulationPhase.FINALIZING: "finalizing",
    SimulationPhase.COMPLETE: "complete",
    SimulationPhase.REPLAY: "replay",
}


class _WireModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class WireAgentState(_WireModel):
    signal: WireSignal | None
    confidence: float


class WireGovernorMetrics(_WireModel):
    current_slots: int
    active_count: int
    pressure_level: str
    memory_percent: float
    governor_state: str
    timestamp: float


class WireRationaleEntry(_WireModel):
    seq: int
    ts: float
    agent_id: str
    signal: WireSignal
    rationale: str
    round_num: int


class WireBracketSummary(_WireModel):
    bracket: str
    display_name: str
    buy_count: int
    sell_count: int
    hold_count: int
    total: int
    avg_confidence: float
    avg_sentiment: float


class WireDataSourceAuditEntry(_WireModel):
    ts: float
    source: str
    query: str
    result: str
    used: bool


class WireRunError(_WireModel):
    code: str
    message: str
    round_num: int | None
    ts: float


class WireJobStatus(_WireModel):
    state: Literal["idle", "running", "failed"]
    cycle_id: str | None
    error_code: str | None


class WireJobs(_WireModel):
    advisory: WireJobStatus
    report: WireJobStatus


class WireAppliedShock(_WireModel):
    text: str
    round_num: int


class StateFrame(_WireModel):
    schema_version: Literal[1]
    mode: FrameMode
    phase: WirePhase
    cycle_id: str | None
    num_rounds: int
    round_num: int
    agent_count: int
    agent_states: dict[str, WireAgentState]
    elapsed_seconds: float
    governor_metrics: WireGovernorMetrics
    tps: float
    rationale_entries: list[WireRationaleEntry]
    bracket_summaries: list[WireBracketSummary]
    data_source_audit: list[WireDataSourceAuditEntry]
    edges_version: int
    jobs: WireJobs
    last_error: WireRunError | None
    pending_shock: str | None
    applied_shocks: list[WireAppliedShock]
    shock_window_open: bool


def frame_mode(phase: SimulationPhase) -> FrameMode:
    """idle -> "idle", replay -> "replay", every run phase -> "live"."""
    if phase is SimulationPhase.IDLE:
        return "idle"
    if phase is SimulationPhase.REPLAY:
        return "replay"
    return "live"


def _signal(value: SignalType | str) -> WireSignal:
    return _SIGNALS[SignalType(value)]


def _agent(state: AgentState) -> WireAgentState:
    signal = None if state.signal is None else _signal(state.signal)
    return WireAgentState(signal=signal, confidence=state.confidence)


def _governor(metrics: GovernorMetrics | None, memory_percent: float) -> WireGovernorMetrics:
    # Live host memory always wins; before the governor first reports (idle, replay)
    # an idle placeholder keeps the UI's memory gauge fed (docs/DECISIONS.md#p999-3-d-01).
    if metrics is None:
        return WireGovernorMetrics(
            current_slots=0,
            active_count=0,
            pressure_level="green",
            memory_percent=memory_percent,
            governor_state="idle",
            timestamp=0.0,
        )
    return WireGovernorMetrics(
        current_slots=metrics.current_slots,
        active_count=metrics.active_count,
        pressure_level=metrics.pressure_level,
        memory_percent=memory_percent,
        governor_state=metrics.governor_state,
        timestamp=metrics.timestamp,
    )


def _rationale(entry: RationaleEntry) -> WireRationaleEntry:
    return WireRationaleEntry(
        seq=entry.seq,
        ts=entry.ts,
        agent_id=entry.agent_id,
        signal=_signal(entry.signal),
        rationale=entry.rationale,
        round_num=entry.round_num,
    )


def _bracket(summary: BracketSummary) -> WireBracketSummary:
    return WireBracketSummary(
        bracket=summary.bracket,
        display_name=summary.display_name,
        buy_count=summary.buy_count,
        sell_count=summary.sell_count,
        hold_count=summary.hold_count,
        total=summary.total,
        avg_confidence=summary.avg_confidence,
        avg_sentiment=summary.avg_sentiment,
    )


def _job(status: JobStatus) -> WireJobStatus:
    return WireJobStatus(state=status.state, cycle_id=status.cycle_id, error_code=status.error_code)


def _run_error(err: RunError | None) -> WireRunError | None:
    if err is None:
        return None
    return WireRunError(code=err.code, message=err.message, round_num=err.round_num, ts=err.ts)


def _shock(shock: AppliedShock) -> WireAppliedShock:
    return WireAppliedShock(text=shock.text, round_num=shock.round_num)


def build_frame(
    snapshot: StateSnapshot, *, jobs: JobsSnapshot, memory_percent: float
) -> StateFrame:
    """Map one snapshot onto the wire. Pure: no clock, no I/O.

    ``jobs`` comes from the live StateStore even while a replay is shown, so a
    reload during replay still sees a running report. ``memory_percent`` is the
    host reading taken by the caller for this tick.
    """
    return StateFrame(
        schema_version=SCHEMA_VERSION,
        mode=frame_mode(snapshot.phase),
        phase=_PHASES[snapshot.phase],
        cycle_id=snapshot.cycle_id,
        num_rounds=snapshot.num_rounds,
        round_num=snapshot.round_num,
        agent_count=snapshot.agent_count,
        agent_states={aid: _agent(s) for aid, s in snapshot.agent_states.items()},
        elapsed_seconds=snapshot.elapsed_seconds,
        governor_metrics=_governor(snapshot.governor_metrics, memory_percent),
        tps=snapshot.tps,
        rationale_entries=[_rationale(e) for e in snapshot.rationale_entries],
        bracket_summaries=[_bracket(b) for b in snapshot.bracket_summaries],
        data_source_audit=[
            WireDataSourceAuditEntry(
                ts=e.ts, source=e.source, query=e.query, result=e.result, used=e.used
            )
            for e in snapshot.data_source_audit
        ],
        edges_version=snapshot.edges_version,
        jobs=WireJobs(advisory=_job(jobs.advisory), report=_job(jobs.report)),
        last_error=_run_error(snapshot.last_error),
        pending_shock=snapshot.pending_shock,
        applied_shocks=[_shock(s) for s in snapshot.applied_shocks],
        shock_window_open=snapshot.shock_window_open,
    )
