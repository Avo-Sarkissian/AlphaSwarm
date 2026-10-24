"""run_simulation: run seed, per-call seeds and the run manifest."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from alphaswarm import simulation
from alphaswarm.inference.types import ProviderRole
from alphaswarm.ingestion.providers import FakeMarketDataProvider, FakeNewsProvider
from alphaswarm.ingestion.types import NewsSlice
from alphaswarm.manifest import (
    ModelRef,
    RunManifest,
    RunProvenance,
    derive_call_seed,
    derive_sim_seed,
)
from alphaswarm.personas import compute_prompt_template_hash
from alphaswarm.rounds import SimulationDeps
from alphaswarm.settings import AppSettings, SimulationSettings
from alphaswarm.types import AgentPersona, BracketConfig
from tests.conftest import FIXED_GIT_SHA
from tests.engine.scenario import (
    SCENARIO_CYCLE_ID,
    SCENARIO_MODIFIERS_JSON,
    SCENARIO_SEED_JSON,
    RunScenario,
)
from tests.inference.fakes import ScriptedProvider

OTHER_CYCLE_ID = "00000000-0000-4000-8000-000000000002"
HEADLINE = "ZZZT Holdings confirms a strategic review"


def _written_manifest(graph: MagicMock) -> tuple[str, RunManifest]:
    cycle_id, manifest = graph.write_run_manifest.await_args.args
    return cycle_id, manifest


def _metrics(graph: MagicMock) -> dict[str, Any]:
    return dict(graph.write_cycle_metrics.await_args.args[1])


def _round_exposures(graph: MagicMock, round_num: int) -> dict[str, tuple[str, ...]]:
    """Exposures of the most recently persisted ``round_num``."""
    call = [c for c in graph.persist_round.await_args_list if c.args[1] == round_num][-1]
    return {agent_id: tuple(peers) for agent_id, peers in call.kwargs["exposures"].items()}


def _fresh_orchestrator(personas: list[AgentPersona]) -> ScriptedProvider:
    """The scripted orchestrator's replies are consumed once, so each run needs its own."""
    return ScriptedProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="scripted-orchestrator",
        personas=personas,
        orchestrator_script=[SCENARIO_SEED_JSON, SCENARIO_MODIFIERS_JSON],
    )


async def test_manifest_is_written_after_seeding_and_before_round_one(
    run_scenario: RunScenario, fake_graph: MagicMock
) -> None:
    await run_scenario()
    names = [name for name, _, _ in fake_graph.mock_calls if name and "." not in name]

    fake_graph.write_run_manifest.assert_awaited_once()
    assert names.index("create_cycle_with_seed_event") < names.index("write_run_manifest")
    assert names.index("write_run_manifest") < names.index("persist_round")
    cycle_id, manifest = _written_manifest(fake_graph)
    assert cycle_id == manifest.cycle_id == SCENARIO_CYCLE_ID
    assert manifest.sim_seed == derive_sim_seed(SCENARIO_CYCLE_ID)
    assert (manifest.git_sha, manifest.git_dirty) == (FIXED_GIT_SHA, False)
    assert manifest.num_rounds == 3
    assert manifest.inference_mode == "local"
    assert (manifest.orchestrator.model, manifest.worker.model) == (
        "scripted-orchestrator",
        "scripted-worker",
    )
    assert manifest.experiment_tag is None


async def test_explicit_sim_seed_seeds_every_worker_call(
    run_scenario: RunScenario,
    scripted_worker: ScriptedProvider,
    fake_graph: MagicMock,
    scenario_settings: AppSettings,
) -> None:
    scenario_settings.simulation = SimulationSettings(sim_seed=4242, experiment_tag="p7-1-test")
    await run_scenario()

    calls = scripted_worker.calls_for("decision")
    assert len(calls) == 300
    for call in calls:
        assert call.agent_id is not None and call.round_num is not None
        assert call.kwargs["seed"] == derive_call_seed(4242, call.agent_id, call.round_num)
    _, manifest = _written_manifest(fake_graph)
    assert (manifest.sim_seed, manifest.simulation["sim_seed"]) == (4242, 4242)
    assert manifest.experiment_tag == "p7-1-test"
    assert _metrics(fake_graph)["peer_seed_source"] == "sim_seed"


async def test_peers_follow_the_sim_seed_not_the_cycle_id(
    run_scenario: RunScenario,
    make_scripted_worker: Any,
    fake_graph: MagicMock,
    scenario_settings: AppSettings,
    all_personas: list[AgentPersona],
) -> None:
    """The same manifest and seed pick the same Round 2 peers in another cycle.

    Round 2 peers depend only on the run seed and on which Round 1 agents failed
    (Round 1 shows no peers, so no citation weights exist yet); the scripted
    worker is deterministic, so a different cycle id must not change them.
    """
    scenario_settings.simulation = SimulationSettings(sim_seed=4242)
    await run_scenario()
    first = _round_exposures(fake_graph, 2)

    fake_graph.create_cycle_with_seed_event.return_value = OTHER_CYCLE_ID
    await run_scenario(worker=make_scripted_worker(), orchestrator=_fresh_orchestrator(all_personas))
    same_seed_other_cycle = _round_exposures(fake_graph, 2)

    scenario_settings.simulation = SimulationSettings(sim_seed=4343)
    await run_scenario(worker=make_scripted_worker(), orchestrator=_fresh_orchestrator(all_personas))
    other_seed = _round_exposures(fake_graph, 2)

    assert same_seed_other_cycle == first
    assert other_seed != first


async def test_manifest_records_prompts_modifiers_and_the_market_block(
    run_scenario: RunScenario, fake_graph: MagicMock, all_brackets: list[BracketConfig]
) -> None:
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
    _, manifest = _written_manifest(fake_graph)

    assert manifest.market_context is not None and HEADLINE in manifest.market_context
    assert set(manifest.prompt_hashes) == {
        "persona_template",
        "json_output_instructions",
        "modifier_prompt",
        *(f"bracket:{b.bracket_type.value}" for b in all_brackets),
    }
    assert manifest.prompt_hashes["persona_template"] == compute_prompt_template_hash(all_brackets)
    assert all(len(value) == 64 for value in manifest.prompt_hashes.values())
    assert manifest.modifier_parse_tier in (1, 2)
    assert any(manifest.modifiers.values())


async def test_composition_root_provenance_wins_over_the_fallback(
    scenario_settings: AppSettings, all_brackets: list[BracketConfig]
) -> None:
    graph = MagicMock()
    graph.write_run_manifest = AsyncMock()
    provenance = RunProvenance(
        orchestrator=ModelRef(provider="ollama", model="alphaswarm-orchestrator", digest="sha256:" + "a" * 64),
        worker=ModelRef(provider="openai_compatible", model="fictional-cloud-worker"),
        inference_mode="mixed",
    )
    deps = SimulationDeps(
        settings=scenario_settings,
        graph=graph,
        controller=MagicMock(),
        orchestrator=MagicMock(),
        worker=MagicMock(),
        provenance=provenance,
    )

    seed = await simulation._record_run_manifest(deps, SCENARIO_CYCLE_ID, all_brackets, None, None, git=(None, None))

    _, manifest = _written_manifest(graph)
    assert seed == manifest.sim_seed == derive_sim_seed(SCENARIO_CYCLE_ID)
    assert (manifest.orchestrator, manifest.worker) == (provenance.orchestrator, provenance.worker)
    assert manifest.inference_mode == "mixed"
    assert (manifest.git_sha, manifest.git_dirty) == (None, None)
    assert set(manifest.modifiers.values()) == {""}
    assert manifest.market_context is None
