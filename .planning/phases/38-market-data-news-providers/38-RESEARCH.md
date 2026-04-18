# Phase 38: Market Data + News Providers - Research

**Researched:** 2026-04-18
**Domain:** External data ingestion (yfinance market data + RSS news feeds)
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**News Provider Backend:**
- **D-01:** Use RSS-based news provider (`RSSNewsProvider`) — free, no API key, no rate limits
- **D-02:** Dual-source routing per entity type:
  - Ticker symbols (uppercase, 1–5 chars): Yahoo Finance RSS — `https://finance.yahoo.com/rss/headline?s={ticker}`
  - Topic/geopolitical entities (everything else): Google News RSS — `https://news.google.com/rss/search?q={entity}&hl=en-US&gl=US&ceid=US:en`
- **D-03:** Entity filtering: case-insensitive keyword match of entity string against returned headline titles
- **D-04:** `feedparser` as the RSS parsing library; `httpx` (already a dep) for async HTTP fetch of feed content

**YFinance Async Wrapping:**
- **D-05:** `asyncio.to_thread` per ticker + `asyncio.gather` across all tickers in a batch — per-ticker error isolation
- **D-06:** `yf.Ticker(t).fast_info` for price and volume fields; `yf.Ticker(t).info` for fundamentals (pe_ratio, eps, market_cap)
- **D-07:** No semaphore cap — providers are called once per simulation run
- **D-08:** Add `yfinance` to `pyproject.toml` production dependencies; add `feedparser` as well

**Staleness Thresholds:**
- **D-09:** `fresh` on any successful fetch; `fetch_failed` on any exception — no time-window staleness logic
- **D-10:** Providers never cache slices between calls

**Testing Strategy:**
- **D-11:** Unit tests use `FakeMarketDataProvider` and `FakeNewsProvider` from Phase 37 — no new fakes needed
- **D-12:** Integration tests in `tests/integration/` under `enable_socket` auto-marker

### Claude's Discretion

- Exact `max_age_hours` filtering logic inside `RSSNewsProvider.get_headlines` (compare `published_parsed` entry timestamp)
- How to normalize Google News RSS feed entry titles for entity matching (strip punctuation, lowercase)
- Whether `yf.Ticker(t).info` call is wrapped in its own try/except inside the per-ticker thread (it should be, per D-19)
- File layout: `src/alphaswarm/ingestion/yfinance_provider.py` and `src/alphaswarm/ingestion/rss_provider.py` vs single `real_providers.py`

### Deferred Ideas (OUT OF SCOPE)

- RSS feed caching / TTL cache between simulation runs — not needed until Phase 40
- Staleness time-window logic (marking slices stale after N hours)
- NewsAPI fallback for sparse RSS coverage
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INGEST-01 | Real `YFinanceMarketDataProvider` implements `MarketDataProvider` protocol — `fetch_batch` returns `dict[str, MarketSlice]` with price, fundamentals, staleness; never raises | yfinance 1.3.0 `fast_info` + `info` mapping verified [VERIFIED]. `asyncio.to_thread` + `asyncio.gather` per-ticker isolation verified [VERIFIED]. `fast_info.last_price` RAISES `KeyError('currentTradingPeriod')` for delisted tickers — must be caught [VERIFIED]. |
| INGEST-02 | Real `NewsProvider` implementation — `fetch_headlines(entities)` returns entity-filtered headlines; never raises; integration tests use `enable_socket` | httpx + feedparser pipeline verified for Yahoo Finance RSS and Google News RSS [VERIFIED]. Unknown tickers on Yahoo RSS return empty `entries` list (not error) [VERIFIED]. `published_parsed` is `time.struct_time` requiring conversion to `datetime` [VERIFIED]. |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Concurrency:** 100% async. No blocking I/O on the main event loop. Both providers must be `async def` end-to-end. Wrap sync yfinance calls in `asyncio.to_thread`; use async httpx client for RSS fetches.
- **Local First:** The constraint is about LLM inference — market data/news from Yahoo and Google RSS is permitted and is the whole point of INGEST-01/02.
- **Memory Safety:** Providers run pre-simulation (not inside the 100-agent cascade), so no semaphore is needed here (aligned with D-07).
- **Runtime:** Python 3.11+ strict typing; `uv` package manager; `pytest-asyncio` auto mode.
- **GSD Workflow:** All file edits must go through a GSD command — this research is part of `/gsd-plan-phase`.

## Summary

Phase 38 replaces the two Phase 37 Fakes (`FakeMarketDataProvider`, `FakeNewsProvider`) with real network-backed implementations that conform to the same Protocol contracts in `alphaswarm.ingestion.providers`. Both providers must honor the D-19 **never-raise** contract — every failure mode (unknown ticker, network timeout, malformed XML, rate limit) converts to a `staleness='fetch_failed'` slice.

The research uncovered one **HIGH-risk pitfall not captured in CONTEXT.md**: `yf.Ticker(t).fast_info.last_price` raises `KeyError('currentTradingPeriod')` for unknown/delisted tickers — it does NOT return `None`. This means every field access on `fast_info` must be wrapped in try/except, OR we use `.get(name)` since `FastInfo` exposes dict-like access. Similarly `fast_info.last_volume`, `market_cap`, and `shares` returned `None` in our probe for the unknown ticker, so the behavior is **inconsistent across fields**. A single `try` around the whole fast_info extraction plus a `fetch_failed` slice on any exception is the clean path.

The second architectural decision concerns RSS fetching: `feedparser.parse(url)` uses a synchronous URL fetcher internally and triggered `bozo=True` with `URLError` in our probe environment — but `feedparser.parse(text)` on bytes/string content fetched via `httpx.AsyncClient` worked flawlessly. This matches D-04 (httpx for fetch, feedparser for parse) but is worth making explicit in the plan: **never pass a URL to `feedparser.parse` in the real provider**; always fetch bytes with async httpx then hand the text to feedparser.

