"""Raw export rows for the seeded cycle on neo4j-test."""

from __future__ import annotations

import pytest

from alphaswarm.graph import GraphStateManager
from tests.support.seed_builder import PEER_CONTEXT_TEXT, SHOCK_ROUND, SHOCK_TEXT, SeededCycle

pytestmark = pytest.mark.neo4j

UNKNOWN_CYCLE = "00000000-0000-4000-8000-0000000000ff"


async def test_seeded_rows_hold_the_whole_cycle(seeded_cycle: SeededCycle, graph_reader: GraphStateManager) -> None:
    rows = await graph_reader.read_cycle_export_rows(seeded_cycle.cycle_id)

    cycle = rows["cycle"]
    assert cycle is not None
    assert cycle["cycle_id"] == seeded_cycle.cycle_id
    assert cycle["num_rounds"] == seeded_cycle.num_rounds
    assert cycle["created_at"][:4].isdigit() and "T" in cycle["created_at"]
    assert cycle["metrics"]["agent_count"] == 100
    assert not {"seed_rumor", "created_at", "status", "run_manifest_json"} & set(cycle["metrics"])
    assert len(rows["agents"]) == 100
    assert len(rows["decisions"]) == 100 * seeded_cycle.num_rounds
    assert rows["decisions"] == sorted(rows["decisions"], key=lambda d: (d["round_num"], d["agent_id"]))
    assert all(d["peer_ids"] == [] and d["control"] is False for d in rows["decisions"])
    for round_num in range(1, seeded_cycle.num_rounds + 1):
        pairs = {(c["source_id"], c["target_id"]) for c in rows["citations"] if c["round_num"] == round_num}
        assert pairs == set(seeded_cycle.cited_pairs[round_num])
    assert rows["shocks"] == [{"text": SHOCK_TEXT, "injected_before_round": SHOCK_ROUND}]
    assert PEER_CONTEXT_TEXT not in repr(rows)


async def test_unknown_cycle_has_no_rows(graph_reader: GraphStateManager) -> None:
    assert await graph_reader.read_cycle_export_rows(UNKNOWN_CYCLE) == {
        "cycle": None,
        "agents": [],
        "decisions": [],
        "citations": [],
        "shocks": [],
    }
