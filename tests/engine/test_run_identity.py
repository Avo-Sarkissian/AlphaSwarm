"""The live frame's run identity follows the engine (docs/DECISIONS.md#adr-ws-broadcaster)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from unittest.mock import MagicMock

from alphaswarm.inference.types import ProviderRole
from alphaswarm.simulation import RoundCompleteEvent
from alphaswarm.types import AgentPersona
from tests.engine.scenario import (
    SCENARIO_CYCLE_ID,
    SCENARIO_MODIFIERS_JSON,
    SCENARIO_SEED_JSON,
    RecordingStateStore,
    RunScenario,
)
from tests.inference.fakes import ScriptedProvider

SECOND_CYCLE_ID = "00000000-0000-4000-8000-000000000002"


def _recorder(
    store: RecordingStateStore, seen: list[tuple[int, str | None, int]]
) -> Callable[[RoundCompleteEvent], Awaitable[None]]:
    async def on_round_complete(event: RoundCompleteEvent) -> None:
        snap = store.snapshot()
        seen.append((event.round_num, snap.cycle_id, snap.edges_version))

    return on_round_complete


async def test_cycle_id_and_edges_version_follow_a_three_round_run(
    run_scenario: RunScenario, scenario_store: RecordingStateStore
) -> None:
    seen: list[tuple[int, str | None, int]] = []
    await run_scenario(on_round_complete=_recorder(scenario_store, seen))

    assert seen == [(1, SCENARIO_CYCLE_ID, 0), (2, SCENARIO_CYCLE_ID, 1), (3, SCENARIO_CYCLE_ID, 2)]
    final = scenario_store.snapshot()
    assert (final.cycle_id, final.edges_version, final.num_rounds) == (SCENARIO_CYCLE_ID, 2, 3)


async def test_two_round_run_reports_two_rounds(run_scenario: RunScenario, scenario_store: RecordingStateStore) -> None:
    await run_scenario(num_rounds=2)
    snap = scenario_store.snapshot()
    assert (snap.num_rounds, snap.edges_version) == (2, 1)


async def test_second_run_reports_its_own_cycle_and_restarts_edges_version(
    run_scenario: RunScenario,
    scenario_store: RecordingStateStore,
    fake_graph: MagicMock,
    all_personas: list[AgentPersona],
) -> None:
    await run_scenario()
    assert scenario_store.snapshot().edges_version == 2

    fake_graph.create_cycle_with_seed_event.side_effect = None
    fake_graph.create_cycle_with_seed_event.return_value = SECOND_CYCLE_ID
    second_orchestrator = ScriptedProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="scripted-orchestrator",
        personas=all_personas,
        orchestrator_script=[SCENARIO_SEED_JSON, SCENARIO_MODIFIERS_JSON],
    )
    seen: list[tuple[int, str | None, int]] = []
    await run_scenario(orchestrator=second_orchestrator, on_round_complete=_recorder(scenario_store, seen))

    assert seen[0] == (1, SECOND_CYCLE_ID, 0)
    assert scenario_store.snapshot().edges_version == 2
