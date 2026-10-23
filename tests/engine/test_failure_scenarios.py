"""Failure-path scenarios for run_simulation (docs/DECISIONS.md#adr-taskgroup-dispatch).

Builds on the engine scenario harness: ScriptedProvider workers, the autospecced
fake_graph and scenario_settings (jitter 0). All values are fictional.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from alphaswarm.config import AppSettings
from alphaswarm.errors import BudgetExceededError, Neo4jUnavailableError, RoundFailedError
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


class BlockOnRound2(ScriptedProvider):
    """Worker that never answers a round-2 decision call, so a test can cancel mid-round."""

    def __init__(self, *, personas: Sequence[AgentPersona]) -> None:
        super().__init__(personas=personas)
        self.reached_round_2 = asyncio.Event()
        self._decision_calls = 0
        self._agents = len(personas)

    async def chat(self, messages: Any, **kwargs: Any) -> Any:
        if kwargs.get("response_schema") is not None:
            self._decision_calls += 1
            if self._decision_calls > self._agents:
                self.reached_round_2.set()
                await asyncio.Event().wait()
        return await super().chat(messages, **kwargs)


async def test_successful_run_marks_cycle_complete(
    graph: MagicMock,
    scenario_settings: AppSettings,
    all_personas: list[AgentPersona],
    all_brackets: list[BracketConfig],
) -> None:
    await run_case(
        settings=scenario_settings,
        graph=graph,
        worker=ScriptedProvider(personas=all_personas),
        personas=all_personas,
        brackets=all_brackets,
    )
    graph.set_cycle_status.assert_awaited_once_with(CYCLE_ID, "complete")


async def test_round_failure_marks_cycle_failed(
    graph: MagicMock,
    scenario_settings: AppSettings,
    all_personas: list[AgentPersona],
    all_brackets: list[BracketConfig],
) -> None:
    def decide(agent_id: str, round_num: int, call: ScriptedCall) -> AgentDecision | BaseException:
        if round_num == 2:
            return RuntimeError("model server died")
        return default_decision_script(agent_id, round_num, call)

    with pytest.raises(RoundFailedError):
        await run_case(
            settings=scenario_settings,
            graph=graph,
            worker=ScriptedProvider(personas=all_personas, decide=decide),
            personas=all_personas,
            brackets=all_brackets,
        )
    graph.set_cycle_status.assert_awaited_once_with(CYCLE_ID, "failed", error_code="round_failed")


async def test_budget_error_marks_cycle_failed(
    graph: MagicMock,
    scenario_settings: AppSettings,
    all_personas: list[AgentPersona],
    all_brackets: list[BracketConfig],
) -> None:
    def decide(agent_id: str, round_num: int, call: ScriptedCall) -> AgentDecision | BaseException:
        if round_num == 3:
            return BudgetExceededError(Decimal("5.00"), Decimal("4.00"))
        return default_decision_script(agent_id, round_num, call)

    with pytest.raises(BudgetExceededError):
        await run_case(
            settings=scenario_settings,
            graph=graph,
            worker=ScriptedProvider(personas=all_personas, decide=decide),
            personas=all_personas,
            brackets=all_brackets,
        )
    graph.set_cycle_status.assert_awaited_once_with(CYCLE_ID, "failed", error_code="budget_exceeded")


async def test_cancel_mid_round_marks_cycle_cancelled(
    graph: MagicMock,
    scenario_settings: AppSettings,
    all_personas: list[AgentPersona],
    all_brackets: list[BracketConfig],
) -> None:
    # Stop pressed during round 2.
    worker = BlockOnRound2(personas=all_personas)
    task = asyncio.create_task(
        run_case(
            settings=scenario_settings,
            graph=graph,
            worker=worker,
            personas=all_personas,
            brackets=all_brackets,
        )
    )
    await asyncio.wait_for(worker.reached_round_2.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    graph.set_cycle_status.assert_awaited_once_with(CYCLE_ID, "cancelled", error_code=None)
    assert persisted_rounds(graph) == [1]


async def test_failure_before_the_cycle_exists_writes_no_status(
    graph: MagicMock,
    scenario_settings: AppSettings,
    all_personas: list[AgentPersona],
    all_brackets: list[BracketConfig],
) -> None:
    def _crash(call: ScriptedCall) -> str:
        raise RuntimeError("orchestrator crashed while parsing the seed")

    with pytest.raises(RuntimeError):
        await run_case(
            settings=scenario_settings,
            graph=graph,
            worker=ScriptedProvider(personas=all_personas),
            personas=all_personas,
            brackets=all_brackets,
            orch=orchestrator(all_personas, script=_crash),
        )
    graph.create_cycle_with_seed_event.assert_not_awaited()
    graph.set_cycle_status.assert_not_awaited()


async def test_status_write_failure_never_masks_the_original_error(
    graph: MagicMock,
    scenario_settings: AppSettings,
    all_personas: list[AgentPersona],
    all_brackets: list[BracketConfig],
) -> None:
    graph.set_cycle_status.side_effect = Neo4jUnavailableError("down", op="set_cycle_status")

    def decide(agent_id: str, round_num: int, call: ScriptedCall) -> AgentDecision | BaseException:
        if round_num == 2:
            return BudgetExceededError(Decimal("5.00"), Decimal("4.00"))
        return default_decision_script(agent_id, round_num, call)

    with pytest.raises(BudgetExceededError):
        await run_case(
            settings=scenario_settings,
            graph=graph,
            worker=ScriptedProvider(personas=all_personas, decide=decide),
            personas=all_personas,
            brackets=all_brackets,
        )


async def test_complete_status_write_failure_fails_the_run(
    graph: MagicMock,
    scenario_settings: AppSettings,
    all_personas: list[AgentPersona],
    all_brackets: list[BracketConfig],
) -> None:
    graph.set_cycle_status.side_effect = [
        Neo4jUnavailableError("down", op="set_cycle_status"),  # "complete"
        None,  # "failed"
    ]
    store = RecordingStateStore()
    with pytest.raises(Neo4jUnavailableError):
        await run_case(
            settings=scenario_settings,
            graph=graph,
            worker=ScriptedProvider(personas=all_personas),
            personas=all_personas,
            brackets=all_brackets,
            state_store=store,
        )
    second = graph.set_cycle_status.await_args_list[1]
    assert second.args == (CYCLE_ID, "failed")
    assert second.kwargs == {"error_code": "graph_unavailable"}
    assert SimulationPhase.COMPLETE not in store.phases