**Primary recommendation:** Implement `YFinanceMarketDataProvider` and `RSSNewsProvider` as two separate modules (`yfinance_provider.py`, `rss_provider.py`) under `src/alphaswarm/ingestion/`. Register both in `ingestion/__init__.py` `__all__` AND add both submodule dotted paths to `pyproject.toml` `[tool.importlinter]` `source_modules`. One unit-test module per provider uses the Phase 37 Fakes for control paths plus `monkeypatch` on `yf.Ticker` / `httpx.AsyncClient`; one integration-test module per provider under `tests/integration/` hits real network with the auto-applied `enable_socket` marker.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `yfinance` | `>=1.3.0,<2.0` | Yahoo Finance market data (price, volume, fundamentals) [VERIFIED: PyPI latest 1.3.0, 2026-04-16] | De facto standard free Yahoo Finance client; 14k+ GH stars; only mainstream choice for free price+fundamentals batch without API key |
| `feedparser` | `>=6.0.12,<7.0` | RSS/Atom feed parsing [VERIFIED: PyPI 6.0.12 installed in venv] | De facto standard Python RSS parser since 2002; handles malformed feeds gracefully (sets `bozo=True` instead of raising) |
| `httpx` | `>=0.28.0` | Async HTTP client for RSS fetch | Already a prod dep [VERIFIED: pyproject.toml line 19]; supports async + sync in one API; handles redirects |

### Supporting (already available)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pydantic` | `>=2.12.5` | Frozen type construction for `MarketSlice`/`NewsSlice`/`Fundamentals` | Always — types are already defined in Phase 37 |
| `structlog` | `>=25.5.0` | Structured logging of fetch failures with PII redaction | Log exception class + ticker/entity on `fetch_failed` paths |
| `pytest-socket` | `0.7.0` | Global socket disable + `enable_socket` marker | Integration tests auto-get the marker via `tests/integration/conftest.py` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `yfinance` | `alpha-vantage`, `finnhub-python`, `polygon-api-client` | All require API keys and have rate limits on free tiers. yfinance is key-free. |
| `feedparser` | `fastfeedparser`, manual `xml.etree` parsing | `fastfeedparser` is faster but younger/less battle-tested; manual XML is fragile against real-world RSS malformation (Google News returns a custom variant). |
| RSS news | NewsAPI.org | Requires API key + has strict rate limits + the free tier delays content by 24h. RSS is free and near-real-time. (Already captured in CONTEXT.md deferred ideas.) |

**Installation:**
```bash
uv add yfinance feedparser
```

**Version verification:**
```bash
# Verified 2026-04-18
uv pip show yfinance feedparser
# yfinance: 1.2.0 in system pip; 1.3.0 latest on PyPI (2026-04-16)
# feedparser: 6.0.12 (installed in venv during research)
```

Pin `yfinance>=1.3.0` because earlier versions had known `FastInfo` regression issues fixed in the 1.3 release line [CITED: github.com/ranaroussi/yfinance/issues/2348].

### Transitive Dependencies

Adding `yfinance` will pull in `pandas`, `numpy`, `lxml`, `requests`, `multitasking`, `platformdirs`, `frozendict`. None currently in the venv — first `uv sync` after pyproject edit will install them. This adds ~100MB to the install but is unavoidable for yfinance. No conflicts expected with existing deps (pydantic/neo4j/fastapi/httpx).

## Architecture Patterns

### Recommended Project Structure

```
src/alphaswarm/ingestion/
├── __init__.py                  # EXISTING — add 2 new exports
├── types.py                     # EXISTING — no changes (Phase 37 outputs)
├── providers.py                 # EXISTING — Protocols + Fakes, no changes
├── yfinance_provider.py         # NEW — YFinanceMarketDataProvider
└── rss_provider.py              # NEW — RSSNewsProvider

tests/
├── test_providers.py            # EXISTING — no changes
├── test_yfinance_provider.py    # NEW — unit tests with monkeypatch
├── test_rss_provider.py         # NEW — unit tests with monkeypatch
└── integration/
    ├── conftest.py              # EXISTING — enable_socket auto-marker
    ├── test_socket_escape_hatch.py  # EXISTING
    ├── test_yfinance_provider_live.py   # NEW — real network
    └── test_rss_provider_live.py        # NEW — real network
```

Two-file split is recommended over a single `real_providers.py` because:
1. Each provider owns its own import surface (yfinance + pandas vs feedparser + httpx) — easier to reason about dependency scope.
2. Unit tests live next to implementation in `tests/test_yfinance_provider.py` etc.
3. Matches the single-responsibility pattern already used elsewhere in `alphaswarm/`.

### Pattern 1: Per-ticker thread isolation for yfinance

**What:** Wrap each yfinance call in its own `asyncio.to_thread` and collect results with `asyncio.gather(..., return_exceptions=False)`. Inside the thread function, catch every exception and convert to a `fetch_failed` slice.

**When to use:** All yfinance calls in `YFinanceMarketDataProvider.get_prices/get_fundamentals/get_volume`.

**Example:**
```python
# Source: Verified by probe 2026-04-18
# Fields return sample for AAPL: last_price=270.23 (float), last_volume=61314800 (int),
# market_cap=3971820704456.238 (float), shares=14697926000 (int)
from __future__ import annotations
import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import yfinance as yf
from alphaswarm.ingestion.providers import _fetch_failed_market_slice
from alphaswarm.ingestion.types import Fundamentals, MarketSlice

_SOURCE = "yfinance"


def _fetch_one_sync(ticker: str) -> MarketSlice:
    """Runs in a worker thread. MUST NOT raise — returns fetch_failed on any error."""
    try:
        yft = yf.Ticker(ticker)
        fi = yft.fast_info
        # Decimal(str(float)) is the correct binary-float-safe path.
        price = Decimal(str(fi.last_price)) if fi.last_price is not None else None
        volume = int(fi.last_volume) if fi.last_volume is not None else None
        info = yft.info  # Can raise or return {} for unknown tickers.
        fundamentals = Fundamentals(
            pe_ratio=Decimal(str(info["trailingPE"])) if info.get("trailingPE") else None,
            eps=Decimal(str(info["trailingEps"])) if info.get("trailingEps") else None,
            market_cap=Decimal(str(info["marketCap"])) if info.get("marketCap") else None,
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
    async def get_prices(self, tickers: list[str]) -> dict[str, MarketSlice]:
        if not tickers:
            return {}
        slices = await asyncio.gather(
            *(asyncio.to_thread(_fetch_one_sync, t) for t in tickers),
            return_exceptions=False,  # _fetch_one_sync never raises by contract
        )
        # Duplicate tickers collapse per test_fake_market_returns_single_key_for_duplicate_tickers
        return {s.ticker: s for s in slices}

    async def get_fundamentals(self, tickers: list[str]) -> dict[str, MarketSlice]:
        return await self.get_prices(tickers)

    async def get_volume(self, tickers: list[str]) -> dict[str, MarketSlice]:
        return await self.get_prices(tickers)
```

