"""Cycle metadata is stamped when the Cycle is created, not only at completion."""

from __future__ import annotations

import pytest

from alphaswarm.graph import GraphStateManager
from alphaswarm.types import SignalType
from tests.support.mini_cycle import cypher, dec, write_mini_cycle

pytestmark = pytest.mark.neo4j


@pytest.mark.parametrize("num_rounds", [2, 3])
async def test_cycle_has_num_rounds_before_completion(
    graph_manager_test: GraphStateManager, num_rounds: int,
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
