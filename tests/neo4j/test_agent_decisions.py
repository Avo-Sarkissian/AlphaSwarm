"""Per-agent decision history. Fictional data only."""

from __future__ import annotations

import pytest

from alphaswarm.graph import GraphStateManager
from alphaswarm.types import SignalType
from tests.support.mini_cycle import dec, write_mini_cycle

pytestmark = pytest.mark.neo4j

ROW_KEYS = {"round_num", "signal", "confidence", "sentiment", "rationale", "cited_agents"}


async def _three_round_cycle(gm: GraphStateManager) -> str:
    return await write_mini_cycle(
        gm,
        num_rounds=3,
        rounds={
            1: [
                (
                    "quants_01",
                    dec(SignalType.BUY, 0.8, sentiment=0.4, rationale="ZZZT deal looks accretive"),
                ),
                ("degens_02", dec(SignalType.SELL, 0.6)),
                ("macro_03", dec(SignalType.HOLD, 0.5)),
            ],
            2: [
                (
                    "quants_01",
                    dec(
                        SignalType.SELL,
                        0.65,
                        sentiment=-0.2,
                        rationale="Financing risk on QQQX",
                        cited=("macro_03", "degens_02"),
                    ),
                ),
                ("degens_02", dec(SignalType.SELL, 0.7)),
                ("macro_03", dec(SignalType.HOLD, 0.5)),
            ],
            3: [
                (
                    "quants_01",
                    dec(SignalType.PARSE_ERROR, 0.0, sentiment=0.0, rationale="unparseable output"),
                ),
                ("degens_02", dec(SignalType.SELL, 0.7)),
                ("macro_03", dec(SignalType.BUY, 0.55, cited=("quants_01",))),
            ],
        },
    )


async def test_rows_are_ordered_by_round_with_sorted_citations(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await _three_round_cycle(graph_manager_test)

    rows = await graph_manager_test.read_agent_decisions(cycle_id, "quants_01")

    assert [set(r) for r in rows] == [ROW_KEYS] * 3
    assert [(r["round_num"], r["signal"]) for r in rows] == [
        (1, "buy"),
        (2, "sell"),
        (3, "parse_error"),
    ]
    assert rows[0]["confidence"] == pytest.approx(0.8)
    assert rows[1]["sentiment"] == pytest.approx(-0.2)
    assert rows[1]["rationale"] == "Financing risk on QQQX"
    assert rows[1]["cited_agents"] == ["degens_02", "macro_03"]
    assert rows[0]["cited_agents"] == []


async def test_rows_belong_to_one_cycle_and_one_agent(
    graph_manager_test: GraphStateManager,
) -> None:
    first = await _three_round_cycle(graph_manager_test)
    second = await write_mini_cycle(
        graph_manager_test,
        num_rounds=2,
        rounds={
            1: [("quants_01", dec(SignalType.HOLD, 0.3))],
            2: [("quants_01", dec(SignalType.HOLD, 0.3))],
        },
    )

    rows = await graph_manager_test.read_agent_decisions(second, "quants_01")

    assert [(r["round_num"], r["signal"]) for r in rows] == [(1, "hold"), (2, "hold")]
    assert await graph_manager_test.read_agent_decisions(first, "allocators_05") == []