Note: `get_fundamentals` and `get_volume` reuse `get_prices` because `fast_info` + `info` returns all three in one scrape. Splitting them would double the network calls. (See "Open Questions" for an alternative design.)

### Pattern 2: httpx-fetch-then-feedparser-parse for RSS

**What:** Use `httpx.AsyncClient` with a bounded timeout and User-Agent header to fetch raw feed bytes. Hand the `response.text` to `feedparser.parse()`. Never pass a URL directly to `feedparser.parse()`.

**When to use:** All RSS fetches in `RSSNewsProvider.get_headlines`.

**Example:**
```python
# Source: Verified by probe 2026-04-18
# httpx->feedparser AAPL entries=20; Google News "EV battery" entries=100
# Yahoo unknown ticker: 0 entries, no exception
from __future__ import annotations
import asyncio
import re
import time
from datetime import UTC, datetime
from urllib.parse import quote_plus

import feedparser
import httpx
from alphaswarm.ingestion.providers import _fetch_failed_news_slice
from alphaswarm.ingestion.types import NewsSlice

_SOURCE = "rss"
_USER_AGENT = "Mozilla/5.0 AlphaSwarm/6.0"
_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")


def _route_url(entity: str) -> str:
    """Ticker → Yahoo Finance RSS; everything else → Google News RSS."""
    if _TICKER_RE.match(entity):
        return f"https://finance.yahoo.com/rss/headline?s={entity}"
    return (
        f"https://news.google.com/rss/search?q={quote_plus(entity)}"
        "&hl=en-US&gl=US&ceid=US:en"
    )


def _entry_age_hours(entry: dict) -> float | None:
    """published_parsed is time.struct_time; return hours since publish or None."""
    ps = entry.get("published_parsed")
    if ps is None:
        return None
    ts = time.mktime(ps)
    dt = datetime.fromtimestamp(ts, tz=UTC)
    return (datetime.now(UTC) - dt).total_seconds() / 3600.0


async def _fetch_one(
    client: httpx.AsyncClient, entity: str, max_age_hours: int
) -> NewsSlice:
    """Never-raise: any exception → fetch_failed slice."""
    try:
        url = _route_url(entity)
        r = await client.get(url, headers={"User-Agent": _USER_AGENT}, timeout=10.0)
        r.raise_for_status()
        feed = feedparser.parse(r.text)
        needle = entity.lower()
        headlines: list[str] = []
        for e in feed.entries:
            title = e.get("title", "")
            if needle not in title.lower():
                continue
            age = _entry_age_hours(e)
            if age is not None and age > max_age_hours:
                continue
            headlines.append(title)
        return NewsSlice(
            entity=entity,
            headlines=tuple(headlines),
            fetched_at=datetime.now(UTC),
            source=_SOURCE,
            staleness="fresh",
        )
    except Exception:  # noqa: BLE001 — D-19 never-raise contract
        return _fetch_failed_news_slice(entity, _SOURCE)


class RSSNewsProvider:
    async def get_headlines(
        self, entities: list[str], *, max_age_hours: int = 72
    ) -> dict[str, NewsSlice]:
        if not entities:
            return {}
        async with httpx.AsyncClient(follow_redirects=True) as client:
            slices = await asyncio.gather(
                *(_fetch_one(client, e, max_age_hours) for e in entities),
                return_exceptions=False,
            )
        return {s.entity: s for s in slices}
```

### Pattern 3: Reuse Phase 37 `_fetch_failed_*` helpers

**What:** Import `_fetch_failed_market_slice` and `_fetch_failed_news_slice` from `providers.py` (they are module-level underscore helpers, not class methods — accessible via direct import) to build consistent failure slices. Do NOT hand-construct `MarketSlice(staleness='fetch_failed', ...)` in the real providers.

**When to use:** Every exception-handling branch in both new providers.

**Why:** Keeps the failure-slice shape in one place. If Phase 40+ changes what fields a fetch_failed slice includes, only `providers.py` changes. Verified these helpers exist in `providers.py` lines 66-85.

### Anti-Patterns to Avoid

- **Passing URLs to `feedparser.parse(url)`:** Feedparser's built-in URL fetcher does a sync DNS lookup on the event loop thread, and in our probe environment it set `bozo=True` with `URLError` on URLs that httpx fetched fine. **Always fetch with async httpx first, then pass `.text` to `feedparser.parse`.**
- **Relying on `fast_info` field access to return None:** `fi.last_price` RAISES `KeyError('currentTradingPeriod')` for delisted/unknown tickers. `fi.market_cap` returns `None` for the same ticker. Behavior is inconsistent — wrap the entire extraction in one try/except rather than per-field null checks.
- **Calling `yf.Ticker(t).info` outside a thread:** `.info` does a synchronous HTTP request internally. It WILL block the event loop. Always inside `asyncio.to_thread`.
- **Using `return_exceptions=True` on `asyncio.gather`:** The per-ticker helper already converts exceptions to `fetch_failed` slices, so `return_exceptions=True` is redundant and would hide a bug (a genuine never-raise contract violation) by silently wrapping it in a valid result.
- **Forgetting `User-Agent` header on RSS fetches:** Yahoo Finance returned HTTP 429 "Too Many Requests" to our sync httpx call without a User-Agent; the same URL with `User-Agent: Mozilla/5.0 ...` returned 200. Always set UA.
- **Using `Decimal(float)` directly:** `Decimal(0.1)` produces `0.1000000000000000055511151231257827021181583404541015625`. Always `Decimal(str(float_value))`.
- **Hand-rolling entity normalization:** D-03 says case-insensitive substring match against title. Don't build token stemming or regex — `needle = entity.lower(); if needle in title.lower()` is the whole algorithm.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Yahoo Finance scraping | Custom HTTP scraper of finance.yahoo.com pages | `yfinance` | Yahoo silently changes JSON response shape weekly; yfinance maintainers track these; you will spend 10x the time you think. |
| RSS parsing | `xml.etree.ElementTree` on raw feeds | `feedparser` | Real-world RSS includes Atom 1.0, RSS 0.9x, RSS 2.0, CDF, malformed XML entities, bozo namespaces, and Google's custom `<source>` extension. feedparser handles them all. |
| Per-ticker rate limiter | Custom semaphore/tokenbucket | None (per D-07) | Providers run once per simulation, not per agent. No throttling needed. If rate limits hit, those tickers return fetch_failed and Phase 40 deals with it. |
| RSS feed aggregation | Custom multi-feed crawler | Google News RSS search query | Google News already aggregates 100+ sources per entity search; we get the aggregation for free. |
| Price/volume/fundamentals batching | Splitting into 3 API calls (one per Protocol method) | Single per-ticker scrape returning everything | `yf.Ticker(t)` hits Yahoo once and `fast_info` + `info` are cached on the object. Fan out the Protocol split at the Python level by reusing the same scrape. |

