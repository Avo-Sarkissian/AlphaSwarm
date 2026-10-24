"""Round 1 retest: a second draw of Round 1 gives the noise floor."""

from __future__ import annotations

from collections import Counter
from typing import Any
from unittest.mock import MagicMock

from alphaswarm.inference.types import ProviderRole
from alphaswarm.manifest import RETEST_ROUND, derive_call_seed
from alphaswarm.settings import AppSettings, SimulationSettings
from alphaswarm.types import AgentDecision, AgentPersona, SignalType
from tests.engine.scenario import (
    SCENARIO_MODIFIERS_JSON,
    SCENARIO_SEED_JSON,
    RunScenario,
    round_calls,
)
from tests.inference.fakes import DecisionFn, ScriptedCall, ScriptedProvider, default_decision_script


def _metrics(graph: MagicMock) -> dict[str, Any]:
    return dict(graph.write_cycle_metrics.await_args.args[1])


def _fresh_orchestrator(personas: list[AgentPersona]) -> ScriptedProvider:
    """The scripted orchestrator's replies are consumed once, so a second run needs its own."""
    return ScriptedProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="scripted-orchestrator",
        personas=personas,
        orchestrator_script=[SCENARIO_SEED_JSON, SCENARIO_MODIFIERS_JSON],
    )


def _later_rounds(graph: MagicMock, start: int) -> list[object]:
    """Decisions persisted for Rounds 2+ from call ``start`` on."""
    return [c.args[2] for c in graph.persist_round.await_args_list[start:] if c.args[1] >= 2]


def _second_draw_flips(flip_ids: frozenset[str], first: dict[str, SignalType]) -> DecisionFn:
    """Round 1 answers change on the second draw for ``flip_ids`` only."""
    draws: Counter[tuple[str, int]] = Counter()

    def decide(agent_id: str, round_num: int, call: ScriptedCall) -> AgentDecision:
        base = default_decision_script(agent_id, round_num, call)
        draws[(agent_id, round_num)] += 1
        if round_num != 1:
            return base
        if draws[(agent_id, 1)] == 1:
            first[agent_id] = base.signal
            return base
        if agent_id in flip_ids:
            other = SignalType.SELL if base.signal != SignalType.SELL else SignalType.BUY
            return base.model_copy(update={"signal": other})
        return base

    return decide


async def test_retest_is_off_by_default(
    run_scenario: RunScenario, scripted_worker: ScriptedProvider, fake_graph: MagicMock
) -> None:
    await run_scenario()

    assert len(round_calls(scripted_worker, 1)) == 100
    assert not any(key.startswith("r1_retest_") for key in _metrics(fake_graph))


async def test_retest_redraws_round_one_with_fresh_seeds_and_reports_the_noise_floor(
    run_scenario: RunScenario,
    make_scripted_worker: Any,
    fake_graph: MagicMock,
    scenario_settings: AppSettings,
    all_personas: list[AgentPersona],
) -> None:
    scenario_settings.simulation = SimulationSettings(sim_seed=4242, retest_round1=True)
    flip_ids = frozenset(p.id for p in all_personas[:7])
    first: dict[str, SignalType] = {}
    worker: ScriptedProvider = make_scripted_worker(_second_draw_flips(flip_ids, first))

    await run_scenario(worker=worker)

    r1 = round_calls(worker, 1)
    assert len(r1) == 200
    assert {(c.agent_id, c.kwargs["seed"]) for c in r1} == (
        {(p.id, derive_call_seed(4242, p.id, 1)) for p in all_personas}
        | {(p.id, derive_call_seed(4242, p.id, RETEST_ROUND)) for p in all_personas}
    )
    persisted = next(c for c in fake_graph.persist_round.await_args_list if c.args[1] == 1)
    assert len(persisted.args[2]) == 100
    assert {agent_id: d.signal for agent_id, d in persisted.args[2]} == first
    metrics = _metrics(fake_graph)
    assert metrics["r1_retest_pairs"] == 100
    assert metrics["r1_retest_flips"] == 7
    assert metrics["r1_retest_flip_rate"] == 0.07
    assert len(round_calls(worker, 2)) == 100
    assert len(round_calls(worker, 3)) == 100


async def test_retest_does_not_change_later_rounds(
    run_scenario: RunScenario,
    make_scripted_worker: Any,
    fake_graph: MagicMock,
    scenario_settings: AppSettings,
    all_personas: list[AgentPersona],
) -> None:
    scenario_settings.simulation = SimulationSettings(sim_seed=4242)
    await run_scenario(worker=make_scripted_worker())
    without = _later_rounds(fake_graph, 0)
    start = len(fake_graph.persist_round.await_args_list)

    scenario_settings.simulation = SimulationSettings(sim_seed=4242, retest_round1=True)
    await run_scenario(worker=make_scripted_worker(), orchestrator=_fresh_orchestrator(all_personas))

    assert _later_rounds(fake_graph, start) == without
