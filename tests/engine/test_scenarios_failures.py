"""Failure-path scenarios: agent errors, malformed output, hard stops, cancellation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from alphaswarm.errors import BudgetExceededError, InferenceError, RoundFailedError
from alphaswarm.inference.types import InferenceMessage, InferenceResult
from alphaswarm.types import AgentDecision, AgentPersona, SignalType, SimulationPhase
from tests.engine.scenario import (
    RecordingStateStore,
    RunScenario,
    failing_in_round,
    persisted_rounds,
    recorded_decisions,
    round_calls,
)
from tests.inference.fakes import ScriptedProvider
from tests.support.controllers import ImmediateController


def _decision(fake_graph: MagicMock, round_num: int, agent_id: str) -> AgentDecision:
    return dict(recorded_decisions(fake_graph)[round_num])[agent_id]


def _timeout(agent_id: str) -> BaseException:
    return InferenceError("read timed out", provider="ollama", model="scripted-worker")


def _ollama_died(agent_id: str) -> BaseException:
    return InferenceError("ollama died", provider="ollama", model="scripted-worker")


def _budget_stop(agent_id: str) -> BaseException:
    return BudgetExceededError(Decimal("1.00"), Decimal("0.50"))


async def _run_until(run: asyncio.Task[Any], reached: asyncio.Event, what: str) -> None:
    """Wait until ``reached`` is set; fail (without hanging) if the run ends first."""
    waiter = asyncio.create_task(reached.wait())
    done, _ = await asyncio.wait({run, waiter}, return_when=asyncio.FIRST_COMPLETED)
    if waiter not in done:
        waiter.cancel()
        raise AssertionError(f"the run finished before {what}")


class _GarbledOutput(ScriptedProvider):
    """Returns non-JSON text for one (agent, round); every other call is scripted."""

    def __init__(self, *, agent_id: str, round_num: int, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._target = (agent_id, round_num)

    async def chat(self, messages: list[InferenceMessage], **kwargs: Any) -> InferenceResult:
        result = await super().chat(messages, **kwargs)
        last = self.scripted_calls[-1]
        if last.kind == "decision" and (last.agent_id, last.round_num) == self._target:
            return InferenceResult(content="BUY BUY BUY, no JSON today", model=self.model)
        return result


class _StallingWorker(ScriptedProvider):
    """Blocks every decision call of ``stall_round`` until the run is cancelled."""

    def __init__(self, *, stall_round: int, current_round: Callable[[], int], **kwargs: Any) -> None:
        super().__init__(round_source=current_round, **kwargs)
        self._stall_round = stall_round
        self._current_round = current_round
        self.stalled = asyncio.Event()

    async def chat(self, messages: list[InferenceMessage], **kwargs: Any) -> InferenceResult:
        if kwargs.get("response_schema") is not None and self._current_round() == self._stall_round:
            self.stalled.set()
            await asyncio.Event().wait()  # never set: only cancellation ends this call
        return await super().chat(messages, **kwargs)


async def test_single_agent_inference_failure_becomes_parse_error_hidden_from_peers(
    run_scenario: RunScenario,
    make_scripted_worker: Callable[..., ScriptedProvider],
    fake_graph: MagicMock,
    scenario_controller: ImmediateController,
    scenario_store: RecordingStateStore,
) -> None:
    worker = make_scripted_worker(failing_in_round(1, _timeout, agent_ids={"sell_side_01"}))
    await run_scenario(worker=worker)
    failed = _decision(fake_graph, 1, "sell_side_01")
    assert failed.signal is SignalType.PARSE_ERROR
    assert failed.rationale.startswith("Inference failed for sell_side_01")
    assert failed.error_kind == "inference"
    assert len(round_calls(worker, 2)) == 100
    assert all("sell_side_01" not in c.shown_peer_ids for c in round_calls(worker, 2))
    assert fake_graph.write_cycle_metrics.await_args.args[1]["r1_parse_errors"] == 1
    assert scenario_controller.wave_reports == [(99, 1)]
    assert scenario_controller.failures == 1
    assert scenario_store.phases[-1] is SimulationPhase.COMPLETE


async def test_malformed_worker_output_becomes_parse_error_and_run_completes(
    run_scenario: RunScenario,
    all_personas: list[AgentPersona],
    fake_graph: MagicMock,
    scenario_controller: ImmediateController,
    scenario_store: RecordingStateStore,
) -> None:
    worker = _GarbledOutput(
        agent_id="degens_03",
        round_num=1,
        personas=all_personas,
        round_source=lambda: scenario_store.snapshot().round_num,
    )
    await run_scenario(worker=worker)
    garbled = _decision(fake_graph, 1, "degens_03")
    assert garbled.signal is SignalType.PARSE_ERROR
    assert garbled.rationale.startswith("Parse failed:")
    assert garbled.error_kind == "parse"
    assert len(round_calls(worker, 2)) == 100
    assert all("degens_03" not in c.shown_peer_ids for c in round_calls(worker, 2))
    assert fake_graph.write_cycle_metrics.await_args.args[1]["r1_parse_errors"] == 1
    assert scenario_controller.wave_reports == [(99, 1)]
    assert scenario_controller.failures == 0  # the call succeeded; only parsing failed
    assert scenario_store.phases[-1] is SimulationPhase.COMPLETE


async def test_round_where_every_agent_fails_aborts_before_persisting(
    run_scenario: RunScenario,
    make_scripted_worker: Callable[..., ScriptedProvider],
    fake_graph: MagicMock,
) -> None:
    worker = make_scripted_worker(failing_in_round(2, _ollama_died))
    with pytest.raises(RoundFailedError) as excinfo:
        await run_scenario(worker=worker)
    assert (excinfo.value.round_num, excinfo.value.failed) == (2, 100)
    assert persisted_rounds(fake_graph) == [1]


async def test_budget_exceeded_halts_run_without_persisting_the_round(
    run_scenario: RunScenario,
    make_scripted_worker: Callable[..., ScriptedProvider],
    fake_graph: MagicMock,
    scenario_store: RecordingStateStore,
    scenario_controller: ImmediateController,
) -> None:
    worker = make_scripted_worker(failing_in_round(2, _budget_stop, agent_ids={"quants_01"}))
    with pytest.raises(BudgetExceededError) as excinfo:
        await run_scenario(worker=worker)
    assert isinstance(excinfo.value.__cause__, ExceptionGroup)
    assert persisted_rounds(fake_graph) == [1]
    assert scenario_store.phases[-1] is SimulationPhase.ROUND_2
    assert worker.prepare_calls == worker.teardown_calls
    assert scenario_controller.monitoring_starts == scenario_controller.monitoring_stops
    assert scenario_controller.in_use == 0
    fake_graph.write_cycle_metrics.assert_not_awaited()


async def test_budget_exceeded_surfaces_unwrapped(
    run_scenario: RunScenario, make_scripted_worker: Callable[..., ScriptedProvider]
) -> None:
    worker = make_scripted_worker(failing_in_round(2, _budget_stop, agent_ids={"quants_01"}))
    with pytest.raises(BudgetExceededError):
        await run_scenario(worker=worker)


async def test_cancellation_mid_round_releases_worker_and_governor(
    run_scenario: RunScenario,
    all_personas: list[AgentPersona],
    fake_graph: MagicMock,
    scenario_store: RecordingStateStore,
    scenario_controller: ImmediateController,
) -> None:
    worker = _StallingWorker(
        stall_round=2,
        current_round=lambda: scenario_store.snapshot().round_num,
        personas=all_personas,
    )
    run = asyncio.create_task(run_scenario(worker=worker))
    await _run_until(run, worker.stalled, "round 2 dispatch started")
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    assert persisted_rounds(fake_graph) == [1]
    assert scenario_store.phases[-1] is SimulationPhase.ROUND_2
    assert worker.prepare_calls == worker.teardown_calls
    assert scenario_controller.monitoring_starts == scenario_controller.monitoring_stops
    assert scenario_controller.in_use == 0
    fake_graph.write_cycle_metrics.assert_not_awaited()