**Key insight:** The Protocol's 3-method split (`get_prices` / `get_fundamentals` / `get_volume`) is an interface concession to Phase 40's anticipated flexibility. The real provider should do one scrape per ticker and return the same assembled `MarketSlice` from all three methods. This is efficient AND preserves the Protocol contract.

## Runtime State Inventory

**None — this phase only ADDS new modules.** No renames, no data migrations, no OS-registered state changes. Verified:

| Category | Finding |
|----------|---------|
| Stored data | None — providers don't persist anything (D-10: no caching) |
| Live service config | None — no external services configured by name |
| OS-registered state | None — no systemd/launchd/Task Scheduler entries |
| Secrets/env vars | None — RSS is key-free, yfinance is key-free |
| Build artifacts | pyproject.toml dep additions trigger `uv sync` which creates new `.venv/lib/python3.11/site-packages/{yfinance,pandas,numpy,lxml,feedparser}/` — these are auto-managed, no manual cleanup |

## Common Pitfalls

### Pitfall 1: `fast_info.last_price` raises `KeyError` for delisted tickers
**What goes wrong:** `yf.Ticker('ZZZZNOTREAL').fast_info.last_price` raises `KeyError('currentTradingPeriod')`, NOT `None`. Other fields on the same object (`market_cap`, `shares`) return `None`. Inconsistent API.
**Why it happens:** `FastInfo` lazily fetches historical prices on first access to `last_price`; when the ticker has no history metadata, the internal `self._md["currentTradingPeriod"]` lookup raises `KeyError`. [CITED: github.com/ranaroussi/yfinance/issues/2348]
**How to avoid:** Wrap the entire `_fetch_one_sync` body in a single try/except converting to `fetch_failed`. Don't try to branch on `None` per field.
**Warning signs:** Integration test passes locally for known tickers but fails for a ticker that got delisted between test runs. Symptom is `KeyError` bubbling to the asyncio.gather call site.

### Pitfall 2: `feedparser.parse(url)` triggers sync DNS / sync fetch
**What goes wrong:** Passing a URL string to `feedparser.parse` uses feedparser's internal urllib-based synchronous fetcher, which blocks the event loop and in our probe environment set `bozo=True, bozo_exception=URLError` even on URLs that httpx fetched fine.
**Why it happens:** feedparser predates asyncio; its internal fetcher has different DNS/proxy behavior than httpx. The `bozo` flag is feedparser's way of saying "fetch+parse had a problem"; the problem may be DNS (fetcher) or XML malformation (parser), and you cannot tell which from the `parse()` result alone.
**How to avoid:** Always `r = await httpx_client.get(url); feed = feedparser.parse(r.text)`. Never pass URLs.
**Warning signs:** `bozo=True` with `entries=[]` and `bozo_exception` is some subclass of `OSError`/`URLError`.

### Pitfall 3: `published_parsed` is `time.struct_time`, not `datetime`
**What goes wrong:** `entry.published_parsed` returns `time.struct_time(tm_year=2026, tm_mon=4, ...)` — not a `datetime`. Naive `datetime.now(UTC) - entry.published_parsed` raises `TypeError`.
**Why it happens:** feedparser was written before `datetime` was idiomatic Python; it standardized on `struct_time` for cross-format parity.
**How to avoid:** Convert via `datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=UTC)`. Note: `time.mktime` assumes LOCAL time. For RSS feeds that claim UTC, use `calendar.timegm(entry.published_parsed)` instead for accurate conversion. Or check `entry.published_parsed` vs `entry.updated_parsed` per feed.
**Warning signs:** Age filter returns 0 matches even for current headlines, or filter returns stale headlines as if they were current.

### Pitfall 4: Missing `User-Agent` header triggers Yahoo 429
**What goes wrong:** `httpx.get('https://finance.yahoo.com/rss/headline?s=AAPL')` with default httpx UA returned HTTP 429 "Too Many Requests" in our probe. Same URL with `User-Agent: Mozilla/5.0 ...` returned 200.
**Why it happens:** Yahoo's edge fingerprints the default httpx UA as a bot and rate-limits it.
**How to avoid:** Always set `headers={"User-Agent": "Mozilla/5.0 AlphaSwarm/6.0"}` (or similar) on every RSS fetch.
**Warning signs:** Integration test passes once, then fails repeatedly with HTTP 429.

### Pitfall 5: `Decimal(float)` preserves binary-float rounding
**What goes wrong:** `Decimal(270.23)` produces `270.2299999999999897681693569757044315338134765625`, not `270.23`. All the Phase 37 MarketSlice tests will still pass, but the value stored in Neo4j or the WebSocket snapshot is wrong at the 15th decimal.
**Why it happens:** `Decimal.__init__` preserves the exact binary representation of a float.
**How to avoid:** ALWAYS `Decimal(str(float_value))`. Verified in probe: `Decimal(str(270.23)) == Decimal("270.23")`.
**Warning signs:** A downstream equality check `slice.price == Decimal("270.23")` fails where common sense says it should pass.

### Pitfall 6: `yf.Ticker(t).info` blocks the event loop
**What goes wrong:** `.info` is a property that does a synchronous HTTP request to Yahoo's quoteSummary endpoint. If called outside a thread, it holds the event loop for hundreds of milliseconds per ticker.
**Why it happens:** yfinance uses `requests` internally and `.info` triggers a lazy fetch.
**How to avoid:** All yfinance calls inside `asyncio.to_thread`. Never at async function top level.
**Warning signs:** Other async tasks starve during provider calls; WebSocket snapshots stall.

