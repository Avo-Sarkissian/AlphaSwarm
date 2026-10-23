"""Schema statements apply over a legacy schema and are idempotent.

See docs/DECISIONS.md#adr-neo4j-schema.
"""

from __future__ import annotations

import uuid

import pytest

from alphaswarm.episodes import EpisodeRecord
from alphaswarm.errors import Neo4jWriteError
from alphaswarm.graph import GraphStateManager
from alphaswarm.types import SignalType
from tests.support.mini_cycle import cypher, dec, write_mini_cycle

pytestmark = pytest.mark.neo4j

NEW_INDEXES = {
    "decision_cycle_round",
    "decision_cycle",
    "influenced_by_cycle_round",
    "cycle_created",
    "cycle_status",
}
DROPPED = {"agent_id_idx", "decision_id_idx", "post_cycle_round", "post_id_idx", "episode_cycle_round"}


async def _index_names(gm: GraphStateManager) -> set[str]:
    return {r["name"] for r in await cypher(gm, "SHOW INDEXES YIELD name RETURN name")}


async def _constraint_names(gm: GraphStateManager) -> set[str]:
    return {r["name"] for r in await cypher(gm, "SHOW CONSTRAINTS YIELD name RETURN name")}


async def test_schema_statements_apply_over_legacy_indexes(
    graph_manager_test: GraphStateManager,
) -> None:
    gm = graph_manager_test
    await cypher(gm, "DROP CONSTRAINT decision_id_unique IF EXISTS")
    await cypher(gm, "CREATE INDEX decision_id_idx IF NOT EXISTS FOR (d:Decision) ON (d.decision_id)")
    await cypher(gm, "CREATE INDEX post_id_idx IF NOT EXISTS FOR (p:Post) ON (p.post_id)")
    await cypher(
        gm,
        "CREATE INDEX episode_cycle_round IF NOT EXISTS FOR (re:RationaleEpisode) ON (re.cycle_id, re.round)",
    )

    await gm.ensure_schema()
    await gm.ensure_schema()  # idempotent

    indexes = await _index_names(gm)
    assert indexes >= NEW_INDEXES
    assert indexes.isdisjoint(DROPPED)
    assert "decision_id_unique" in await _constraint_names(gm)


async def test_duplicate_decision_id_is_rejected(graph_manager_test: GraphStateManager) -> None:
    cycle_id = await write_mini_cycle(
        graph_manager_test,
        num_rounds=2,
        rounds={1: [("quants_01", dec(SignalType.BUY))]},
    )
    existing = await cypher(
        graph_manager_test,
        "MATCH (d:Decision {cycle_id: $id}) RETURN d.decision_id AS id",
        id=cycle_id,
    )
    decision_id = existing[0]["id"]
    episode = EpisodeRecord(
        decision_id=decision_id,
        agent_id="quants_02",
        rationale="dup",
        peer_context_received="",
        flip_type="none",
        round_num=2,
        cycle_id=cycle_id,
    )

    with pytest.raises(Neo4jWriteError):
        await graph_manager_test.persist_round(
            cycle_id,
            2,
            [("quants_02", dec(SignalType.SELL))],
            decision_ids=[decision_id],
            episodes=[episode],
            entity_matches=[],
        )


async def test_existing_duplicate_decision_ids_never_block_startup(
    graph_manager_test: GraphStateManager,
) -> None:
    """Duplicates leave the plain index in place; removing them lets the constraint in."""
    gm = graph_manager_test
    # A cycle id no fixture keeps, so the fixture's scoped cleanup removes these nodes too.
    cycle_id = f"dup-{uuid.uuid4()}"
    shared_id = str(uuid.uuid4())
    await cypher(gm, "DROP CONSTRAINT decision_id_unique IF EXISTS")
    await cypher(
        gm,
        "UNWIND range(1, 2) AS i CREATE (:Decision {decision_id: $did, cycle_id: $cid, round: i})",
        did=shared_id,
        cid=cycle_id,
    )

    await gm.ensure_schema()  # must not raise over existing duplicates

    assert "decision_id_unique" not in await _constraint_names(gm)
    assert "decision_id_idx" in await _index_names(gm)
    rows = await cypher(gm, "MATCH (d:Decision {decision_id: $did}) RETURN count(d) AS n", did=shared_id)
    assert rows == [{"n": 2}]  # no data deleted

    await cypher(gm, "MATCH (d:Decision {cycle_id: $cid}) DETACH DELETE d", cid=cycle_id)
    await gm.ensure_schema()

    assert "decision_id_unique" in await _constraint_names(gm)
    assert "decision_id_idx" not in await _index_names(gm)
