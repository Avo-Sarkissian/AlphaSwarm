"""run_simulation binds the cycle id for the rest of the run (docs/DECISIONS.md#adr-security-2026-08)."""

from __future__ import annotations

from typing import Any

import structlog

from alphaswarm.simulation import RoundCompleteEvent
from tests.engine.scenario import SCENARIO_CYCLE_ID, RunScenario


async def test_cycle_id_is_bound_after_seeding(run_scenario: RunScenario) -> None:
    seen: list[tuple[int, dict[str, Any]]] = []

    async def _on_round(event: RoundCompleteEvent) -> None:
        seen.append((event.round_num, dict(structlog.contextvars.get_contextvars())))

    await run_scenario(num_rounds=2, on_round_complete=_on_round)
    assert [round_num for round_num, _ in seen] == [1, 2]
    assert all(context.get("cycle_id") == SCENARIO_CYCLE_ID for _, context in seen)
