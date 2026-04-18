# Phase 38: Market Data + News Providers - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-18
**Phase:** 38-market-data-news-providers
**Areas discussed:** News provider backend, YFinance async wrapping, Staleness thresholds

---

## News Provider Backend

| Option | Description | Selected |
|--------|-------------|----------|
| RSS only | feedparser over curated financial feeds. Free, no key, no rate limits. Entity filtering via keyword match. | ✓ |
| NewsAPI only | Structured entity search via NEWSAPI_KEY. Cleaner matching but 100 req/day free cap. | |
| RSS + NewsAPI fallback | Best coverage, doubles complexity, still requires NewsAPI key. | |

**User's choice:** RSS only

**Follow-up — RSS feed strategy:**

| Option | Description | Selected |
|--------|-------------|----------|
| Hardcoded curated list | Fixed set of financial feeds baked in. | |
| Google News + Yahoo Finance per ticker | Google News RSS per topic entity; Yahoo Finance RSS per ticker symbol. | ✓ |
| Config-driven feed map | Feed URLs from pydantic-settings config. | |

**User's choice:** Google News RSS for topic/geopolitical entities + Yahoo Finance RSS for recognized ticker symbols

**Rationale:** User noted that hardcoded feed lists would fail for dynamic seed rumors spanning different domains (US-Iran war vs EV industry). Dynamic per-entity feed construction solves this.

---

## YFinance Async Wrapping

| Option | Description | Selected |
|--------|-------------|----------|
| asyncio.to_thread per ticker + gather | One thread per ticker, concurrent gather, per-ticker error isolation. Uses yf.Ticker fast_info + info. | ✓ |
| asyncio.to_thread for whole batch | Single thread wrapping yf.download(tickers). Simpler but one failure fails all tickers. | |

**User's choice:** asyncio.to_thread per ticker + asyncio.gather

**Notes:** Semaphore cap deemed overkill — providers called once per simulation run pre-cascade, not inside the 100-agent governor loop.

---

## Staleness Thresholds

| Option | Description | Selected |
|--------|-------------|----------|
| Simple: always fresh on success | fresh on any successful fetch, fetch_failed on exception. No time-window logic. | ✓ |
| Time-window: stale if older than N hours | Compare yfinance timestamp to now(UTC). Mark stale if delta > threshold. | |

**User's choice:** Simple — always `fresh` on success, `fetch_failed` on exception

---

## Claude's Discretion

- File layout: separate `yfinance_provider.py` and `rss_provider.py` vs single `real_providers.py`
- `max_age_hours` filtering implementation using RSS `published_parsed` entry timestamps
- Google News headline text normalization for entity matching
- Per-ticker try/except inside the `asyncio.to_thread` callback

## Deferred Ideas

- RSS feed caching/TTL between simulation runs
- Staleness time-window logic
- NewsAPI fallback for sparse RSS coverage
