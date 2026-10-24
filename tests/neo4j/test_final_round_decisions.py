"""Final-round decisions with the entities each one references (docs/DECISIONS.md#adr-grounded-advisory)."""

from __future__ import annotations

import pytest

from alphaswarm.graph import GraphStateManager
from alphaswarm.types import EntityType, SeedEntity, SignalType
from tests.support.golden import assert_golden
from tests.support.mini_cycle import dec, write_mini_cycle
from tests.support.seed_builder import SeededCycle

pytestmark = pytest.mark.neo4j

ENTITIES = (
    SeedEntity(name="ZZZT Holdings", type=EntityType.COMPANY, relevance=0.95, sentiment=0.6, ticker="ZZZT"),
    SeedEntity(name="QQQX Robotics", type=EntityType.COMPANY, relevance=0.9, sentiment=0.7),
    SeedEntity(name="Industrial Automation", type=EntityType.SECTOR, relevance=0.6, sentiment=0.4),
)


async def _two_round_cycle(gm: GraphStateManager) -> str:
    return await write_mini_cycle(
        gm,
        num_rounds=2,
        rounds={
            1: [
                ("quants_01", dec(SignalType.SELL, rationale="ZZZT Holdings looks rich")),
                ("shorts_01", dec(SignalType.SELL, rationale="QQQX Robotics is overvalued")),
            ],
            2: [
                ("quants_01", dec(SignalType.BUY, rationale="ZZZT Holdings and QQQX Robotics both benefit")),
                ("shorts_01", dec(SignalType.SELL, rationale="QQQX Robotics is overpaying")),
                ("macro_01", dec(SignalType.HOLD, rationale="Rates matter more than this deal")),
                ("degens_01", dec(SignalType.PARSE_ERROR, rationale="")),
            ],
        },
        entities=ENTITIES,
    )


async def test_final_round_rows_carry_referenced_entities_and_tickers(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await _two_round_cycle(graph_manager_test)

    rows = await graph_manager_test.read_final_round_decisions(cycle_id)

    assert [r["agent_id"] for r in rows] == ["degens_01", "macro_01", "quants_01", "shorts_01"]
    by_id = {r["agent_id"]: r for r in rows}
    assert by_id["degens_01"]["signal"] == "parse_error"
    assert by_id["macro_01"]["entities"] == []
    assert by_id["quants_01"]["signal"] == "buy"
    assert by_id["quants_01"]["bracket"] == "quants"
    assert by_id["quants_01"]["reach"] == pytest.approx(0.55)
    assert by_id["quants_01"]["entities"] == [
        {"name": "QQQX Robotics", "type": "company", "ticker": None},
        {"name": "ZZZT Holdings", "type": "company", "ticker": "ZZZT"},
    ]
    assert by_id["shorts_01"]["entities"] == [
        {"name": "QQQX Robotics", "type": "company", "ticker": None},
    ]


async def test_unknown_cycle_has_no_rows(graph_manager_test: GraphStateManager) -> None:
    assert await graph_manager_test.read_final_round_decisions("00000000-0000-4000-8000-0000000000ff") == []


async def test_seeded_cycle_golden(graph_manager_test: GraphStateManager, seeded_cycle: SeededCycle) -> None:
    rows = await graph_manager_test.read_final_round_decisions(seeded_cycle.cycle_id)
    assert len(rows) == 100
    assert_golden("reads/read_final_round_decisions.json", rows)
