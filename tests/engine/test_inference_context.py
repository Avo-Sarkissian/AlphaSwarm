"""Every worker call of a run sees cycle_id, round and agent_id in structlog contextvars."""

from __future__ import annotations

from collections.abc import Callable

import structlog

from alphaswarm.types import AgentDecision
from tests.engine.scenario import RunScenario
from tests.inference.fakes import ScriptedCall, ScriptedProvider, default_decision_script


async def test_round_calls_carry_cycle_round_and_agent(
    run_scenario: RunScenario,
    make_scripted_worker: Callable[..., ScriptedProvider],
) -> None:
    seen: list[dict[str, object]] = []

    def decide(agent_id: str, round_num: int, call: ScriptedCall) -> AgentDecision:
        seen.append(dict(structlog.contextvars.get_contextvars()))
        return default_decision_script(agent_id, round_num, call)

    await run_scenario(worker=make_scripted_worker(decide))
    assert {c.get("round") for c in seen} == {1, 2, 3}
    assert all(c.get("cycle_id") for c in seen)
    assert all(c.get("agent_id") for c in seen)
