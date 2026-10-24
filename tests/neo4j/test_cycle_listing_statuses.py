"""Cycle listing by status on neo4j-test."""

from __future__ import annotations

import pytest

from alphaswarm.graph import GraphStateManager
from alphaswarm.types import SignalType
from tests.support.mini_cycle import dec, write_mini_cycle

pytestmark = pytest.mark.neo4j

ROUNDS = {1: [("quants_01", dec(SignalType.BUY))], 2: [("quants_01", dec(SignalType.SELL))]}


async def test_listing_filters_by_status(graph_manager_test: GraphStateManager) -> None:
    failed = await write_mini_cycle(graph_manager_test, num_rounds=2, rounds=ROUNDS)
    await graph_manager_test.set_cycle_status(failed, "failed", error_code="internal_error")
    running = await write_mini_cycle(graph_manager_test, num_rounds=2, rounds=ROUNDS)
    await graph_manager_test.set_cycle_status(running, "running")  # write_mini_cycle ends 'complete'

    default_ids = {r["cycle_id"] for r in await graph_manager_test.read_completed_cycles(100)}
    failed_rows = await graph_manager_test.read_completed_cycles(100, statuses=("failed",))
    every_id = {
        r["cycle_id"]
        for r in await graph_manager_test.read_completed_cycles(
            100, statuses=("running", "complete", "failed", "cancelled")
        )
    }

    assert failed not in default_ids and running not in default_ids
    assert failed in {r["cycle_id"] for r in failed_rows}
    assert all(r["status"] == "failed" for r in failed_rows)
    assert {failed, running} <= every_id
