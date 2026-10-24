"""Seed and modifier generation through chat_structured (docs/DECISIONS.md#adr-structured-output)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from alphaswarm.inference.structured import chat_structured
from alphaswarm.inference.types import InferenceResult, ProviderRole
from alphaswarm.seed import (
    ModifiersLLMOutput,
    SeedLLMOutput,
    generate_modifiers,
    inject_seed,
)
from alphaswarm.types import BracketType, EntityType, SeedEntity, SeedEvent
from tests.inference.fakes import FakeInferenceProvider

RUMOR = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."
SEED_JSON = json.dumps(
    {
        "entities": [
            {"name": "ZZZT Holdings", "type": "company", "relevance": 0.95, "sentiment": 0.6},
            {"name": "QQQX Robotics", "type": "company", "relevance": 0.9, "sentiment": 0.7},
            {"name": "Industrial Automation", "type": "sector", "relevance": 0.6, "sentiment": 0.4},
        ],
        "overall_sentiment": 0.55,
    }
)
ENTITY_JSON = '{"name": "ZZZT Holdings", "type": "company", "relevance": 0.9, "sentiment": 0.5}'


def _seed_reply(overall_sentiment: str | None) -> str:
    """A seed reply with one valid entity; ``None`` leaves overall_sentiment out."""
    if overall_sentiment is None:
        return f'{{"entities": [{ENTITY_JSON}]}}'
    return f'{{"entities": [{ENTITY_JSON}], "overall_sentiment": {overall_sentiment}}}'


def _orchestrator(*contents: str) -> FakeInferenceProvider:
    return FakeInferenceProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="fake-orch",
        scripted=[InferenceResult(content=c, model="fake-orch") for c in contents],
    )


def _graph() -> AsyncMock:
    graph = AsyncMock()
    graph.create_cycle_with_seed_event = AsyncMock(return_value="00000000-0000-4000-8000-0000000000a1")
    return graph


def _settings() -> MagicMock:
    settings = MagicMock()
    settings.num_rounds = 3
    return settings


class TestSeedLLMOutput:
    def test_valid_reply(self) -> None:
        out = SeedLLMOutput.model_validate_json(SEED_JSON)
        event = out.to_seed_event(RUMOR)
        assert event.raw_rumor == RUMOR
        assert [e.name for e in event.entities] == [
            "ZZZT Holdings",
            "QQQX Robotics",
            "Industrial Automation",
        ]

    def test_invalid_entities_are_dropped_not_fatal(self) -> None:
        out = SeedLLMOutput.model_validate(
            {
                "entities": [
                    {"name": "ZZZT Holdings", "type": "company", "relevance": 0.9, "sentiment": 0.8},
                    {"name": "Somewhere", "type": "location", "relevance": 0.5, "sentiment": 0.0},
                    "not an entity",
                ],
                "overall_sentiment": 0.5,
            }
        )
        assert [e.name for e in out.entities] == ["ZZZT Holdings"]

    def test_out_of_range_values_are_clamped(self) -> None:
        out = SeedLLMOutput.model_validate(
            {
                "entities": [
                    {"name": "ZZZT Holdings", "type": "COMPANY", "relevance": 1.2, "sentiment": 0.8},
                ],
                "overall_sentiment": 5.0,
            }
        )
        assert out.entities[0].relevance == 1.0
        assert out.overall_sentiment == 1.0

    def test_null_entities_and_extra_keys(self) -> None:
        with pytest.raises(ValueError):
            SeedLLMOutput.model_validate({"entities": None, "overall_sentiment": 0.5})
        out = SeedLLMOutput.model_validate(
            {"entities": [], "overall_sentiment": 0.1, "raw_rumor": "fabricated", "summary": "x"}
        )
        assert out.to_seed_event(RUMOR).raw_rumor == RUMOR

    def test_entity_extra_keys_are_ignored(self) -> None:
        out = SeedLLMOutput.model_validate_json(
            json.dumps(
                {
                    "entities": [
                        {
                            "name": "ZZZT Holdings",
                            "type": "company",
                            "relevance": 0.9,
                            "sentiment": 0.8,
                            "reasoning": "fictional acquirer",
                        }
                    ],
                    "overall_sentiment": 0.5,
                    "summary": "bullish",
                }
            )
        )
        assert [e.name for e in out.entities] == ["ZZZT Holdings"]

    @pytest.mark.parametrize("sentiment", ["NaN", '"NaN"', '"nan"'])
    def test_nan_overall_sentiment_is_rejected(self, sentiment: str) -> None:
        # Clamping cannot fix NaN, so the field's own range must reject it here,
        # inside chat_structured, and never later in SeedEvent.
        with pytest.raises(ValidationError):
            SeedLLMOutput.model_validate_json(_seed_reply(sentiment))

    def test_schema_advertises_the_sentiment_range(self) -> None:
        sentiment = SeedLLMOutput.model_json_schema()["properties"]["overall_sentiment"]
        assert (sentiment["minimum"], sentiment["maximum"]) == (-1.0, 1.0)

    async def test_nan_then_valid_reply_is_tier1_after_one_retry(self) -> None:
        provider = _orchestrator(_seed_reply("NaN"), SEED_JSON)
        result = await chat_structured(provider, [{"role": "user", "content": RUMOR}], SeedLLMOutput)
        assert (result.parse_tier, result.attempts) == (1, 2)
        assert result.value.overall_sentiment == 0.55
        correction = provider.calls[1]["messages"][-1]["content"]
        assert "overall_sentiment" in correction


class TestInjectSeed:
    async def test_tier1_sends_the_seed_schema_once(self) -> None:
        provider = _orchestrator(SEED_JSON)
        cycle_id, parsed, _ = await inject_seed(
            rumor=RUMOR,
            settings=_settings(),
            orchestrator=provider,
            graph_manager=_graph(),
        )
        assert cycle_id == "00000000-0000-4000-8000-0000000000a1"
        assert parsed.parse_tier == 1
        assert len(parsed.seed_event.entities) == 3
        call = provider.calls[0]
        assert call["json_mode"] is False
        assert set(call["response_schema"]["properties"]) == {"entities", "overall_sentiment"}
        assert call["messages"][1] == {"role": "user", "content": RUMOR}

    async def test_fenced_reply_is_tier2(self) -> None:
        provider = _orchestrator(f"```json\n{SEED_JSON}\n```")
        _, parsed, _ = await inject_seed(
            rumor=RUMOR,
            settings=_settings(),
            orchestrator=provider,
            graph_manager=_graph(),
        )
        assert parsed.parse_tier == 2
        assert len(provider.calls) == 1

    async def test_two_invalid_replies_fall_back_to_tier3(self) -> None:
        provider = _orchestrator("I cannot help with that", "still no JSON")
        graph = _graph()
        _, parsed, _ = await inject_seed(
            rumor=RUMOR,
            settings=_settings(),
            orchestrator=provider,
            graph_manager=graph,
        )
        assert parsed.parse_tier == 3
        assert parsed.seed_event.entities == []
        assert parsed.seed_event.overall_sentiment == 0.0
        assert parsed.seed_event.raw_rumor == RUMOR
        assert len(provider.calls) == 2
        graph.create_cycle_with_seed_event.assert_awaited_once()

    @pytest.mark.parametrize(
        "reply",
        [_seed_reply("NaN"), _seed_reply('"NaN"'), _seed_reply(None)],
        ids=["nan-literal", "nan-string", "missing"],
    )
    async def test_unusable_overall_sentiment_twice_falls_back_to_tier3(self, reply: str) -> None:
        provider = _orchestrator(reply, reply)
        graph = _graph()
        _, parsed, _ = await inject_seed(
            rumor=RUMOR,
            settings=_settings(),
            orchestrator=provider,
            graph_manager=graph,
        )
        assert parsed.parse_tier == 3
        assert parsed.seed_event.entities == []
        assert parsed.seed_event.overall_sentiment == 0.0
        assert len(provider.calls) == 2
        graph.create_cycle_with_seed_event.assert_awaited_once()


def _seed_event() -> SeedEvent:
    return SeedEvent(
        raw_rumor=RUMOR,
        entities=[SeedEntity(name="ZZZT Holdings", type=EntityType.COMPANY, relevance=0.9, sentiment=0.6)],
        overall_sentiment=0.55,
    )


def _full_modifiers(prefix: str = "specialist tracking the ZZZT-QQQX deal for") -> str:
    return json.dumps({b.value: f"{prefix} the {b.value} desk" for b in BracketType})


class TestModifiers:
    def test_model_fields_match_the_brackets(self) -> None:
        assert set(ModifiersLLMOutput.model_fields) == {b.value for b in BracketType}

    async def test_tier1_all_ten(self) -> None:
        provider = _orchestrator(_full_modifiers())
        result = await generate_modifiers(_seed_event(), provider)
        assert result.parse_tier == 1
        assert result.modifiers[BracketType.QUANTS].endswith("the quants desk")
        assert set(provider.calls[0]["response_schema"]["properties"]) == {b.value for b in BracketType}

    async def test_fenced_is_tier2(self) -> None:
        result = await generate_modifiers(_seed_event(), _orchestrator(f"```json\n{_full_modifiers()}\n```"))
        assert result.parse_tier == 2

    async def test_partial_reply_applies_only_generated_brackets(self) -> None:
        partial = {b.value: f"custom {b.value}" for b in list(BracketType)[:7]}
        result = await generate_modifiers(_seed_event(), _orchestrator(json.dumps(partial)))
        assert result.parse_tier == 1
        assert result.modifiers == {b: f"custom {b.value}" for b in list(BracketType)[:7]}

    async def test_keys_are_case_insensitive_and_non_strings_are_missing(self) -> None:
        upper: dict[str, object] = {b.value.upper(): f"upper {b.value}" for b in BracketType}
        upper["MACRO"] = 7
        result = await generate_modifiers(_seed_event(), _orchestrator(json.dumps(upper)))
        assert result.modifiers[BracketType.QUANTS] == "upper quants"
        assert BracketType.MACRO not in result.modifiers

    async def test_long_modifiers_are_truncated(self) -> None:
        long_text = "word " * 80
        reply = json.dumps({b.value: long_text for b in BracketType})
        result = await generate_modifiers(_seed_event(), _orchestrator(reply))
        assert all(len(text) <= 150 for text in result.modifiers.values())

    async def test_two_invalid_replies_give_no_modifiers(self) -> None:
        provider = _orchestrator("not json", "still not json")
        result = await generate_modifiers(_seed_event(), provider)
        assert (result.parse_tier, result.modifiers) == (3, {})
        assert len(provider.calls) == 2
