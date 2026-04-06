# Phase 17: Market Data Pipeline - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the discussion.

**Date:** 2026-04-06
**Phase:** 17-market-data-pipeline
**Mode:** discuss
**Areas discussed:** Data shape, Cache strategy, News source, Ticker nodes in Neo4j

## Gray Areas Presented

| Area | Question | Options offered |
|------|----------|----------------|
| Data shape | Price history window | 30-day, 5-day, 90-day OHLCV |
| Financials | Which fundamentals | Compact (P/E + market cap), Extended (+revenue/margin/D/E), Earnings-focused |
| Cache TTL | How long before re-fetch | 4 hours, 24 hours, 1 hour |
| Cache location | Where on disk | data/market_cache/, .alphaswarm/cache/, per-cycle |
| News source | Headlines origin | yfinance.news w/fallback, Alpha Vantage NEWS_SENTIMENT, Skip in Phase 17 |
| Headline count | How many headlines | 5, 10 |
| Ticker nodes | Neo4j persistence | Ticker+MarketData nodes, in-memory only, Ticker nodes only |
| AV fallback | Alpha Vantage integration | Key in env var + optional, yfinance-only, mock AV |

## Decisions Made

### Data Shape
- **Price history:** 90-day OHLCV (user override — wanted maximum context coverage)
- **Financials:** Full set — P/E, market cap, 52w range, EPS, revenue TTM, gross margin %, debt/equity, earnings surprise %, next earnings date. User stated: "everything that will help it be as accurate as possible"

### Cache Strategy
- **TTL:** 1 hour (user chose: more aggressive refresh, stays current across back-to-back sims)
- **Location:** `data/market_cache/` (consistent with Phase 16 `data/sec_tickers.json`)

### News Source
- **Decision:** Skip news in Phase 17 — defer DATA-03 to Phase 18 when prompt engineering is done
- **Reserve:** `MarketDataSnapshot.headlines: list[str] = []` placeholder field for Phase 18

### Ticker Nodes in Neo4j
- **Decision:** Create `Ticker` nodes with `HAS_MARKET_DATA` relationship to `MarketDataSnapshot` node
- **Rationale:** Makes market data queryable for Phase 20 post-simulation report

### Alpha Vantage
- **Decision:** `ALPHA_VANTAGE_API_KEY` in pydantic-settings `.env`, optional. If absent → skip AV. If both fail → degraded snapshot + structlog warning.

## No Corrections

All options were selected as presented or refined via "Other" input. No reversals.
