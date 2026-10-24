"""metrics_version 2: the run clock starts before seeding and seed_seconds is recorded."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import alphaswarm.simulation as simulation_module
from alphaswarm.types import SimulationPhase
from tests.engine.scenario import RecordingStateStore, RunScenario


class _TickClock:
    """monotonic() advances one second per call, so durations count clock reads."""

    def __init__(self) -> None:
        self.ticks = 0

    def monotonic(self) -> float:
        self.ticks += 1
        return float(self.ticks)


class _ClockedStore(RecordingStateStore):
    """Records how many simulation-clock reads happened before each phase began."""

    def __init__(self, clock: _TickClock) -> None:
        super().__init__()
        self._clock = clock
        self.ticks_at_phase: dict[str, int] = {}

    async def set_phase(self, phase: SimulationPhase) -> None:
        self.ticks_at_phase.setdefault(phase.value, self._clock.ticks)
        await super().set_phase(phase)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _TickClock:
    fake = _TickClock()
    monkeypatch.setattr(
        simulation_module,
        "time",
        SimpleNamespace(monotonic=fake.monotonic, perf_counter=time.perf_counter, time=time.time),
    )
    return fake


@pytest.fixture
def scenario_store(clock: _TickClock) -> _ClockedStore:
    """Overrides tests/engine/conftest.py: a store that sees the simulation clock."""
    return _ClockedStore(clock)


async def test_run_clock_starts_before_seeding_and_seed_time_is_recorded(
    run_scenario: RunScenario, fake_graph: MagicMock, scenario_store: _ClockedStore
) -> None:
    await run_scenario()
    metrics = dict(fake_graph.write_cycle_metrics.await_args.args[1])
    assert metrics["metrics_version"] == 3  # 3 since the methodology estimators; the telemetry keys are unchanged
    assert scenario_store.ticks_at_phase["seeding"] >= 1  # the clock was read before SEEDING
    assert 0 < metrics["seed_seconds"] < metrics["total_seconds"]
