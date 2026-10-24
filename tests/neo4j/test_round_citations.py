"""Per-round citations with the previous-round signal of each cited agent.

Runs on neo4j-test only. Fictional data.
"""

from __future__ import annotations

from typing import Any

import pytest

from alphaswarm.graph import GraphStateManager
from alphaswarm.graph.rows import UNKNOWN_SIGNAL
from alphaswarm.types import SignalType
from tests.support.golden import assert_golden
from tests.support.mini_cycle import dec, write_mini_cycle
from tests.support.seed_builder import SeededCycle

pytestmark = pytest.mark.neo4j


async def test_seeded_rounds_match_the_builder(seeded_cycle: SeededCycle, graph_reader: GraphStateManager) -> None:
    by_round: dict[str, list[Any]] = {}
    for round_num in range(1, seeded_cycle.num_rounds + 1):
        rows = await graph_reader.read_round_citations(seeded_cycle.cycle_id, round_num)
        by_round[str(round_num)] = list(rows)
        assert {(r["source_id"], r["target_id"]) for r in rows} == set(seeded_cycle.cited_pairs[round_num])
        assert rows == sorted(rows, key=lambda r: (r["source_id"], r["target_id"]))
        if round_num >= 2:
            previous = {agent_id: d.signal.value for agent_id, d in seeded_cycle.decisions[round_num - 1]}
            assert all(r["cited_signal"] == previous[r["target_id"]] for r in rows)
    assert_golden("reads/read_round_citations.json", by_round)


async def test_round_one_and_rounds_past_the_cycle_are_empty(
    seeded_cycle_2r: SeededCycle, graph_reader: GraphStateManager
) -> None:
    assert await graph_reader.read_round_citations(seeded_cycle_2r.cycle_id, 1) == []
    assert await graph_reader.read_round_citations(seeded_cycle_2r.cycle_id, 3) == []
    assert await graph_reader.read_round_citations(seeded_cycle_2r.cycle_id, 2) != []


async def test_self_and_duplicate_citations_collapse(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await write_mini_cycle(
        graph_manager_test,
        num_rounds=2,
        rounds={
            1: [("quants_01", dec(SignalType.BUY)), ("degens_01", dec(SignalType.SELL))],
            2: [
                ("quants_01", dec(SignalType.SELL, cited=["quants_01", "degens_01", "degens_01"])),
                ("degens_01", dec(SignalType.SELL)),
            ],
        },
    )

    rows = await graph_manager_test.read_round_citations(cycle_id, 2)

    assert rows == [{"source_id": "quants_01", "target_id": "degens_01", "cited_signal": "sell"}]


async def test_missing_previous_decision_is_unknown(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await write_mini_cycle(
        graph_manager_test,
        num_rounds=2,
        rounds={
            1: [("quants_01", dec(SignalType.BUY))],
            2: [
                ("quants_01", dec(SignalType.HOLD, cited=["macro_01"])),
                ("macro_01", dec(SignalType.SELL)),
            ],
        },
    )

    rows = await graph_manager_test.read_round_citations(cycle_id, 2)

    assert rows == [{"source_id": "quants_01", "target_id": "macro_01", "cited_signal": UNKNOWN_SIGNAL}]
