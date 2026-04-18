# Phase 38: Market Data + News Providers - Context

**Gathered:** 2026-04-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Implement real `YFinanceMarketDataProvider` and `RSSNewsProvider` against the Phase 37 Protocol contracts. Both providers must be async, never raise (D-19), use `StalenessState` typing, and have integration tests using `tests/integration/` with `enable_socket`. No simulation wiring — that is Phase 40.

</domain>

<decisions>
## Implementation Decisions

### News Provider Backend
- **D-01:** Use RSS-based news provider (`RSSNewsProvider`) — free, no API key, no rate limits
- **D-02:** Dual-source routing per entity type:
  - Ticker symbols (uppercase, 1–5 chars): Yahoo Finance RSS — `https://finance.yahoo.com/rss/headline?s={ticker}`
  - Topic/geopolitical entities (everything else): Google News RSS — `https://news.google.com/rss/search?q={entity}&hl=en-US&gl=US&ceid=US:en`
- **D-03:** Entity filtering: case-insensitive keyword match of entity string against returned headline titles
- **D-04:** `feedparser` as the RSS parsing library; `httpx` (already a dep) for async HTTP fetch of feed content

### YFinance Async Wrapping
- **D-05:** `asyncio.to_thread` per ticker + `asyncio.gather` across all tickers in a batch — per-ticker error isolation ensures one bad ticker returns a `fetch_failed` slice without killing the batch
- **D-06:** `yf.Ticker(t).fast_info` for price and volume fields; `yf.Ticker(t).info` for fundamentals (pe_ratio, eps, market_cap)
- **D-07:** No semaphore cap — providers are called once per simulation run (pre-cascade context assembly in Phase 40), not inside the 100-agent governor loop
- **D-08:** Add `yfinance` to `pyproject.toml` production dependencies; add `feedparser` as well

### Staleness Thresholds
- **D-09:** `fresh` on any successful fetch; `fetch_failed` on any exception — no time-window staleness logic
- **D-10:** Providers never cache slices between calls; each invocation fetches fresh data from the network

### Testing Strategy
- **D-11:** Unit tests use `FakeMarketDataProvider` and `FakeNewsProvider` from Phase 37 — no new fakes needed
- **D-12:** Integration tests in `tests/integration/` hit real network under `enable_socket` auto-marker; one test per provider verifying real data returns a non-empty `dict[str, MarketSlice/NewsSlice]` with `staleness='fresh'`

### Claude's Discretion
- Exact `max_age_hours` filtering logic inside `RSSNewsProvider.get_headlines` (compare `published_parsed` entry timestamp)
- How to normalize Google News RSS feed entry titles for entity matching (strip punctuation, lowercase)
- Whether `yf.Ticker(t).info` call is wrapped in its own try/except inside the per-ticker thread (it should be, per D-19)
- File layout: `src/alphaswarm/ingestion/yfinance_provider.py` and `src/alphaswarm/ingestion/rss_provider.py` vs single `real_providers.py`

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Protocol contracts (Phase 37 outputs)
- `src/alphaswarm/ingestion/providers.py` — `MarketDataProvider` and `NewsProvider` Protocol definitions, `FakeMarketDataProvider`, `FakeNewsProvider`, D-19 never-raise contract
- `src/alphaswarm/ingestion/types.py` — `MarketSlice`, `NewsSlice`, `ContextPacket`, `Fundamentals`, `StalenessState` frozen pydantic types

### Requirements
- `.planning/REQUIREMENTS.md` §INGEST-01, §INGEST-02 — acceptance criteria for Phase 38

### Test infrastructure
- `tests/integration/conftest.py` — auto-applies `enable_socket` marker by path; integration tests must live under `tests/integration/`
- `tests/test_providers.py` — existing conformance tests; Phase 38 real providers must pass the same structural checks

### Importlinter contract
- `pyproject.toml` §[tool.importlinter] — forbidden contract; new provider modules under `alphaswarm.ingestion` must NOT import `alphaswarm.holdings`; run `uv run lint-imports` after adding files

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `FakeMarketDataProvider` / `FakeNewsProvider` (`ingestion/providers.py`): unit test fakes already wired — real providers don't need new fakes
- `_fetch_failed_market_slice` / `_fetch_failed_news_slice` helpers (`ingestion/providers.py`): reuse these in real provider error paths to ensure consistent `fetch_failed` slice construction
- `httpx` is already a production dependency — can be used for async RSS feed fetching if needed

### Established Patterns
- `asyncio_mode = "auto"` project-wide — async test functions need no `@pytest.mark.asyncio` decorator
- `pytest-socket` global `--disable-socket` gate — integration tests must be under `tests/integration/` to get `enable_socket` applied automatically
- `StalenessState` must be a typed Literal value, not a bare string (existing tests assert `get_args(StalenessState)`)

### Integration Points
- `alphaswarm.ingestion.__init__` re-exports all provider types — new real provider classes must be added to `__init__.py` exports and `__all__`
- `pyproject.toml [tool.importlinter]` `source_modules` whitelist — new `alphaswarm.ingestion.*` submodules must be added to the whitelist or the drift-resistant coverage test (`test_importlinter_coverage.py`) will fail

</code_context>

<specifics>
## Specific Ideas

- News feeds must be dynamic per entity — a hardcoded list of financial feeds would not work for seed rumors spanning geopolitics (e.g., "US-Iran war") vs industry topics (e.g., "EV battery supply chain"). The dual-source routing (Google News for topics, Yahoo Finance for tickers) solves this.
- yfinance wrapping: per-ticker `asyncio.to_thread` + `asyncio.gather` chosen specifically for error isolation — one delisted/unknown ticker must not fail the whole batch. This mirrors how `FakeMarketDataProvider._resolve` handles unknown tickers silently.

</specifics>

<deferred>
## Deferred Ideas

- RSS feed caching / TTL cache between simulation runs — not needed until Phase 40 shows repeated provider calls per session
- Staleness time-window logic (marking slices stale after N hours) — deferred; would only add value if providers are cached across runs
- NewsAPI fallback for sparse RSS coverage — deferred; RSS is sufficient for the expected seed entity types (major tickers, sector topics, geopolitical events via Google News)

</deferred>

---

*Phase: 38-market-data-news-providers*
*Context gathered: 2026-04-18*
