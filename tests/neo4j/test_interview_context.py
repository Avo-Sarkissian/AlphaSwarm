"""Per-cycle decision narratives and interview context (docs/DECISIONS.md#p11-d-10)."""

from __future__ import annotations

import pytest

from alphaswarm.errors import AgentNotFoundError
from alphaswarm.graph import GraphStateManager
from alphaswarm.prompts.decision import JSON_OUTPUT_INSTRUCTIONS
from alphaswarm.types import BracketType, SignalType
from tests.support.mini_cycle import cypher, dec, write_mini_cycle

pytestmark = pytest.mark.neo4j

BUY, HOLD = SignalType.BUY, SignalType.HOLD


async def _two_rounds(gm: GraphStateManager, *agents: str) -> str:
    return await write_mini_cycle(
        gm,
        num_rounds=2,
        rounds={1: [(a, dec(BUY)) for a in agents], 2: [(a, dec(HOLD)) for a in agents]},
    )


async def test_decision_narrative_round_trip_on_final_round(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await _two_rounds(graph_manager_test, "quants_01")

    assert await graph_manager_test.read_decision_narrative(cycle_id, "quants_01") is None
    await graph_manager_test.write_decision_narrative(
        cycle_id,
        "quants_01",
        "Fictional arc: bought, then held.",
    )

    assert await graph_manager_test.read_decision_narrative(cycle_id, "quants_01") == (
        "Fictional arc: bought, then held."
    )
    rows = await cypher(
        graph_manager_test,
        "MATCH (:Agent {id: 'quants_01'})-[:MADE]->(d:Decision {cycle_id: $id}) "
        "RETURN d.round AS round, d.narrative AS narrative ORDER BY d.round",
        id=cycle_id,
    )
    assert rows == [
        {"round": 1, "narrative": None},
        {"round": 2, "narrative": "Fictional arc: bought, then held."},
    ]


async def test_narrative_write_without_decision_is_a_no_op(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await _two_rounds(graph_manager_test, "quants_01")

    await graph_manager_test.write_decision_narrative(cycle_id, "degens_09", "orphan")

    assert await graph_manager_test.read_decision_narrative(cycle_id, "degens_09") is None


async def test_only_remove_legacy_properties_drops_the_agent_level_narrative(
    graph_manager_test: GraphStateManager,
) -> None:
    await cypher(
        graph_manager_test,
        "MATCH (a:Agent {id: 'quants_01'}) SET a.decision_narrative = 'legacy text'",
    )
    count = "MATCH (a:Agent) WHERE a.decision_narrative IS NOT NULL RETURN count(a) AS n"

    try:
        await graph_manager_test.ensure_schema()
        assert await cypher(graph_manager_test, count) == [{"n": 1}]

        await graph_manager_test.remove_legacy_properties()
        assert await cypher(graph_manager_test, count) == [{"n": 0}]
    finally:
        await cypher(graph_manager_test, "MATCH (a:Agent {id: 'quants_01'}) REMOVE a.decision_narrative")


async def test_interview_prompt_contains_the_cycles_focus_line(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await write_mini_cycle(
        graph_manager_test,
        num_rounds=2,
        rounds={
            1: [("quants_01", dec(BUY))],
            2: [("quants_01", dec(HOLD, cited=["sell_side_01"]))],
        },
        modifiers={BracketType.QUANTS: "fictional catalyst watcher"},
    )

    ctx = await graph_manager_test.read_agent_interview_context("quants_01", cycle_id)

    assert "This cycle you are focused as a fictional catalyst watcher." in (ctx.interview_system_prompt)
    assert JSON_OUTPUT_INSTRUCTIONS not in ctx.interview_system_prompt
    assert [(d.round_num, d.signal, d.cited_agents) for d in ctx.decisions] == [
        (1, "buy", ()),
        (2, "hold", ("sell_side_01",)),
    ]


async def test_interview_context_for_legacy_cycle_without_modifiers(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await _two_rounds(graph_manager_test, "quants_01")
    await cypher(
        graph_manager_test,
        "MATCH (a:Agent {id: 'quants_01'}) SET a.decision_narrative = 'another cycle text'",
    )
    try:
        ctx = await graph_manager_test.read_agent_interview_context("quants_01", cycle_id)
    finally:
        await cypher(
            graph_manager_test,
            "MATCH (a:Agent {id: 'quants_01'}) REMOVE a.decision_narrative",
        )

    assert "This cycle you are focused" not in ctx.interview_system_prompt
    assert ctx.decision_narrative == ""


async def test_interview_narrative_comes_from_this_cycles_final_decision(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_a = await _two_rounds(graph_manager_test, "quants_01")
    cycle_b = await _two_rounds(graph_manager_test, "quants_01")
    await graph_manager_test.write_decision_narrative(cycle_a, "quants_01", "Arc for cycle A.")

    ctx_a = await graph_manager_test.read_agent_interview_context("quants_01", cycle_a)
    ctx_b = await graph_manager_test.read_agent_interview_context("quants_01", cycle_b)

    assert ctx_a.decision_narrative == "Arc for cycle A."
    assert ctx_b.decision_narrative == ""


async def test_unknown_agent_raises_agent_not_found(graph_manager_test: GraphStateManager) -> None:
    cycle_id = await _two_rounds(graph_manager_test, "quants_01")

    with pytest.raises(AgentNotFoundError):
        await graph_manager_test.read_agent_interview_context("nobody_99", cycle_id)


async def test_agent_outside_the_roster_raises_agent_not_found(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await _two_rounds(graph_manager_test, "quants_01")
    await cypher(
        graph_manager_test,
        "MERGE (:Agent {id: 'zz_legacy_01', name: 'Legacy 1', bracket: 'legacy_suits'})",
    )
    try:
        with pytest.raises(AgentNotFoundError):
            await graph_manager_test.read_agent_interview_context("zz_legacy_01", cycle_id)
    finally:
        await cypher(graph_manager_test, "MATCH (a:Agent {id: 'zz_legacy_01'}) DETACH DELETE a")
