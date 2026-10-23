"""Full report for the seeded cycles: one orchestrator call, golden markdown."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from alphaswarm.inference.types import ProviderRole
from alphaswarm.report import generate_report
from tests.inference.fakes import ScriptedProvider
from tests.support.golden import assert_golden

if TYPE_CHECKING:
    from alphaswarm.graph import GraphStateManager
    from alphaswarm.types import AgentPersona
    from tests.support.seed_builder import SeededCycle

pytestmark = pytest.mark.neo4j

NARRATIVE_JSON = json.dumps(
    {
        "summary": "The seeded swarm ended with a mixed final round after peer rounds moved several brackets.",
        "moments": ["R2: the first peer round changed several positions.", "R3: degens_99 piled in."],
        "dissent": ["Several agents finished against their bracket majority."],
        "followups": ["Re-run with a shock before round 2 to compare pivot rates."],
    }
)


def _orchestrator(personas: list[AgentPersona]) -> ScriptedProvider:
    return ScriptedProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="scripted-orchestrator",
        personas=personas,
        orchestrator_script=[NARRATIVE_JSON],
    )


async def test_full_report_golden(
    graph_reader: GraphStateManager,
    seeded_cycle: SeededCycle,
    all_personas: list[AgentPersona],
    tmp_path: Path,
) -> None:
    orchestrator = _orchestrator(all_personas)
    result = await generate_report(
        gm=graph_reader,
        provider=orchestrator,
        cycle_id=seeded_cycle.cycle_id,
        reports_dir=tmp_path,
    )
    assert len(orchestrator.calls_for("orchestrator")) == 1
    assert "degens_99" not in result.content  # an ungrounded agent id is dropped
    assert_golden("report/full_report.md", result.content)
    assert_golden("report/full_report_sections.json", dataclasses.asdict(result.sections))


async def test_two_round_cycle_report(
    graph_reader: GraphStateManager,
    seeded_cycle_2r: SeededCycle,
    all_personas: list[AgentPersona],
    tmp_path: Path,
) -> None:
    orchestrator = _orchestrator(all_personas)
    result = await generate_report(
        gm=graph_reader,
        provider=orchestrator,
        cycle_id=seeded_cycle_2r.cycle_id,
        reports_dir=tmp_path,
    )
    assert "**Rounds:** 2" in result.content
    assert [row["round_num"] for row in result.sections.convergence] == [1, 2]
    user_prompt = orchestrator.calls_for("orchestrator")[0].messages[-1]["content"]
    assert '"final_round": 2' in user_prompt
    assert "Round 3" not in result.content
