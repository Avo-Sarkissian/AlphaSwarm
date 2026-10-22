"""Fixtures for the neo4j-test suites (each module sets ``pytestmark = pytest.mark.neo4j``)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest_asyncio

from alphaswarm.config import DEFAULT_BRACKETS, generate_personas
from alphaswarm.graph import GraphStateManager
from tests.conftest import NEO4J_TEST_DATABASE

if TYPE_CHECKING:
    from neo4j import AsyncDriver


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def graph_reader(neo4j_test_driver: AsyncDriver) -> GraphStateManager:
    """Read-only GraphStateManager over neo4j-test. Never call close(): the driver is shared."""
    return GraphStateManager(
        driver=neo4j_test_driver,
        personas=generate_personas(DEFAULT_BRACKETS),
        database=NEO4J_TEST_DATABASE,
    )
