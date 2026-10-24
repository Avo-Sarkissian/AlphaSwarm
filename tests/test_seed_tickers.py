"""Seed entities carry an orchestrator-proposed ticker (docs/DECISIONS.md#adr-ticker-resolution)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from alphaswarm.inference.types import InferenceResult, ProviderRole
from alphaswarm.seed import ORCHESTRATOR_SYSTEM_PROMPT, inject_seed
from alphaswarm.types import EntityType, SeedEntity
from tests.inference.fakes import FakeInferenceProvider

RUMOR = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ZZZT", "ZZZT"),
        (" zzzt ", "ZZZT"),
        ("$qqqx", "QQQX"),
        ("TOOLONG", None),
        ("ZZ.T", None),
        ("", None),
        (None, None),
        (42, None),
    ],
)
def test_ticker_is_normalised_or_dropped(raw: object, expected: str | None) -> None:
    entity = SeedEntity.model_validate(
        {"name": "ZZZT Holdings", "type": "company", "relevance": 0.9, "sentiment": 0.5, "ticker": raw}
    )
    assert entity.ticker == expected


def test_ticker_defaults_to_none() -> None:
    entity = SeedEntity(name="Industrial Automation", type=EntityType.SECTOR, relevance=0.5, sentiment=0.1)
    assert entity.ticker is None


def test_seed_prompt_asks_for_listed_company_tickers_only() -> None:
    assert "- ticker:" in ORCHESTRATOR_SYSTEM_PROMPT
    assert "null for private companies" in ORCHESTRATOR_SYSTEM_PROMPT


def _entity_properties(schema: dict[str, Any]) -> dict[str, Any]:
    items = schema["properties"]["entities"]["items"]
    if "$ref" in items:
        items = schema["$defs"][items["$ref"].rsplit("/", 1)[-1]]
    return items["properties"]


async def test_seed_schema_and_reply_carry_the_ticker() -> None:
    reply = json.dumps(
        {
            "entities": [
                {"name": "ZZZT Holdings", "type": "company", "relevance": 0.95, "sentiment": 0.6, "ticker": "zzzt"},
                {"name": "Industrial Automation", "type": "sector", "relevance": 0.6, "sentiment": 0.4},
            ],
            "overall_sentiment": 0.5,
        }
    )
    provider = FakeInferenceProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="fake-orch",
        scripted=[InferenceResult(content=reply, model="fake-orch")],
    )
    graph = AsyncMock()
    graph.create_cycle_with_seed_event = AsyncMock(return_value="00000000-0000-4000-8000-0000000000a1")
    settings = MagicMock()
    settings.num_rounds = 3
    _, parsed, _ = await inject_seed(rumor=RUMOR, settings=settings, orchestrator=provider, graph_manager=graph)
    assert "ticker" in _entity_properties(provider.calls[0]["response_schema"])
    assert [e.ticker for e in parsed.seed_event.entities] == ["ZZZT", None]
