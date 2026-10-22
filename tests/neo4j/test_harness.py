"""The neo4j-test harness wires markers, the session loop and the guards (C-TEST-09)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from neo4j import AsyncDriver

    from alphaswarm.graph import GraphStateManager

pytestmark = pytest.mark.neo4j


# Cycle ids this module protected. Only these are released again; the session-scoped
# seeded cycles stay protected for the whole session.
_HARNESS_CYCLES: list[str] = []


async def test_neo4j_items_get_sockets_and_the_session_loop(
    request: pytest.FixtureRequest, neo4j_test_driver: AsyncDriver
) -> None:
    assert request.node.get_closest_marker("enable_socket") is not None
    asyncio_marker = request.node.get_closest_marker("asyncio")
    assert asyncio_marker is not None
    assert asyncio_marker.kwargs.get("loop_scope") == "session"
    await neo4j_test_driver.verify_connectivity()


async def test_graph_manager_test_keeps_protected_cycles(
    graph_manager_test: GraphStateManager,
) -> None:
    """A cycle id in NEO4J_PROTECTED_CYCLES survives another test's teardown."""
    from alphaswarm.types import SeedEvent
    from tests.conftest import NEO4J_PROTECTED_CYCLES

    rumor = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."
    cycle_id = await graph_manager_test.create_cycle_with_seed_event(
        rumor, SeedEvent(raw_rumor=rumor, entities=[], overall_sentiment=0.0)
    )
    NEO4J_PROTECTED_CYCLES.add(cycle_id)
    _HARNESS_CYCLES.append(cycle_id)
    # The next test checks it is still there after this test's teardown.


async def test_protected_cycle_survived_the_previous_teardown(
    neo4j_test_driver: AsyncDriver,
) -> None:
    from tests.conftest import NEO4J_PROTECTED_CYCLES

    assert _HARNESS_CYCLES, "the previous test must run first (same module, in order)"
    async with neo4j_test_driver.session(database="neo4j") as session:
        result = await session.run(
            "MATCH (c:Cycle) WHERE c.cycle_id IN $ids RETURN count(c) AS n",
            ids=sorted(_HARNESS_CYCLES),
        )
        record = await result.single()
    assert record is not None and record["n"] == len(_HARNESS_CYCLES)
    NEO4J_PROTECTED_CYCLES.difference_update(_HARNESS_CYCLES)
    _HARNESS_CYCLES.clear()
