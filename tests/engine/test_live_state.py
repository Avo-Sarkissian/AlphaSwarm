"""Live StateStore contract during a scripted run: roster at SEEDING, failures visible.

The scenario harness (tests/engine/conftest.py) drives the real run_simulation on
scripted fakes; this module overrides the scenario_store fixture with a store
that records the agent roster at the moment Round 1 starts.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from alphaswarm.types import AgentPersona, SignalType, SimulationPhase
from tests.engine.scenario import RecordingStateStore, RunScenario, failing_in_round
from tests.inference.fakes import DecisionFn, ScriptedProvider


class RosterProbeStore(RecordingStateStore):
    """Records the agent ids present when Round 1 begins."""

    def __init__(self) -> None:
        super().__init__()
        self.roster_at_round_1: list[str] | None = None

    async def set_phase(self, phase: SimulationPhase) -> None:
        if phase is SimulationPhase.ROUND_1 and self.roster_at_round_1 is None:
            self.roster_at_round_1 = list(self.snapshot().agent_states)
        await super().set_phase(phase)


@pytest.fixture
def scenario_store() -> RosterProbeStore:
    return RosterProbeStore()


async def test_roster_is_installed_before_round_1(
    run_scenario: RunScenario,
    scenario_store: RosterProbeStore,
    all_personas: list[AgentPersona],
) -> None:
    await run_scenario(num_rounds=2)
    expected = [p.id for p in all_personas]
    assert scenario_store.roster_at_round_1 == expected
    snap = scenario_store.snapshot()
    assert list(snap.agent_states) == expected
    assert snap.agent_count == len(all_personas)


async def test_failed_agents_show_parse_error_not_thinking(
    run_scenario: RunScenario,
    scenario_store: RosterProbeStore,
    make_scripted_worker: Callable[[DecisionFn], ScriptedProvider],
) -> None:
    failing = {"quants_01", "degens_02", "macro_03"}
    worker = make_scripted_worker(
        failing_in_round(
            2,
            lambda aid: RuntimeError(f"scripted failure for {aid}"),
            agent_ids=failing,
        )
    )
    await run_scenario(num_rounds=2, worker=worker)
    states = scenario_store.snapshot().agent_states
    assert {aid for aid, s in states.items() if s.signal is SignalType.PARSE_ERROR} == failing
    assert all(s.signal is not None for s in states.values())
