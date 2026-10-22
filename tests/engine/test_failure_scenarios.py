"""Failure-path scenarios for run_simulation (docs/DECISIONS.md#adr-taskgroup-dispatch).

Builds on the engine scenario harness: ScriptedProvider workers, the autospecced
fake_graph and scenario_settings (jitter 0). All values are fictional.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from alphaswarm.config import AppSettings
from alphaswarm.errors import BudgetExceededError
from alphaswarm.inference.types import ProviderRole
from alphaswarm.simulation import SimulationResult, run_simulation
from alphaswarm.state import StateStore
from alphaswarm.types import (
    AgentDecision,
    AgentPersona,
    BracketConfig,
    BracketType,
)
from tests.engine.scenario import persisted_rounds
from tests.inference.fakes import ScriptedCall, ScriptedProvider, default_decision_script
from tests.support.controllers import ImmediateController

CYCLE_ID = "00000000-0000-4000-8000-000000000005"
RUMOR = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."
SEED_JSON = json.dumps(
    {
        "entities": [
            {"name": "ZZZT Holdings", "type": "company", "relevance": 0.9, "sentiment": 0.5},
            {"name": "QQQX Robotics", "type": "company", "relevance": 0.8, "sentiment": 0.6},
            {"name": "Industrial Automation", "type": "sector", "relevance": 0.6, "sentiment": 0.3},
        ],
        "overall_sentiment": 0.4,
    }
)
MODIFIERS_JSON = json.dumps(
    {b.value: "Weigh the ZZZT Holdings and QQQX Robotics deal terms." for b in BracketType}
)


def orchestrator(personas: Sequence[AgentPersona], script: Any = None) -> ScriptedProvider:
    return ScriptedProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="scripted-orchestrator",
        personas=personas,
        orchestrator_script=script if script is not None else [SEED_JSON, MODIFIERS_JSON],
    )


def with_threshold(settings: AppSettings, percent: float) -> AppSettings:
    governor = settings.governor.model_copy(update={"round_abort_failure_percent": percent})
    return settings.model_copy(update={"governor": governor})


@pytest.fixture()
def graph(fake_graph: MagicMock) -> MagicMock:
    """fake_graph with the returns these scenarios depend on pinned explicitly."""
    fake_graph.create_cycle_with_seed_event.side_effect = None
    fake_graph.create_cycle_with_seed_event.return_value = CYCLE_ID
    fake_graph.compute_influence_edges.side_effect = None
    fake_graph.compute_influence_edges.return_value = {}
    return fake_graph


async def run_case(
    *,
    settings: AppSettings,
    graph: MagicMock,
    worker: ScriptedProvider,
    personas: Sequence[AgentPersona],
    brackets: Sequence[BracketConfig],
    state_store: StateStore | None = None,
    generate_narratives: bool = False,
    orch: ScriptedProvider | None = None,
) -> SimulationResult:
    return await run_simulation(
        RUMOR,
        settings,
        MagicMock(name="ollama_client"),
        AsyncMock(name="model_manager"),
        graph,
        ImmediateController(),
        list(personas),
        list(brackets),
        state_store=state_store,
        generate_narratives=generate_narratives,
        orchestrator_provider=orch if orch is not None else orchestrator(personas),
        worker_provider=worker,
    )


async def test_budget_error_in_round_2_raises_bare_budget_error(
    graph: MagicMock,
    scenario_settings: AppSettings,
    all_personas: list[AgentPersona],
    all_brackets: list[BracketConfig],
) -> None:
    def decide(agent_id: str, round_num: int, call: ScriptedCall) -> AgentDecision | BaseException:
        if round_num == 2:
            return BudgetExceededError(Decimal("5.00"), Decimal("4.00"))
        return default_decision_script(agent_id, round_num, call)

    worker = ScriptedProvider(personas=all_personas, decide=decide)
    with pytest.raises(BudgetExceededError) as exc_info:
        await run_case(
            settings=scenario_settings,
            graph=graph,
            worker=worker,
            personas=all_personas,
            brackets=all_brackets,
        )

    assert isinstance(exc_info.value.__cause__, ExceptionGroup)
    assert persisted_rounds(graph) == [1]
