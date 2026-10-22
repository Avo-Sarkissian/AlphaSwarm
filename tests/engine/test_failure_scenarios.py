"""Failure-path scenarios for run_simulation (docs/DECISIONS.md#adr-taskgroup-dispatch).

Builds on the engine scenario harness: ScriptedProvider workers, the autospecced
fake_graph and scenario_settings (jitter 0). All values are fictional.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from alphaswarm.config import AppSettings
from alphaswarm.errors import BudgetExceededError, RoundFailedError
from alphaswarm.inference.types import ProviderRole
from alphaswarm.simulation import SimulationResult, run_simulation
from alphaswarm.state import StateStore
from alphaswarm.types import (
    AgentDecision,
    AgentPersona,
    BracketConfig,
    BracketType,
    SimulationPhase,
)
from tests.engine.scenario import RecordingStateStore, persisted_rounds
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
MODIFIERS_JSON = json.dumps({b.value: "Weigh the ZZZT Holdings and QQQX Robotics deal terms." for b in BracketType})


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


async def test_fully_failed_final_round_skips_influence_edges(
    graph: MagicMock,
    scenario_settings: AppSettings,
    all_personas: list[AgentPersona],
    all_brackets: list[BracketConfig],
) -> None:
    def decide(agent_id: str, round_num: int, call: ScriptedCall) -> AgentDecision | BaseException:
        if round_num == 3:
            return RuntimeError("model server died")
        return default_decision_script(agent_id, round_num, call)

    worker = ScriptedProvider(personas=all_personas, decide=decide)
    result = await run_case(
        settings=with_threshold(scenario_settings, 100.0),
        graph=graph,
        worker=worker,
        personas=all_personas,
        brackets=all_brackets,
    )

    assert len(result.round3_decisions) == len(all_personas)
    rounds = [c.kwargs["up_to_round"] for c in graph.compute_influence_edges.await_args_list]
    assert rounds == [2]


async def test_all_agents_failing_in_round_1_aborts_before_persisting(
    graph: MagicMock,
    scenario_settings: AppSettings,
    all_personas: list[AgentPersona],
    all_brackets: list[BracketConfig],
) -> None:
    # The model server dies mid-round: nothing of the round may be persisted.
    def decide(agent_id: str, round_num: int, call: ScriptedCall) -> AgentDecision | BaseException:
        if round_num == 1:
            return RuntimeError("connection refused by the model server")
        return default_decision_script(agent_id, round_num, call)

    worker = ScriptedProvider(personas=all_personas, decide=decide)
    with pytest.raises(RoundFailedError) as exc_info:
        await run_case(
            settings=scenario_settings,
            graph=graph,
            worker=worker,
            personas=all_personas,
            brackets=all_brackets,
        )

    err = exc_info.value
    assert (err.round_num, err.failed, err.total) == (1, len(all_personas), len(all_personas))
    assert persisted_rounds(graph) == []
    graph.write_cycle_metrics.assert_not_awaited()


async def test_metrics_count_inference_errors_per_round(
    graph: MagicMock,
    scenario_settings: AppSettings,
    all_personas: list[AgentPersona],
    all_brackets: list[BracketConfig],
) -> None:
    flaky = {p.id for p in sorted(all_personas, key=lambda p: p.id)[:10]}

    def decide(agent_id: str, round_num: int, call: ScriptedCall) -> AgentDecision | BaseException:
        if round_num == 2 and agent_id in flaky:
            return RuntimeError("timeout")
        return default_decision_script(agent_id, round_num, call)

    worker = ScriptedProvider(personas=all_personas, decide=decide)
    await run_case(
        settings=scenario_settings,
        graph=graph,
        worker=worker,
        personas=all_personas,
        brackets=all_brackets,
    )

    _, metrics = graph.write_cycle_metrics.await_args.args
    assert metrics["r1_inference_errors"] == 0
    assert metrics["r2_inference_errors"] == 10
    assert metrics["r2_parse_errors"] == 10
    assert metrics["r3_inference_errors"] == 0
    assert metrics["final_round"] == 3


async def test_phase_sequence_includes_finalizing(
    graph: MagicMock,
    scenario_settings: AppSettings,
    all_personas: list[AgentPersona],
    all_brackets: list[BracketConfig],
) -> None:
    store = RecordingStateStore()
    # The phase the UI sees while each post-round write runs: FINALIZING must
    # already be live, not merely appear somewhere in the set_phase order.
    live_phase: dict[str, SimulationPhase] = {}

    def phase_during(write: str) -> Callable[..., None]:
        def record(*_args: object, **_kwargs: object) -> None:
            live_phase[write] = store.snapshot().phase

        return record

    graph.write_decision_narratives.side_effect = phase_during("narratives")
    graph.write_cycle_metrics.side_effect = phase_during("metrics")
    await run_case(
        settings=scenario_settings,
        graph=graph,
        worker=ScriptedProvider(personas=all_personas),
        personas=all_personas,
        brackets=all_brackets,
        state_store=store,
        generate_narratives=True,
    )
    assert store.phases == [
        SimulationPhase.IDLE,
        SimulationPhase.SEEDING,
        SimulationPhase.ROUND_1,
        SimulationPhase.ROUND_2,
        SimulationPhase.ROUND_3,
        SimulationPhase.FINALIZING,
        SimulationPhase.COMPLETE,
    ]
    assert live_phase == {
        "narratives": SimulationPhase.FINALIZING,
        "metrics": SimulationPhase.FINALIZING,
    }
