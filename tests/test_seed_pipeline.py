"""Unit tests for the seed injection pipeline (inject_seed)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alphaswarm.types import EntityType, ParsedSeedResult, SeedEntity, SeedEvent


@pytest.fixture()
def mock_settings() -> MagicMock:
    """Mock AppSettings with orchestrator model alias."""
    settings = MagicMock()
    settings.ollama.orchestrator_model_alias = "alphaswarm-orchestrator"
    return settings


@pytest.fixture()
def mock_ollama_client() -> AsyncMock:
    """Mock OllamaClient returning valid seed JSON from chat()."""
    client = AsyncMock()
    response = MagicMock()
    response.message.content = json.dumps({
        "entities": [
            {"name": "NVIDIA", "type": "company", "relevance": 0.95, "sentiment": 0.8},
            {"name": "Semiconductors", "type": "sector", "relevance": 0.7, "sentiment": 0.5},
        ],
        "overall_sentiment": 0.6,
    })
    response.message.thinking = None
    client.chat.return_value = response
    return client


@pytest.fixture()
def mock_model_manager() -> AsyncMock:
    """Mock OllamaModelManager with load/unload."""
    return AsyncMock()


@pytest.fixture()
def mock_graph_manager() -> AsyncMock:
    """Mock GraphStateManager returning a cycle_id."""
    manager = AsyncMock()
    manager.create_cycle_with_seed_event.return_value = "test-cycle-id-123"
    return manager


@pytest.mark.asyncio()
async def test_inject_seed_loads_orchestrator_model(
    mock_settings: MagicMock,
    mock_ollama_client: AsyncMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
) -> None:
    """inject_seed calls model_manager.load_model with the orchestrator alias."""
    from alphaswarm.seed import inject_seed

    await inject_seed(
        rumor="NVIDIA announces breakthrough",
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
    )

    mock_model_manager.load_model.assert_awaited_once_with("alphaswarm-orchestrator")


@pytest.mark.asyncio()
async def test_inject_seed_calls_chat_with_json_format_and_think(
    mock_settings: MagicMock,
    mock_ollama_client: AsyncMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
) -> None:
    """inject_seed calls ollama_client.chat with format='json' and think=True."""
    from alphaswarm.seed import inject_seed

    await inject_seed(
        rumor="NVIDIA announces breakthrough",
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
    )

    mock_ollama_client.chat.assert_awaited_once()
    call_kwargs = mock_ollama_client.chat.call_args[1]
    assert call_kwargs["format"] == "json"
    assert call_kwargs["think"] is True


@pytest.mark.asyncio()
async def test_inject_seed_calls_create_cycle_with_seed_event(
    mock_settings: MagicMock,
    mock_ollama_client: AsyncMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
) -> None:
    """inject_seed calls graph_manager.create_cycle_with_seed_event (not separate ops)."""
    from alphaswarm.seed import inject_seed

    await inject_seed(
        rumor="NVIDIA announces breakthrough",
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
    )

    mock_graph_manager.create_cycle_with_seed_event.assert_awaited_once()
    call_args = mock_graph_manager.create_cycle_with_seed_event.call_args
    # First arg is the rumor, second is the SeedEvent
    assert call_args[0][0] == "NVIDIA announces breakthrough"
    assert isinstance(call_args[0][1], SeedEvent)


@pytest.mark.asyncio()
async def test_inject_seed_unloads_model_on_error(
    mock_settings: MagicMock,
    mock_ollama_client: AsyncMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
) -> None:
    """inject_seed calls unload_model even when chat raises an error (finally block)."""
    from alphaswarm.errors import OllamaInferenceError
    from alphaswarm.seed import inject_seed

    mock_ollama_client.chat.side_effect = OllamaInferenceError(
        message="test error", model="test"
    )

    with pytest.raises(OllamaInferenceError):
        await inject_seed(
            rumor="NVIDIA announces breakthrough",
            settings=mock_settings,
            ollama_client=mock_ollama_client,
            model_manager=mock_model_manager,
            graph_manager=mock_graph_manager,
        )

    mock_model_manager.unload_model.assert_awaited_once_with("alphaswarm-orchestrator")


@pytest.mark.asyncio()
async def test_inject_seed_returns_cycle_id_and_parsed_result(
    mock_settings: MagicMock,
    mock_ollama_client: AsyncMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
) -> None:
    """inject_seed returns a (cycle_id, ParsedSeedResult) tuple."""
    from alphaswarm.seed import inject_seed

    cycle_id, parsed_result = await inject_seed(
        rumor="NVIDIA announces breakthrough",
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
    )

    assert cycle_id == "test-cycle-id-123"
    assert isinstance(parsed_result, ParsedSeedResult)
    assert parsed_result.parse_tier == 1


@pytest.mark.asyncio()
async def test_inject_seed_parsed_result_has_correct_entities(
    mock_settings: MagicMock,
    mock_ollama_client: AsyncMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
) -> None:
    """With valid mock response, ParsedSeedResult.seed_event has correct entities."""
    from alphaswarm.seed import inject_seed

    _, parsed_result = await inject_seed(
        rumor="NVIDIA announces breakthrough",
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
    )

    entities = parsed_result.seed_event.entities
    assert len(entities) == 2
    assert entities[0].name == "NVIDIA"
    assert entities[0].type == EntityType.COMPANY
    assert entities[1].name == "Semiconductors"


@pytest.mark.asyncio()
async def test_inject_seed_logs_warning_on_parse_tier_3(
    mock_settings: MagicMock,
    mock_ollama_client: AsyncMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
) -> None:
    """inject_seed logs a warning when parse_tier=3 (fallback used)."""
    from alphaswarm.seed import inject_seed

    # Return unparseable content to trigger tier 3 fallback
    response = MagicMock()
    response.message.content = "This is not valid JSON at all"
    response.message.thinking = None
    mock_ollama_client.chat.return_value = response

    with patch("alphaswarm.seed.logger") as mock_logger:
        await inject_seed(
            rumor="NVIDIA announces breakthrough",
            settings=mock_settings,
            ollama_client=mock_ollama_client,
            model_manager=mock_model_manager,
            graph_manager=mock_graph_manager,
        )

        mock_logger.warning.assert_called_once()
        call_kwargs = mock_logger.warning.call_args
        assert "seed_parse_used_fallback" in call_kwargs[0]


@pytest.mark.asyncio()
async def test_inject_seed_orchestrator_system_prompt_exists() -> None:
    """ORCHESTRATOR_SYSTEM_PROMPT is defined and mentions entity extraction."""
    from alphaswarm.seed import ORCHESTRATOR_SYSTEM_PROMPT

    assert isinstance(ORCHESTRATOR_SYSTEM_PROMPT, str)
    assert "entities" in ORCHESTRATOR_SYSTEM_PROMPT.lower()
    assert "overall_sentiment" in ORCHESTRATOR_SYSTEM_PROMPT


@pytest.mark.asyncio()
async def test_inject_seed_passes_rumor_as_user_message(
    mock_settings: MagicMock,
    mock_ollama_client: AsyncMock,
    mock_model_manager: AsyncMock,
    mock_graph_manager: AsyncMock,
) -> None:
    """inject_seed passes the rumor as the user message to ollama_client.chat."""
    from alphaswarm.seed import inject_seed

    await inject_seed(
        rumor="Tesla CEO steps down unexpectedly",
        settings=mock_settings,
        ollama_client=mock_ollama_client,
        model_manager=mock_model_manager,
        graph_manager=mock_graph_manager,
    )

    call_kwargs = mock_ollama_client.chat.call_args[1]
    messages = call_kwargs["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "Tesla CEO steps down unexpectedly"
