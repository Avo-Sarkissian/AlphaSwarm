"""Deterministic run_simulation scenarios: rounds, shocks and round persistence."""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable, Sequence
from unittest.mock import MagicMock

from alphaswarm.config import AppSettings, SimulationSettings
from alphaswarm.episodes import EntityMatch, EpisodeRecord, compute_flip_type
from alphaswarm.graph import PersistRoundResult
from alphaswarm.types import AgentDecision, AgentPersona, SignalType, SimulationPhase
from alphaswarm.worker import PEER_FENCE_CLOSE, PEER_FENCE_OPEN
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
from tests.inference.fakes import ScriptedCall, ScriptedProvider, default_decision_script
from tests.support.golden import assert_golden
from tests.support.graph_fakes import SCENARIO_ENTITIES, fake_persist_round

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
# Rounds 2+ also lead the user message with the reader's fenced peer block
# (docs/DECISIONS.md#adr-security-2026-08): an intro line, the fence, a closing line.
PEER_FENCE_BLOCK = re.compile(
    rf"^[^\n]*\n{re.escape(PEER_FENCE_OPEN)}\n(?P<body>.*?)\n{re.escape(PEER_FENCE_CLOSE)}\n[^\n]*\n\n",
    re.DOTALL,
)


def _metrics(fake_graph: MagicMock) -> dict[str, object]:
    return dict(fake_graph.write_cycle_metrics.await_args.args[1])


def _user_messages(worker: ScriptedProvider, round_num: int) -> set[str]:
    return {
        OWN_PRIOR_PREFIX.sub("", PEER_FENCE_BLOCK.sub("", c.messages[-1]["content"], count=1), count=1)
        for c in round_calls(worker, round_num)
    }


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
    assert len(round_calls(scripted_worker, 3)) == 100
    assert all(SHOCK_SUFFIX in message for message in _user_messages(scripted_worker, 3))


QQQX = next(e for e in SCENARIO_ENTITIES if e.name == "QQQX Robotics")


def _names_qqqx(agent_id: str, round_num: int) -> bool:
    """A different third of the agents names QQQX Robotics in each round."""
    return int(agent_id[-2:]) % 3 == round_num % 3


def _decide_naming_qqqx(agent_id: str, round_num: int, call: ScriptedCall) -> AgentDecision:
    decision = default_decision_script(agent_id, round_num, call)
    if not _names_qqqx(agent_id, round_num):
        return decision
    return decision.model_copy(update={"rationale": f"{decision.rationale}; watching {QQQX.name}"})


def _peer_block(call: ScriptedCall) -> str:
    """The peer block one decision call carried, "" when it had none."""
    blocks = [
        match.group("body")
        for message in call.messages
        if message["role"] == "user" and (match := PEER_FENCE_BLOCK.match(message["content"]))
    ]
    assert len(blocks) <= 1
    return blocks[0] if blocks else ""


async def _drop_round_num_citations(
    cycle_id: str,
    round_num: int,
    decisions: Sequence[tuple[str, AgentDecision]],
    *,
    decision_ids: Sequence[str],
    episodes: Sequence[EpisodeRecord],
    entity_matches: Sequence[EntityMatch],
    **later_kwargs: object,
) -> PersistRoundResult:
    """fake_persist_round, reporting round_num dropped citations so every round's count differs."""
    result = await fake_persist_round(
        cycle_id,
        round_num,
        decisions,
        decision_ids=decision_ids,
        episodes=episodes,
        entity_matches=entity_matches,
        **later_kwargs,
    )
    return dataclasses.replace(result, citations_dropped=round_num)


async def test_each_round_is_persisted_from_its_own_rationales_peers_and_counts(
    run_scenario: RunScenario,
    make_scripted_worker: Callable[..., ScriptedProvider],
    fake_graph: MagicMock,
    scenario_settings: AppSettings,
) -> None:
    """run_simulation feeds every round's persist_round call from that round (docs/DECISIONS.md#p4-d-08).

    REFERENCES come from the round's rationales and the cycle's entities, each episode
    stores the peer block its reader was shown (none for the holdout), flips compare
    with the round before, and each round's dropped citations reach its own metric key.
    """
    scenario_settings.simulation = SimulationSettings(control_fraction=0.2)
    fake_graph.persist_round.side_effect = _drop_round_num_citations
    worker = make_scripted_worker(_decide_naming_qqqx)
    await run_scenario(worker=worker)

    fake_graph.read_cycle_entities.assert_awaited_once_with(SCENARIO_CYCLE_ID)
    calls = {int(c.args[1]): c for c in fake_graph.persist_round.await_args_list}
    assert sorted(calls) == [1, 2, 3]
    previous: dict[str, SignalType] = {}
    for round_num, call in sorted(calls.items()):
        decisions: list[tuple[str, AgentDecision]] = list(call.args[2])
        decision_ids = list(call.kwargs["decision_ids"])
        assert call.kwargs["entity_matches"] == [
            EntityMatch(did, QQQX.name, QQQX.type, "token")
            for did, (agent_id, _) in zip(decision_ids, decisions, strict=True)
            if _names_qqqx(agent_id, round_num)
        ]
        shown = {c.agent_id: _peer_block(c) for c in round_calls(worker, round_num)}
        assert sum(1 for block in shown.values() if block) == (0 if round_num == 1 else 80)
        episodes: list[EpisodeRecord] = list(call.kwargs["episodes"])
        assert {e.agent_id: e.peer_context_received for e in episodes} == shown
        assert [e.flip_type for e in episodes] == [
            compute_flip_type(previous.get(agent_id), decision.signal).value for agent_id, decision in decisions
        ]
        previous = {agent_id: decision.signal for agent_id, decision in decisions}
    metrics = dict(fake_graph.write_cycle_metrics.await_args.args[1])
    assert [metrics[f"r{n}_citations_dropped"] for n in (1, 2, 3)] == [1, 2, 3]
