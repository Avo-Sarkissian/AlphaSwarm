"""Engine-level checks for the focal-instrument line (docs/DECISIONS.md#adr-decision-prompt)
and seeded persona traits (docs/DECISIONS.md#adr-persona-traits)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

from alphaswarm.inference.types import ProviderRole
from alphaswarm.ingestion.providers import FakeMarketDataProvider, FakeNewsProvider
from alphaswarm.ingestion.types import NewsSlice
from alphaswarm.settings import AppSettings, SimulationSettings
from alphaswarm.types import AgentPersona
from tests.engine.scenario import (
    SCENARIO_MODIFIERS_JSON,
    SCENARIO_RUMOR,
    SCENARIO_SEED_JSON,
    RunScenario,
    round_calls,
)
from tests.inference.fakes import ScriptedCall, ScriptedProvider

SEED_WITH_TICKERS = json.dumps(
    {
        "entities": [
            {
                "name": "ZZZT Holdings",
                "type": "company",
                "relevance": 0.95,
                "sentiment": 0.6,
                "ticker": "ZZZT",
            },
            {
                "name": "QQQX Robotics",
                "type": "company",
                "relevance": 0.9,
                "sentiment": 0.7,
                "ticker": "QQQX",
            },
            {"name": "Industrial Automation", "type": "sector", "relevance": 0.6, "sentiment": 0.4},
        ],
        "overall_sentiment": 0.55,
    }
)
FOCAL = "Instrument in focus: ZZZT (ZZZT Holdings)."


def _orchestrator(personas: list[AgentPersona], *script: str) -> ScriptedProvider:
    return ScriptedProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="scripted-orchestrator",
        personas=personas,
        orchestrator_script=list(script),
    )


async def test_every_decision_ends_with_the_focal_line(
    run_scenario: RunScenario, scripted_worker: ScriptedProvider, all_personas: list[AgentPersona]
) -> None:
    await run_scenario(
        num_rounds=2,
        orchestrator=_orchestrator(all_personas, SEED_WITH_TICKERS, SCENARIO_MODIFIERS_JSON),
    )
    calls = scripted_worker.calls_for("decision")
    assert len(calls) == 200
    for call in calls:
        user = call.messages[-1]["content"]
        assert user.index(SCENARIO_RUMOR) < user.index(FOCAL)
        assert user.rstrip().endswith("the way your role instructions define them.")
        assert all(FOCAL not in m["content"] for m in call.messages if m["role"] == "system")


async def test_seed_without_tickers_sends_no_focal_line(
    run_scenario: RunScenario, scripted_worker: ScriptedProvider
) -> None:
    await run_scenario(num_rounds=2)
    calls = scripted_worker.calls_for("decision")
    assert calls
    assert all("Instrument in focus" not in c.messages[-1]["content"] for c in calls)


def _system_text(call: ScriptedCall) -> str:
    return "\n".join(m["content"] for m in call.messages if m["role"] == "system")


async def test_persona_traits_reach_every_agent(
    run_scenario: RunScenario, scripted_worker: ScriptedProvider, scenario_settings: AppSettings
) -> None:
    scenario_settings.simulation = SimulationSettings(persona_traits=True, sim_seed=101)
    await run_scenario(num_rounds=2)
    systems = [_system_text(c) for c in round_calls(scripted_worker, 1)]
    assert len(systems) == 100 and all("Your horizon:" in s for s in systems)
    assert len(set(systems)) == 100


async def test_persona_traits_off_sends_no_trait_line(
    run_scenario: RunScenario, scripted_worker: ScriptedProvider, scenario_settings: AppSettings
) -> None:
    scenario_settings.simulation = SimulationSettings(persona_traits=False, sim_seed=101)
    await run_scenario(num_rounds=2)
    calls = scripted_worker.calls_for("decision")
    assert calls and all("Your horizon:" not in _system_text(c) for c in calls)


def _metrics(fake_graph: MagicMock) -> dict[str, object]:
    return dict(fake_graph.write_cycle_metrics.await_args_list[-1].args[1])


async def test_tier3_modifiers_add_no_focus_line(
    run_scenario: RunScenario,
    scripted_worker: ScriptedProvider,
    fake_graph: MagicMock,
    all_personas: list[AgentPersona],
) -> None:
    orchestrator = _orchestrator(all_personas, SCENARIO_SEED_JSON, "not json", "still not json")
    await run_scenario(num_rounds=2, orchestrator=orchestrator)
    calls = scripted_worker.calls_for("decision")
    assert calls and all("This cycle you are focused as" not in _system_text(c) for c in calls)
    assert _metrics(fake_graph)["modifier_parse_tier"] == 3


async def test_partial_modifiers_focus_only_the_filled_brackets(
    run_scenario: RunScenario, scripted_worker: ScriptedProvider, all_personas: list[AgentPersona]
) -> None:
    only_quants = json.dumps({"quants": "specialist modelling deal-spread mean reversion"})
    await run_scenario(num_rounds=2, orchestrator=_orchestrator(all_personas, SCENARIO_SEED_JSON, only_quants))
    focused = {
        c.agent_id for c in round_calls(scripted_worker, 1) if "This cycle you are focused as" in _system_text(c)
    }
    assert focused == {p.id for p in all_personas if p.bracket.value == "quants"}


async def test_modifier_request_carries_no_entity_sentiment(
    run_scenario: RunScenario, scripted_orchestrator: ScriptedProvider, fake_graph: MagicMock
) -> None:
    await run_scenario(num_rounds=2)
    modifier_call = scripted_orchestrator.calls_for("orchestrator")[1]
    user = modifier_call.messages[-1]["content"]
    assert "(type: company)" in user and "sentiment" not in user
    assert _metrics(fake_graph)["modifier_parse_tier"] == 1


def _news(headlines_per_entity: int) -> FakeNewsProvider:
    at = datetime(2026, 10, 3, tzinfo=UTC)
    return FakeNewsProvider(
        {
            name: NewsSlice(
                entity=name,
                headlines=tuple(f"{name} headline {i}" for i in range(1, headlines_per_entity + 1)),
                fetched_at=at,
                source="fake_news",
            )
            for name in ("ZZZT Holdings", "QQQX Robotics")
        }
    )


async def test_private_headlines_flag_gives_agents_different_blocks(
    run_scenario: RunScenario, scripted_worker: ScriptedProvider, scenario_settings: AppSettings
) -> None:
    scenario_settings.simulation = SimulationSettings(private_headlines=True, sim_seed=101)
    await run_scenario(num_rounds=2, market_provider=FakeMarketDataProvider(), news_provider=_news(8))
    users = [c.messages[-1]["content"] for c in round_calls(scripted_worker, 1)]
    assert len(users) == 100 and len(set(users)) > 1
    assert all("ZZZT Holdings headline" in u for u in users)


async def test_private_headlines_off_shares_one_block(
    run_scenario: RunScenario, scripted_worker: ScriptedProvider, scenario_settings: AppSettings
) -> None:
    scenario_settings.simulation = SimulationSettings(private_headlines=False, sim_seed=101)
    await run_scenario(num_rounds=2, market_provider=FakeMarketDataProvider(), news_provider=_news(8))
    users = {c.messages[-1]["content"] for c in round_calls(scripted_worker, 1)}
    assert len(users) == 1 and "ZZZT Holdings headline 5" in next(iter(users))
