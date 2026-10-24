"""run_round: citations filtered to exposure, exposure and holdout persisted."""

from __future__ import annotations

from collections import Counter
from typing import Any
from unittest.mock import MagicMock

import pytest

from alphaswarm.settings import AppSettings, SimulationSettings
from alphaswarm.types import AgentDecision, AgentPersona
from tests.engine.scenario import RunScenario, round_calls
from tests.inference.fakes import DecisionFn, ScriptedCall, ScriptedProvider, default_decision_script


def _persist_calls(graph: MagicMock) -> dict[int, Any]:
    return {int(call.args[1]): call for call in graph.persist_round.await_args_list}


def _metrics(graph: MagicMock) -> dict[str, Any]:
    return dict(graph.write_cycle_metrics.await_args.args[1])


def _hallucinating(personas: list[AgentPersona]) -> DecisionFn:
    ids = [p.id for p in personas]

    def decide(agent_id: str, round_num: int, call: ScriptedCall) -> AgentDecision:
        base = default_decision_script(agent_id, round_num, call)
        if round_num < 2 or not call.shown_peer_ids:
            return base
        shown = call.shown_peer_ids[0]
        unshown = next(i for i in ids if i != agent_id and i not in call.shown_peer_ids)
        cited = [f" {shown.upper()} ", agent_id, "ghost_99", shown, unshown]
        return base.model_copy(update={"cited_agents": cited})

    return decide


async def test_hallucinated_citations_are_dropped_and_counted(
    run_scenario: RunScenario,
    make_scripted_worker: Any,
    fake_graph: MagicMock,
    all_personas: list[AgentPersona],
) -> None:
    """Unseen, self and duplicate ids never persist; each one is counted."""
    worker: ScriptedProvider = make_scripted_worker(_hallucinating(all_personas))
    result = await run_scenario(worker=worker)
    calls = _persist_calls(fake_graph)

    for round_num in (2, 3):
        shown_by_agent = {c.agent_id: c.shown_peer_ids for c in round_calls(worker, round_num)}
        invalid = calls[round_num].kwargs["citations_invalid"]
        for agent_id, decision in calls[round_num].args[2]:
            shown = shown_by_agent[agent_id]
            if shown:
                assert decision.cited_agents == [shown[0]]
                assert invalid[agent_id] == 4
            else:
                assert decision.cited_agents == []
        # The outcome feeds the next round's personal boost: it must hold the filtered
        # citations too, not the raw ones.
        outcome = result.outcome(round_num)
        assert outcome is not None
        assert dict(outcome.decisions) == dict(calls[round_num].args[2])
    metrics = _metrics(fake_graph)
    r2_invalid = sum(calls[2].kwargs["citations_invalid"].values())
    r2_valid = sum(len(d.cited_agents) for _, d in calls[2].args[2])
    assert metrics["r2_citations_invalid"] == r2_invalid > 0
    assert metrics["r2_citation_validity_rate"] == pytest.approx(r2_valid / (r2_valid + r2_invalid), abs=1e-6)
    assert all("ghost_99" not in d.cited_agents for c in calls.values() for _, d in c.args[2])


async def test_exposures_persist_what_each_reader_was_shown(
    run_scenario: RunScenario, scripted_worker: ScriptedProvider, fake_graph: MagicMock
) -> None:
    await run_scenario()
    calls = _persist_calls(fake_graph)

    assert set(map(tuple, calls[1].kwargs["exposures"].values())) == {()}
    for round_num in (2, 3):
        exposures = calls[round_num].kwargs["exposures"]
        for call in round_calls(scripted_worker, round_num):
            assert tuple(exposures[call.agent_id]) == call.shown_peer_ids


async def test_control_readers_see_no_peers_in_any_round(
    run_scenario: RunScenario,
    scripted_worker: ScriptedProvider,
    fake_graph: MagicMock,
    scenario_settings: AppSettings,
    all_personas: list[AgentPersona],
) -> None:
    scenario_settings.simulation = SimulationSettings(control_fraction=0.2)
    await run_scenario()
    calls = _persist_calls(fake_graph)
    control = frozenset(calls[1].kwargs["control_ids"])
    bracket_of = {p.id: p.bracket.value for p in all_personas}

    assert Counter(bracket_of[a] for a in control) == {
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
    assert all(frozenset(calls[r].kwargs["control_ids"]) == control for r in (2, 3))
    for round_num in (2, 3):
        for call in round_calls(scripted_worker, round_num):
            if call.agent_id in control:
                assert call.shown_peer_ids == ()
                assert "Your Round" in call.messages[-1]["content"]
            else:
                assert call.shown_peer_ids
    metrics = _metrics(fake_graph)
    assert metrics["r2_control_agents"] == 20
    for n in (2, 3):
        assert metrics[f"r{n}_flips_control"] + metrics[f"r{n}_flips_treated"] == metrics[f"r{n}_flips"]


async def test_cite_rates_are_reported_per_bracket(run_scenario: RunScenario, fake_graph: MagicMock) -> None:
    await run_scenario()
    metrics = _metrics(fake_graph)

    rates = {k: v for k, v in metrics.items() if k.startswith("r2_cite_rate_")}
    assert rates
    assert all(0.0 < v < 1.0 for v in rates.values())
