"""Engine-level checks for the focal-instrument line (docs/DECISIONS.md#adr-decision-prompt)
and seeded persona traits (docs/DECISIONS.md#adr-persona-traits)."""

from __future__ import annotations

import json

from alphaswarm.inference.types import ProviderRole
from alphaswarm.settings import AppSettings, SimulationSettings
from alphaswarm.types import AgentPersona
from tests.engine.scenario import (
    SCENARIO_MODIFIERS_JSON,
    SCENARIO_RUMOR,
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
