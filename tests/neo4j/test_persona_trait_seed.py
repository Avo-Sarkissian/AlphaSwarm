"""The interview persona's trait seed comes from the cycle (docs/DECISIONS.md#adr-persona-traits)."""

from __future__ import annotations

import pytest

from alphaswarm.graph import GraphStateManager
from alphaswarm.types import SignalType
from tests.support.manifests import make_manifest
from tests.support.mini_cycle import cypher, dec, write_mini_cycle

pytestmark = pytest.mark.neo4j


async def _cycle(gm: GraphStateManager) -> str:
    return await write_mini_cycle(gm, num_rounds=2, rounds={1: [("quants_01", dec(SignalType.BUY))]})


async def _write_manifest(gm: GraphStateManager, cycle_id: str, *, persona_traits: bool) -> None:
    manifest = make_manifest(cycle_id=cycle_id)
    manifest = manifest.model_copy(update={"simulation": {**manifest.simulation, "persona_traits": persona_traits}})
    await gm.write_run_manifest(cycle_id, manifest)


async def test_traits_on_returns_the_cycle_sim_seed(graph_manager_test: GraphStateManager) -> None:
    cycle_id = await _cycle(graph_manager_test)
    await _write_manifest(graph_manager_test, cycle_id, persona_traits=True)
    [row] = await cypher(graph_manager_test, "MATCH (c:Cycle {cycle_id: $cid}) RETURN c.sim_seed AS s", cid=cycle_id)
    assert row["s"] == 4242
    assert await graph_manager_test.read_persona_trait_seed(cycle_id) == 4242


async def test_traits_off_or_no_manifest_returns_none(graph_manager_test: GraphStateManager) -> None:
    legacy = await _cycle(graph_manager_test)
    assert await graph_manager_test.read_persona_trait_seed(legacy) is None
    off = await _cycle(graph_manager_test)
    await _write_manifest(graph_manager_test, off, persona_traits=False)
    assert await graph_manager_test.read_persona_trait_seed(off) is None
    assert await graph_manager_test.read_persona_trait_seed("00000000-0000-4000-8000-0000000000ee") is None


async def test_unreadable_manifest_returns_none(graph_manager_test: GraphStateManager) -> None:
    cycle_id = await _cycle(graph_manager_test)
    await cypher(
        graph_manager_test,
        "MATCH (c:Cycle {cycle_id: $cid}) SET c.run_manifest_json = 'not json', c.sim_seed = 7",
        cid=cycle_id,
    )
    assert await graph_manager_test.read_persona_trait_seed(cycle_id) is None
