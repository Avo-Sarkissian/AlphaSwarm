"""write_cycle_metrics persists str and bool provenance values as flat Cycle properties."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from tests.conftest import NEO4J_TEST_DATABASE

if TYPE_CHECKING:
    from neo4j import AsyncDriver

    from alphaswarm.graph import GraphStateManager

pytestmark = pytest.mark.neo4j


async def test_write_cycle_metrics_round_trips_str_and_bool(
    graph_manager_test: GraphStateManager, neo4j_test_driver: AsyncDriver
) -> None:
    cycle_id = str(uuid.uuid4())
    async with neo4j_test_driver.session(database=NEO4J_TEST_DATABASE) as session:
        created = await session.run("CREATE (:Cycle {cycle_id: $cycle_id})", cycle_id=cycle_id)
        await created.consume()
    metrics: dict[str, float | int | str | bool] = {
        "metrics_version": 1,
        "peer_selection_version": 2,
        "peer_personal_boost": 0.3,
        "peer_seed_source": "sim_seed",
        "worker_provider": "ollama",
        "git_sha": "0" * 40,
        "git_dirty": False,
        "r2_exposure_quants": 120,
    }

    await graph_manager_test.write_cycle_metrics(cycle_id, metrics)

    async with neo4j_test_driver.session(database=NEO4J_TEST_DATABASE) as session:
        result = await session.run(
            "MATCH (c:Cycle {cycle_id: $cycle_id}) RETURN properties(c) AS props",
            cycle_id=cycle_id,
        )
        record = await result.single()
    assert record is not None
    props = record["props"]
    for key, value in metrics.items():
        assert props[key] == value
        assert type(props[key]) is type(value)
    assert props["metrics_recorded_at"] is not None
