"""Unit tests for the Round 1 simulation pipeline (run_round1)."""

from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alphaswarm.config import AppSettings, GovernorSettings
from alphaswarm.types import (
    AgentDecision,
    AgentPersona,
    BracketType,
    EntityType,
    ParsedSeedResult,
    SeedEntity,
    SeedEvent,
    SignalType,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

MOCK_RUMOR = "NVIDIA announces breakthrough"

MOCK_SEED_EVENT = SeedEvent(
    raw_rumor=MOCK_RUMOR,
    entities=[
        SeedEntity(name="NVIDIA", type=EntityType.COMPANY, relevance=0.95, sentiment=0.8),
    ],
    overall_sentiment=0.6,
)

MOCK_PARSED_RESULT = ParsedSeedResult(seed_event=MOCK_SEED_EVENT, parse_tier=1)

TEST_PERSONAS = [
    AgentPersona(
        id="quants_01",
        name="Quants 1",
        bracket=BracketType.QUANTS,
        risk_profile=0.4,
        temperature=0.3,
        system_prompt="test prompt quants 1",
        influence_weight_base=0.7,
    ),
    AgentPersona(
        id="quants_02",
        name="Quants 2",
        bracket=BracketType.QUANTS,
        risk_profile=0.4,
        temperature=0.3,
        system_prompt="test prompt quants 2",
        influence_weight_base=0.7,
    ),
    AgentPersona(
        id="degens_01",
        name="Degens 1",
        bracket=BracketType.DEGENS,
        risk_profile=0.95,
        temperature=1.2,
        system_prompt="test prompt degens 1",
        influence_weight_base=0.3,
    ),
    AgentPersona(
        id="degens_02",
        name="Degens 2",
        bracket=BracketType.DEGENS,
        risk_profile=0.95,
        temperature=1.2,
        system_prompt="test prompt degens 2",
        influence_weight_base=0.3,
    ),
]


@pytest.fixture()
def mock_settings() -> AppSettings:
    """AppSettings with no .env influence."""
    return AppSettings(_env_file=None)  # type: ignore[call-arg]


@pytest.fixture()
def mock_ollama_client() -> MagicMock:
    """Mock OllamaClient."""
    return MagicMock()


@pytest.fixture()
def mock_model_manager() -> AsyncMock:
    """Mock OllamaModelManager with load_model, unload_model, ensure_clean_state."""
    mm = AsyncMock()
    mm.load_model = AsyncMock()
    mm.unload_model = AsyncMock()
    mm.ensure_clean_state = AsyncMock()
    return mm


@pytest.fixture()
def mock_graph_manager() -> AsyncMock:
    """Mock GraphStateManager with write_decisions."""
    gm = AsyncMock()
    gm.write_decisions = AsyncMock()
    return gm


@pytest.fixture()
def mock_governor() -> AsyncMock:
    """Mock ResourceGovernor with start_monitoring and stop_monitoring."""
    gov = AsyncMock()
    gov.start_monitoring = AsyncMock()
    gov.stop_monitoring = AsyncMock()
    gov.report_wave_failures = MagicMock()
    return gov


def _default_decisions(count: int) -> list[AgentDecision]:
    """Return a list of BUY AgentDecision for testing."""
    return [AgentDecision(signal=SignalType.BUY, confidence=0.8)] * count


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock)
@patch("alphaswarm.simulation.inject_seed", new_callable=AsyncMock)
async def test_run_round1_dispatches_with_no_peer_context(
    mock_inject: AsyncMock,
    mock_dispatch: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """dispatch_wave is called with peer_context=None for Round 1."""
    from alphaswarm.simulation import run_round1

    mock_inject.return_value = ("test-cycle-id", MOCK_PARSED_RESULT)
    mock_dispatch.return_value = _default_decisions(len(TEST_PERSONAS))

    await run_round1(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
    )

    assert mock_dispatch.call_args.kwargs["peer_context"] is None


@patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock)
@patch("alphaswarm.simulation.inject_seed", new_callable=AsyncMock)
async def test_run_round1_starts_governor_monitoring(
    mock_inject: AsyncMock,
    mock_dispatch: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """governor.start_monitoring is awaited once before dispatch."""
    from alphaswarm.simulation import run_round1

    mock_inject.return_value = ("test-cycle-id", MOCK_PARSED_RESULT)
    mock_dispatch.return_value = _default_decisions(len(TEST_PERSONAS))

    await run_round1(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
    )

    mock_governor.start_monitoring.assert_awaited_once()


@patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock)
@patch("alphaswarm.simulation.inject_seed", new_callable=AsyncMock)
async def test_run_round1_stops_governor_monitoring_in_finally(
    mock_inject: AsyncMock,
    mock_dispatch: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """governor.stop_monitoring is called even when dispatch_wave raises."""
    from alphaswarm.simulation import run_round1

    mock_inject.return_value = ("test-cycle-id", MOCK_PARSED_RESULT)
    mock_dispatch.side_effect = Exception("boom")

    with pytest.raises(Exception, match="boom"):
        await run_round1(
            rumor=MOCK_RUMOR,
            settings=mock_settings,
            ollama_client=mock_ollama_client,
            model_manager=mock_model_manager,
            graph_manager=mock_graph_manager,
            governor=mock_governor,
            personas=TEST_PERSONAS,
        )

    mock_governor.stop_monitoring.assert_awaited_once()


@patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock)
@patch("alphaswarm.simulation.inject_seed", new_callable=AsyncMock)
async def test_run_round1_loads_worker_after_orchestrator(
    mock_inject: AsyncMock,
    mock_dispatch: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """model_manager.load_model is called with the worker model alias."""
    from alphaswarm.simulation import run_round1

    mock_inject.return_value = ("test-cycle-id", MOCK_PARSED_RESULT)
    mock_dispatch.return_value = _default_decisions(len(TEST_PERSONAS))

    await run_round1(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
    )

    mock_model_manager.load_model.assert_awaited_with(
        mock_settings.ollama.worker_model_alias
    )


@patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock)
@patch("alphaswarm.simulation.inject_seed", new_callable=AsyncMock)
async def test_run_round1_calls_ensure_clean_state_before_worker_load(
    mock_inject: AsyncMock,
    mock_dispatch: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """ensure_clean_state is called before load_model (review concern #4)."""
    from alphaswarm.simulation import run_round1

    mock_inject.return_value = ("test-cycle-id", MOCK_PARSED_RESULT)
    mock_dispatch.return_value = _default_decisions(len(TEST_PERSONAS))

    # Track call order
    call_order: list[str] = []
    mock_model_manager.ensure_clean_state.side_effect = lambda: call_order.append("ensure_clean_state")
    original_load = mock_model_manager.load_model.side_effect

    async def track_load(model: str) -> None:
        call_order.append("load_model")

    mock_model_manager.load_model.side_effect = track_load

    await run_round1(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
    )

    assert "ensure_clean_state" in call_order
    assert "load_model" in call_order
    assert call_order.index("ensure_clean_state") < call_order.index("load_model")


@patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock)
@patch("alphaswarm.simulation.inject_seed", new_callable=AsyncMock)
async def test_run_round1_unloads_worker_on_error(
    mock_inject: AsyncMock,
    mock_dispatch: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """model_manager.unload_model is called even when dispatch_wave raises."""
    from alphaswarm.simulation import run_round1

    mock_inject.return_value = ("test-cycle-id", MOCK_PARSED_RESULT)
    mock_dispatch.side_effect = Exception("boom")

    with pytest.raises(Exception, match="boom"):
        await run_round1(
            rumor=MOCK_RUMOR,
            settings=mock_settings,
            ollama_client=mock_ollama_client,
            model_manager=mock_model_manager,
            graph_manager=mock_graph_manager,
            governor=mock_governor,
            personas=TEST_PERSONAS,
        )

    mock_model_manager.unload_model.assert_awaited()


@patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock)
@patch("alphaswarm.simulation.inject_seed", new_callable=AsyncMock)
async def test_run_round1_persists_decisions_round_1(
    mock_inject: AsyncMock,
    mock_dispatch: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """graph_manager.write_decisions is called with round_num=1."""
    from alphaswarm.simulation import run_round1

    mock_inject.return_value = ("test-cycle-id", MOCK_PARSED_RESULT)
    mock_dispatch.return_value = _default_decisions(len(TEST_PERSONAS))

    await run_round1(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
    )

    mock_graph_manager.write_decisions.assert_awaited_once()
    call_args = mock_graph_manager.write_decisions.call_args
    assert call_args[1]["round_num"] == 1 or call_args[0][2] == 1


@patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock)
@patch("alphaswarm.simulation.inject_seed", new_callable=AsyncMock)
async def test_run_round1_passes_raw_rumor_to_agents(
    mock_inject: AsyncMock,
    mock_dispatch: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """dispatch_wave receives the raw rumor string as user_message."""
    from alphaswarm.simulation import run_round1

    mock_inject.return_value = ("test-cycle-id", MOCK_PARSED_RESULT)
    mock_dispatch.return_value = _default_decisions(len(TEST_PERSONAS))

    await run_round1(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
    )

    assert mock_dispatch.call_args.kwargs["user_message"] == MOCK_RUMOR


@patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock)
@patch("alphaswarm.simulation.inject_seed", new_callable=AsyncMock)
async def test_run_round1_returns_round1_result(
    mock_inject: AsyncMock,
    mock_dispatch: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """run_round1 returns a Round1Result with correct cycle_id and agent_decisions."""
    from alphaswarm.simulation import Round1Result, run_round1

    mock_inject.return_value = ("test-cycle-id", MOCK_PARSED_RESULT)
    mock_dispatch.return_value = _default_decisions(len(TEST_PERSONAS))

    result = await run_round1(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
    )

    assert isinstance(result, Round1Result)
    assert result.cycle_id == "test-cycle-id"


@patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock)
@patch("alphaswarm.simulation.inject_seed", new_callable=AsyncMock)
async def test_run_round1_result_agent_decisions_count_matches_personas(
    mock_inject: AsyncMock,
    mock_dispatch: AsyncMock,
    mock_settings: AppSettings,
    mock_ollama_client: MagicMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
    mock_governor: AsyncMock,
) -> None:
    """len(result.agent_decisions) equals the number of personas."""
    from alphaswarm.simulation import run_round1

    mock_inject.return_value = ("test-cycle-id", MOCK_PARSED_RESULT)
    mock_dispatch.return_value = _default_decisions(len(TEST_PERSONAS))

    result = await run_round1(
        rumor=MOCK_RUMOR,
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
        governor=mock_governor,
        personas=TEST_PERSONAS,
    )

    assert len(result.agent_decisions) == len(TEST_PERSONAS)


def test_round1_result_is_frozen() -> None:
    """Round1Result is a frozen dataclass with no redundant decisions field."""
    from alphaswarm.simulation import Round1Result

    assert dataclasses.is_dataclass(Round1Result)
    field_names = {f.name for f in dataclasses.fields(Round1Result)}
    assert "agent_decisions" in field_names
    assert "decisions" not in field_names, "Round1Result should not have a redundant 'decisions' field"

    # Verify frozen
    result = Round1Result(
        cycle_id="test",
        parsed_result=MOCK_PARSED_RESULT,
        agent_decisions=[],
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.cycle_id = "mutated"  # type: ignore[misc]
