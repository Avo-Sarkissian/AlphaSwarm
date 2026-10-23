"""Cycle metadata is stamped when the Cycle is created, not only at completion."""

from __future__ import annotations

import pytest

from alphaswarm.graph import GraphStateManager
from alphaswarm.types import BracketType, SignalType
from tests.support.mini_cycle import cypher, dec, write_mini_cycle

pytestmark = pytest.mark.neo4j


@pytest.mark.parametrize("num_rounds", [2, 3])
async def test_cycle_has_num_rounds_before_completion(
    graph_manager_test: GraphStateManager,
    num_rounds: int,
) -> None:
    cycle_id = await write_mini_cycle(
        graph_manager_test,
        num_rounds=num_rounds,
        rounds={1: [("quants_01", dec(SignalType.BUY))]},
    )

    rows = await cypher(
        graph_manager_test,
        "MATCH (c:Cycle {cycle_id: $id}) RETURN c.num_rounds AS num_rounds",
        id=cycle_id,
    )

    assert rows == [{"num_rounds": num_rounds}]


async def test_cycle_stores_modifiers_and_prompt_hash(graph_manager_test: GraphStateManager) -> None:
    cycle_id = await write_mini_cycle(
        graph_manager_test,
        num_rounds=2,
        rounds={1: [("quants_01", dec(SignalType.BUY))]},
        modifiers={BracketType.QUANTS: "fictional catalyst watcher", BracketType.DEGENS: "fictional meme scout"},
        prompt_template_hash="ab" * 32,
    )

    rows = await cypher(
        graph_manager_test,
        "MATCH (c:Cycle {cycle_id: $id}) RETURN c.modifiers_json AS modifiers, c.prompt_template_hash AS hash",
        id=cycle_id,
    )

    assert rows == [
        {
            "modifiers": '{"degens": "fictional meme scout", "quants": "fictional catalyst watcher"}',
            "hash": "ab" * 32,
        }
    ]


async def test_cycle_without_modifiers_has_no_property(graph_manager_test: GraphStateManager) -> None:
    cycle_id = await write_mini_cycle(
        graph_manager_test,
        num_rounds=2,
        rounds={1: [("quants_01", dec(SignalType.BUY))]},
    )

    rows = await cypher(
        graph_manager_test,
        "MATCH (c:Cycle {cycle_id: $id}) RETURN c.modifiers_json AS modifiers",
        id=cycle_id,
    )

    assert rows == [{"modifiers": None}]
