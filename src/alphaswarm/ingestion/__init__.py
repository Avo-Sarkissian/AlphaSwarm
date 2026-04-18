"""Ingestion subpackage — swarm-safe types and provider Protocols.

Types (ContextPacket, MarketSlice, NewsSlice, Fundamentals) have ZERO
holdings-shaped fields by construction (ISOL-02) and reject unknown keys at
runtime via extra='forbid'.
Provider Protocols (MarketDataProvider, NewsProvider) define the Phase 38
seam (ISOL-05) with explicit async signatures.
Real providers (YFinanceMarketDataProvider, RSSNewsProvider) implement
INGEST-01 and INGEST-02 respectively.
"""

from alphaswarm.ingestion.providers import (
    FakeMarketDataProvider,
    FakeNewsProvider,
    MarketDataProvider,
    NewsProvider,
)
from alphaswarm.ingestion.types import (
    ContextPacket,
    Fundamentals,
    MarketSlice,
    NewsSlice,
    StalenessState,
)
from alphaswarm.ingestion.yfinance_provider import YFinanceMarketDataProvider

__all__ = [
    "ContextPacket",
    "FakeMarketDataProvider",
    "FakeNewsProvider",
    "Fundamentals",
    "MarketDataProvider",
    "MarketSlice",
    "NewsProvider",
    "NewsSlice",
    "StalenessState",
    "YFinanceMarketDataProvider",
]
