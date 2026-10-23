"""Fixtures for deterministic run_simulation scenarios."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator, Mapping
from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest

from alphaswarm.config import AppSettings, GovernorSettings
from alphaswarm.graph import GraphStateManager
from alphaswarm.inference.concurrency import ConcurrencyController
from alphaswarm.inference.provider import InferenceProvider
from alphaswarm.inference.types import ProviderRole
from alphaswarm.ingestion.providers import MarketDataProvider, NewsProvider
from alphaswarm.ingestion.types import ContextPacket
from alphaswarm.ollama_client import OllamaClient
from alphaswarm.ollama_models import OllamaModelManager
from alphaswarm.simulation import OnRoundComplete, SimulationResult, run_simulation
from alphaswarm.types import AgentDecision, AgentPersona, BracketConfig
from tests.engine.scenario import (
    SCENARIO_CYCLE_ID,
    SCENARIO_MODIFIERS_JSON,
    SCENARIO_RUMOR,
    SCENARIO_SEED_JSON,
    RecordingStateStore,
    RunScenario,
    influence_weights_from_writes,
)
from tests.inference.fakes import DecisionFn, ScriptedProvider, default_decision_script
from tests.support.controllers import ImmediateController
from tests.support.graph_fakes import SCENARIO_ENTITIES, fake_persist_round

__all__ = ["SCENARIO_CYCLE_ID"]  # re-exported for fixture users; canonical home is scenario.py


@pytest.fixture(autouse=True)
def forbid_real_sleep(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
    """Fail any engine test that asks asyncio.sleep for wall-clock time.

    Positive delays are recorded (not slept) and asserted empty at teardown, so a
    jitter or retry regression is loud even when the dispatcher would otherwise
    swallow the error into a PARSE_ERROR.
    """
    real_sleep = asyncio.sleep
    attempted: list[float] = []

    async def _guarded(delay: float, result: Any = None) -> Any:
        if delay > 0:
            attempted.append(delay)
        return await real_sleep(0, result)

    monkeypatch.setattr(asyncio, "sleep", _guarded)
    yield attempted
    assert attempted == [], f"engine scenario attempted real sleeps: {attempted}"


@pytest.fixture
def scenario_settings() -> AppSettings:
    """Hermetic settings with dispatch jitter disabled."""
    return AppSettings(  # type: ignore[call-arg]
        _env_file=None,
        governor=GovernorSettings(jitter_min_seconds=0.0, jitter_max_seconds=0.0),
    )


@pytest.fixture
def scenario_store() -> RecordingStateStore:
    return RecordingStateStore()


@pytest.fixture
def scenario_controller() -> ImmediateController:
    return ImmediateController()


@pytest.fixture
def make_scripted_worker(
    all_personas: list[AgentPersona], scenario_store: RecordingStateStore
) -> Callable[..., ScriptedProvider]:
    """Build a worker whose round number follows the store (robust to retries)."""

    def _make(decide: DecisionFn = default_decision_script) -> ScriptedProvider:
        return ScriptedProvider(
            personas=all_personas,
            decide=decide,
            round_source=lambda: scenario_store.snapshot().round_num,
        )

    return _make


@pytest.fixture
def scripted_worker(make_scripted_worker: Callable[..., ScriptedProvider]) -> ScriptedProvider:
    return make_scripted_worker()


@pytest.fixture
def scripted_orchestrator(all_personas: list[AgentPersona]) -> ScriptedProvider:
    return ScriptedProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="scripted-orchestrator",
        personas=all_personas,
        orchestrator_script=[SCENARIO_SEED_JSON, SCENARIO_MODIFIERS_JSON],
    )


@pytest.fixture
def fake_graph() -> MagicMock:
    """Autospecced GraphStateManager: wrong call signatures raise TypeError."""
    graph = create_autospec(GraphStateManager, instance=True)
    graph.create_cycle_with_seed_event.return_value = SCENARIO_CYCLE_ID

    def _write_posts(
        agent_decisions: list[tuple[str, AgentDecision]],
        decision_ids: list[str],
        cycle_id: str,
        round_num: int,
    ) -> list[str]:
        return [f"post-r{round_num}-{i:03d}" for i in range(len(agent_decisions))]

    def _influence(cycle_id: str, up_to_round: int, total_agents: int) -> dict[str, float]:
        return influence_weights_from_writes(graph, up_to_round=up_to_round, total_agents=total_agents)

    graph.write_posts.side_effect = _write_posts
    graph.read_cycle_entities.return_value = list(SCENARIO_ENTITIES)
    graph.persist_round.side_effect = fake_persist_round
    graph.compute_influence_edges.side_effect = _influence
    graph.write_shock_event.return_value = "shock-0001"
    return graph


@pytest.fixture
def fake_model_manager() -> MagicMock:
    return create_autospec(OllamaModelManager, instance=True)


@pytest.fixture
def run_scenario(
    scripted_worker: ScriptedProvider,
    scripted_orchestrator: ScriptedProvider,
    fake_graph: MagicMock,
    fake_model_manager: MagicMock,
    scenario_settings: AppSettings,
    scenario_store: RecordingStateStore,
    scenario_controller: ImmediateController,
    all_personas: list[AgentPersona],
    all_brackets: list[BracketConfig],
) -> RunScenario:
    """Run the real run_simulation on scripted fakes."""

    async def _run(
        *,
        num_rounds: int = 3,
        shocks: Mapping[int, str] | None = None,
        worker: InferenceProvider | None = None,
        orchestrator: InferenceProvider | None = None,
        controller: ConcurrencyController | None = None,
        generate_narratives: bool = True,
        market_provider: MarketDataProvider | None = None,
        news_provider: NewsProvider | None = None,
        context_fixture: ContextPacket | None = None,
        on_round_complete: OnRoundComplete = None,
    ) -> SimulationResult:
        pending = dict(shocks or {})

        def consume_shock() -> str | None:
            return pending.pop(scenario_store.snapshot().round_num, None)

        ollama_client = create_autospec(OllamaClient, instance=True)
        ollama_client.chat.side_effect = AssertionError("scenarios must not reach OllamaClient")
        chosen_worker = worker if worker is not None else scripted_worker
        chosen_orchestrator = orchestrator if orchestrator is not None else scripted_orchestrator
        chosen_controller = controller if controller is not None else scenario_controller
        return await run_simulation(
            rumor=SCENARIO_RUMOR,
            settings=scenario_settings.model_copy(update={"num_rounds": num_rounds}),
            ollama_client=ollama_client,
            model_manager=fake_model_manager,
            graph_manager=fake_graph,
            governor=chosen_controller,
            personas=list(all_personas),
            brackets=list(all_brackets),
            on_round_complete=on_round_complete,
            state_store=scenario_store,
            generate_narratives=generate_narratives,
            consume_shock=consume_shock,
            market_provider=market_provider,
            news_provider=news_provider,
            orchestrator_provider=chosen_orchestrator,
            worker_provider=chosen_worker,
            context_fixture=context_fixture,
        )

    return _run
