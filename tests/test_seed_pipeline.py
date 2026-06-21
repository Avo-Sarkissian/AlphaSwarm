"""Unit tests for the seed injection pipeline (inject_seed).

Updated for Task 5A: inject_seed now accepts an InferenceProvider (orchestrator)
instead of OllamaClient + OllamaModelManager. FakeInferenceProvider is used here.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alphaswarm.inference.types import InferenceResult, ProviderRole
from alphaswarm.types import EntityType, ParsedSeedResult, SeedEntity, SeedEvent
from tests.inference.fakes import FakeInferenceProvider

VALID_SEED_JSON = json.dumps(
    {
        "entities": [
            {"name": "NVIDIA", "type": "company", "relevance": 0.95, "sentiment": 0.8},
            {"name": "Semiconductors", "type": "sector", "relevance": 0.7, "sentiment": 0.5},
        ],
        "overall_sentiment": 0.6,
    }
)


@pytest.fixture()
def mock_settings() -> MagicMock:
    """Mock AppSettings with orchestrator model alias."""
    settings = MagicMock()
    settings.ollama.orchestrator_model_alias = "alphaswarm-orchestrator"
    return settings


@pytest.fixture()
def fake_provider() -> FakeInferenceProvider:
    """FakeInferenceProvider scripted with valid seed JSON."""
    return FakeInferenceProvider(
        ProviderRole.ORCHESTRATOR,
        "alphaswarm-orchestrator",
        scripted=[
            InferenceResult(content=VALID_SEED_JSON, model="alphaswarm-orchestrator")
        ],
    )


@pytest.fixture()
def mock_graph_manager() -> AsyncMock:
    """Mock GraphStateManager returning a cycle_id."""
    manager = AsyncMock()
    manager.create_cycle_with_seed_event.return_value = "test-cycle-id-123"
    return manager


@pytest.mark.asyncio()
async def test_inject_seed_loads_orchestrator_model(
    mock_settings: MagicMock,
    fake_provider: FakeInferenceProvider,
    mock_graph_manager: AsyncMock,
) -> None:
    """inject_seed calls provider.prepare() (equivalent to model load) with the orchestrator."""
    from alphaswarm.seed import inject_seed

    prepare_calls: list[str] = []

    async def _prepare() -> None:
        prepare_calls.append("prepare")

    fake_provider.prepare = _prepare  # type: ignore[method-assign]

    await inject_seed(
        rumor="NVIDIA announces breakthrough",
        settings=mock_settings,
        orchestrator=fake_provider,
        graph_manager=mock_graph_manager,
    )

    assert prepare_calls == ["prepare"]


@pytest.mark.asyncio()
async def test_inject_seed_calls_chat_with_json_mode(
    mock_settings: MagicMock,
    fake_provider: FakeInferenceProvider,
    mock_graph_manager: AsyncMock,
) -> None:
    """inject_seed calls provider.chat() with json_mode=True.

    Phase 41.4 model decision: think=False. think=True added ~265s/call with
    marginal quality gain on this workload.
    See .planning/phases/41.4-r3-inference-and-ws-stall/41.4-MODEL-DECISION-LOG.md
    for revisit triggers and how to flip back.
    """
    from alphaswarm.seed import inject_seed

    await inject_seed(
        rumor="NVIDIA announces breakthrough",
        settings=mock_settings,
        orchestrator=fake_provider,
        graph_manager=mock_graph_manager,
    )

    assert len(fake_provider.calls) == 1
    call = fake_provider.calls[0]
    assert call["json_mode"] is True


@pytest.mark.asyncio()
async def test_inject_seed_calls_create_cycle_with_seed_event(
    mock_settings: MagicMock,
    fake_provider: FakeInferenceProvider,
    mock_graph_manager: AsyncMock,
) -> None:
    """inject_seed calls graph_manager.create_cycle_with_seed_event (not separate ops)."""
    from alphaswarm.seed import inject_seed

    await inject_seed(
        rumor="NVIDIA announces breakthrough",
        settings=mock_settings,
        orchestrator=fake_provider,
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
    mock_graph_manager: AsyncMock,
) -> None:
    """inject_seed calls provider.teardown() even when chat raises an error (finally block)."""
    from alphaswarm.seed import inject_seed

    teardown_calls: list[str] = []

    error_provider = FakeInferenceProvider(
        ProviderRole.ORCHESTRATOR,
        "alphaswarm-orchestrator",
        scripted=lambda **_: (_ for _ in ()).throw(RuntimeError("test error")),
    )

    async def _teardown() -> None:
        teardown_calls.append("teardown")

    error_provider.teardown = _teardown  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="test error"):
        await inject_seed(
            rumor="NVIDIA announces breakthrough",
            settings=mock_settings,
            orchestrator=error_provider,
            graph_manager=mock_graph_manager,
        )

    assert teardown_calls == ["teardown"]


@pytest.mark.asyncio()
async def test_inject_seed_returns_cycle_id_and_parsed_result(
    mock_settings: MagicMock,
    fake_provider: FakeInferenceProvider,
    mock_graph_manager: AsyncMock,
) -> None:
    """inject_seed returns a (cycle_id, ParsedSeedResult, None) tuple."""
    from alphaswarm.seed import inject_seed

    cycle_id, parsed_result, _modifier_result = await inject_seed(
        rumor="NVIDIA announces breakthrough",
        settings=mock_settings,
        orchestrator=fake_provider,
        graph_manager=mock_graph_manager,
    )

    assert cycle_id == "test-cycle-id-123"
    assert isinstance(parsed_result, ParsedSeedResult)
    assert parsed_result.parse_tier == 1


@pytest.mark.asyncio()
async def test_inject_seed_parsed_result_has_correct_entities(
    mock_settings: MagicMock,
    fake_provider: FakeInferenceProvider,
    mock_graph_manager: AsyncMock,
) -> None:
    """With valid mock response, ParsedSeedResult.seed_event has correct entities."""
    from alphaswarm.seed import inject_seed

    _, parsed_result, _modifier_result = await inject_seed(
        rumor="NVIDIA announces breakthrough",
        settings=mock_settings,
        orchestrator=fake_provider,
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
    mock_graph_manager: AsyncMock,
) -> None:
    """inject_seed logs a warning when parse_tier=3 (fallback used)."""
    from alphaswarm.seed import inject_seed

    bad_provider = FakeInferenceProvider(
        ProviderRole.ORCHESTRATOR,
        "alphaswarm-orchestrator",
        scripted=[
            InferenceResult(content="This is not valid JSON at all", model="alphaswarm-orchestrator")
        ],
    )

    with patch("alphaswarm.seed.logger") as mock_logger:
        await inject_seed(
            rumor="NVIDIA announces breakthrough",
            settings=mock_settings,
            orchestrator=bad_provider,
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
    mock_graph_manager: AsyncMock,
) -> None:
    """inject_seed passes the rumor as the user message to provider.chat()."""
    from alphaswarm.seed import inject_seed

    provider = FakeInferenceProvider(
        ProviderRole.ORCHESTRATOR,
        "alphaswarm-orchestrator",
        scripted=[
            InferenceResult(content=VALID_SEED_JSON, model="alphaswarm-orchestrator")
        ],
    )

    await inject_seed(
        rumor="Tesla CEO steps down unexpectedly",
        settings=mock_settings,
        orchestrator=provider,
        graph_manager=mock_graph_manager,
    )

    messages = provider.calls[0]["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "Tesla CEO steps down unexpectedly"
