"""Eager narrative generation.

It must not swallow hard-stop errors (docs/DECISIONS.md#adr-taskgroup-dispatch), and its
prompt describes the rounds that actually ran (docs/DECISIONS.md#adr-num-rounds).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest

from alphaswarm.config import GovernorSettings
from alphaswarm.errors import BudgetExceededError
from alphaswarm.governor import ResourceGovernor
from alphaswarm.inference.types import InferenceResult, ProviderRole
from alphaswarm.simulation import _generate_decision_narratives
from alphaswarm.types import AgentDecision, AgentPersona, SignalType
from tests.inference.fakes import FakeInferenceProvider


def _decisions(personas: list[AgentPersona]) -> dict[int, list[tuple[str, AgentDecision]]]:
    return {
        1: [
            (p.id, AgentDecision(signal=SignalType.BUY, confidence=0.6, rationale="ZZZT deal"))
            for p in personas
        ]
    }


async def test_budget_error_during_narratives_raises_bare(all_personas: list[AgentPersona]) -> None:
    personas = all_personas[:3]

    def _script(**_: Any) -> InferenceResult:
        raise BudgetExceededError(Decimal("5.00"), Decimal("4.00"))

    graph = AsyncMock()
    with pytest.raises(BudgetExceededError):
        await _generate_decision_narratives(
            personas=personas,
            all_decisions=_decisions(personas),
            graph_manager=graph,
            governor=ResourceGovernor(GovernorSettings(baseline_parallel=4)),
            provider=FakeInferenceProvider(ProviderRole.WORKER, "fake-worker", scripted=_script),
        )
    graph.write_decision_narratives.assert_not_awaited()


async def test_ordinary_failure_skips_only_that_agent(all_personas: list[AgentPersona]) -> None:
    personas = all_personas[:3]
    failing_name = personas[1].name

    def _script(*, messages: list[dict[str, str]], **_: Any) -> InferenceResult:
        if any(f"Agent: {failing_name} " in m["content"] for m in messages):
            raise RuntimeError("model server hiccup")
        return InferenceResult(content="Held BUY throughout.", model="fake-worker")

    graph = AsyncMock()
    narratives = await _generate_decision_narratives(
        personas=personas,
        all_decisions=_decisions(personas),
        graph_manager=graph,
        governor=ResourceGovernor(GovernorSettings(baseline_parallel=4)),
        provider=FakeInferenceProvider(ProviderRole.WORKER, "fake-worker", scripted=_script),
    )
    assert sorted(n["agent_id"] for n in narratives) == sorted([personas[0].id, personas[2].id])
    graph.write_decision_narratives.assert_awaited_once()


async def test_prompt_names_the_number_of_rounds_that_ran(
    all_personas: list[AgentPersona],
) -> None:
    persona = all_personas[0]
    user_prompts: list[str] = []

    def _script(*, messages: list[dict[str, str]], **_: Any) -> InferenceResult:
        user_prompts.extend(m["content"] for m in messages if m["role"] == "user")
        return InferenceResult(content="Turned from BUY to SELL.", model="fake-worker")

    two_rounds: dict[int, list[tuple[str, AgentDecision]]] = {
        1: [(persona.id, AgentDecision(signal=SignalType.BUY, confidence=0.6, rationale="ZZZT"))],
        2: [(persona.id, AgentDecision(signal=SignalType.SELL, confidence=0.7, rationale="QQQX"))],
    }
    await _generate_decision_narratives(
        personas=[persona],
        all_decisions=two_rounds,
        graph_manager=AsyncMock(),
        governor=ResourceGovernor(GovernorSettings(baseline_parallel=4)),
        provider=FakeInferenceProvider(ProviderRole.WORKER, "fake-worker", scripted=_script),
    )

    [prompt] = user_prompts
    assert "Summarize this agent's 2-round decision arc" in prompt
    assert "3-round" not in prompt
