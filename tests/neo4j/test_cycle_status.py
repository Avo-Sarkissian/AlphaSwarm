"""Cycle.status lifecycle against neo4j-test (docs/DECISIONS.md#adr-cycle-metrics)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from neo4j import AsyncDriver

from alphaswarm.errors import Neo4jWriteError
from alphaswarm.graph import GraphStateManager
from alphaswarm.types import AgentPersona, EntityType, SeedEntity, SeedEvent
from alphaswarm.web.routes.replay import router as replay_router
from tests.conftest import NEO4J_TEST_DATABASE

pytestmark = pytest.mark.neo4j

RUMOR = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."
SEED = SeedEvent(
    raw_rumor=RUMOR,
    entities=[SeedEntity(name="ZZZT Holdings", type=EntityType.COMPANY, relevance=0.9, sentiment=0.5)],
    overall_sentiment=0.4,
)


async def _cypher(driver: AsyncDriver, query: str, **params: Any) -> list[dict[str, Any]]:
    async with driver.session(database=NEO4J_TEST_DATABASE) as session:
        result = await session.run(query, **params)
        return [dict(r) async for r in result]


async def _cycle_at(gm: GraphStateManager, driver: AsyncDriver, created_at: str) -> str:
    cycle_id = await gm.create_cycle_with_seed_event(RUMOR, SEED, num_rounds=3)
    await _cypher(
        driver,
        "MATCH (c:Cycle {cycle_id: $id}) SET c.created_at = datetime($ts)",
        id=cycle_id,
        ts=created_at,
    )
    return cycle_id


async def _status(driver: AsyncDriver, cycle_id: str) -> dict[str, Any]:
    rows = await _cypher(
        driver,
        "MATCH (c:Cycle {cycle_id: $id}) RETURN c.status AS status, c.error_code AS error_code",
        id=cycle_id,
    )
    return rows[0]


async def test_new_cycle_starts_running(
    graph_manager_test: GraphStateManager,
    neo4j_test_driver: AsyncDriver,
) -> None:
    cycle_id = await graph_manager_test.create_cycle_with_seed_event(RUMOR, SEED, num_rounds=3)
    assert await _status(neo4j_test_driver, cycle_id) == {"status": "running", "error_code": None}


async def test_set_cycle_status_records_and_clears_error_code(
    graph_manager_test: GraphStateManager,
    neo4j_test_driver: AsyncDriver,
) -> None:
    cycle_id = await graph_manager_test.create_cycle_with_seed_event(RUMOR, SEED, num_rounds=3)
    await graph_manager_test.set_cycle_status(cycle_id, "failed", error_code="round_failed")
    assert await _status(neo4j_test_driver, cycle_id) == {"status": "failed", "error_code": "round_failed"}
    await graph_manager_test.set_cycle_status(cycle_id, "complete")
    assert await _status(neo4j_test_driver, cycle_id) == {"status": "complete", "error_code": None}


async def test_set_cycle_status_unknown_cycle_raises(graph_manager_test: GraphStateManager) -> None:
    with pytest.raises(Neo4jWriteError):
        await graph_manager_test.set_cycle_status(str(uuid.uuid4()), "complete")


async def test_readers_filter_on_status(
    graph_manager_test: GraphStateManager,
    neo4j_test_driver: AsyncDriver,
) -> None:
    gm, drv = graph_manager_test, neo4j_test_driver
    complete = await _cycle_at(gm, drv, "2099-01-01T10:00:00Z")
    failed = await _cycle_at(gm, drv, "2099-01-01T11:00:00Z")
    cancelled = await _cycle_at(gm, drv, "2099-01-01T12:00:00Z")
    running = await _cycle_at(gm, drv, "2099-01-01T13:00:00Z")  # also = a hard-killed run
    await gm.set_cycle_status(complete, "complete")
    await gm.set_cycle_status(failed, "failed", error_code="graph_unavailable")
    await gm.set_cycle_status(cancelled, "cancelled")

    listed = {c["cycle_id"] for c in await gm.read_completed_cycles(limit=100)}
    assert complete in listed
    assert not listed & {failed, cancelled, running}
    assert await gm.read_latest_cycle_id() == complete
    assert await gm.read_latest_cycle_id(statuses=("running", "complete")) == running


async def test_ensure_schema_backfills_legacy_cycles(
    graph_manager_test: GraphStateManager,
    neo4j_test_driver: AsyncDriver,
    all_personas: list[AgentPersona],
) -> None:
    # Cycles written before Cycle.status existed (an upgrade before the back-fill ran).
    gm, drv = graph_manager_test, neo4j_test_driver
    metrics_id, r3_id, crashed_id, running_id = (str(uuid.uuid4()) for _ in range(4))
    # Distinct timestamps in the future: the newest legacy *complete* cycle is r3_id; the
    # crashed and running cycles are newer but must never become the default.
    await _cypher(
        drv,
        """
        CREATE (:Cycle {cycle_id: $metrics_id, seed_rumor: 'legacy',
                        created_at: datetime('2099-03-01T10:00:00Z'), metrics_recorded_at: datetime()})
        CREATE (:Cycle {cycle_id: $r3_id, seed_rumor: 'legacy',
                        created_at: datetime('2099-03-01T11:00:00Z')})
        CREATE (:Cycle {cycle_id: $crashed_id, seed_rumor: 'legacy',
                        created_at: datetime('2099-03-01T12:00:00Z')})
        CREATE (:Cycle {cycle_id: $running_id, seed_rumor: 'new',
                        created_at: datetime('2099-03-01T13:00:00Z'), status: 'running'})
        """,
        metrics_id=metrics_id,
        r3_id=r3_id,
        crashed_id=crashed_id,
        running_id=running_id,
    )
    await _cypher(
        drv,
        """
        MATCH (a:Agent {id: $agent_id})
        CREATE (a)-[:MADE]->(:Decision {decision_id: $decision_id, cycle_id: $r3_id, round: 3,
                                        signal: 'buy', confidence: 0.5})
        """,
        agent_id=all_personas[0].id,
        decision_id=str(uuid.uuid4()),
        r3_id=r3_id,
    )

    async def _assert_readers() -> None:
        listed = {c["cycle_id"] for c in await gm.read_completed_cycles(limit=100)}
        assert {metrics_id, r3_id} <= listed
        assert crashed_id not in listed and running_id not in listed
        assert await gm.read_latest_cycle_id() == r3_id  # the `alphaswarm report` default

    # Before any back-fill the readers already apply the legacy rule.
    await _assert_readers()

    expected = {metrics_id: "complete", r3_id: "complete", crashed_id: "failed", running_id: "running"}
    for _ in range(2):  # idempotent
        await gm.ensure_schema()
        rows = await _cypher(
            drv,
            "MATCH (c:Cycle) WHERE c.cycle_id IN $ids RETURN c.cycle_id AS id, c.status AS status",
            ids=list(expected),
        )
        assert {r["id"]: r["status"] for r in rows} == expected
        await _assert_readers()  # the back-fill gives the same answer


async def test_cancelled_cycle_absent_from_replay_cycles_route(
    graph_manager_test: GraphStateManager,
    neo4j_test_driver: AsyncDriver,
) -> None:
    # A stopped run never shows up as replayable.
    cycle_id = await _cycle_at(graph_manager_test, neo4j_test_driver, "2099-02-01T10:00:00Z")
    await graph_manager_test.set_cycle_status(cycle_id, "cancelled")

    app = FastAPI()
    app.include_router(replay_router, prefix="/api")
    app.state.app_state = SimpleNamespace(graph_manager=graph_manager_test)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.get("/api/replay/cycles")

    assert resp.status_code == 200
    assert cycle_id not in {c["cycle_id"] for c in resp.json()["cycles"]}
