"""Golden StateFrames shared with the frontend tests (docs/DECISIONS.md#adr-ws-broadcaster).

The frames are built from a real StateStore driven through its public API under a
frozen clock, then serialised exactly as the broadcaster sends them.
frontend/src/__tests__/frame.test.ts and data.test.ts read the same files.

Regenerate only in a commit that changes the wire on purpose:
    UPDATE_GOLDEN=1 uv run pytest -q tests/test_wire_contract.py && (cd frontend && npx vitest run)
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Final

import pytest

import alphaswarm.data_audit as data_audit_module
import alphaswarm.errors as errors_module
import alphaswarm.state as state_module
from alphaswarm.errors import RoundFailedError, run_error_from_exception
from alphaswarm.personas import DEFAULT_BRACKETS
from alphaswarm.state import (
    AgentState,
    BracketSummary,
    GovernorMetrics,
    JobStatus,
    RationaleEntry,
    ReplayStore,
    StateStore,
)
from alphaswarm.types import SignalType, SimulationPhase
from alphaswarm.web.broadcaster import snapshot_to_json
from tests.support.golden import assert_golden_file

REPO: Final = Path(__file__).resolve().parents[1]
FIXTURES: Final = REPO / "frontend" / "src" / "__tests__" / "fixtures"
LIVE_CYCLE: Final = "00000000-0000-4000-8000-000000000001"
REPLAY_CYCLE: Final = "00000000-0000-4000-8000-000000000002"
FAILED_CYCLE: Final = "00000000-0000-4000-8000-000000000003"
SHOCK_APPLIED: Final = "QQQX Robotics board rejects the offer as undervalued."
SHOCK_PENDING: Final = "ZZZT Holdings confirms the financing is fully committed."

ROUND_1: Final = (
    ("institutions_01", SignalType.HOLD, 0.6),
    ("sell_side_03", SignalType.BUY, 0.7),
    ("event_driven_05", SignalType.BUY, 0.65),
    ("degens_07", SignalType.BUY, 0.9),
    ("macro_02", SignalType.HOLD, 0.5),
    ("shorts_02", SignalType.SELL, 0.75),
)
# sell_side_03 is still thinking in round 2; degens_07 failed to parse.
ROUND_2: Final = (
    ("institutions_01", SignalType.BUY, 0.82),
    ("event_driven_05", SignalType.SELL, 0.4),
    ("degens_07", SignalType.PARSE_ERROR, 0.0),
    ("macro_02", SignalType.HOLD, 0.55),
    ("shorts_02", SignalType.SELL, 0.8),
)
SUMMARIES: Final = (
    BracketSummary("sell_side", "Sell-Side", 4, 3, 3, 10, 0.61, 0.1),
    BracketSummary("event_driven", "Event-Driven", 5, 2, 3, 10, 0.55, -0.2),
)


class FrozenClock:
    """Replaces the ``time`` module inside alphaswarm.state, .data_audit and .errors."""

    def __init__(self, *, wall: float, mono: float) -> None:
        self.wall = wall
        self.mono = mono

    def time(self) -> float:
        return self.wall

    def monotonic(self) -> float:
        return self.mono


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FrozenClock:
    frozen = FrozenClock(wall=1_790_000_000.0, mono=1_000.0)
    monkeypatch.setattr(state_module, "time", frozen)
    monkeypatch.setattr(data_audit_module, "time", frozen)
    monkeypatch.setattr(errors_module, "time", frozen)
    monkeypatch.setattr(
        "alphaswarm.web.broadcaster.psutil.virtual_memory",
        lambda: SimpleNamespace(percent=61.2),
    )
    return frozen


def _pretty(raw: str) -> str:
    """The broadcaster's exact JSON, indented for review (key order kept)."""
    return json.dumps(json.loads(raw), indent=2, ensure_ascii=False)


