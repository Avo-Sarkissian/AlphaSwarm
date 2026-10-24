"""Shock treatment split: half of each bracket sees the shock."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from alphaswarm.settings import AppSettings, SimulationSettings
from tests.engine.scenario import SCENARIO_SHOCK_TEXT, RunScenario, round_calls
from tests.inference.fakes import ScriptedProvider


def _persist_calls(graph: MagicMock) -> dict[int, Any]:
    return {int(call.args[1]): call for call in graph.persist_round.await_args_list}


def _metrics(graph: MagicMock) -> dict[str, Any]:
    return dict(graph.write_cycle_metrics.await_args.args[1])


async def test_split_shows_the_shock_to_half_of_each_bracket(
    run_scenario: RunScenario,
    scripted_worker: ScriptedProvider,
    fake_graph: MagicMock,
    scenario_settings: AppSettings,
) -> None:
    scenario_settings.simulation = SimulationSettings(shock_treatment_split=True)
    await run_scenario(shocks={2: SCENARIO_SHOCK_TEXT})
    calls = _persist_calls(fake_graph)

    assert calls[1].kwargs["shock_treated_ids"] is None
    treated = frozenset(calls[2].kwargs["shock_treated_ids"])
    assert len(treated) == 52
    assert frozenset(calls[3].kwargs["shock_treated_ids"]) == treated  # carried forward
    for round_num in (2, 3):
        for call in round_calls(scripted_worker, round_num):
            assert (SCENARIO_SHOCK_TEXT in call.messages[-1]["content"]) is (call.agent_id in treated)
    metrics = _metrics(fake_graph)
    assert metrics["r2_shock_treated_agents"] == 52
    assert metrics["r2_pivots_shock_treated"] + metrics["r2_pivots_shock_untreated"] == metrics["r2_flips"]


async def test_without_the_split_everyone_sees_the_shock(
    run_scenario: RunScenario, scripted_worker: ScriptedProvider, fake_graph: MagicMock
) -> None:
    await run_scenario(shocks={2: SCENARIO_SHOCK_TEXT})

    assert _persist_calls(fake_graph)[2].kwargs["shock_treated_ids"] is None
    assert all(SCENARIO_SHOCK_TEXT in c.messages[-1]["content"] for c in round_calls(scripted_worker, 2))
    assert "r2_shock_treated_agents" not in _metrics(fake_graph)


async def test_split_without_a_shock_changes_nothing(
    run_scenario: RunScenario, fake_graph: MagicMock, scenario_settings: AppSettings
) -> None:
    scenario_settings.simulation = SimulationSettings(shock_treatment_split=True)
    await run_scenario()

    assert all(c.kwargs["shock_treated_ids"] is None for c in _persist_calls(fake_graph).values())
