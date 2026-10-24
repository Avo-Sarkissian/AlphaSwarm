"""Round inputs: own priors, market rounds, uniform temperature, seeds."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from alphaswarm.ingestion.providers import FakeMarketDataProvider, FakeNewsProvider
from alphaswarm.ingestion.types import NewsSlice
from alphaswarm.manifest import derive_call_seed
from alphaswarm.personas import DEFAULT_BRACKETS, generate_personas
from alphaswarm.rounds import RoundContext, RoundOutcome, SimulationDeps, prepare_round_inputs
from alphaswarm.settings import AppSettings, SimulationSettings
from alphaswarm.types import AgentDecision, SignalType
from alphaswarm.worker import UNTRUSTED_DATA_OPEN
from tests.engine.scenario import SCENARIO_CYCLE_ID, SCENARIO_RUMOR, RunScenario, round_calls
from tests.inference.fakes import ScriptedProvider

PERSONAS = generate_personas(DEFAULT_BRACKETS)
HEADLINE = "ZZZT Holdings confirms a strategic review"


def _ctx(sim: SimulationSettings, *, sim_seed: int | None = None) -> RoundContext:
    settings = AppSettings(_env_file=None, simulation=sim)  # type: ignore[call-arg]
    deps = SimulationDeps(
        settings=settings,
        graph=MagicMock(),
        controller=MagicMock(),
        orchestrator=MagicMock(),
        worker=MagicMock(),
        state=None,
        market=None,
        news=None,
    )
    return RoundContext(
        deps=deps,
        cycle_id=SCENARIO_CYCLE_ID,
        personas=tuple(PERSONAS),
        brackets=tuple(DEFAULT_BRACKETS),
        rumor=SCENARIO_RUMOR,
        market_context="MARKET BLOCK",
        entities=(),
        run_seed="run-1",
        on_round_complete=None,
        sim_seed=sim_seed,
    )


def _prev() -> RoundOutcome:
    decisions = tuple(
        (p.id, AgentDecision(signal=SignalType.BUY, confidence=0.6, rationale=f"view {i}"))
        for i, p in enumerate(PERSONAS)
    )
    return RoundOutcome(
        round_num=1,
        decisions=decisions,
        decision_ids=tuple(f"d{i}" for i in range(len(decisions))),
        exposures=((),) * len(decisions),
        shift=None,
        bracket_summaries=(),
        influence_weights={},
        applied_shocks=(),
        seconds=0.0,
        metrics={},
    )


@pytest.mark.parametrize(
    ("rounds", "round_num", "expected"),
    [(1, 1, "MARKET BLOCK"), (1, 2, None), (3, 3, "MARKET BLOCK"), (0, 1, None), (2, 3, None)],
)
def test_market_block_is_gated_by_round(rounds: int, round_num: int, expected: str | None) -> None:
    ctx = _ctx(SimulationSettings(market_context_rounds=rounds))
    prev = None if round_num == 1 else _prev()

    assert prepare_round_inputs(ctx, round_num, prev, ()).market_context == expected


def test_uniform_temperature_overrides_bracket_temperatures() -> None:
    uniform = prepare_round_inputs(_ctx(SimulationSettings(uniform_temperature=0.7)), 1, None, ())
    per_bracket = prepare_round_inputs(_ctx(SimulationSettings()), 1, None, ())

    assert {c["temperature"] for c in uniform.worker_configs} == {0.7}
    assert {c["temperature"] for c in per_bracket.worker_configs} == {p.temperature for p in PERSONAS}


def test_call_seeds_follow_the_run_seed() -> None:
    assert prepare_round_inputs(_ctx(SimulationSettings()), 2, _prev(), ()).call_seeds is None
    seeded = prepare_round_inputs(_ctx(SimulationSettings(), sim_seed=42), 2, _prev(), ())

    assert seeded.call_seeds == tuple(derive_call_seed(42, p.id, 2) for p in PERSONAS)


def test_user_message_carries_active_shocks_oldest_first() -> None:
    inputs = prepare_round_inputs(_ctx(SimulationSettings()), 3, _prev(), ("first shock", "second shock"))

    assert inputs.user_message == (f"{SCENARIO_RUMOR}\n\n[MARKET SHOCK]: first shock\n\n[MARKET SHOCK]: second shock")


async def test_round_prompts_carry_each_agents_own_prior(
    run_scenario: RunScenario, scripted_worker: ScriptedProvider, scenario_settings: AppSettings
) -> None:
    scenario_settings.simulation = SimulationSettings(own_prior_memory=True)
    await run_scenario()

    for round_num in (2, 3):
        for call in round_calls(scripted_worker, round_num):
            user = call.messages[-1]["content"]
            marker = f"Your Round {round_num - 1} position: "
            assert marker in user
            assert user.index(marker) < user.index(SCENARIO_RUMOR)
    assert all("position: " not in c.messages[-1]["content"] for c in round_calls(scripted_worker, 1))


async def test_own_prior_memory_off_sends_no_prior(
    run_scenario: RunScenario, scripted_worker: ScriptedProvider, scenario_settings: AppSettings
) -> None:
    scenario_settings.simulation = SimulationSettings(own_prior_memory=False)
    await run_scenario()

    assert all("position: " not in c.messages[-1]["content"] for c in scripted_worker.calls_for("decision"))


@pytest.mark.parametrize(("rounds", "expected"), [(1, {1}), (3, {1, 2, 3}), (0, set())])
async def test_market_block_reaches_the_configured_rounds(
    run_scenario: RunScenario,
    scripted_worker: ScriptedProvider,
    scenario_settings: AppSettings,
    rounds: int,
    expected: set[int],
) -> None:
    scenario_settings.simulation = SimulationSettings(market_context_rounds=rounds)
    news = FakeNewsProvider(
        {
            "ZZZT Holdings": NewsSlice(
                entity="ZZZT Holdings",
                headlines=(HEADLINE,),
                fetched_at=datetime(2026, 10, 3, tzinfo=UTC),
                source="fake_news",
            )
        }
    )
    await run_scenario(market_provider=FakeMarketDataProvider(), news_provider=news)

    seen = {
        c.round_num for c in scripted_worker.calls_for("decision") if UNTRUSTED_DATA_OPEN in c.messages[-1]["content"]
    }
    assert seen == expected


async def test_uniform_temperature_reaches_every_call(
    run_scenario: RunScenario, scripted_worker: ScriptedProvider, scenario_settings: AppSettings
) -> None:
    scenario_settings.simulation = SimulationSettings(uniform_temperature=0.7)
    await run_scenario(num_rounds=2)

    assert {c.kwargs["temperature"] for c in scripted_worker.calls_for("decision")} == {0.7}
