"""_persist_round_records assembles one persist_round call per round."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from alphaswarm.episodes import EntityRef
from alphaswarm.simulation import _persist_round_records
from alphaswarm.types import AgentDecision, AgentPersona, SignalType
from tests.support.graph_fakes import fake_persist_round


async def test_episodes_carry_peer_context_flip_type_and_entity_matches(
    all_personas: list[AgentPersona],
) -> None:
    personas = all_personas[:2]
    a, b = personas[0].id, personas[1].id
    prev = [
        (a, AgentDecision(signal=SignalType.BUY, confidence=0.7)),
        (b, AgentDecision(signal=SignalType.SELL, confidence=0.6)),
    ]
    decisions = [
        (a, AgentDecision(signal=SignalType.SELL, confidence=0.5, rationale="ZZZT Holdings overpays")),
        (b, AgentDecision(signal=SignalType.SELL, confidence=0.6, rationale="no change")),
    ]
    graph = AsyncMock()
    graph.persist_round = AsyncMock(side_effect=fake_persist_round)

    result = await _persist_round_records(
        graph,
        "c1",
        2,
        decisions,
        personas=personas,
        peer_contexts=["peer block for a", None],
        prev_decisions=prev,
        entities=[EntityRef("ZZZT Holdings", "company")],
    )

    graph.persist_round.assert_awaited_once()
    call = graph.persist_round.await_args
    assert call.args[:2] == ("c1", 2)
    episodes = call.kwargs["episodes"]
    assert [e.peer_context_received for e in episodes] == ["peer block for a", ""]
    assert [e.flip_type for e in episodes] == ["buy_to_sell", "none"]
    assert [e.decision_id for e in episodes] == list(call.kwargs["decision_ids"])
    matches = call.kwargs["entity_matches"]
    assert [(m.decision_id, m.entity_name) for m in matches] == [(episodes[0].decision_id, "ZZZT Holdings")]
    assert result.decision_ids == tuple(call.kwargs["decision_ids"])


async def test_round_1_has_no_peers_and_no_flips(all_personas: list[AgentPersona]) -> None:
    personas = all_personas[:1]
    decisions = [(personas[0].id, AgentDecision(signal=SignalType.HOLD, confidence=0.5))]
    graph = AsyncMock()
    graph.persist_round = AsyncMock(side_effect=fake_persist_round)

    await _persist_round_records(
        graph,
        "c1",
        1,
        decisions,
        personas=personas,
        peer_contexts=None,
        prev_decisions=None,
        entities=[],
    )
    (episode,) = graph.persist_round.await_args.kwargs["episodes"]
    assert (episode.peer_context_received, episode.flip_type, episode.round_num) == ("", "none", 1)


async def test_control_ids_are_forwarded_to_persist_round(all_personas: list[AgentPersona]) -> None:
    personas = all_personas[:2]
    decisions = [(p.id, AgentDecision(signal=SignalType.HOLD, confidence=0.5)) for p in personas]
    graph = AsyncMock()
    graph.persist_round = AsyncMock(side_effect=fake_persist_round)

    await _persist_round_records(
        graph,
        "c1",
        2,
        decisions,
        personas=personas,
        peer_contexts=[None, None],
        prev_decisions=None,
        entities=[],
        control_ids=frozenset({personas[1].id}),
    )
    assert graph.persist_round.await_args.kwargs["control_ids"] == frozenset({personas[1].id})


async def test_misaligned_peer_contexts_fail_loudly(all_personas: list[AgentPersona]) -> None:
    graph = AsyncMock()
    graph.persist_round = AsyncMock(side_effect=fake_persist_round)
    with pytest.raises(ValueError):
        await _persist_round_records(
            graph,
            "c1",
            2,
            [],
            personas=all_personas[:2],
            peer_contexts=["only one"],
            prev_decisions=None,
            entities=[],
        )
