"""run_simulation orchestration: rounds, lifecycle, shocks, context, metrics."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from alphaswarm.ingestion.providers import FakeMarketDataProvider, FakeNewsProvider
from alphaswarm.ingestion.types import MarketSlice, NewsSlice
from alphaswarm.settings import AppSettings
from alphaswarm.simulation import SimulationDeps, assemble_market_context, run_simulation
from alphaswarm.types import (
    EntityType,
    ParsedSeedResult,
    SeedEntity,
    SeedEvent,
)


def test_run_simulation_makes_no_eager_narrative_calls() -> None:
    """Narratives are generated lazily on first interview, never in the run."""
    from alphaswarm import simulation
    from alphaswarm.graph import GraphStateManager

    assert "generate_narratives" not in inspect.signature(simulation.run_simulation).parameters
    assert not hasattr(simulation, "_generate_decision_narratives")
    assert not hasattr(GraphStateManager, "write_decision_narratives")


_CONTEXT_CYCLE = "00000000-0000-4000-8000-0000000000c1"
_CONTEXT_HEADLINE = "ZZZT Holdings confirms a strategic review"
_CONTEXT_RUMOR = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."


def _context_seed(*names: str) -> ParsedSeedResult:
    entities = [SeedEntity(name=n, type=EntityType.COMPANY, relevance=0.9, sentiment=0.5) for n in names]
    event = SeedEvent(raw_rumor=_CONTEXT_RUMOR, entities=entities, overall_sentiment=0.5)
    return ParsedSeedResult(seed_event=event, parse_tier=1)


class _RecordingMarket(FakeMarketDataProvider):
    def __init__(self) -> None:
        super().__init__()
        self.requested: list[list[str]] = []

    async def get_prices(self, tickers: list[str]) -> dict[str, MarketSlice]:
        self.requested.append(list(tickers))
        return await super().get_prices(tickers)


class _RecordingNews(FakeNewsProvider):
    def __init__(self, fixtures: dict[str, NewsSlice] | None = None) -> None:
        super().__init__(fixtures)
        self.requested: list[list[str]] = []

    async def get_headlines(self, entities: list[str], *, max_age_hours: int = 72) -> dict[str, NewsSlice]:
        self.requested.append(list(entities))
        return await super().get_headlines(entities, max_age_hours=max_age_hours)


def _news_slice(entity: str) -> NewsSlice:
    return NewsSlice(
        entity=entity,
        headlines=(_CONTEXT_HEADLINE,),
        fetched_at=datetime(2026, 10, 3, tzinfo=UTC),
        source="fake_news",
    )


def test_run_simulation_takes_deps_and_optional_callbacks() -> None:
    params = inspect.signature(run_simulation).parameters
    assert list(params)[:4] == ["rumor", "deps", "personas", "brackets"]
    assert params["on_round_complete"].default is None
    assert params["consume_shock"].default is None
    assert not {"ollama_client", "model_manager", "orchestrator_provider", "worker_provider"} & set(params)


def test_simulation_deps_requires_both_providers() -> None:
    with pytest.raises(TypeError):
        SimulationDeps(  # type: ignore[call-arg]
            settings=AppSettings(_env_file=None),  # type: ignore[call-arg]
            graph=MagicMock(),
            controller=MagicMock(),
        )


def test_simulation_deps_is_the_rounds_type_reexported() -> None:
    from alphaswarm import rounds, simulation

    assert simulation.SimulationDeps is rounds.SimulationDeps
    assert "SimulationDeps" in simulation.__all__


@pytest.mark.parametrize(
    ("market", "news"),
    [(None, None), (FakeMarketDataProvider(), None), (None, FakeNewsProvider())],
    ids=["both_missing", "news_missing", "market_missing"],
)
async def test_market_context_skipped_without_both_providers(
    market: FakeMarketDataProvider | None, news: FakeNewsProvider | None
) -> None:
    assert await assemble_market_context(_CONTEXT_CYCLE, _context_seed("ZZZT"), market, news) is None


async def test_only_ticker_shaped_names_reach_the_market_provider() -> None:
    market, news = _RecordingMarket(), _RecordingNews()
    names = ("ZZZT", "QQQX Robotics", "Industrial Automation")

    await assemble_market_context(_CONTEXT_CYCLE, _context_seed(*names), market, news)

    assert market.requested == [["ZZZT"]]
    assert news.requested == [list(names)]


async def test_company_name_entity_gets_news_only() -> None:
    news = _RecordingNews({"QQQX Robotics": _news_slice("QQQX Robotics")})

    block = await assemble_market_context(_CONTEXT_CYCLE, _context_seed("QQQX Robotics"), _RecordingMarket(), news)

    assert block is not None
    assert "== QQQX Robotics ==" in block
    assert _CONTEXT_HEADLINE in block
    assert "Price:" not in block


async def test_all_fetch_failed_yields_no_block() -> None:
    block = await assemble_market_context(
        _CONTEXT_CYCLE,
        _context_seed("ZZZT", "QQQX Robotics"),
        FakeMarketDataProvider(),
        FakeNewsProvider(),
    )
    assert block is None
