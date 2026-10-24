"""Interviews rebuild the persona with the traits the agent ran with (docs/DECISIONS.md#adr-persona-traits)."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from alphaswarm.interview import interview_persona, load_interview_context
from alphaswarm.personas import generate_personas, load_bracket_configs
from tests.support.interview_fakes import interview_rows

if TYPE_CHECKING:
    from alphaswarm.graph import AgentInterviewRows, GraphStateManager


def test_interview_persona_carries_the_cycles_traits() -> None:
    rows = interview_rows("quants_01")
    expected = next(p for p in generate_personas(load_bracket_configs(), seed=101) if p.id == "quants_01")
    assert interview_persona(rows, "c1", trait_seed=101).system_prompt == expected.system_prompt
    assert "Your horizon:" not in interview_persona(rows, "c1").system_prompt


class _Graph:
    def __init__(self, trait_seed: int | None) -> None:
        self._trait_seed = trait_seed
        self.trait_reads: list[str] = []

    async def read_agent_interview_rows(self, agent_id: str, cycle_id: str) -> AgentInterviewRows:
        return interview_rows(agent_id)

    async def read_persona_trait_seed(self, cycle_id: str) -> int | None:
        self.trait_reads.append(cycle_id)
        return self._trait_seed


async def test_load_interview_context_reads_the_trait_seed() -> None:
    traits_on, traits_off = _Graph(101), _Graph(None)
    with_traits = await load_interview_context(cast("GraphStateManager", traits_on), "quants_01", "c1")
    without = await load_interview_context(cast("GraphStateManager", traits_off), "quants_01", "c1")
    assert "Your horizon:" in with_traits.interview_system_prompt
    assert "Your horizon:" not in without.interview_system_prompt
    assert traits_on.trait_reads == ["c1"]
