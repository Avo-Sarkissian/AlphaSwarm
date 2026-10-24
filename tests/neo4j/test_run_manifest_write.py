"""Run manifest, run seed and experiment tag on the Cycle node (neo4j-test)."""

from __future__ import annotations

from typing import Any

import pytest
from neo4j import AsyncDriver

from alphaswarm.errors import Neo4jWriteError
from alphaswarm.graph import GraphStateManager
from alphaswarm.manifest import RunManifest
from alphaswarm.types import EntityType, SeedEntity, SeedEvent
from tests.conftest import NEO4J_TEST_DATABASE
from tests.support.manifests import make_manifest

pytestmark = pytest.mark.neo4j

RUMOR = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."
SEED = SeedEvent(
    raw_rumor=RUMOR,
    entities=[SeedEntity(name="ZZZT Holdings", type=EntityType.COMPANY, relevance=0.9, sentiment=0.5)],
    overall_sentiment=0.4,
)


async def _cycle_props(driver: AsyncDriver, cycle_id: str) -> dict[str, Any]:
    async with driver.session(database=NEO4J_TEST_DATABASE) as session:
        result = await session.run("MATCH (c:Cycle {cycle_id: $cid}) RETURN properties(c) AS props", cid=cycle_id)
        record = await result.single()
    assert record is not None
    return dict(record["props"])


async def test_manifest_seed_and_tag_land_on_the_cycle(
    graph_manager_test: GraphStateManager, neo4j_test_driver: AsyncDriver
) -> None:
    cycle_id = await graph_manager_test.create_cycle_with_seed_event(RUMOR, SEED, num_rounds=3)
    manifest = make_manifest(cycle_id=cycle_id, tag="p7-3-control")

    await graph_manager_test.write_run_manifest(cycle_id, manifest)
    props = await _cycle_props(neo4j_test_driver, cycle_id)

    assert props["sim_seed"] == 4242
    assert props["experiment_tag"] == "p7-3-control"
    assert RunManifest.model_validate_json(props["run_manifest_json"]) == manifest


async def test_untagged_run_leaves_no_tag_property(
    graph_manager_test: GraphStateManager, neo4j_test_driver: AsyncDriver
) -> None:
    cycle_id = await graph_manager_test.create_cycle_with_seed_event(RUMOR, SEED, num_rounds=3)

    await graph_manager_test.write_run_manifest(cycle_id, make_manifest(cycle_id=cycle_id))

    assert "experiment_tag" not in await _cycle_props(neo4j_test_driver, cycle_id)


async def test_unknown_cycle_raises(graph_manager_test: GraphStateManager) -> None:
    with pytest.raises(Neo4jWriteError):
        await graph_manager_test.write_run_manifest("00000000-0000-4000-8000-00000000dead", make_manifest())


async def test_experiment_tag_index_exists(
    graph_manager_test: GraphStateManager, neo4j_test_driver: AsyncDriver
) -> None:
    async with neo4j_test_driver.session(database=NEO4J_TEST_DATABASE) as session:
        result = await session.run("SHOW INDEXES YIELD name WHERE name = 'cycle_experiment_tag' RETURN count(*) AS n")
        record = await result.single()

    assert record is not None and record["n"] == 1
