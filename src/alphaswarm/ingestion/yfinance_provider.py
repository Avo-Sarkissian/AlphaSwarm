"""YFinanceMarketDataProvider: price, volume and fundamentals from yfinance.

Invariants:
- Never raises: any failure for a ticker, including yfinance's own errors on
  delisted or unknown symbols, becomes a ``fetch_failed`` MarketSlice
  (docs/DECISIONS.md#adr-provider-never-raise).
- One ``yf.Ticker`` scrape per ticker, run in ``asyncio.to_thread`` and gathered
  per ticker so one bad symbol cannot fail the batch. No cache, no semaphore
  (called once per run, not per agent).
- Money values use ``Decimal(str(x))``; NaN and infinities become ``None``.
- Tickers pass through unchanged; callers normalise them.
- ``get_prices``, ``get_fundamentals`` and ``get_volume`` return the same full
  slice from one scrape; callers use exactly one of them per run.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
from datetime import UTC, datetime
from decimal import Decimal

import yfinance as yf

from alphaswarm.ingestion.providers import _fetch_failed_market_slice
from alphaswarm.ingestion.types import Fundamentals, MarketSlice

_SOURCE = "yfinance"


def _decimal_or_none(value: object) -> Decimal | None:
    """Convert a yfinance numeric field to Decimal, or None if absent/invalid.

    Pitfall 5: Decimal(str(...)) — never Decimal(float) — to avoid binary-float
    rounding on money values.

    NaN/Inf guard (Gemini review): yfinance can return float('nan') for
    trailingPE on pre-earnings companies. Decimal(str(float('nan'))) produces
    Decimal('NaN'), not None, which would leak a NaN Decimal into downstream
    consumers. Guard here instead of at every call site.
    """
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return Decimal(str(value))


def _fetch_one_sync(ticker: str) -> MarketSlice:
    """Runs in a worker thread. MUST NOT raise — returns fetch_failed on any error.

    The broad try/except is required to catch Pitfall 1: fast_info.last_price
    raises KeyError('currentTradingPeriod') on delisted tickers. Catching
    per-field with None-checks would miss this because the field access itself
    raises before a None can be returned.
    """
    try:
        yft = yf.Ticker(ticker)
        fi = yft.fast_info
        price = _decimal_or_none(fi.last_price)
        # last_volume can be float('nan') (e.g. pre-market) — int(nan) raises
        # ValueError, which would downgrade the whole slice to fetch_failed
        # even when price was valid. NaN/Inf → None (volume is int | None).
        raw_volume = fi.last_volume
        if raw_volume is None or (isinstance(raw_volume, float) and (math.isnan(raw_volume) or math.isinf(raw_volume))):
            volume = None
        else:
            volume = int(raw_volume)
        info = yft.info  # sync HTTP — must be inside thread (Pitfall 6)
        fundamentals = Fundamentals(
            pe_ratio=_decimal_or_none(info.get("trailingPE")),
            eps=_decimal_or_none(info.get("trailingEps")),
            market_cap=_decimal_or_none(info.get("marketCap")),
        )
        return MarketSlice(
            ticker=ticker,
            price=price,
            volume=volume,
            fundamentals=fundamentals,
            fetched_at=datetime.now(UTC),
            source=_SOURCE,
            staleness="fresh",
        )
    except Exception:  # noqa: BLE001 — D-19 never-raise contract
        return _fetch_failed_market_slice(ticker, _SOURCE)


class YFinanceMarketDataProvider:
    """Real MarketDataProvider backed by yfinance.

    All three Protocol methods share a single _fetch_batch_shared implementation
    because yfinance returns price, volume, and fundamentals in one scrape
    per ticker (see module docstring and Research Open Question 1).

    ITEM 5 of quick task 260512-jqn: providers MAY accept an optional
    state_store via attach_audit_sink() to surface each fetch on the WS
    SignalWire ticker. The hook is dependency-free — passing None or never
    calling attach keeps behavior identical to the prior contract.
    """

    def __init__(self) -> None:
        # Lazy-typed to avoid forcing alphaswarm.state import at module load.
        # Set via attach_audit_sink() once StateStore is available on app.state.
        self._audit_sink: object | None = None

    def attach_audit_sink(self, state_store: object) -> None:
        """Attach a StateStore-shaped object (`record_data_source` callable).

        The provider only calls `state_store.record_data_source(source, query,
        result, used)` — no other attribute. Decoupled this way so unit tests
        can pass any duck-typed sink. Lifespan wires this from
        alphaswarm.web.app after app_state is constructed.
        """
        self._audit_sink = state_store

    def _audit(self, query: str, result: str, used: bool) -> None:
        """Non-fatal audit shim — never raises into the fetch path."""
        sink = self._audit_sink
        if sink is None:
            return
        with contextlib.suppress(Exception):  # observability must never break the fetch
            sink.record_data_source(  # type: ignore[attr-defined]
                source="yfinance",
                query=query,
                result=result,
                used=used,
            )

    async def _fetch_batch_shared(self, tickers: list[str]) -> dict[str, MarketSlice]:
        if not tickers:  # Pitfall 9 — empty input must not call gather
            return {}
        slices = await asyncio.gather(
            *(asyncio.to_thread(_fetch_one_sync, t) for t in tickers),
            return_exceptions=False,  # _fetch_one_sync is contractually never-raise
        )
        # Audit one entry per ticker so the SignalWire ticker matches batch shape.
        for s in slices:
            ok = s.staleness != "fetch_failed"
            self._audit(
                query=f"{s.ticker} OHLCV",
                result="ok" if ok else "error: fetch_failed",
                used=True,
            )
        # Duplicate tickers collapse to single key (matches FakeMarketDataProvider)
        return {s.ticker: s for s in slices}

    async def get_prices(self, tickers: list[str]) -> dict[str, MarketSlice]:
        return await self._fetch_batch_shared(tickers)

    async def get_fundamentals(self, tickers: list[str]) -> dict[str, MarketSlice]:
        return await self._fetch_batch_shared(tickers)

    async def get_volume(self, tickers: list[str]) -> dict[str, MarketSlice]:
        return await self._fetch_batch_shared(tickers)
