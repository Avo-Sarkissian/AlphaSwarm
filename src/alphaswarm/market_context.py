"""Round market context: which entities, which symbols, one block (docs/DECISIONS.md#adr-market-context).

Entities are ordered by relevance so the most relevant survive the formatter's
budget. Only tickers resolved on the swarm side reach the market provider and the
Yahoo per-ticker feed (docs/DECISIONS.md#adr-ticker-resolution); every entity still
gets news by name. Providers never raise (docs/DECISIONS.md#adr-provider-never-raise).
Never imports alphaswarm.advisory (tests/invariants/test_swarm_ticker_resolution.py).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from alphaswarm.context_formatter import format_market_context
from alphaswarm.ingestion.types import ContextPacket

if TYPE_CHECKING:
    from alphaswarm.ingestion.providers import MarketDataProvider, NewsProvider
    from alphaswarm.types import ParsedSeedResult, SeedEntity

# Same component as the block's previous home in simulation.py, so log queries keep working.
logger = structlog.get_logger(component="simulation")


def order_entities(entities: Sequence[SeedEntity]) -> list[SeedEntity]:
    """Highest relevance first; ties keep the orchestrator's order."""
    return sorted(entities, key=lambda entity: -entity.relevance)


async def build_context_packet(
    cycle_id: str,
    parsed_result: ParsedSeedResult,
    market: MarketDataProvider | None,
    news: NewsProvider | None,
) -> ContextPacket | None:
    """Fetch prices for resolved tickers and headlines for every entity; None without providers."""
    if market is None or news is None:
        logger.warning("context_assembly_skipped", reason="no_providers_configured", cycle_id=cycle_id)
        return None
    ordered = order_entities(parsed_result.seed_event.entities)
    names = list(dict.fromkeys(entity.name for entity in ordered))
    entity_tickers = {e.name: e.ticker for e in ordered if e.ticker is not None}
    tickers = list(dict.fromkeys(entity_tickers.values()))
    async with asyncio.TaskGroup() as group:
        prices = group.create_task(market.get_prices(tickers))
        headlines = group.create_task(news.get_headlines(names, tickers=entity_tickers))
    packet = ContextPacket(
        cycle_id=cycle_id,
        as_of=datetime.now(UTC),
        entities=tuple(names),
        market=tuple(prices.result().values()),
        news=tuple(headlines.result().values()),
        entity_tickers=tuple(entity_tickers.items()),
    )
    logger.info(
        "context_packet_assembled",
        cycle_id=cycle_id,
        entity_count=len(names),
        ticker_count=len(tickers),
        market_success=sum(1 for s in packet.market if s.staleness != "fetch_failed"),
        stale_quotes=sum(1 for s in packet.market if s.staleness == "stale"),
        news_success=sum(1 for s in packet.news if s.staleness != "fetch_failed"),
        total_headlines=sum(len(s.headlines) for s in packet.news if s.staleness != "fetch_failed"),
    )
    return packet


async def assemble_market_context(
    cycle_id: str,
    parsed_result: ParsedSeedResult,
    market: MarketDataProvider | None,
    news: NewsProvider | None,
) -> str | None:
    """The block agents see (fenced by the worker), or None when nothing renderable came back."""
    packet = await build_context_packet(cycle_id, parsed_result, market, news)
    return format_market_context(packet) if packet is not None else None
