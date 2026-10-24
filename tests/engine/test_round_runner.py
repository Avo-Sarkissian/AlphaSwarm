"""run_round in isolation on the scripted harness (docs/DECISIONS.md#adr-round-runner)."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

from alphaswarm.errors import RoundAlignmentError
from alphaswarm.rounds import RoundCompleteEvent, RoundContext, SimulationDeps, run_round
from alphaswarm.settings import AppSettings, SimulationSettings
from alphaswarm.state import AppliedShock
from alphaswarm.types import AgentDecision, AgentPersona, BracketConfig, SignalType
from alphaswarm.worker import UNTRUSTED_DATA_OPEN
from tests.engine.scenario import (
    SCENARIO_CYCLE_ID,
    SCENARIO_RUMOR,
    RecordingStateStore,
    failing_in_round,
    round_calls,
)
from tests.inference.fakes import ScriptedProvider
from tests.support.controllers import ImmediateController
from tests.support.graph_fakes import SCENARIO_ENTITIES

MARKET_BLOCK = "== ZZZT Holdings ==\n  - ZZZT Holdings confirms a strategic review"
SHOCK_A = "QQQX Robotics board rejects the offer as undervalued."
SHOCK_B = "ZZZT Holdings raises its offer for QQQX Robotics to $4.6B in cash."


class RoundClock:
    """Round number the scripted worker reports; a test advances it between rounds."""

    def __init__(self) -> None:
        self.round = 1

    def __call__(self) -> int:
        return self.round


@pytest.fixture
def clock() -> RoundClock:
    return RoundClock()


@pytest.fixture
def round_worker(all_personas: list[AgentPersona], clock: RoundClock) -> ScriptedProvider:
    return ScriptedProvider(personas=all_personas, round_source=clock)


@pytest.fixture
def make_ctx(
    fake_graph: MagicMock,
    scenario_settings: AppSettings,
    scenario_store: RecordingStateStore,
    round_worker: ScriptedProvider,
    all_personas: list[AgentPersona],
    all_brackets: list[BracketConfig],
) -> Callable[..., RoundContext]:
    def _make(**overrides: Any) -> RoundContext:
        deps = SimulationDeps(
            settings=overrides.pop("settings", scenario_settings),
            graph=fake_graph,
            controller=ImmediateController(),
            orchestrator=round_worker,
            worker=overrides.pop("worker", round_worker),
            state=scenario_store,
        )
        fields: dict[str, Any] = {
            "deps": deps,
            "cycle_id": SCENARIO_CYCLE_ID,
            "personas": tuple(all_personas),
            "brackets": tuple(all_brackets),
            "rumor": SCENARIO_RUMOR,
            "market_context": MARKET_BLOCK,
            "entities": SCENARIO_ENTITIES,
            "run_seed": SCENARIO_CYCLE_ID,
            "on_round_complete": None,
        }
        fields.update(overrides)
        return RoundContext(**fields)

    return _make


async def test_round_1_sends_the_market_block_and_no_peers(
    make_ctx: Callable[..., RoundContext],
    round_worker: ScriptedProvider,
    fake_graph: MagicMock,
    all_personas: list[AgentPersona],
) -> None:
    outcome = await run_round(make_ctx(), 1, None, ())

    calls = round_calls(round_worker, 1)
    assert len(calls) == len(all_personas)
    assert all(c.shown_peer_ids == () for c in calls)
    assert all(UNTRUSTED_DATA_OPEN in c.messages[-1]["content"] for c in calls)
    assert (outcome.shift, dict(outcome.influence_weights), outcome.applied_shocks) == (None, {}, ())
    assert outcome.exposures == tuple(() for _ in all_personas)
    fake_graph.compute_influence_edges.assert_not_awaited()
    fake_graph.write_shock_event.assert_not_awaited()


async def test_round_2_reads_peers_from_the_previous_outcome_and_drops_the_market_block(
    make_ctx: Callable[..., RoundContext],
    round_worker: ScriptedProvider,
    clock: RoundClock,
    fake_graph: MagicMock,
    scenario_settings: AppSettings,
) -> None:
    # Pins the Round 1-only market block and peers for every reader.
    scenario_settings.simulation = SimulationSettings(market_context_rounds=1, control_fraction=0.0)
    ctx = make_ctx()
    first = await run_round(ctx, 1, None, ())
    clock.round = 2
    second = await run_round(ctx, 2, first, ())

    calls = round_calls(round_worker, 2)
    assert all(UNTRUSTED_DATA_OPEN not in c.messages[-1]["content"] for c in calls)
    assert all(len(c.shown_peer_ids) >= 1 for c in calls)
    assert second.shift is not None
    assert second.metrics["r2_distinct_peers_shown"] >= 1
    active = sum(1 for _, d in second.decisions if d.signal != SignalType.PARSE_ERROR)
    fake_graph.compute_influence_edges.assert_awaited_once_with(SCENARIO_CYCLE_ID, up_to_round=2, total_agents=active)


async def test_round_message_is_rumor_plus_active_shocks(
    make_ctx: Callable[..., RoundContext],
    round_worker: ScriptedProvider,
    clock: RoundClock,
    fake_graph: MagicMock,
    scenario_store: RecordingStateStore,
) -> None:
    """New shocks are written once; active shocks are carried forward."""
    ctx = make_ctx()
    first = await run_round(ctx, 1, None, ())
    clock.round = 2
    second = await run_round(ctx, 2, first, (SHOCK_A,))
    clock.round = 3
    third = await run_round(ctx, 3, second, (SHOCK_A, SHOCK_B))

    writes = [(c.args[1], c.kwargs["injected_before_round"]) for c in fake_graph.write_shock_event.await_args_list]
    assert writes == [(SHOCK_A, 2), (SHOCK_B, 3)]
    assert (first.applied_shocks, second.applied_shocks, third.applied_shocks) == (
        (),
        (SHOCK_A,),
        (SHOCK_A, SHOCK_B),
    )
    assert scenario_store.snapshot().applied_shocks == (
        AppliedShock(SHOCK_A, 2),
        AppliedShock(SHOCK_B, 3),
    )
    r1_user = round_calls(round_worker, 1)[0].messages[-1]["content"]
    r3_user = round_calls(round_worker, 3)[0].messages[-1]["content"]
    assert r1_user.endswith(SCENARIO_RUMOR)
    assert r3_user.endswith(f"{SCENARIO_RUMOR}\n\n[MARKET SHOCK]: {SHOCK_A}\n\n[MARKET SHOCK]: {SHOCK_B}")


async def test_round_outcome_is_frozen_and_aligned(
    make_ctx: Callable[..., RoundContext],
    fake_graph: MagicMock,
    all_personas: list[AgentPersona],
) -> None:
    outcome = await run_round(make_ctx(), 1, None, ())

    assert dataclasses.is_dataclass(outcome)
    with pytest.raises(dataclasses.FrozenInstanceError):
        outcome.round_num = 2  # type: ignore[misc]
    assert [agent_id for agent_id, _ in outcome.decisions] == [p.id for p in all_personas]
    assert outcome.decision_ids == tuple(fake_graph.persist_round.await_args.kwargs["decision_ids"])
    assert set(outcome.metrics) == {
        "r1_seconds",
        "r1_parse_errors",
        "r1_inference_errors",
        "r1_citations_dropped",
        "r1_parse_tier1",
        "r1_parse_tier2",
        "r1_parse_tier3",
        "r1_latency_p50_ms",
        "r1_latency_p95_ms",
        "r1_mean_prompt_tokens",
        "r1_mean_completion_tokens",
        "r1_mean_prefill_ms",
        "r1_mean_decode_ms",
        "r1_total_load_ms",
        "r1_cold_loads",
        "r1_truncations",
        "r1_ctx_warnings",
    }


async def test_misaligned_dispatch_raises_before_persisting(
    make_ctx: Callable[..., RoundContext],
    fake_graph: MagicMock,
    all_personas: list[AgentPersona],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _short_wave(**kwargs: Any) -> list[AgentDecision]:
        return [AgentDecision(signal=SignalType.HOLD, confidence=0.5) for _ in kwargs["personas"][:-1]]

    monkeypatch.setattr("alphaswarm.rounds.dispatch_wave", _short_wave)

    with pytest.raises(RoundAlignmentError) as exc_info:
        await run_round(make_ctx(), 1, None, ())

    assert (exc_info.value.expected, exc_info.value.actual) == (
        len(all_personas),
        len(all_personas) - 1,
    )
    fake_graph.persist_round.assert_not_awaited()


async def test_round_complete_callback_receives_the_outcome(
    make_ctx: Callable[..., RoundContext],
) -> None:
    events: list[RoundCompleteEvent] = []

    async def _collect(event: RoundCompleteEvent) -> None:
        events.append(event)

    outcome = await run_round(make_ctx(on_round_complete=_collect), 1, None, ())

    (event,) = events
    assert (event.round_num, event.cycle_id, event.shift) == (1, SCENARIO_CYCLE_ID, None)
    assert event.agent_decisions == outcome.decisions
    assert event.bracket_summaries == outcome.bracket_summaries


async def test_round_without_active_agents_skips_influence_edges(
    make_ctx: Callable[..., RoundContext],
    scenario_settings: AppSettings,
    all_personas: list[AgentPersona],
    clock: RoundClock,
    scenario_store: RecordingStateStore,
    fake_graph: MagicMock,
) -> None:
    """Every agent failed but the abort threshold is 100 %: no edges, no division by zero.

    The skipped edge step still counts as finished (docs/DECISIONS.md#adr-ws-broadcaster),
    so the version is 1 after round 2 exactly as when edges were computed."""
    governor = scenario_settings.governor.model_copy(update={"round_abort_failure_percent": 100.0})
    settings = scenario_settings.model_copy(update={"governor": governor})
    failing = ScriptedProvider(
        personas=all_personas,
        round_source=clock,
        decide=failing_in_round(2, lambda agent_id: RuntimeError("model server died")),
    )
    ctx = make_ctx(settings=settings, worker=failing)

    first = await run_round(ctx, 1, None, ())
    clock.round = 2
    second = await run_round(ctx, 2, first, ())

    assert all(d.signal == SignalType.PARSE_ERROR for _, d in second.decisions)
    assert dict(second.influence_weights) == {}
    fake_graph.compute_influence_edges.assert_not_awaited()
    assert scenario_store.snapshot().edges_version == 1


async def test_round_2_holds_out_the_seeded_control_readers(
    make_ctx: Callable[..., RoundContext],
    scenario_settings: AppSettings,
    round_worker: ScriptedProvider,
    clock: RoundClock,
    fake_graph: MagicMock,
    all_personas: list[AgentPersona],
) -> None:
    """Control readers get no peers, are flagged on their Decisions and split the flip metrics."""
    sim = scenario_settings.simulation.model_copy(update={"control_fraction": 0.2})
    ctx = make_ctx(settings=scenario_settings.model_copy(update={"simulation": sim}))
    first = await run_round(ctx, 1, None, ())
    clock.round = 2
    second = await run_round(ctx, 2, first, ())

    control_ids = set(fake_graph.persist_round.await_args.kwargs["control_ids"])
    assert fake_graph.persist_round.await_args_list[0].kwargs["control_ids"] == ()
    assert len(control_ids) == second.metrics["r2_control_agents"] == 20
    shown = {c.agent_id: c.shown_peer_ids for c in round_calls(round_worker, 2)}
    assert all(shown[agent_id] == () for agent_id in control_ids)
    assert all(shown[p.id] for p in all_personas if p.id not in control_ids)
    assert second.metrics["r2_flips_control"] + second.metrics["r2_flips_treated"] == second.metrics["r2_flips"]
