"""Scenario on the real ResourceGovernor: zero jitter must not break the slot limit."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

from alphaswarm.governor import ResourceGovernor
from alphaswarm.inference.types import InferenceMessage, InferenceResult
from alphaswarm.types import AgentPersona, SimulationPhase
from tests.engine.scenario import RecordingStateStore, RunScenario, persisted_rounds
from tests.inference.fakes import ScriptedProvider
from tests.support.monitor import ScriptedMonitor, fast_governor_settings, reading

BASELINE_SLOTS = 4


class _ConcurrencyProbe(ScriptedProvider):
    """Counts chat() calls in flight; each call yields twice so overlap can build up."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.in_flight = 0
        self.max_in_flight = 0

    async def chat(self, messages: list[InferenceMessage], **kwargs: Any) -> InferenceResult:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            return await super().chat(messages, **kwargs)
        finally:
            self.in_flight -= 1


async def test_zero_jitter_with_real_governor_never_exceeds_baseline_slots(
    run_scenario: RunScenario,
    all_personas: list[AgentPersona],
    scenario_store: RecordingStateStore,
    fake_graph: MagicMock,
) -> None:
    governor = ResourceGovernor(
        fast_governor_settings(baseline_parallel=BASELINE_SLOTS, max_parallel=BASELINE_SLOTS),
        monitor=ScriptedMonitor([reading(50.0)], repeat_last=False),
    )
    worker = _ConcurrencyProbe(personas=all_personas, round_source=lambda: scenario_store.snapshot().round_num)
    await run_scenario(worker=worker, controller=governor)
    assert 1 < worker.max_in_flight <= BASELINE_SLOTS
    assert persisted_rounds(fake_graph) == [1, 2, 3]
    assert scenario_store.phases[-1] is SimulationPhase.COMPLETE
