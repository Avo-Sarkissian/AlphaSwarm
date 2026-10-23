"""run_simulation orchestration on the scripted harness (docs/DECISIONS.md#adr-round-runner).

Replaces the tests that patched run_round1 and Ollama objects. All data is fictional.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

from alphaswarm.errors import RoundFailedError
from alphaswarm.inference.types import ProviderRole
from alphaswarm.rounds import RoundCompleteEvent
from alphaswarm.settings import AppSettings
from alphaswarm.simulation import SimulationDeps, run_simulation
from alphaswarm.state import AppliedShock
from alphaswarm.types import AgentPersona, BracketConfig, SimulationPhase
from tests.engine.scenario import (
    SCENARIO_CYCLE_ID,
    SCENARIO_MODIFIERS_JSON,
    SCENARIO_RUMOR,
    SCENARIO_SEED_JSON,
    SCENARIO_SHOCK_TEXT,
    RecordingStateStore,
    RunScenario,
    failing_in_round,
    round_calls,
)
from tests.inference.fakes import ScriptedProvider
from tests.support.controllers import ImmediateController

SECOND_SHOCK_TEXT = "ZZZT Holdings raises its offer for QQQX Robotics to $4.6B in cash."
FIXED_GIT_SHA = "0" * 40  # pinned by the fixed_git_revision autouse fixture in tests/conftest.py


class LoggedProvider(ScriptedProvider):
    """ScriptedProvider that appends its lifecycle calls to a shared log."""

    def __init__(self, log: list[str], label: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._log = log
        self._label = label

    async def prepare(self) -> None:
        self._log.append(f"{self._label}.prepare")
        await super().prepare()

    async def teardown(self) -> None:
        self._log.append(f"{self._label}.teardown")
        await super().teardown()


class LoggedController(ImmediateController):
    """ImmediateController that appends monitoring calls to a shared log."""

    def __init__(self, log: list[str]) -> None:
        super().__init__()
        self._log = log

    async def start_monitoring(self) -> None:
        self._log.append("monitoring.start")
        await super().start_monitoring()

    async def stop_monitoring(self) -> None:
        self._log.append("monitoring.stop")
        await super().stop_monitoring()


class BlockInRound2(ScriptedProvider):
    """Worker that never answers a round-2 decision call, so a test can press Stop."""

    def __init__(self, *, agents: int, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.reached_round_2 = asyncio.Event()
        self._agents = agents
        self._decisions = 0

    async def chat(self, messages: Any, **kwargs: Any) -> Any:
        if kwargs.get("response_schema") is not None:
            self._decisions += 1
            if self._decisions > self._agents:
                self.reached_round_2.set()
                await asyncio.Event().wait()
        return await super().chat(messages, **kwargs)


async def test_orchestrator_torn_down_before_worker_prepared(
    run_scenario: RunScenario,
    all_personas: list[AgentPersona],
    scenario_store: RecordingStateStore,
) -> None:
    """Never co-resident during rounds; one worker load inside one governor session."""
    log: list[str] = []
    orchestrator = LoggedProvider(
        log,
        "orchestrator",
        role=ProviderRole.ORCHESTRATOR,
        model="scripted-orchestrator",
        personas=all_personas,
        orchestrator_script=[SCENARIO_SEED_JSON, SCENARIO_MODIFIERS_JSON],
    )
    worker = LoggedProvider(
        log,
        "worker",
        personas=all_personas,
        round_source=lambda: scenario_store.snapshot().round_num,
    )

    await run_scenario(orchestrator=orchestrator, worker=worker, controller=LoggedController(log))

    assert log == [
        "orchestrator.prepare",
        "orchestrator.teardown",
        "monitoring.start",
        "worker.prepare",
        "worker.teardown",
        "monitoring.stop",
    ]


async def test_failed_round_tears_down_worker_and_stops_monitoring(
    run_scenario: RunScenario,
    make_scripted_worker: Callable[..., ScriptedProvider],
    scenario_controller: ImmediateController,
    fake_graph: MagicMock,
) -> None:
    """The model server dies in round 2."""
    worker = make_scripted_worker(failing_in_round(2, lambda agent_id: RuntimeError("model server died")))

    with pytest.raises(RoundFailedError):
        await run_scenario(worker=worker)

    assert (worker.prepare_calls, worker.teardown_calls) == (1, 1)
    assert (scenario_controller.monitoring_starts, scenario_controller.monitoring_stops) == (1, 1)
    fake_graph.set_cycle_status.assert_awaited_once_with(SCENARIO_CYCLE_ID, "failed", error_code="round_failed")


async def test_cancel_mid_round_tears_down_worker_once(
    run_scenario: RunScenario,
    all_personas: list[AgentPersona],
    scenario_store: RecordingStateStore,
    scenario_controller: ImmediateController,
    fake_graph: MagicMock,
) -> None:
    """Stop pressed during round 2."""
    worker = BlockInRound2(
        agents=len(all_personas),
        personas=all_personas,
        round_source=lambda: scenario_store.snapshot().round_num,
    )
    task = asyncio.create_task(run_scenario(worker=worker))
    await asyncio.wait_for(worker.reached_round_2.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert (worker.prepare_calls, worker.teardown_calls) == (1, 1)
    assert (scenario_controller.monitoring_starts, scenario_controller.monitoring_stops) == (1, 1)
    fake_graph.set_cycle_status.assert_awaited_once_with(SCENARIO_CYCLE_ID, "cancelled", error_code=None)


async def test_on_round_complete_fires_once_per_round_in_order(run_scenario: RunScenario) -> None:
    events: list[RoundCompleteEvent] = []

    async def _collect(event: RoundCompleteEvent) -> None:
        events.append(event)

    result = await run_scenario(on_round_complete=_collect)

    assert [e.round_num for e in events] == [1, 2, 3]
    assert events[0].shift is None
    assert all(e.shift is not None for e in events[1:])
    assert [e.agent_decisions for e in events] == [o.decisions for o in result.rounds]
    assert [e.bracket_summaries for e in events] == [o.bracket_summaries for o in result.rounds]
    assert {e.cycle_id for e in events} == {SCENARIO_CYCLE_ID}


async def test_result_has_one_outcome_per_round(
    run_scenario: RunScenario,
    scripted_worker: ScriptedProvider,
    all_personas: list[AgentPersona],
) -> None:
    result = await run_scenario()

    assert [o.round_num for o in result.rounds] == [1, 2, 3]
    assert result.round2_decisions == result.rounds[1].decisions
    assert result.round3_shifts == result.rounds[2].shift
    first, second, _ = result.rounds
    assert first.shift is None
    assert dict(first.influence_weights) == {}
    assert first.exposures == tuple(() for _ in all_personas)
    shown = {c.agent_id: set(c.shown_peer_ids) for c in round_calls(scripted_worker, 2)}
    exposures = dict(zip((p.id for p in all_personas), second.exposures, strict=True))
    assert {agent: set(peers) for agent, peers in exposures.items()} == shown
    assert len(second.decision_ids) == len(all_personas)
    assert second.shift is not None
    assert second.metrics["r2_flips"] == second.shift.total_flips


async def test_two_round_run_result_and_metrics(
    run_scenario: RunScenario,
    scenario_store: RecordingStateStore,
    fake_graph: MagicMock,
) -> None:
    """ALPHASWARM_NUM_ROUNDS=2."""
    result = await run_scenario(num_rounds=2)

    assert [o.round_num for o in result.rounds] == [1, 2]
    assert (result.round3_decisions, result.round3_summaries) == ((), ())
    assert result.round3_shifts.total_flips == 0
    assert scenario_store.phases[-3:] == [
        SimulationPhase.ROUND_2,
        SimulationPhase.FINALIZING,
        SimulationPhase.COMPLETE,
    ]
    _, metrics = fake_graph.write_cycle_metrics.await_args.args
    assert (metrics["num_rounds"], metrics["final_round"]) == (2, 2)
    assert (metrics["r3_flips"], metrics["r3_parse_errors"], metrics["r3_seconds"]) == (0, 0, 0.0)
    assert sorted(k for k in metrics if k.startswith("r3_")) == [
        "r3_flips",
        "r3_parse_errors",
        "r3_seconds",
    ]


async def test_shocks_are_written_once_and_carried_forward(
    run_scenario: RunScenario,
    scripted_worker: ScriptedProvider,
    scenario_store: RecordingStateStore,
    fake_graph: MagicMock,
) -> None:
    """Shocks before round 2 and before round 3."""
    result = await run_scenario(shocks={2: SCENARIO_SHOCK_TEXT, 3: SECOND_SHOCK_TEXT})

    writes = [(c.args[1], c.kwargs["injected_before_round"]) for c in fake_graph.write_shock_event.await_args_list]
    assert writes == [(SCENARIO_SHOCK_TEXT, 2), (SECOND_SHOCK_TEXT, 3)]
    assert result.rounds[2].applied_shocks == (SCENARIO_SHOCK_TEXT, SECOND_SHOCK_TEXT)
    assert scenario_store.snapshot().applied_shocks == (
        AppliedShock(SCENARIO_SHOCK_TEXT, 2),
        AppliedShock(SECOND_SHOCK_TEXT, 3),
    )
    r3_user = round_calls(scripted_worker, 3)[0].messages[-1]["content"]
    assert r3_user.endswith(
        f"{SCENARIO_RUMOR}\n\n[MARKET SHOCK]: {SCENARIO_SHOCK_TEXT}\n\n[MARKET SHOCK]: {SECOND_SHOCK_TEXT}"
    )


async def test_shock_is_consumed_after_the_round_starts(
    scenario_settings: AppSettings,
    fake_graph: MagicMock,
    scenario_controller: ImmediateController,
    scripted_orchestrator: ScriptedProvider,
    scripted_worker: ScriptedProvider,
    scenario_store: RecordingStateStore,
    all_personas: list[AgentPersona],
    all_brackets: list[BracketConfig],
) -> None:
    """The last round consumes with the shock window already closed."""
    seen: list[tuple[str, int, bool]] = []

    def consume_shock() -> str | None:
        snap = scenario_store.snapshot()
        seen.append((snap.phase.value, snap.round_num, scenario_store.shock_window_open()))
        return None

    deps = SimulationDeps(
        settings=scenario_settings,
        graph=fake_graph,
        controller=scenario_controller,
        orchestrator=scripted_orchestrator,
        worker=scripted_worker,
        state=scenario_store,
    )
    await run_simulation(SCENARIO_RUMOR, deps, list(all_personas), list(all_brackets), consume_shock=consume_shock)

    assert seen == [("round_2", 2, True), ("round_3", 3, False)]


async def test_cycle_metrics_carry_exposure_and_provenance(
    run_scenario: RunScenario,
    all_personas: list[AgentPersona],
    scenario_store: RecordingStateStore,
    fake_graph: MagicMock,
) -> None:
    worker = ScriptedProvider(
        personas=all_personas,
        model="cloud-worker",
        is_local=False,
        round_source=lambda: scenario_store.snapshot().round_num,
    )

    await run_scenario(worker=worker)

    _, metrics = fake_graph.write_cycle_metrics.await_args.args
    assert (metrics["worker_model"], metrics["worker_provider"]) == ("cloud-worker", "cloud")
    assert (metrics["orchestrator_provider"], metrics["inference_mode"]) == ("ollama", "mixed")
    assert metrics["git_sha"] == FIXED_GIT_SHA
    for n in (2, 3):
        assert metrics[f"r{n}_distinct_peers_shown"] > 0
        assert f"r{n}_exposure_quants" in metrics
    assert "r1_distinct_peers_shown" not in metrics


async def test_git_state_is_read_off_the_event_loop(
    run_scenario: RunScenario, fake_graph: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The git subprocess (up to two 5 s timeouts) never blocks the event loop's thread."""
    git_threads: list[int] = []

    def git_state() -> tuple[str, bool]:
        git_threads.append(threading.get_ident())
        return "c" * 40, False

    monkeypatch.setattr("alphaswarm.simulation.current_git_revision", git_state)

    await run_scenario()

    loop_thread = threading.get_ident()  # an async test body runs on the loop's thread
    assert len(git_threads) == 1
    assert git_threads[0] != loop_thread
    _, metrics = fake_graph.write_cycle_metrics.await_args.args
    assert metrics["git_sha"] == "c" * 40
