"""Final-round analytics must follow the cycle's num_rounds, not a literal round 3."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio

from alphaswarm.types import SignalType
from tests.support.seed_builder import SeededCycle, build_seeded_cycle

if TYPE_CHECKING:
    from alphaswarm.graph import GraphStateManager

pytestmark = pytest.mark.neo4j

_T15 = pytest.mark.xfail(
    strict=True, reason="T1.5: final-round reads hard-code round 3 (fix: plan 06)"
)


@pytest_asyncio.fixture(loop_scope="session")
async def two_round_cycle(graph_manager_test: GraphStateManager) -> SeededCycle:
    """A 2-round copy of the seeded data; graph_manager_test deletes it after the test."""
    return await build_seeded_cycle(graph_manager_test, num_rounds=2)


async def test_consensus_summary_uses_the_final_round(
    graph_manager_test: GraphStateManager, two_round_cycle: SeededCycle
) -> None:
    row = await graph_manager_test.read_consensus_summary(two_round_cycle.cycle_id)
    tally = Counter(d.signal for _, d in two_round_cycle.decisions[2])
    assert (row["buy_count"], row["sell_count"], row["hold_count"]) == (
        tally[SignalType.BUY],
        tally[SignalType.SELL],
        tally[SignalType.HOLD],
    )


@_T15
async def test_bracket_narratives_use_the_final_round(
    graph_manager_test: GraphStateManager, two_round_cycle: SeededCycle
) -> None:
    rows = await graph_manager_test.read_bracket_narratives(two_round_cycle.cycle_id)
    assert {r["bracket"] for r in rows} >= {p.bracket.value for p in two_round_cycle.personas}


@_T15
async def test_key_dissenters_use_the_final_round(
    graph_manager_test: GraphStateManager, two_round_cycle: SeededCycle
) -> None:
    rows = await graph_manager_test.read_key_dissenters(two_round_cycle.cycle_id)
    final = dict(two_round_cycle.decisions[2])
    assert rows
    assert all(final[r["agent_id"]].signal.value == r["signal"] for r in rows)


@_T15
async def test_influence_leaders_use_the_final_round(
    graph_manager_test: GraphStateManager, two_round_cycle: SeededCycle
) -> None:
    rows = await graph_manager_test.read_influence_leaders(two_round_cycle.cycle_id)
    assert [(r["agent_id"], r["citation_count"]) for r in rows[:1]] == [("sell_side_01", 12)]
