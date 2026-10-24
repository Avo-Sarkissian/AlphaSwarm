"""Deleting one cycle removes only its data on neo4j-test."""

from __future__ import annotations

from typing import Any

import pytest

from alphaswarm.graph import GraphStateManager
from alphaswarm.types import EntityType, SeedEntity, SignalType
from tests.support.mini_cycle import MINI_ENTITIES, cypher, dec, write_mini_cycle

pytestmark = pytest.mark.neo4j

ONLY_HERE = SeedEntity(name="QZZX Sensors", type=EntityType.COMPANY, relevance=0.4, sentiment=0.1)
SHOCK = "QQQX Robotics says the ZZZT talks ended without a deal."
ROUNDS = {
    1: [("quants_01", dec(SignalType.BUY)), ("degens_01", dec(SignalType.SELL))],
    2: [
        ("quants_01", dec(SignalType.SELL, cited=["degens_01"])),
        ("degens_01", dec(SignalType.SELL, cited=["quants_01"])),
    ],
}


async def _count(gm: GraphStateManager, query: str, **params: Any) -> int:
    return int((await cypher(gm, query, **params))[0]["n"])


async def _others(gm: GraphStateManager, doomed: str) -> dict[str, int]:
    """Counts of everything that does not belong to *doomed*, across all cycles in the database."""
    queries = {
        "cycles": "MATCH (c:Cycle) WHERE c.cycle_id <> $c RETURN count(c) AS n",
        "decisions": "MATCH (d:Decision) WHERE d.cycle_id <> $c RETURN count(d) AS n",
        "episodes": "MATCH (re:RationaleEpisode) WHERE re.cycle_id <> $c RETURN count(re) AS n",
        "edges": "MATCH ()-[r:INFLUENCED_BY]->() WHERE r.cycle_id <> $c RETURN count(r) AS n",
        "shocks": "MATCH (c:Cycle)-[:HAS_SHOCK]->(se:ShockEvent) WHERE c.cycle_id <> $c RETURN count(se) AS n",
        "mentions": "MATCH (c:Cycle)-[m:MENTIONS]->(:Entity) WHERE c.cycle_id <> $c RETURN count(m) AS n",
        "cited": "MATCH (d:Decision)-[r:CITED]->(:Agent) WHERE d.cycle_id <> $c RETURN count(r) AS n",
    }
    return {key: await _count(gm, query, c=doomed) for key, query in queries.items()}


async def test_delete_removes_only_that_cycle(graph_manager_test: GraphStateManager) -> None:
    gm = graph_manager_test
    doomed = await write_mini_cycle(
        gm, num_rounds=2, rounds=ROUNDS, entities=(*MINI_ENTITIES, ONLY_HERE), shock=(2, SHOCK)
    )
    kept = await write_mini_cycle(gm, num_rounds=2, rounds=ROUNDS)
    agents_before = await _count(gm, "MATCH (a:Agent) RETURN count(a) AS n")
    kept_decisions = await _count(gm, "MATCH (d:Decision {cycle_id: $c}) RETURN count(d) AS n", c=kept)
    kept_edges = await _count(gm, "MATCH ()-[r:INFLUENCED_BY {cycle_id: $c}]->() RETURN count(r) AS n", c=kept)
    assert kept_edges > 0

    others_before = await _others(gm, doomed)

    removed = await gm.delete_cycle(doomed, batch_size=2)

    assert removed == 1 + 4 + 4 + 1  # Cycle, 4 decisions, 4 episodes, 1 shock
    for query in (
        "MATCH (c:Cycle {cycle_id: $c}) RETURN count(c) AS n",
        "MATCH (d:Decision {cycle_id: $c}) RETURN count(d) AS n",
        "MATCH (re:RationaleEpisode {cycle_id: $c}) RETURN count(re) AS n",
        "MATCH ()-[r:INFLUENCED_BY {cycle_id: $c}]->() RETURN count(r) AS n",
    ):
        assert await _count(gm, query, c=doomed) == 0, query
    assert await _count(gm, "MATCH (se:ShockEvent {shock_text: $t}) RETURN count(se) AS n", t=SHOCK) == 0
    assert await _count(gm, "MATCH (e:Entity {name: 'QZZX Sensors'}) RETURN count(e) AS n") == 0
    assert await _count(gm, "MATCH (e:Entity {name: 'ZZZT Holdings'}) RETURN count(e) AS n") == 1
    assert await _count(gm, "MATCH (a:Agent) RETURN count(a) AS n") == agents_before
    assert await _count(gm, "MATCH (d:Decision {cycle_id: $c}) RETURN count(d) AS n", c=kept) == kept_decisions
    assert await _count(gm, "MATCH ()-[r:INFLUENCED_BY {cycle_id: $c}]->() RETURN count(r) AS n", c=kept) == kept_edges
    assert await _others(gm, doomed) == others_before  # every other cycle in the database survives


async def test_delete_twice_is_a_no_op(graph_manager_test: GraphStateManager) -> None:
    doomed = await write_mini_cycle(graph_manager_test, num_rounds=2, rounds=ROUNDS)
    assert await graph_manager_test.delete_cycle(doomed) > 0
    assert await graph_manager_test.delete_cycle(doomed) == 0
