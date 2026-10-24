"""Seed entities carry an orchestrator-proposed ticker (docs/DECISIONS.md#adr-ticker-resolution)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from alphaswarm.inference.types import InferenceResult, ProviderRole
from alphaswarm.ingestion.tickers import TickerResolver
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


SEC_FIXTURE = TickerResolver.from_sec_payload(
    {
        "0": {"cik_str": 1, "ticker": "ZZZT", "title": "ZZZT Holdings Inc."},
        "1": {"cik_str": 2, "ticker": "QQQX", "title": "QQQX Robotics Corp"},
    }
)
MIXED_REPLY = json.dumps(
    {
        "entities": [
            {"name": "ZZZT Holdings", "type": "company", "relevance": 0.95, "sentiment": 0.6, "ticker": "ZZZT"},
            {
                "name": "Private Robotics Startup",
                "type": "company",
                "relevance": 0.7,
                "sentiment": 0.5,
                "ticker": "QQQX",
            },
            {"name": "Federal Reserve", "type": "company", "relevance": 0.4, "sentiment": 0.0, "ticker": "FED"},
            {"name": "Industrial Automation", "type": "sector", "relevance": 0.6, "sentiment": 0.4, "ticker": "XQZW"},
        ],
        "overall_sentiment": 0.5,
    }
)


async def _inject(resolver: TickerResolver | None) -> tuple[list[str | None], list[str | None]]:
    provider = FakeInferenceProvider(
        role=ProviderRole.ORCHESTRATOR,
        model="fake-orch",
        scripted=[InferenceResult(content=MIXED_REPLY, model="fake-orch")],
    )
    graph = AsyncMock()
    graph.create_cycle_with_seed_event = AsyncMock(return_value="00000000-0000-4000-8000-0000000000a1")
    settings = MagicMock()
    settings.num_rounds = 3
    _, parsed, _ = await inject_seed(
        rumor=RUMOR,
        settings=settings,
        orchestrator=provider,
        graph_manager=graph,
        ticker_resolver=resolver,
    )
    persisted = graph.create_cycle_with_seed_event.await_args.args[1]
    return [e.ticker for e in parsed.seed_event.entities], [e.ticker for e in persisted.entities]


async def test_inject_seed_persists_only_sec_confirmed_tickers() -> None:
    returned, persisted = await _inject(SEC_FIXTURE)
    assert returned == persisted == ["ZZZT", None, None, None]


async def test_inject_seed_without_a_map_drops_acronyms_and_non_companies() -> None:
    returned, persisted = await _inject(None)
    assert returned == persisted == ["ZZZT", "QQQX", None, None]
