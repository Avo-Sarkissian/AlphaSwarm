"""Deterministic run_simulation scenarios: rounds and shocks."""

from __future__ import annotations

import re
from unittest.mock import MagicMock

from alphaswarm.types import AgentPersona, SimulationPhase
from tests.engine.scenario import (
    SCENARIO_CYCLE_ID,
    SCENARIO_RUMOR,
    SCENARIO_SHOCK_TEXT,
    RecordingStateStore,
    RunScenario,
    persisted_rounds,
    round_calls,
    scenario_summary,
)
from tests.inference.fakes import ScriptedProvider
from tests.support.golden import assert_golden

THREE_ROUND_PHASES = [
    SimulationPhase.IDLE,
    SimulationPhase.SEEDING,
    SimulationPhase.ROUND_1,
    SimulationPhase.ROUND_2,
    SimulationPhase.ROUND_3,
    SimulationPhase.FINALIZING,
    SimulationPhase.COMPLETE,
]
TWO_ROUND_PHASES = [p for p in THREE_ROUND_PHASES if p is not SimulationPhase.ROUND_3]
SHOCK_SUFFIX = f"\n\n[MARKET SHOCK]: {SCENARIO_SHOCK_TEXT}"
# Rounds 2-3 prefix the reader's own prior; its presence and position are pinned in
# tests/engine/test_fast_track_rounds.py (docs/DECISIONS.md#adr-diverse-peer-context).
OWN_PRIOR_PREFIX = re.compile(r"^Your Round \d+ position: [^\n]*\n\n")


def _metrics(fake_graph: MagicMock) -> dict[str, object]:
    return dict(fake_graph.write_cycle_metrics.await_args.args[1])


def _user_messages(worker: ScriptedProvider, round_num: int) -> set[str]:
    return {OWN_PRIOR_PREFIX.sub("", c.messages[-1]["content"], count=1) for c in round_calls(worker, round_num)}


def _summary(
    store: RecordingStateStore,
    worker: ScriptedProvider,
    graph: MagicMock,
    personas: list[AgentPersona],
) -> dict[str, object]:
    return scenario_summary(store=store, worker=worker, graph=graph, personas=personas)


async def test_three_round_scenario(
    run_scenario: RunScenario,
    scenario_store: RecordingStateStore,
    scripted_worker: ScriptedProvider,
    fake_graph: MagicMock,
    all_personas: list[AgentPersona],
) -> None:
    result = await run_scenario()
    assert scenario_store.phases == THREE_ROUND_PHASES
    assert persisted_rounds(fake_graph) == [1, 2, 3]
    assert len(result.round3_decisions) == 100
    metrics = _metrics(fake_graph)
    assert (metrics["num_rounds"], metrics["r2_flips"], metrics["r3_flips"]) == (3, 65, 71)
    assert (metrics["final_buy"], metrics["final_sell"], metrics["final_hold"]) == (35, 26, 39)
    assert all(_user_messages(scripted_worker, r) == {SCENARIO_RUMOR} for r in (1, 2, 3))
    assert_golden(
        "scenarios/three_rounds.json",
        _summary(scenario_store, scripted_worker, fake_graph, all_personas),
    )


async def test_two_round_scenario(
    run_scenario: RunScenario,
    scenario_store: RecordingStateStore,
    scripted_worker: ScriptedProvider,
    fake_graph: MagicMock,
    all_personas: list[AgentPersona],
) -> None:
    result = await run_scenario(num_rounds=2)
    assert scenario_store.phases == TWO_ROUND_PHASES
    assert persisted_rounds(fake_graph) == [1, 2]
    assert result.round3_decisions == ()
    assert len(scripted_worker.calls_for("decision")) == 200
    metrics = _metrics(fake_graph)
    assert (metrics["num_rounds"], metrics["r2_flips"], metrics["r3_flips"]) == (2, 65, 0)
    assert (metrics["final_buy"], metrics["final_sell"], metrics["final_hold"]) == (37, 26, 37)
    assert_golden(
        "scenarios/two_rounds.json",
        _summary(scenario_store, scripted_worker, fake_graph, all_personas),
    )


async def test_shock_before_round_2(
    run_scenario: RunScenario,
    scenario_store: RecordingStateStore,
    scripted_worker: ScriptedProvider,
    fake_graph: MagicMock,
    all_personas: list[AgentPersona],
) -> None:
    await run_scenario(shocks={2: SCENARIO_SHOCK_TEXT})
    assert _user_messages(scripted_worker, 1) == {SCENARIO_RUMOR}
    assert _user_messages(scripted_worker, 2) == {SCENARIO_RUMOR + SHOCK_SUFFIX}
    fake_graph.write_shock_event.assert_awaited_once_with(
        SCENARIO_CYCLE_ID, SCENARIO_SHOCK_TEXT, injected_before_round=2
    )
    assert_golden(
        "scenarios/shock_before_r2.json",
        _summary(scenario_store, scripted_worker, fake_graph, all_personas),
    )


async def test_shock_before_round_3(
    run_scenario: RunScenario,
    scenario_store: RecordingStateStore,
    scripted_worker: ScriptedProvider,
    fake_graph: MagicMock,
    all_personas: list[AgentPersona],
) -> None:
    await run_scenario(shocks={3: SCENARIO_SHOCK_TEXT})
    assert _user_messages(scripted_worker, 2) == {SCENARIO_RUMOR}
    assert _user_messages(scripted_worker, 3) == {SCENARIO_RUMOR + SHOCK_SUFFIX}
    fake_graph.write_shock_event.assert_awaited_once_with(
        SCENARIO_CYCLE_ID, SCENARIO_SHOCK_TEXT, injected_before_round=3
    )
    assert_golden(
        "scenarios/shock_before_r3.json",
        _summary(scenario_store, scripted_worker, fake_graph, all_personas),
    )


async def test_shock_before_round_2_is_carried_into_round_3(
    run_scenario: RunScenario, scripted_worker: ScriptedProvider
) -> None:
    await run_scenario(shocks={2: SCENARIO_SHOCK_TEXT})
    assert all(SHOCK_SUFFIX in message for message in _user_messages(scripted_worker, 3))
