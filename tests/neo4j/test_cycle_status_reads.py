"""read_cycle_status / cycle_exists against the isolated neo4j-test database.

Cycles are created with raw Cypher so each status shape (including legacy cycles
without ``c.status``) is exercised directly. graph_manager_test deletes every
cycle created during the test.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from alphaswarm.graph import GraphStateManager

pytestmark = pytest.mark.neo4j

_RUMOR = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."


async def _create_cycle(gm: GraphStateManager, **props: object) -> str:
    cycle_id = str(uuid.uuid4())
    async with gm._driver.session(database=gm._database) as session:
        await session.run(
            "CREATE (c:Cycle {cycle_id: $cycle_id, created_at: datetime(), seed_rumor: $rumor}) "
            "SET c += $props",
            cycle_id=cycle_id,
            rumor=_RUMOR,
            props=dict(props),
        )
    return cycle_id


async def _add_decision(gm: GraphStateManager, cycle_id: str, round_num: int) -> None:
    # Decisions hang off a seeded Agent (ensure_schema seeds them), the same shape
    # the legacy completeness rule matches: (:Agent)-[:MADE]->(:Decision).
    async with gm._driver.session(database=gm._database) as session:
        await session.run(
            "MATCH (a:Agent) WITH a LIMIT 1 "
            "CREATE (a)-[:MADE]->(:Decision "
            "{decision_id: $did, cycle_id: $cid, round: $r, signal: 'hold'})",
            did=str(uuid.uuid4()),
            cid=cycle_id,
            r=round_num,
        )


async def test_unknown_cycle_is_none(graph_manager_test: GraphStateManager) -> None:
    missing = str(uuid.uuid4())
    assert await graph_manager_test.read_cycle_status(missing) is None
    assert await graph_manager_test.cycle_exists(missing) is False


@pytest.mark.parametrize("status", ["running", "complete", "failed", "cancelled"])
async def test_status_property_is_returned(
    graph_manager_test: GraphStateManager,
    status: str,
) -> None:
    cycle_id = await _create_cycle(graph_manager_test, status=status)
    assert await graph_manager_test.read_cycle_status(cycle_id) == status
    assert await graph_manager_test.cycle_exists(cycle_id) is True


async def test_legacy_cycle_without_evidence_is_failed(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await _create_cycle(graph_manager_test)
    assert await graph_manager_test.read_cycle_status(cycle_id) == "failed"


async def test_legacy_cycle_with_metrics_is_complete(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await _create_cycle(graph_manager_test, metrics_recorded_at=datetime.now(UTC))
    assert await graph_manager_test.read_cycle_status(cycle_id) == "complete"


async def test_legacy_three_round_cycle_with_round3_decision_is_complete(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await _create_cycle(graph_manager_test)
    await _add_decision(graph_manager_test, cycle_id, 3)
    assert await graph_manager_test.read_cycle_status(cycle_id) == "complete"


async def test_legacy_cycle_stopped_after_round_two_is_failed(
    graph_manager_test: GraphStateManager,
) -> None:
    # Same rule as the status back-fill and read_completed_cycles: without metrics,
    # only a round-3 decision marks a legacy cycle complete (2-round runs always
    # stamp metrics, so they are covered by the metrics branch).
    cycle_id = await _create_cycle(graph_manager_test)
    await _add_decision(graph_manager_test, cycle_id, 2)
    assert await graph_manager_test.read_cycle_status(cycle_id) == "failed"


async def test_unexpected_status_value_reads_as_failed(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await _create_cycle(graph_manager_test, status="weird")
    assert await graph_manager_test.read_cycle_status(cycle_id) == "failed"
