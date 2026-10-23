"""Paged cycle listing with stored run metrics.

Cycles in these tests get created_at values in 2099 so they are newer than
the session's seeded cycles. Fictional data only.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

import pytest
from pydantic import TypeAdapter

from alphaswarm.graph import GraphStateManager
from alphaswarm.types import SignalType
from tests.support.mini_cycle import cypher, dec, write_mini_cycle
from tests.support.seed_builder import SeededCycle

pytestmark = pytest.mark.neo4j

# The route parses ?before= with pydantic; reuse the exact same parser here.
_AS_FASTAPI_PARSES = TypeAdapter(datetime)

ROW_KEYS = {
    "cycle_id",
    "created_at",
    "seed_rumor",
    "round_count",
    "status",
    "final_buy",
    "final_sell",
    "final_hold",
    "total_flips",
    "total_seconds",
    "agent_count",
}
HISTORY_COLUMNS = (
    "final_buy",
    "final_sell",
    "final_hold",
    "total_flips",
    "total_seconds",
    "agent_count",
)
HISTORY_METRICS: Mapping[str, float | int] = {
    "metrics_version": 1,
    "num_rounds": 2,
    "final_buy": 60,
    "final_sell": 25,
    "final_hold": 10,
    "r2_flips": 7,
    "r3_flips": 0,
    "total_seconds": 754.3,
    "agent_count": 100,
}


async def _complete_cycle_at(
    gm: GraphStateManager,
    created_at: str,
    *,
    metrics: Mapping[str, float | int] | None = None,
) -> str:
    """Write a small 2-round cycle, mark it complete and pin its created_at.

    The stored Cycle.status is what the effective-status rule reads first, so a
    cycle without metrics still lists as complete.
    """
    cycle_id = await write_mini_cycle(
        gm,
        num_rounds=2,
        rounds={1: [("quants_01", dec(SignalType.BUY))], 2: [("quants_01", dec(SignalType.SELL))]},
    )
    if metrics is not None:
        await gm.write_cycle_metrics(cycle_id, dict(metrics))
    await cypher(
        gm,
        "MATCH (c:Cycle {cycle_id: $id}) SET c.status = 'complete', c.created_at = datetime($ts)",
        id=cycle_id,
        ts=created_at,
    )
    return cycle_id


async def test_rows_carry_the_stored_history_metrics(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await _complete_cycle_at(
        graph_manager_test, "2099-02-01T00:00:00Z", metrics=HISTORY_METRICS
    )

    rows = await graph_manager_test.read_completed_cycles(5)

    row = next(r for r in rows if r["cycle_id"] == cycle_id)
    assert set(row) == ROW_KEYS
    assert (row["status"], row["round_count"]) == ("complete", 2)
    assert (row["final_buy"], row["final_sell"], row["final_hold"]) == (60, 25, 10)
    assert row["total_flips"] == 7
    assert row["total_seconds"] == pytest.approx(754.3)
    assert row["agent_count"] == 100


async def test_cycle_without_metrics_returns_none_for_every_history_column(
    graph_manager_test: GraphStateManager,
) -> None:
    cycle_id = await _complete_cycle_at(graph_manager_test, "2099-02-02T00:00:00Z")

    rows = await graph_manager_test.read_completed_cycles(5)

    row = next(r for r in rows if r["cycle_id"] == cycle_id)
    assert [row[key] for key in HISTORY_COLUMNS] == [None] * len(HISTORY_COLUMNS)


async def test_default_page_is_twenty_newest_first(graph_manager_test: GraphStateManager) -> None:
    for day in range(1, 23):
        await _complete_cycle_at(graph_manager_test, f"2099-03-{day:02d}T00:00:00Z")

    rows = await graph_manager_test.read_completed_cycles()

    assert len(rows) == 20
    assert rows[0]["created_at"].startswith("2099-03-22")
    assert rows[19]["created_at"].startswith("2099-03-03")


async def test_cursor_round_trips_the_servers_own_timestamp(
    graph_manager_test: GraphStateManager,
) -> None:
    gm = graph_manager_test
    newest = await _complete_cycle_at(gm, "2099-01-03T00:00:00.123456789Z")
    middle = await _complete_cycle_at(gm, "2099-01-02T00:00:00.000000001Z")
    oldest = await _complete_cycle_at(gm, "2099-01-01T00:00:00Z")

    page1 = await gm.read_completed_cycles(1)
    assert [r["cycle_id"] for r in page1] == [newest]

    page2 = await gm.read_completed_cycles(
        1, before=_AS_FASTAPI_PARSES.validate_python(page1[0]["created_at"])
    )
    assert [r["cycle_id"] for r in page2] == [middle]

    page3 = await gm.read_completed_cycles(
        1, before=_AS_FASTAPI_PARSES.validate_python(page2[0]["created_at"])
    )
    assert [r["cycle_id"] for r in page3] == [oldest]


async def test_naive_cursor_is_read_as_utc(graph_manager_test: GraphStateManager) -> None:
    later = await _complete_cycle_at(graph_manager_test, "2099-01-02T18:00:00Z")
    earlier = await _complete_cycle_at(graph_manager_test, "2099-01-02T06:00:00Z")

    rows = await graph_manager_test.read_completed_cycles(5, before=datetime(2099, 1, 2, 12, 0))

    assert rows, "a naive cursor compared as LocalDateTime returns no rows"
    assert rows[0]["cycle_id"] == earlier
    assert later not in {r["cycle_id"] for r in rows}


async def test_seeded_cycle_lists_consensus_flips_and_duration(
    graph_manager_test: GraphStateManager,
    seeded_cycle: SeededCycle,
) -> None:
    rows = await graph_manager_test.read_completed_cycles(100)

    row = next(r for r in rows if r["cycle_id"] == seeded_cycle.cycle_id)
    missing = [
        k
        for k in ("final_buy", "final_sell", "final_hold", "total_flips", "total_seconds")
        if row[k] is None
    ]
    assert missing == []