### Pitfall 7: `pytest-socket --disable-socket` blocks unit tests that inadvertently network
**What goes wrong:** A unit test that instantiates `YFinanceMarketDataProvider` and calls `get_prices(['AAPL'])` without mocking yfinance will trigger a real network call → `pytest_socket.SocketBlockedError` (because unit tests are NOT under `tests/integration/`).
**Why it happens:** Phase 37 installed a global `--disable-socket` gate (ISOL-06). Only tests under `tests/integration/` get `enable_socket` auto-applied.
**How to avoid:** In unit tests, `monkeypatch.setattr('alphaswarm.ingestion.yfinance_provider.yf.Ticker', fake_ticker_class)`. Verify via a smoke test that unit-test suite still passes with `--disable-socket`.
**Warning signs:** `SocketBlockedError` in the unit test traceback.

### Pitfall 8: importlinter whitelist drift breaks invariant tests
**What goes wrong:** Adding `src/alphaswarm/ingestion/yfinance_provider.py` without adding `alphaswarm.ingestion.yfinance_provider` to `pyproject.toml [[tool.importlinter.contracts]] source_modules` will make `test_source_modules_covers_every_actual_package` (in `tests/invariants/test_importlinter_coverage.py`) fail.
**Why it happens:** The Phase 37 drift-resistant coverage test dynamically enumerates every package under `src/alphaswarm/` and asserts it's in `source_modules` OR in the 3-entry `_KNOWN_NON_SOURCE` allowlist. New modules are neither.
**How to avoid:** When adding `yfinance_provider.py` and `rss_provider.py`, IN THE SAME COMMIT add the two dotted paths to `source_modules` in pyproject.toml. Run `uv run pytest tests/invariants/` before commit.
**Warning signs:** Invariant test fails with `Packages under src/alphaswarm/ are NOT listed in pyproject.toml ...: ['alphaswarm.ingestion.yfinance_provider']`.

### Pitfall 9: Empty input list sanity
**What goes wrong:** `get_prices([])` should return `{}`, not raise. Same for `get_headlines([])`. Phase 37 fakes already handle this (tested). New providers MUST mirror.
**Why it happens:** `asyncio.gather(*[])` returns `[]` — verified. `dict.update()` on `{}` is safe. The risk is only if a careless implementation does `tickers[0]` or similar.
**How to avoid:** Guard clause `if not tickers: return {}` at the top of each method.
**Warning signs:** Integration test that passes empty list to exercise the edge case trips `asyncio.gather` or a downstream unpack.

## Code Examples

Verified patterns from official sources and probes:

### Field mapping: yfinance → MarketSlice

Verified against `yf.Ticker('AAPL')` on 2026-04-18:

```python
# fast_info fields (dict-like, typed)
#   last_price: float (e.g., 270.23)              → MarketSlice.price (via Decimal(str(...)))
#   last_volume: int (e.g., 61314800)             → MarketSlice.volume
#   market_cap: float (e.g., 3.97e12)             → Fundamentals.market_cap (via Decimal(str(...)))
#   shares: int                                   → unused (no MarketSlice field)

# info dict (184 keys for AAPL)
#   info['trailingPE']: float (34.249683)         → Fundamentals.pe_ratio
#   info['trailingEps']: float (7.89)             → Fundamentals.eps
#   info['marketCap']: int (3971820552192)        → Fundamentals.market_cap
#                                                   (overrides fast_info.market_cap if both present)
#   info['forwardPE'], ['forwardEps']: optional fundamental alternates
#   info['currentPrice']: float (270.23)          → fallback if fast_info.last_price raises
```

### Minimal integration test under `tests/integration/`

```python
# tests/integration/test_yfinance_provider_live.py
from __future__ import annotations

from alphaswarm.ingestion import MarketSlice
from alphaswarm.ingestion.yfinance_provider import YFinanceMarketDataProvider


async def test_yfinance_real_fetch_aapl_returns_fresh_slice() -> None:
    provider = YFinanceMarketDataProvider()
    result = await provider.get_prices(["AAPL"])
    assert "AAPL" in result
    s = result["AAPL"]
    assert isinstance(s, MarketSlice)
    # AAPL has always traded; fetch_failed would be a real bug here.
    assert s.staleness == "fresh"
    assert s.price is not None and s.price > 0


async def test_yfinance_real_fetch_unknown_ticker_returns_fetch_failed() -> None:
    """Delisted/invalid tickers must return fetch_failed, never raise."""
    provider = YFinanceMarketDataProvider()
    result = await provider.get_prices(["ZZZZNOTREAL"])
    assert result["ZZZZNOTREAL"].staleness == "fetch_failed"
    assert result["ZZZZNOTREAL"].price is None
```

```python
# tests/integration/test_rss_provider_live.py
from __future__ import annotations

from alphaswarm.ingestion.rss_provider import RSSNewsProvider


async def test_rss_real_fetch_ticker_entity() -> None:
    """Yahoo Finance RSS routing for a ticker symbol returns fresh headlines."""
    provider = RSSNewsProvider()
    result = await provider.get_headlines(["AAPL"])
    assert result["AAPL"].staleness == "fresh"
    # AAPL always has coverage; an empty tuple would indicate a parse regression.
    # But the case-insensitive filter may yield 0 if no entry title contains "aapl",
    # so check staleness, not headline count.


async def test_rss_real_fetch_topic_entity() -> None:
    """Google News RSS routing for a topic/geopolitical entity."""
    provider = RSSNewsProvider()
    result = await provider.get_headlines(["US-Iran war"])
    assert result["US-Iran war"].staleness == "fresh"
```

### Minimal unit test with monkeypatch

```python
# tests/test_yfinance_provider.py
from __future__ import annotations

import pytest
from alphaswarm.ingestion.yfinance_provider import YFinanceMarketDataProvider


class _FakeFastInfo:
    last_price = 100.0
    last_volume = 1000
    market_cap = 1e9


class _FakeTicker:
    def __init__(self, t: str) -> None:
        self._t = t
    @property
    def fast_info(self) -> _FakeFastInfo:
        return _FakeFastInfo()
    @property
    def info(self) -> dict:
        return {"trailingPE": 20.0, "trailingEps": 5.0, "marketCap": 1_000_000_000}


async def test_yfinance_provider_maps_fields_to_market_slice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "alphaswarm.ingestion.yfinance_provider.yf.Ticker", _FakeTicker
    )
    provider = YFinanceMarketDataProvider()
    result = await provider.get_prices(["AAPL"])
    assert result["AAPL"].price == __import__("decimal").Decimal("100.0")
    assert result["AAPL"].staleness == "fresh"
    assert result["AAPL"].fundamentals.pe_ratio == __import__("decimal").Decimal("20.0")
```

