"""Unit tests for inject_seed + generate_modifiers with InferenceProvider (Task 5A).

These tests replace the OllamaClient/OllamaModelManager mocks with
FakeInferenceProvider, verifying that:
- inject_seed calls provider.prepare() then provider.teardown() (lifecycle)
- inference is routed through provider.chat() with json_mode=True
- generate_modifiers calls provider.chat() with json_mode=True
- behaviour (prompts, parsing, return values) is identical to the old path
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alphaswarm.inference.types import InferenceResult, ProviderRole
from alphaswarm.types import (
    BracketType,
    EntityType,
    ParsedModifiersResult,
    ParsedSeedResult,
    SeedEntity,
    SeedEvent,
)
from tests.inference.fakes import FakeInferenceProvider

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

VALID_SEED_JSON = json.dumps(
    {
        "entities": [
            {"name": "NVIDIA", "type": "company", "relevance": 0.95, "sentiment": 0.8},
            {"name": "Semiconductors", "type": "sector", "relevance": 0.7, "sentiment": 0.5},
        ],
        "overall_sentiment": 0.6,
    }
)

VALID_MODIFIER_JSON = json.dumps(
    {
        "institutions": "buy-side PM managing large-cap US equity against index benchmark",
        "sell_side": "senior equity analyst with active price targets on semiconductor stocks",
        "event_driven": "merger-arb specialist handicapping regulatory approval timelines",
        "quants": "momentum factor modeler tracking chipmaker earnings revision cycles",
        "degens": "retail options trader YOLO-ing on AI chip supply chain squeeze",
        "narrators": "FinTwit commentator framing the AI compute scarcity narrative",
        "algos": "trend-following system reacting to semiconductor volume breakout",
        "macro": "cross-asset strategist mapping AI capex surge to bond spreads",
        "shorts": "forensic accountant questioning NVIDIA revenue recognition timing",
        "allocators": "sovereign wealth allocator assessing decade-long AI infrastructure theme",
    }
)


def _make_seed_provider() -> FakeInferenceProvider:
    return FakeInferenceProvider(
        ProviderRole.ORCHESTRATOR,
        "alphaswarm-orchestrator",
        scripted=[
            InferenceResult(
                content=VALID_SEED_JSON,
                model="alphaswarm-orchestrator",
            )
        ],
    )


def _make_seed_and_modifier_provider() -> FakeInferenceProvider:
    """Returns a provider scripted for both the seed call and the modifier call."""
    return FakeInferenceProvider(
        ProviderRole.ORCHESTRATOR,
        "alphaswarm-orchestrator",
        scripted=[
            InferenceResult(content=VALID_SEED_JSON, model="alphaswarm-orchestrator"),
            InferenceResult(content=VALID_MODIFIER_JSON, model="alphaswarm-orchestrator"),
        ],
    )


@pytest.fixture()
def mock_settings() -> MagicMock:
    settings = MagicMock()
    settings.ollama.orchestrator_model_alias = "alphaswarm-orchestrator"
    return settings


@pytest.fixture()
def mock_graph_manager() -> AsyncMock:
    manager = AsyncMock()
    manager.create_cycle_with_seed_event.return_value = "test-cycle-id-123"
    return manager


# ---------------------------------------------------------------------------
# inject_seed — lifecycle tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_inject_seed_calls_prepare_on_provider(
    mock_settings: MagicMock,
    mock_graph_manager: AsyncMock,
) -> None:
    """inject_seed calls provider.prepare() before any inference."""
    from unittest.mock import AsyncMock as AM

    from alphaswarm.seed import inject_seed

    provider = _make_seed_provider()
    prepare_spy = AM(wraps=provider.prepare)
    provider.prepare = prepare_spy  # type: ignore[method-assign]

    await inject_seed(
        rumor="NVIDIA announces breakthrough",
        settings=mock_settings,
        orchestrator=provider,
        graph_manager=mock_graph_manager,
    )

    prepare_spy.assert_awaited_once()


@pytest.mark.asyncio()
async def test_inject_seed_calls_teardown_on_provider(
    mock_settings: MagicMock,
    mock_graph_manager: AsyncMock,
) -> None:
    """inject_seed calls provider.teardown() after inference (even on success)."""
    from unittest.mock import AsyncMock as AM

    from alphaswarm.seed import inject_seed

    provider = _make_seed_provider()
    teardown_spy = AM(wraps=provider.teardown)
    provider.teardown = teardown_spy  # type: ignore[method-assign]

    await inject_seed(
        rumor="NVIDIA announces breakthrough",
        settings=mock_settings,
        orchestrator=provider,
        graph_manager=mock_graph_manager,
    )

    teardown_spy.assert_awaited_once()


@pytest.mark.asyncio()
async def test_inject_seed_calls_teardown_on_error(
    mock_settings: MagicMock,
    mock_graph_manager: AsyncMock,
) -> None:
    """inject_seed calls provider.teardown() even when chat raises (finally block)."""
    from unittest.mock import AsyncMock as AM

    from alphaswarm.seed import inject_seed

    provider = FakeInferenceProvider(
        ProviderRole.ORCHESTRATOR,
        "alphaswarm-orchestrator",
        scripted=lambda **_: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    teardown_spy = AM(wraps=provider.teardown)
    provider.teardown = teardown_spy  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="boom"):
        await inject_seed(
            rumor="NVIDIA announces breakthrough",
            settings=mock_settings,
            orchestrator=provider,
            graph_manager=mock_graph_manager,
        )

    teardown_spy.assert_awaited_once()


@pytest.mark.asyncio()
async def test_inject_seed_prepare_before_teardown(
    mock_settings: MagicMock,
    mock_graph_manager: AsyncMock,
) -> None:
    """provider.prepare() is called before provider.teardown() in the happy path."""
    from alphaswarm.seed import inject_seed

    call_order: list[str] = []

    provider = _make_seed_provider()

    async def _prepare() -> None:
        call_order.append("prepare")

    async def _teardown() -> None:
        call_order.append("teardown")

    provider.prepare = _prepare  # type: ignore[method-assign]
    provider.teardown = _teardown  # type: ignore[method-assign]

    await inject_seed(
        rumor="NVIDIA announces breakthrough",
        settings=mock_settings,
        orchestrator=provider,
        graph_manager=mock_graph_manager,
    )

    assert call_order == ["prepare", "teardown"]


# ---------------------------------------------------------------------------
# inject_seed — inference call shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_inject_seed_routes_inference_through_provider(
    mock_settings: MagicMock,
    mock_graph_manager: AsyncMock,
) -> None:
    """inject_seed calls provider.chat() exactly once."""
    from alphaswarm.seed import inject_seed

    provider = _make_seed_provider()

    await inject_seed(
        rumor="NVIDIA announces breakthrough",
        settings=mock_settings,
        orchestrator=provider,
        graph_manager=mock_graph_manager,
    )

    assert len(provider.calls) == 1


@pytest.mark.asyncio()
async def test_inject_seed_chat_uses_json_mode(
    mock_settings: MagicMock,
    mock_graph_manager: AsyncMock,
) -> None:
    """inject_seed passes json_mode=True to provider.chat()."""
    from alphaswarm.seed import inject_seed

    provider = _make_seed_provider()

    await inject_seed(
        rumor="NVIDIA announces breakthrough",
        settings=mock_settings,
        orchestrator=provider,
        graph_manager=mock_graph_manager,
    )

    call = provider.calls[0]
    assert call["json_mode"] is True


@pytest.mark.asyncio()
async def test_inject_seed_chat_messages_shape(
    mock_settings: MagicMock,
    mock_graph_manager: AsyncMock,
) -> None:
    """inject_seed sends [system, user] messages with correct roles and rumor content."""
    from alphaswarm.seed import inject_seed

    provider = _make_seed_provider()

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


# ---------------------------------------------------------------------------
# inject_seed — return values
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_inject_seed_returns_cycle_id_and_parsed_result(
    mock_settings: MagicMock,
    mock_graph_manager: AsyncMock,
) -> None:
    """inject_seed returns (cycle_id, ParsedSeedResult, None) with provider."""
    from alphaswarm.seed import inject_seed

    provider = _make_seed_provider()

    cycle_id, parsed_result, modifier_result = await inject_seed(
        rumor="NVIDIA announces breakthrough",
        settings=mock_settings,
        orchestrator=provider,
        graph_manager=mock_graph_manager,
    )

    assert cycle_id == "test-cycle-id-123"
    assert isinstance(parsed_result, ParsedSeedResult)
    assert parsed_result.parse_tier == 1
    assert modifier_result is None


@pytest.mark.asyncio()
async def test_inject_seed_parsed_entities(
    mock_settings: MagicMock,
    mock_graph_manager: AsyncMock,
) -> None:
    """inject_seed correctly parses entities from provider.chat() content."""
    from alphaswarm.seed import inject_seed

    provider = _make_seed_provider()

    _, parsed_result, _ = await inject_seed(
        rumor="NVIDIA announces breakthrough",
        settings=mock_settings,
        orchestrator=provider,
        graph_manager=mock_graph_manager,
    )

    entities = parsed_result.seed_event.entities
    assert len(entities) == 2
    assert entities[0].name == "NVIDIA"
    assert entities[0].type == EntityType.COMPANY
    assert entities[1].name == "Semiconductors"


@pytest.mark.asyncio()
async def test_inject_seed_logs_warning_on_tier3(
    mock_settings: MagicMock,
    mock_graph_manager: AsyncMock,
) -> None:
    """inject_seed logs a warning when parse falls back to tier 3."""
    from alphaswarm.seed import inject_seed

    provider = FakeInferenceProvider(
        ProviderRole.ORCHESTRATOR,
        "alphaswarm-orchestrator",
        scripted=[
            InferenceResult(content="not valid json", model="alphaswarm-orchestrator")
        ],
    )

    with patch("alphaswarm.seed.logger") as mock_logger:
        await inject_seed(
            rumor="NVIDIA announces breakthrough",
            settings=mock_settings,
            orchestrator=provider,
            graph_manager=mock_graph_manager,
        )
        mock_logger.warning.assert_called_once()
        assert "seed_parse_used_fallback" in mock_logger.warning.call_args[0]


# ---------------------------------------------------------------------------
# generate_modifiers — provider-based tests
# ---------------------------------------------------------------------------


def _make_seed_event() -> SeedEvent:
    return SeedEvent(
        raw_rumor="NVIDIA quantum breakthrough",
        entities=[
            SeedEntity(name="NVIDIA", type=EntityType.COMPANY, relevance=0.95, sentiment=0.8),
        ],
        overall_sentiment=0.6,
    )


@pytest.mark.asyncio()
async def test_generate_modifiers_calls_provider_chat() -> None:
    """generate_modifiers calls provider.chat() exactly once."""
    from alphaswarm.config import generate_modifiers

    provider = FakeInferenceProvider(
        ProviderRole.ORCHESTRATOR,
        "alphaswarm-orchestrator",
        scripted=[InferenceResult(content=VALID_MODIFIER_JSON, model="alphaswarm-orchestrator")],
    )

    await generate_modifiers(_make_seed_event(), provider)

    assert len(provider.calls) == 1


@pytest.mark.asyncio()
async def test_generate_modifiers_uses_json_mode() -> None:
    """generate_modifiers passes json_mode=True to provider.chat()."""
    from alphaswarm.config import generate_modifiers

    provider = FakeInferenceProvider(
        ProviderRole.ORCHESTRATOR,
        "alphaswarm-orchestrator",
        scripted=[InferenceResult(content=VALID_MODIFIER_JSON, model="alphaswarm-orchestrator")],
    )

    await generate_modifiers(_make_seed_event(), provider)

    assert provider.calls[0]["json_mode"] is True


@pytest.mark.asyncio()
async def test_generate_modifiers_returns_parsed_modifiers_result() -> None:
    """generate_modifiers returns ParsedModifiersResult with all 10 brackets."""
    from alphaswarm.config import generate_modifiers

    provider = FakeInferenceProvider(
        ProviderRole.ORCHESTRATOR,
        "alphaswarm-orchestrator",
        scripted=[InferenceResult(content=VALID_MODIFIER_JSON, model="alphaswarm-orchestrator")],
    )

    result = await generate_modifiers(_make_seed_event(), provider)

    assert isinstance(result, ParsedModifiersResult)
    assert result.parse_tier == 1
    assert len(result.modifiers) == 10
    assert BracketType.INSTITUTIONS in result.modifiers


@pytest.mark.asyncio()
async def test_generate_modifiers_chat_messages_shape() -> None:
    """generate_modifiers sends [system, user] messages."""
    from alphaswarm.config import generate_modifiers

    provider = FakeInferenceProvider(
        ProviderRole.ORCHESTRATOR,
        "alphaswarm-orchestrator",
        scripted=[InferenceResult(content=VALID_MODIFIER_JSON, model="alphaswarm-orchestrator")],
    )

    await generate_modifiers(_make_seed_event(), provider)

    messages = provider.calls[0]["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    # user message should contain the raw rumor
    assert "NVIDIA quantum breakthrough" in messages[1]["content"]


# ---------------------------------------------------------------------------
# inject_seed with modifier_generator — integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_inject_seed_passes_provider_to_modifier_generator(
    mock_settings: MagicMock,
    mock_graph_manager: AsyncMock,
) -> None:
    """When modifier_generator is provided, inject_seed passes provider through to it."""
    from alphaswarm.config import generate_modifiers
    from alphaswarm.seed import inject_seed

    provider = _make_seed_and_modifier_provider()

    _, _, modifier_result = await inject_seed(
        rumor="NVIDIA announces breakthrough",
        settings=mock_settings,
        orchestrator=provider,
        graph_manager=mock_graph_manager,
        modifier_generator=generate_modifiers,
    )

    # Both seed call and modifier call routed through the same provider
    assert len(provider.calls) == 2
    assert isinstance(modifier_result, ParsedModifiersResult)
    assert modifier_result.parse_tier == 1
