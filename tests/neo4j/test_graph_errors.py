"""Real-driver error mapping: with Neo4j stopped, reads raise Neo4jUnavailableError.

Never touches 127.0.0.1:7687 (docs/DECISIONS.md#p4-d-07)."""

from __future__ import annotations

import socket

import pytest
from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncManagedTransaction

from alphaswarm.errors import Neo4jQueryError, Neo4jUnavailableError
from alphaswarm.graph import GraphStateManager
from alphaswarm.types import AgentPersona
from tests.conftest import FORBIDDEN_NEO4J_PORT, NEO4J_TEST_AUTH, NEO4J_TEST_DATABASE

pytestmark = pytest.mark.neo4j


def _closed_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    assert port != FORBIDDEN_NEO4J_PORT
    return port


async def test_reads_raise_unavailable_when_neo4j_is_down(all_personas: list[AgentPersona]) -> None:
    driver = AsyncGraphDatabase.driver(
        f"bolt://127.0.0.1:{_closed_loopback_port()}",
        auth=NEO4J_TEST_AUTH,
        connection_timeout=1.0,
        connection_acquisition_timeout=1.0,
        max_transaction_retry_time=0.0,
    )
    gm = GraphStateManager(driver, all_personas)
    try:
        with pytest.raises(Neo4jUnavailableError) as exc_info:
            await gm.read_latest_cycle_id()
        assert exc_info.value.op == "read_latest_cycle_id"
        with pytest.raises(Neo4jUnavailableError):
            await gm.verify_connectivity()
    finally:
        await driver.close()


@pytest.mark.slow
async def test_query_timeout_maps_to_query_error(
    neo4j_test_driver: AsyncDriver,
    all_personas: list[AgentPersona],
) -> None:
    gm = GraphStateManager(
        neo4j_test_driver,
        all_personas,
        database=NEO4J_TEST_DATABASE,
        query_timeout_s=1.0,
    )

    async def _slow_tx(tx: AsyncManagedTransaction) -> int:
        result = await tx.run("UNWIND range(1, 2000000000) AS x RETURN count(x) AS n")
        record = await result.single()
        return int(record["n"]) if record else 0

    with pytest.raises(Neo4jQueryError) as exc_info:
        await gm._read(_slow_tx, op="slow_probe")
    assert exc_info.value.op == "slow_probe"
