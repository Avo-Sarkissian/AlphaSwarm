"""Report read models against real Cypher: final-round resolution and parse-error counts."""

from __future__ import annotations

import pytest

from alphaswarm.graph import GraphStateManager
from alphaswarm.types import SignalType
from tests.support.mini_cycle import cypher, dec, write_mini_cycle

pytestmark = pytest.mark.neo4j

BUY, SELL, HOLD, PERR = SignalType.BUY, SignalType.SELL, SignalType.HOLD, SignalType.PARSE_ERROR
ZERO_SUMMARY = {
    "buy_count": 0,
    "sell_count": 0,
    "hold_count": 0,
    "parse_error_count": 0,
    "total": 0,
}


async def _two_round_cycle(gm: GraphStateManager) -> str:
    return await write_mini_cycle(
        gm,
        num_rounds=2,
        rounds={
            1: [("quants_01", dec(SELL)), ("quants_02", dec(SELL)), ("quants_03", dec(SELL))],
            2: [("quants_01", dec(BUY)), ("quants_02", dec(HOLD)), ("quants_03", dec(PERR, 0.0))],
        },
    )


async def test_consensus_counts_final_round_with_parse_errors(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await _two_round_cycle(graph_manager_test)

    summary = await graph_manager_test.read_consensus_summary(cycle_id)

    assert summary == {
        "buy_count": 1,
        "sell_count": 0,
        "hold_count": 1,
        "parse_error_count": 1,
        "total": 3,
    }


async def test_round_timeline_counts_parse_errors(graph_manager_test: GraphStateManager) -> None:
    cycle_id = await _two_round_cycle(graph_manager_test)

    timeline = await graph_manager_test.read_round_timeline(cycle_id)

    assert timeline == [
        {
            "round_num": 1,
            "buy_count": 0,
            "sell_count": 3,
            "hold_count": 0,
            "parse_error_count": 0,
            "total": 3,
        },
        {
            "round_num": 2,
            "buy_count": 1,
            "sell_count": 0,
            "hold_count": 1,
            "parse_error_count": 1,
            "total": 3,
        },
    ]


async def test_legacy_cycle_without_num_rounds_defaults_to_round_3(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await write_mini_cycle(
        graph_manager_test,
        num_rounds=3,
        rounds={
            1: [("quants_01", dec(BUY))],
            2: [("quants_01", dec(BUY))],
            3: [("quants_01", dec(SELL))],
        },
    )
    await cypher(
        graph_manager_test,
        "MATCH (c:Cycle {cycle_id: $id}) REMOVE c.num_rounds",
        id=cycle_id,
    )

    summary = await graph_manager_test.read_consensus_summary(cycle_id)

    assert summary == {**ZERO_SUMMARY, "sell_count": 1, "total": 1}


async def test_unknown_cycle_returns_zero_summary(graph_manager_test: GraphStateManager) -> None:
    summary = await graph_manager_test.read_consensus_summary(
        "00000000-0000-4000-8000-00000000dead",
    )

    assert summary == ZERO_SUMMARY
