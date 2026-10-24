"""The eval scripts' read queries against the real graph schema (neo4j-test only)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import NEO4J_TEST_DATABASE
from tests.support.eval_scripts import load_eval_script

pytestmark = pytest.mark.neo4j
run_eval = load_eval_script("run_eval")


async def _rows(driver: Any, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    async with driver.session(database=NEO4J_TEST_DATABASE) as session:
        result = await session.run(query, params)
        rows: list[dict[str, Any]] = await result.data()
        return rows


async def test_decisions_query_reads_every_agent_of_a_round(neo4j_test_driver: Any, seeded_cycle: Any) -> None:
    final = seeded_cycle.num_rounds
    rows = await _rows(
        neo4j_test_driver, run_eval.DECISIONS_QUERY, {"cycle_id": seeded_cycle.cycle_id, "rounds": [1, final]}
    )
    by_round = run_eval.decisions_by_round(rows)
    assert set(by_round) == {1, final}
    assert len(by_round[1]) == len(seeded_cycle.personas)
    expected = {agent_id: decision.signal for agent_id, decision in seeded_cycle.decisions[1]}
    assert {agent_id: d.signal for agent_id, d in by_round[1]} == expected


async def test_cycle_completed_and_budget_queries_run(neo4j_test_driver: Any, seeded_cycle: Any) -> None:
    assert await _rows(neo4j_test_driver, run_eval.CYCLES_QUERY, {"tags": ["p77.none"]}) == []
    assert await _rows(neo4j_test_driver, run_eval.COMPLETED_QUERY, {"tags": ["p77.none"]}) == []
    budget = await _rows(neo4j_test_driver, run_eval.BUDGET_QUERY, {"limit": 5})
    keys = {"num_rounds", "total_seconds", "seed_seconds", "agent_count"}
    assert all(set(row) == keys for row in budget)