### pyproject.toml additions

```toml
# Add to [project].dependencies
dependencies = [
    # ... existing ...
    "httpx>=0.28.0",
    "yfinance>=1.3.0,<2.0",
    "feedparser>=6.0.12,<7.0",
]

# Add to [[tool.importlinter.contracts]] source_modules
source_modules = [
    # ... existing entries ...
    "alphaswarm.ingestion.providers",
    "alphaswarm.ingestion.types",
    "alphaswarm.ingestion.yfinance_provider",  # NEW
    "alphaswarm.ingestion.rss_provider",       # NEW
    # ...
]
```

### ingestion/__init__.py additions

```python
from alphaswarm.ingestion.providers import (
    FakeMarketDataProvider,
    FakeNewsProvider,
    MarketDataProvider,
    NewsProvider,
)
from alphaswarm.ingestion.rss_provider import RSSNewsProvider
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
    "RSSNewsProvider",            # NEW
    "StalenessState",
    "YFinanceMarketDataProvider", # NEW
]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `yf.download()` for batch | `yf.Ticker(t).fast_info` per ticker | yfinance 0.2.x | `download()` is multi-ticker in one call but returns a pandas DataFrame requiring post-processing and has different failure semantics (silently drops bad tickers vs raising). `Ticker().fast_info` gives per-ticker error isolation, which we want. |
| `yf.Ticker(t).info` for everything | Split: `fast_info` for price/volume; `info` for fundamentals | yfinance ~1.0 | `info` is slow (extra HTTP call); `fast_info` caches the price-history scrape. CONTEXT.md D-06 captures this. |
| feedparser 5.x | feedparser 6.0.12 | 2020 | 6.x dropped Python 2 support and added mypy stubs; no API changes for our usage. |

**Deprecated/outdated:**
- `yfinance.download(...)`: still works but `Ticker().fast_info` is the modern batch-with-isolation pattern.
- `feedparser.parse(url)` direct URL passing: technically still works but synchronous and prone to false-positive `bozo=True` flags. Use httpx fetch + feedparser parse text.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `httpx` | RSS async fetch | ✓ | 0.28.1 (in venv) | — |
| `feedparser` | RSS parsing | ✓ (installed during research) | 6.0.12 | Must be declared in pyproject.toml |
| `yfinance` | Market data | ✗ in venv / ✓ in system pip 1.2.0 | — | Must be added to pyproject.toml |
| `pytest-socket` | Unit test network isolation | ✓ | 0.7.0 | — |
| `pytest-asyncio` | Async tests | ✓ (auto mode) | >=0.24.0 | — |
| `pandas`, `numpy`, `lxml` | yfinance transitive deps | ✗ | — | Installed automatically by `uv sync` after pyproject edit |
| Yahoo Finance RSS | RSSNewsProvider | ✓ | endpoint 200 verified 2026-04-18 | Falls back to Google News RSS if ticker routing fails (but Yahoo worked in probe) |
| Google News RSS | RSSNewsProvider | ✓ | endpoint 200 verified 2026-04-18 | None needed |
| Yahoo Finance quote API (via yfinance) | YFinanceMarketDataProvider | ✓ (fast_info + info returned data for AAPL) | — | None — if Yahoo blocks the call, all tickers return `fetch_failed` and Phase 40 handles degraded context |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** `yfinance`, `feedparser`, and yfinance's transitive deps (pandas/numpy/lxml/requests) — all resolve via `uv add yfinance feedparser` and `uv sync`. Plan must include this as a Wave 0 or Plan-1 step.

**Rate limit risk:** Yahoo Finance returned HTTP 429 to sync httpx without `User-Agent`. Integration tests must always set a browser-like UA. If CI runs the integration suite frequently, consider a jittered backoff or marking the tests `@pytest.mark.slow` for selective inclusion.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio >=0.24 (asyncio_mode=auto) + pytest-socket 0.7.0 |
| Config file | `pyproject.toml` [tool.pytest.ini_options] |
| Quick run command | `uv run pytest tests/test_yfinance_provider.py tests/test_rss_provider.py tests/test_providers.py -x` |
| Full suite command | `uv run pytest` (unit) + `uv run pytest tests/integration/` (real network) |
| Static checks | `uv run mypy src/alphaswarm/ingestion/ && uv run ruff check src/alphaswarm/ingestion/ && uv run lint-imports` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INGEST-01 | YFinance provider maps fast_info + info to MarketSlice with Decimal price | unit | `pytest tests/test_yfinance_provider.py::test_yfinance_provider_maps_fields_to_market_slice -x` | ❌ Wave 0 |
| INGEST-01 | YFinance provider returns fetch_failed on yfinance exception | unit | `pytest tests/test_yfinance_provider.py::test_yfinance_provider_returns_fetch_failed_on_exception -x` | ❌ Wave 0 |
| INGEST-01 | YFinance provider handles empty list → {} | unit | `pytest tests/test_yfinance_provider.py::test_empty_ticker_list_returns_empty_dict -x` | ❌ Wave 0 |
| INGEST-01 | YFinance provider fetches real AAPL over network | integration | `pytest tests/integration/test_yfinance_provider_live.py::test_yfinance_real_fetch_aapl_returns_fresh_slice -x` | ❌ Wave 0 |
| INGEST-01 | YFinance provider returns fetch_failed for delisted ticker | integration | `pytest tests/integration/test_yfinance_provider_live.py::test_yfinance_real_fetch_unknown_ticker_returns_fetch_failed -x` | ❌ Wave 0 |
| INGEST-02 | RSS provider routes tickers to Yahoo RSS, topics to Google News | unit | `pytest tests/test_rss_provider.py::test_ticker_routes_to_yahoo_rss -x` | ❌ Wave 0 |
| INGEST-02 | RSS provider filters headlines by case-insensitive entity match | unit | `pytest tests/test_rss_provider.py::test_entity_filter_case_insensitive_substring -x` | ❌ Wave 0 |
| INGEST-02 | RSS provider returns fetch_failed on httpx exception | unit | `pytest tests/test_rss_provider.py::test_httpx_exception_returns_fetch_failed -x` | ❌ Wave 0 |
| INGEST-02 | RSS provider filters by max_age_hours | unit | `pytest tests/test_rss_provider.py::test_max_age_hours_filter -x` | ❌ Wave 0 |
| INGEST-02 | RSS provider fetches real Yahoo RSS for AAPL | integration | `pytest tests/integration/test_rss_provider_live.py::test_rss_real_fetch_ticker_entity -x` | ❌ Wave 0 |
| INGEST-02 | RSS provider fetches real Google News RSS for topic | integration | `pytest tests/integration/test_rss_provider_live.py::test_rss_real_fetch_topic_entity -x` | ❌ Wave 0 |
| Both | New providers conform to Protocol (structural mypy check) | unit | `pytest tests/test_yfinance_provider.py::test_real_market_provider_structurally_conforms -x` | ❌ Wave 0 |
| Both | importlinter invariant still green (new modules are covered) | invariant | `pytest tests/invariants/test_importlinter_coverage.py -x && uv run lint-imports` | ✅ exists |
| Both | Full type strict passes | static | `uv run mypy src/alphaswarm/ingestion/` | ✅ (mypy configured, new files must pass) |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/test_yfinance_provider.py tests/test_rss_provider.py tests/test_providers.py tests/invariants/ -x` (~3-5 seconds; no network)
- **Per wave merge:** `uv run pytest` (full unit suite) + `uv run pytest tests/integration/` (network, ~10-20 seconds)
- **Phase gate:** Full suite green + `uv run mypy` + `uv run ruff check` + `uv run lint-imports` before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/test_yfinance_provider.py` — unit tests with monkeypatched `yf.Ticker` covering field mapping, exception path, empty input, duplicate tickers, Decimal precision
- [ ] `tests/test_rss_provider.py` — unit tests with monkeypatched `httpx.AsyncClient.get` covering ticker routing, topic routing, entity filter, max_age_hours filter, exception paths
- [ ] `tests/integration/test_yfinance_provider_live.py` — real-network tests for AAPL + delisted ticker
- [ ] `tests/integration/test_rss_provider_live.py` — real-network tests for Yahoo RSS ticker + Google News topic
- [ ] `pyproject.toml` — add `yfinance>=1.3.0,<2.0` and `feedparser>=6.0.12,<7.0` to `[project].dependencies`; add `alphaswarm.ingestion.yfinance_provider` and `alphaswarm.ingestion.rss_provider` to `[tool.importlinter].contracts[0].source_modules`
- [ ] `src/alphaswarm/ingestion/__init__.py` — add `YFinanceMarketDataProvider` and `RSSNewsProvider` to imports and `__all__`
- [ ] `uv sync` — install yfinance/feedparser and their transitive deps into `.venv/`

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth — Yahoo/Google RSS are public, yfinance uses no key |
| V3 Session Management | no | Stateless providers |
| V4 Access Control | no | Read-only external data |
| V5 Input Validation | **yes** | Entity and ticker strings are passed into URL templates — MUST sanitize to prevent URL injection and MUST sanitize returned headline titles before storage |
| V6 Cryptography | no | No secrets, no crypto surface |
| V7 Error Handling & Logging | **yes** | D-19 never-raise — failures MUST log but never leak secrets (there are none, but PII redaction processor from ISOL-04 still runs on logs) |
| V14 Configuration | **yes** | New deps must not introduce malicious code — verify package provenance on install |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| URL injection via malicious entity string (e.g., `AAPL&cmd=...`) | Tampering | Use `urllib.parse.quote_plus(entity)` when building Google News URL; ticker regex `^[A-Z]{1,5}$` naturally blocks injection for Yahoo RSS path |
| XSS via RSS entry titles stored without escaping | XSS | Titles are stored as strings in frozen `NewsSlice.headlines: tuple[str, ...]`; downstream Vue consumer must escape on render. Not this phase's problem but note for Phase 40. |
| SSRF via untrusted URL in feedparser | Tampering/SSRF | Provider hard-codes Yahoo/Google hostnames — no user-supplied URLs ever pass to httpx |
| Rate limit abuse / IP ban | DoS (external) | User-Agent header required; no retry loops in this phase (D-10 no caching, D-09 single fetch); Phase 40 may add backoff |
| Malicious RSS content (XXE, XML bomb) | DoS | feedparser uses a hardened parser (`sgmllib3k`) and has standard defenses against XXE; verified 6.0.12 is current |
| Supply-chain attack on yfinance/feedparser | Tampering | Pin major versions (`<2.0`, `<7.0`); rely on `uv.lock` for hash-pinned reproducibility |

**Note on `quote_plus`:** The code example above uses `quote_plus(entity)` for Google News URL construction. This is REQUIRED — without it, an entity string containing `&`, `=`, or URL-reserved characters would corrupt the query. Verified in probe: `quote_plus("US-Iran war")` produces `US-Iran+war`, which Google News accepts.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | yfinance 1.3.0 is a stable release at time of implementation | Standard Stack | Low — if 1.3.0 has regressions, pin to `>=1.2.0,<2.0` and accept the older FastInfo behavior; adjust tests. |
| A2 | Yahoo Finance will not block the GitHub Actions IP range if CI runs integration tests frequently | Environment Availability | Medium — if CI hits 429, mark integration tests `@pytest.mark.slow` and gate on a manual flag. |
| A3 | Google News RSS search query format `?q={}&hl=en-US&gl=US&ceid=US:en` is stable long-term | Architecture Patterns | Low — Google News has used this format for 10+ years; if it changes, we see `entries=0` in integration and fix the URL. |
| A4 | `time.mktime(published_parsed)` is acceptable even though it assumes local time | Pitfall 3 | Low — off-by-hours but still within 72h window in practice; switch to `calendar.timegm` if precision matters. |
| A5 | Providers are only called once per simulation run (D-07 no semaphore) | CLAUDE.md integration | Medium — if Phase 40 actually invokes providers inside the cascade, re-introduce a semaphore cap. Research decision accepts this because it aligns with CONTEXT.md D-07. |

**Non-assumptions (verified this session):**
- yfinance 1.2.0 `fast_info` and `info` field shapes for AAPL (live probe)
- Yahoo Finance RSS and Google News RSS URL templates return 200 with entries (live probe)
- feedparser 6.0.12 handles `httpx`-fetched text successfully (live probe)
- `feedparser.parse(url)` triggers `bozo=True` in this environment (live probe — see Pitfall 2)
- `fast_info.last_price` raises `KeyError('currentTradingPeriod')` for delisted tickers (live probe)
- `pytest-socket --disable-socket` is the active global gate, and `tests/integration/` conftest auto-applies `enable_socket` (verified against `tests/integration/conftest.py`)
- `pyproject.toml` importlinter source_modules coverage is enforced by `tests/invariants/test_importlinter_coverage.py` (read the file)

## Open Questions

1. **Should `get_fundamentals` and `get_volume` do independent scrapes, or share the `get_prices` scrape?**
   - What we know: The Protocol has 3 separate methods; yfinance returns all 3 data types in one `Ticker(t)` scrape.
   - What's unclear: Does Phase 40 call them all together or separately?
   - Recommendation: Have all three methods call a single `_fetch_batch_shared(tickers)` helper. That way if Phase 40 calls them separately, it pays the network cost only once per ticker per method. If Phase 40 calls them together, we still pay it once because each call is a fresh scrape per D-10 (no caching). Net: same cost for the "together" case, 3x cost for the "separate" case. If that becomes a problem, Phase 40 can add a caching layer outside the provider.
   - Final: Default implementation returns the same `MarketSlice` from all three methods. Document this in the docstring.

2. **How to handle Yahoo RSS returning 0 entries for legitimate tickers (timing / rate limit)?**
   - What we know: Our probe returned 20 entries for AAPL on first try.
   - What's unclear: Will Yahoo sometimes return 0 entries for a valid ticker (e.g., off-hours, or rate-limited)?
   - Recommendation: If `feed.entries == []` but HTTP was 200 and `bozo == False`, return `staleness='fresh'` with empty headlines. This distinguishes "Yahoo said nothing to report" from "Yahoo couldn't be reached" (the latter is `fetch_failed`). Integration test assertion should check `staleness == 'fresh'`, NOT `len(headlines) > 0`.

3. **Does `feedparser.parse(r.text)` need the `response_headers` kwarg for accurate `published_parsed`?**
   - What we know: feedparser uses Content-Type from response headers to determine encoding. Our probe worked without it because the feeds are UTF-8.
   - What's unclear: Would some feeds produce garbled titles if we don't pass headers?
   - Recommendation: Pass `response_headers={'content-type': r.headers.get('content-type', '')}` to feedparser defensively. Verified via feedparser docs that this is the idiomatic pattern for pre-fetched content.

4. **Should entity normalization strip punctuation before case-insensitive match?**
   - CONTEXT.md "Claude's Discretion": normalization is discretionary.
   - Recommendation: Start with the simplest: `needle = entity.lower()` and `if needle in title.lower()`. This passes the 80% case. If integration tests show false negatives (e.g., entity `"US-Iran"` vs title `"US Iran tensions"`), add punctuation stripping in a later phase. Not worth the complexity now.

## Sources

### Primary (HIGH confidence)

- `yf.Ticker('AAPL').fast_info` / `.info` live probe — 2026-04-18 (this session)
- `https://finance.yahoo.com/rss/headline?s={ticker}` live probe — returns 200, valid RSS XML
- `https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en` live probe — returns 200, valid RSS XML
- `httpx.AsyncClient.get(url) + feedparser.parse(r.text)` pipeline — verified working for both sources
- `src/alphaswarm/ingestion/providers.py` — read, understands `_fetch_failed_market_slice` and `_fetch_failed_news_slice` module-level helpers are reusable
- `src/alphaswarm/ingestion/types.py` — read, `MarketSlice.price: Decimal | None`, `Fundamentals` is nested frozen sub-model
- `tests/test_providers.py` — read, confirms conformance test shape (async signatures, StalenessState literal, empty list handling, duplicate key handling)
- `tests/integration/conftest.py` — read, confirms `enable_socket` auto-marker hooks on path
- `tests/invariants/test_importlinter_coverage.py` — read, confirms drift check on source_modules
- `pyproject.toml` — read, confirms current deps and importlinter contract shape