async def _live_store(clock: FrozenClock) -> StateStore:
    """Mid round 2 of a 3-round run."""
    store = StateStore()
    store.set_num_rounds(3)
    await store.set_phase(SimulationPhase.SEEDING)
    await store.set_cycle(LIVE_CYCLE)
    await store.set_phase(SimulationPhase.ROUND_1)
    await store.set_round(1)
    for agent_id, signal, confidence in ROUND_1:
        await store.update_agent_state(agent_id, signal, confidence)
    clock.wall += 10.0
    await store.push_rationale(
        RationaleEntry("quants_01", SignalType.BUY, "Momentum and volume confirm the premium", 1)
    )
    await store.set_phase(SimulationPhase.ROUND_2)
    await store.set_round(2)
    store.record_applied_shock(SHOCK_APPLIED, 2)
    for agent_id, signal, confidence in ROUND_2:
        await store.update_agent_state(agent_id, signal, confidence)
    clock.wall += 5.0
    await store.push_rationale(RationaleEntry("shorts_02", SignalType.SELL, "Crowded long; fade the cascade", 2))
    await store.set_bracket_summaries(SUMMARIES)
    store.update_governor_metrics(GovernorMetrics(16, 12, "green", 58.0, "running", 1_500.0))
    store.record_data_source(source="yfinance", query="ZZZT 1d OHLCV", result="ok", used=True)
    store.update_tps(427, 10_000_000_000)
    store.set_pending_shock(SHOCK_PENDING)
    clock.mono = 1_754.25
    return store


def _replay_store() -> ReplayStore:
    signals = {
        (agent_id, round_num): AgentState(signal=signal, confidence=confidence)
        for round_num, rows in ((1, ROUND_1), (2, ROUND_2))
        for agent_id, signal, confidence in rows
    }
    store = ReplayStore(REPLAY_CYCLE, signals, num_rounds=2)
    store.set_round(2)
    store.set_bracket_summaries(SUMMARIES)
    store.set_rationale_entries(
        (
            RationaleEntry("institutions_01", SignalType.BUY, "Deal spread is attractive", 2, 1),
            RationaleEntry("shorts_02", SignalType.SELL, "Crowded long; fade the cascade", 2, 2),
        )
    )
    return store


async def _failed_store(clock: FrozenClock) -> StateStore:
    """A 3-round run that failed in round 2, left the way SimulationManager leaves it:
    the RunError recorded first, then the phase reset to IDLE."""
    store = StateStore()
    store.set_num_rounds(3)
    await store.set_phase(SimulationPhase.SEEDING)
    await store.set_cycle(FAILED_CYCLE)
    await store.set_phase(SimulationPhase.ROUND_1)
    await store.set_round(1)
    for agent_id, signal, confidence in ROUND_1:
        await store.update_agent_state(agent_id, signal, confidence)
    await store.set_phase(SimulationPhase.ROUND_2)
    await store.set_round(2)
    for agent_id, signal, confidence in ROUND_2:
        await store.update_agent_state(agent_id, signal, confidence)
    clock.wall += 30.0
    clock.mono = 1_090.5
    failure = RoundFailedError(round_num=2, failed=61, total=100, threshold_percent=50.0)
    await store.set_last_error(run_error_from_exception(failure, round_num=2))
    await store.set_phase(SimulationPhase.IDLE)
    return store


async def test_live_frame_matches_golden(clock: FrozenClock) -> None:
    store = await _live_store(clock)
    assert_golden_file(FIXTURES / "ws_snapshot.json", _pretty(snapshot_to_json(store)), normalize_values=False)


def test_replay_frame_matches_golden(clock: FrozenClock) -> None:
    live = StateStore()
    live.set_job_status("report", JobStatus("running", REPLAY_CYCLE))
    manager = SimpleNamespace(has_store=True, store=_replay_store())
    raw = snapshot_to_json(live, manager)  # type: ignore[arg-type]
    assert_golden_file(FIXTURES / "ws_snapshot_replay.json", _pretty(raw), normalize_values=False)


async def test_failed_run_frame_matches_golden(clock: FrozenClock) -> None:
    store = await _failed_store(clock)
    assert_golden_file(
        FIXTURES / "ws_snapshot_failed.json",
        _pretty(snapshot_to_json(store)),
        normalize_values=False,
    )


def test_brackets_fixture_matches_default_brackets() -> None:
    rows = [
        {
            "key": b.bracket_type.value,
            "display_name": b.display_name,
            "count": b.count,
            "influence_weight_base": b.influence_weight_base,
        }
        for b in DEFAULT_BRACKETS
    ]
    assert_golden_file(FIXTURES / "brackets.json", json.dumps(rows, indent=2), normalize_values=False)
