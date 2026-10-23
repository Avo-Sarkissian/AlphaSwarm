"""Seed and modifier generation through chat_structured (docs/DECISIONS.md#adr-structured-output)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from alphaswarm.inference.types import InferenceResult, ProviderRole
from alphaswarm.seed import SeedLLMOutput, inject_seed
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
