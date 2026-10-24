"""Market context assembly: relevance order, resolved tickers only (docs/DECISIONS.md#adr-market-context)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from alphaswarm.ingestion.providers import FakeMarketDataProvider, FakeNewsProvider
from alphaswarm.ingestion.types import ContextPacket, MarketSlice, NewsSlice
from alphaswarm.market_context import (
    assemble_market_context,
    build_context_packet,
    order_entities,
    private_market_contexts,
)
from alphaswarm.personas import generate_personas, load_bracket_configs
from alphaswarm.types import EntityType, ParsedSeedResult, SeedEntity, SeedEvent

CYCLE = "00000000-0000-4000-8000-0000000000c1"
RUMOR = "ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash."
AT = datetime(2026, 10, 2, 20, 0, tzinfo=UTC)


def _seed(*entities: SeedEntity) -> ParsedSeedResult:
    return ParsedSeedResult(
        seed_event=SeedEvent(raw_rumor=RUMOR, entities=list(entities), overall_sentiment=0.5),
        parse_tier=1,
    )


def _e(name: str, relevance: float, ticker: str | None = None, kind: EntityType = EntityType.COMPANY) -> SeedEntity:
    return SeedEntity(name=name, type=kind, relevance=relevance, sentiment=0.3, ticker=ticker)


def _news(entity: str, headline: str) -> NewsSlice:
    return NewsSlice(entity=entity, headlines=(headline,), fetched_at=AT, source="fake_news")


class _RecordingMarket(FakeMarketDataProvider):
    def __init__(self, fixtures: dict[str, MarketSlice] | None = None) -> None:
        super().__init__(fixtures)
        self.requested: list[list[str]] = []

    async def get_prices(self, tickers: list[str]) -> dict[str, MarketSlice]:
        self.requested.append(list(tickers))
        return await super().get_prices(tickers)


class _RecordingNews(FakeNewsProvider):
    def __init__(self, fixtures: dict[str, NewsSlice] | None = None) -> None:
        super().__init__(fixtures)
        self.requested: list[tuple[list[str], dict[str, str]]] = []

    async def get_headlines(
        self,
        entities: list[str],
        *,
        max_age_hours: int = 72,
        tickers: Mapping[str, str] | None = None,
    ) -> dict[str, NewsSlice]:
        self.requested.append((list(entities), dict(tickers or {})))
        return await super().get_headlines(entities, max_age_hours=max_age_hours, tickers=tickers)


def test_entities_are_ordered_by_relevance_with_stable_ties() -> None:
    ordered = order_entities([_e("A Co", 0.5), _e("B Co", 0.9), _e("C Co", 0.5), _e("D Co", 0.95)])
    assert [e.name for e in ordered] == ["D Co", "B Co", "A Co", "C Co"]


async def test_only_resolved_tickers_reach_the_market_provider() -> None:
    market, news = _RecordingMarket(), _RecordingNews()
    seed = _seed(
        _e("Federal Reserve", 0.7),
        _e("ZZZT Holdings", 0.95, "ZZZT"),
        _e("Industrial Automation", 0.6, kind=EntityType.SECTOR),
    )
    packet = await build_context_packet(CYCLE, seed, market, news)
    assert market.requested == [["ZZZT"]]
    assert news.requested == [
        (["ZZZT Holdings", "Federal Reserve", "Industrial Automation"], {"ZZZT Holdings": "ZZZT"})
    ]
    assert packet is not None and packet.entity_tickers == (("ZZZT Holdings", "ZZZT"),)


async def test_price_joins_its_company_by_resolved_ticker() -> None:
    quote = MarketSlice(ticker="ZZZT", price=Decimal("12.34"), fetched_at=AT, as_of=AT, source="fake")
    block = await assemble_market_context(
        CYCLE,
        _seed(_e("ZZZT Holdings", 0.95, "ZZZT")),
        _RecordingMarket({"ZZZT": quote}),
        _RecordingNews({"ZZZT Holdings": _news("ZZZT Holdings", "Deal talk")}),
    )
    assert block is not None
    assert "== ZZZT Holdings (ZZZT) ==" in block
    assert "Price: $12.34 (as of 2026-10-02 20:00 UTC)" in block
    assert "  - Deal talk" in block


@pytest.mark.parametrize(
    ("market", "news"),
    [(None, None), (FakeMarketDataProvider(), None), (None, FakeNewsProvider())],
    ids=["both_missing", "news_missing", "market_missing"],
)
async def test_skipped_without_both_providers(
    market: FakeMarketDataProvider | None, news: FakeNewsProvider | None
) -> None:
    seed = _seed(_e("ZZZT Holdings", 0.9, "ZZZT"))
    assert await assemble_market_context(CYCLE, seed, market, news) is None


async def test_all_fetch_failed_yields_no_block() -> None:
    seed = _seed(_e("ZZZT Holdings", 0.9, "ZZZT"), _e("QQQX Robotics", 0.8))
    assert await assemble_market_context(CYCLE, seed, FakeMarketDataProvider(), FakeNewsProvider()) is None


def _packet_with_headlines() -> ContextPacket:
    quote = MarketSlice(ticker="ZZZT", price=Decimal("12.34"), fetched_at=AT, source="fake")
    news = NewsSlice(
        entity="ZZZT Holdings", headlines=tuple(f"Headline {i}" for i in range(1, 9)), fetched_at=AT, source="fake_news"
    )
    return ContextPacket(
        cycle_id=CYCLE,
        as_of=AT,
        entities=("ZZZT Holdings",),
        market=(quote,),
        news=(news,),
        entity_tickers=(("ZZZT Holdings", "ZZZT"),),
    )


def _headlines(block: str | None) -> tuple[str, ...]:
    assert block is not None
    return tuple(line for line in block.splitlines() if line.startswith("  - "))


def test_private_contexts_keep_prices_and_vary_headlines() -> None:
    personas = generate_personas(load_bracket_configs())[:20]
    blocks = private_market_contexts(_packet_with_headlines(), personas, run_seed="101")
    assert len(blocks) == 20
    assert all(b is not None and "12.34" in b for b in blocks)
    headline_sets = {_headlines(b) for b in blocks}
    assert len(headline_sets) > 1
    assert all(len(s) == 4 for s in headline_sets)  # ceil(8 * 0.5)


def test_private_contexts_are_deterministic_per_seed() -> None:
    personas = generate_personas(load_bracket_configs())[:5]
    first = private_market_contexts(_packet_with_headlines(), personas, run_seed="101")
    assert first == private_market_contexts(_packet_with_headlines(), personas, run_seed="101")
    assert first != private_market_contexts(_packet_with_headlines(), personas, run_seed="102")


def test_private_contexts_keep_failed_and_empty_news() -> None:
    packet = _packet_with_headlines()
    failed = NewsSlice(entity="ZZZT Holdings", fetched_at=AT, source="fake_news", staleness="fetch_failed")
    packet = packet.model_copy(update={"news": (failed,)})
    [block] = private_market_contexts(packet, generate_personas(load_bracket_configs())[:1], run_seed="1")
    assert block is not None and "12.34" in block and not _headlines(block)


@pytest.mark.parametrize("fraction", [0.0, -0.1, 1.5])
def test_keep_fraction_is_validated(fraction: float) -> None:
    with pytest.raises(ValueError, match="keep_fraction"):
        private_market_contexts(_packet_with_headlines(), [], run_seed="1", keep_fraction=fraction)
