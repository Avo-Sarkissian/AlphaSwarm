"""INGEST-01: Real YFinanceMarketDataProvider — wraps yfinance fast_info + info.

D-05: per-ticker asyncio.to_thread + asyncio.gather for error isolation.
D-06: fast_info for price/volume, info for fundamentals (pe_ratio, eps, market_cap).
D-07: no semaphore cap (providers called once per simulation run, not per agent).
D-09: staleness='fresh' on success; 'fetch_failed' on any exception (no time window).
D-10: no caching — each call is a fresh scrape.
D-19: NEVER raises — every failure mode returns _fetch_failed_market_slice(ticker, 'yfinance').

Ticker input contract (Codex review): ticker strings are passed through to
yf.Ticker(t) AS-IS. This provider does NOT sanitize whitespace, case, or
exotic symbols (BRK.B, ^GSPC, BTC-USD). Upstream callers (Phase 40 entity
extraction) are responsible for normalization. Inputs like " aapl " will
produce fetch_failed slices; this is intentional.

Pitfall 1 (HIGH): fast_info.last_price raises KeyError('currentTradingPeriod') on
delisted/unknown tickers. The entire _fetch_one_sync body is wrapped in ONE broad
try/except so this KeyError becomes a fetch_failed slice rather than escaping.

Pitfall 5: Decimal(str(float)) — never Decimal(float). Binary float rounding on
money is a known precision bug.

NaN/Inf guard (Gemini review MEDIUM): yfinance returns float('nan') for
trailingPE on pre-earnings companies and occasionally for other ratio fields.
Decimal(str(float('nan'))) produces Decimal('NaN') — a special value that
is NOT None — which would break Phase 40 advisory synthesis equality checks.
_decimal_or_none MUST check math.isnan(value) / math.isinf(value) and return
None in that case.

Pitfall 6: yf.Ticker(t).info does sync HTTP internally. MUST run inside
asyncio.to_thread, never at async function top level.

Note on Protocol method sharing (Research Open Question 1 + 38-REVIEWS
Codex MEDIUM):
All three methods (get_prices, get_fundamentals, get_volume) return the same
MarketSlice shape and delegate to _fetch_batch_shared. yfinance returns price,
volume, AND fundamentals in one Ticker() scrape; splitting into 3 separate
scrapes would triple the network cost for no benefit. Callers that only need
price can still call get_prices — they just get a complete slice including
fundamentals they may ignore.

PHASE 40 CALL PATTERN (IMPORTANT — Codex review): Phase 40 must call EXACTLY
ONE of the three methods per simulation run (recommended: get_prices, since
it returns the full market slice shape expected by ContextPacket.market).
Calling all three in sequence would hit yfinance three times for the same
data — wasted network cost, identical payload. The three methods are kept
only for NewsProvider Protocol conformance and future caller clarity; they
are NOT intended to be chained.
"""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime
from decimal import Decimal

import yfinance as yf  # type: ignore[import-untyped]

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
        if raw_volume is None or (
            isinstance(raw_volume, float)
            and (math.isnan(raw_volume) or math.isinf(raw_volume))
        ):
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
        try:
            sink.record_data_source(  # type: ignore[attr-defined]
                source="yfinance", query=query, result=result, used=used,
            )
        except Exception:  # noqa: BLE001 — observability MUST NOT break fetch
            pass

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
