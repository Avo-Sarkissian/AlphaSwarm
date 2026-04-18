"""ISOL-05: MarketDataProvider / NewsProvider Protocol definitions + in-memory fakes.

D-17: Two Protocols only. No per-query-type splits.
D-18: Batch-first async signatures (list[str] -> dict[str, Slice]).
D-19: Providers NEVER raise for fetch failures; return staleness='fetch_failed'.
D-20: Fakes included here so Phase 38 is test-first.

REVIEW REVISION (2026-04-18):
- All Protocol methods are declared with `async def` — the project is asyncio-only
  and Phase 38 aggregates 100 tickers concurrently. Sync implementations would
  block the event loop. (Gemini/Codex MEDIUM)
- `StalenessState` is imported from alphaswarm.ingestion.types and used in
  failure-slice construction; no unconstrained string literals. (Codex MEDIUM)
- `fixture_source` callback paths are wrapped so internal exceptions become
  `fetch_failed` slices — the D-19 "never raise" contract holds for unknown
  keys, empty inputs, duplicate inputs, AND callback exceptions. (Codex MEDIUM)

No runtime_checkable decorator — mypy strict is sufficient (Pitfall 8).
Fakes are pure in-memory dict lookups — no network imports, no sleeps (Pitfall 5).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from alphaswarm.ingestion.types import MarketSlice, NewsSlice, StalenessState

_FETCH_FAILED: StalenessState = "fetch_failed"


class MarketDataProvider(Protocol):
    """Batch-first async market data provider.

    Implementations MUST be `async def` (project is asyncio-only) and MUST NOT
    raise for fetch failures. On failure, return a MarketSlice with
    staleness='fetch_failed' so caller aggregation loops don't need try/except
    per ticker (D-19).
    """

    async def get_prices(self, tickers: list[str]) -> dict[str, MarketSlice]:
        ...

    async def get_fundamentals(self, tickers: list[str]) -> dict[str, MarketSlice]:
        ...

    async def get_volume(self, tickers: list[str]) -> dict[str, MarketSlice]:
        ...


class NewsProvider(Protocol):
    """Batch-first async news provider.

    max_age_hours is keyword-only to prevent accidental positional misuse
    across RSS / NewsAPI / future adapters. Method is `async def` for the
    same asyncio-only reason as MarketDataProvider.
    """

    async def get_headlines(
        self, entities: list[str], *, max_age_hours: int = 72
    ) -> dict[str, NewsSlice]:
        ...


def _fetch_failed_market_slice(ticker: str, source: str) -> MarketSlice:
    return MarketSlice(
        ticker=ticker,
        price=None,
        volume=None,
        fundamentals=None,
        fetched_at=datetime.now(UTC),
        source=source,
        staleness=_FETCH_FAILED,
    )


def _fetch_failed_news_slice(entity: str, source: str) -> NewsSlice:
    return NewsSlice(
        entity=entity,
        headlines=(),
        fetched_at=datetime.now(UTC),
        source=source,
        staleness=_FETCH_FAILED,
    )


class FakeMarketDataProvider:
    """In-memory test fake — returns fixture-configured MarketSlice per ticker.

    Unknown tickers return staleness='fetch_failed' (matches D-19 contract).
    Empty input lists return {} (never raise).
    Duplicate tickers collapse via dict-comprehension semantics to a single key.
    A supplied `fixture_source` callback that raises is caught and converted to
    a fetch_failed slice — the D-19 never-raise contract holds even for
    programmer-error fixture sources (REVIEW MEDIUM — Codex).
    Supports sentinel tickers (e.g. SNTL_CANARY_TICKER) for canary tests.
    """

    def __init__(
        self,
        fixtures: dict[str, MarketSlice] | None = None,
        *,
        fixture_source: Callable[[str], MarketSlice] | None = None,
    ) -> None:
        self._fixtures = dict(fixtures) if fixtures else {}
        self._fixture_source = fixture_source
        self._source = "fake_market_data"

    def _resolve(self, ticker: str) -> MarketSlice:
        if ticker in self._fixtures:
            return self._fixtures[ticker]
        if self._fixture_source is not None:
            try:
                return self._fixture_source(ticker)
            except Exception:  # noqa: BLE001 — D-19 contract: never raise
                return _fetch_failed_market_slice(ticker, self._source)
        return _fetch_failed_market_slice(ticker, self._source)

    async def get_prices(self, tickers: list[str]) -> dict[str, MarketSlice]:
        return {t: self._resolve(t) for t in tickers}

    async def get_fundamentals(self, tickers: list[str]) -> dict[str, MarketSlice]:
        return {t: self._resolve(t) for t in tickers}

    async def get_volume(self, tickers: list[str]) -> dict[str, MarketSlice]:
        return {t: self._resolve(t) for t in tickers}


class FakeNewsProvider:
    """In-memory test fake — returns fixture-configured NewsSlice per entity."""

    def __init__(self, fixtures: dict[str, NewsSlice] | None = None) -> None:
        self._fixtures = dict(fixtures) if fixtures else {}
        self._source = "fake_news"

    async def get_headlines(
        self, entities: list[str], *, max_age_hours: int = 72
    ) -> dict[str, NewsSlice]:
        # max_age_hours is part of the contract but ignored by the fake;
        # real providers will filter; the fake passes fixtures through.
        _ = max_age_hours
        return {
            e: self._fixtures.get(e, _fetch_failed_news_slice(e, self._source))
            for e in entities
        }
