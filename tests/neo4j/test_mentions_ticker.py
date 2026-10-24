"""The cycle's MENTIONS edges carry the resolved ticker (docs/DECISIONS.md#adr-ticker-resolution)."""

from __future__ import annotations

import pytest

from alphaswarm.graph import GraphStateManager
from alphaswarm.types import EntityType, SeedEntity, SignalType
from tests.support.mini_cycle import cypher, dec, write_mini_cycle

pytestmark = pytest.mark.neo4j

ENTITIES = (
    SeedEntity(name="ZZZT Holdings", type=EntityType.COMPANY, relevance=0.9, sentiment=0.6, ticker="ZZZT"),
    SeedEntity(name="Industrial Automation", type=EntityType.SECTOR, relevance=0.5, sentiment=0.2),
)


async def test_mentions_carry_the_resolved_ticker(graph_manager_test: GraphStateManager) -> None:
    cycle_id = await write_mini_cycle(
        graph_manager_test,
        num_rounds=2,
        rounds={
            1: [("quants_01", dec(SignalType.BUY, rationale="ZZZT Holdings looks cheap"))],
            2: [("quants_01", dec(SignalType.BUY, rationale="ZZZT Holdings still looks cheap"))],
        },
        entities=ENTITIES,
    )
    rows = await cypher(
        graph_manager_test,
        "MATCH (:Cycle {cycle_id: $cid})-[m:MENTIONS]->(e:Entity) "
        "RETURN e.name AS name, m.ticker AS ticker ORDER BY name",
        cid=cycle_id,
    )
    assert rows == [
        {"name": "Industrial Automation", "ticker": None},
        {"name": "ZZZT Holdings", "ticker": "ZZZT"},
    ]
