"""Dead writes are gone: no Post, no FOR edge, no duplicated episode rationale.

See docs/DECISIONS.md#adr-neo4j-schema.
"""

from __future__ import annotations

import pytest

from alphaswarm.graph import GraphStateManager
from alphaswarm.types import SignalType
from tests.support.mini_cycle import cypher, dec, write_mini_cycle

pytestmark = pytest.mark.neo4j


async def test_persisted_round_has_no_for_edge_or_episode_rationale(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await write_mini_cycle(
        graph_manager_test,
        num_rounds=2,
        rounds={1: [("quants_01", dec(SignalType.BUY, rationale="fictional rationale"))]},
    )

    rows = await cypher(
        graph_manager_test,
        """
        MATCH (d:Decision {cycle_id: $id})
        OPTIONAL MATCH (d)-[f:FOR]->(:Cycle)
        OPTIONAL MATCH (d)-[:HAS_EPISODE]->(re:RationaleEpisode)
        RETURN d.rationale AS rationale, count(f) AS for_edges, count(re) AS episodes,
               collect(re.rationale) AS episode_rationales
        """,
        id=cycle_id,
    )
    posts = await cypher(
        graph_manager_test,
        "MATCH (p:Post {cycle_id: $id}) RETURN count(p) AS n",
        id=cycle_id,
    )

    assert rows == [{"rationale": "fictional rationale", "for_edges": 0, "episodes": 1, "episode_rationales": []}]
    assert posts == [{"n": 0}]
