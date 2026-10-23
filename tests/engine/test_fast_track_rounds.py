"""Fast track: own prior and seeded no-peer holdout in both round blocks.

See docs/DECISIONS.md#adr-diverse-peer-context.
"""

from __future__ import annotations

from collections import Counter
from typing import Any
from unittest.mock import MagicMock

from alphaswarm.config import AppSettings, SimulationSettings
from alphaswarm.types import AgentPersona
from tests.engine.scenario import SCENARIO_RUMOR, RunScenario, round_calls
from tests.inference.fakes import ScriptedProvider

TWENTY_PERCENT = {
    "institutions": 4,
    "sell_side": 2,
    "event_driven": 2,
    "quants": 2,
    "degens": 3,
    "narrators": 2,
    "algos": 2,
    "macro": 1,
    "shorts": 1,
    "allocators": 1,
}


def _writes(graph: MagicMock) -> dict[int, Any]:
    """write_decisions calls keyed by round.

    The round comes from the keyword or positional round_num, like recorded_decisions.
    """
    return {
        int(c.kwargs["round_num"] if "round_num" in c.kwargs else c.args[2]): c
        for c in graph.write_decisions.await_args_list
    }


def _metrics(graph: MagicMock) -> dict[str, Any]:
    return dict(graph.write_cycle_metrics.await_args.args[1])


async def test_rounds_two_and_three_carry_the_own_prior(
    run_scenario: RunScenario, scripted_worker: ScriptedProvider, scenario_settings: AppSettings
) -> None:
    scenario_settings.simulation = SimulationSettings(own_prior_memory=True, control_fraction=0.0)
    await run_scenario()

    for round_num in (2, 3):
        marker = f"Your Round {round_num - 1} position: "
        calls = round_calls(scripted_worker, round_num)
        assert len(calls) == 100
        for call in calls:
            user = call.messages[-1]["content"]
            assert marker in user and user.index(marker) < user.index(SCENARIO_RUMOR)
            system_contents = [m["content"] for m in call.messages if m["role"] == "system"]
            assert len(system_contents) == 2  # persona prompt + peer context
            assert all(marker not in c for c in system_contents)
    assert len(round_calls(scripted_worker, 1)) == 100
    assert all("position: " not in c.messages[-1]["content"] for c in round_calls(scripted_worker, 1))


async def test_own_prior_memory_off_sends_no_prior(
    run_scenario: RunScenario, scripted_worker: ScriptedProvider, scenario_settings: AppSettings
) -> None:
    scenario_settings.simulation = SimulationSettings(own_prior_memory=False, control_fraction=0.0)
    await run_scenario()

    assert len(scripted_worker.calls_for("decision")) == 300
    assert all("position: " not in c.messages[-1]["content"] for c in scripted_worker.calls_for("decision"))


async def test_control_readers_see_no_peers_in_rounds_two_and_three(
    run_scenario: RunScenario,
    scripted_worker: ScriptedProvider,
    fake_graph: MagicMock,
    scenario_settings: AppSettings,
    all_personas: list[AgentPersona],
) -> None:
    scenario_settings.simulation = SimulationSettings(control_fraction=0.2)
    await run_scenario()
    writes = _writes(fake_graph)
    control = frozenset(writes[2].kwargs["control_ids"])
    bracket_of = {p.id: p.bracket.value for p in all_personas}

    assert Counter(bracket_of[a] for a in control) == TWENTY_PERCENT
    assert frozenset(writes[3].kwargs["control_ids"]) == control
    assert "control_ids" not in writes[1].kwargs
    for round_num in (2, 3):
        for call in round_calls(scripted_worker, round_num):
            if call.agent_id in control:
                assert call.shown_peer_ids == ()
                assert "Your Round" in call.messages[-1]["content"]
            else:
                assert call.shown_peer_ids
    metrics = _metrics(fake_graph)
    for n in (2, 3):
        assert metrics[f"r{n}_control_agents"] == 20
        assert metrics[f"r{n}_flips_control"] + metrics[f"r{n}_flips_treated"] == metrics[f"r{n}_flips"]


async def test_holdout_exposure_metrics_count_only_rendered_peers(
    run_scenario: RunScenario,
    scripted_worker: ScriptedProvider,
    fake_graph: MagicMock,
    scenario_settings: AppSettings,
    all_personas: list[AgentPersona],
) -> None:
    """Exposure is what a prompt rendered, so control readers add no slots and no readers."""
    scenario_settings.simulation = SimulationSettings(control_fraction=0.2)
    await run_scenario()
    metrics = _metrics(fake_graph)
    bracket_of = {p.id: p.bracket.value for p in all_personas}

    for n in (2, 3):
        shown = [call.shown_peer_ids for call in round_calls(scripted_worker, n)]
        slots = Counter(bracket_of[pid] for ids in shown for pid in ids)
        readers = Counter(b for ids in shown for b in {bracket_of[pid] for pid in ids})
        assert sum(1 for ids in shown if ids) == 80  # the 20 control readers saw none
        for bracket in set(bracket_of.values()):
            assert metrics[f"r{n}_exposure_{bracket}"] == slots[bracket]
            assert metrics[f"r{n}_readers_seeing_{bracket}"] == readers[bracket]
        assert metrics[f"r{n}_distinct_peers_shown"] == len({p for ids in shown for p in ids})


async def test_without_a_holdout_every_flip_is_treated(
    run_scenario: RunScenario, fake_graph: MagicMock, scenario_settings: AppSettings
) -> None:
    scenario_settings.simulation = SimulationSettings(control_fraction=0.0)
    await run_scenario()
    metrics = _metrics(fake_graph)

    for n in (2, 3):
        assert (metrics[f"r{n}_control_agents"], metrics[f"r{n}_flips_control"]) == (0, 0)
        assert metrics[f"r{n}_flips_treated"] == metrics[f"r{n}_flips"]