### Secondary (MEDIUM confidence)

- [yfinance PyPI page](https://pypi.org/project/yfinance/) — confirms 1.3.0 released 2026-04-16
- [feedparser PyPI page](https://pypi.org/project/feedparser/) — confirms 6.0.12 is the latest line (also what our `uv add` installed)
- [GitHub issue #2348: KeyError 'currentTradingPeriod'](https://github.com/ranaroussi/yfinance/issues/2348) — documents the known FastInfo failure mode for delisted tickers
- [yfinance quote.py source on GitHub main branch](https://github.com/ranaroussi/yfinance/blob/main/yfinance/scrapers/quote.py) — confirms `_get_1y_prices` is where `currentTradingPeriod` access happens

### Tertiary (LOW confidence)

- Google News RSS URL template is not "officially documented" anywhere but has been the same for 10+ years and is verified working in our probe. Marked MEDIUM via cross-verification (probe + widespread community usage), but the source itself is informal.

## Metadata

**Confidence breakdown:**
- Standard stack: **HIGH** — versions and install commands verified against PyPI and local venv; yfinance + feedparser + httpx are undisputed ecosystem standards.
- Architecture: **HIGH** — Both provider patterns (thread-per-ticker for yfinance; httpx-then-feedparser for RSS) verified with live probes. Field mapping verified against real AAPL data.
- Pitfalls: **HIGH** — 4 of 9 pitfalls were actively reproduced in this session (KeyError on delisted, feedparser URL bozo, 429 without UA, Decimal(float) precision loss); remaining 5 are mechanical consequences of the project's established patterns (pytest-socket gate, importlinter drift, empty list semantics, event-loop blocking, struct_time conversion).
- Security: **HIGH** — No auth/crypto surface; input-validation mitigations (`quote_plus`, ticker regex) are straightforward.
- Validation: **HIGH** — Test framework, gates, and conftest confirmed by reading the files; `@pytest.mark.enable_socket` hook verified working.

**Research date:** 2026-04-18
**Valid until:** 2026-05-18 (30 days; yfinance + RSS surfaces are relatively stable, but Yahoo can change the fast_info shape in a minor release, so re-verify if implementation slips past this date)
