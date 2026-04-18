"""INGEST-01: Real YFinanceMarketDataProvider — wraps yfinance fast_info + info.

D-05: per-ticker asyncio.to_thread + asyncio.gather for error isolation.
D-06: fast_info for price/volume, info for fundamentals (pe_ratio, eps, market_cap).
D-07: no semaphore cap (providers called once per simulation run, not per agent).
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

NaN/Inf guard (Gemini review): yfinance can return float('nan') for trailingPE
on pre-earnings companies. Decimal(str(float('nan'))) produces Decimal('NaN'),
not None. _decimal_or_none must guard via math.isnan/isinf.

Pitfall 6: yf.Ticker(t).info does sync HTTP internally. MUST run inside
asyncio.to_thread, never at async function top level.
"""

from __future__ import annotations

import yfinance as yf  # type: ignore[import-untyped]

from alphaswarm.ingestion.types import MarketSlice


class YFinanceMarketDataProvider:
    """Real MarketDataProvider backed by yfinance. Implementation lands in Task 2."""

    async def get_prices(self, tickers: list[str]) -> dict[str, MarketSlice]:
        raise NotImplementedError("YFinanceMarketDataProvider.get_prices — Task 2")

    async def get_fundamentals(self, tickers: list[str]) -> dict[str, MarketSlice]:
        raise NotImplementedError("YFinanceMarketDataProvider.get_fundamentals — Task 2")

    async def get_volume(self, tickers: list[str]) -> dict[str, MarketSlice]:
        raise NotImplementedError("YFinanceMarketDataProvider.get_volume — Task 2")
