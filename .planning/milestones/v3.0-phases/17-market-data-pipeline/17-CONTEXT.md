# Phase 17: Market Data Pipeline - Context

**Gathered:** 2026-04-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Before Round 1 begins, the system fetches and disk-caches live market data (90-day price history, full financial fundamentals) for every ticker in `SeedEvent.tickers`. The output is a `MarketDataSnapshot` per ticker, stored in memory and persisted as `Ticker` nodes in Neo4j, available for downstream consumption by Phase 18 prompt enrichment. News headlines (DATA-03) are explicitly deferred to Phase 18. No agent prompt changes in this phase.

</domain>

<decisions>
## Implementation Decisions

### Market Data Shape
- **D-01:** Price history window is **90 days of daily OHLCV** (open, high, low, close, volume). This covers full earnings cycles and medium-term trends. yfinance `Ticker.history(period="3mo")`.
- **D-02:** Financial fundamentals fetched: P/E ratio, market cap, 52-week high/low, EPS trailing, revenue TTM, gross margin %, debt/equity ratio, earnings surprise %, next earnings date. Use the maximum available from yfinance `Ticker.info` + `Ticker.earnings_dates`. Goal: "everything that helps accuracy."
- **D-03:** A new `MarketDataSnapshot` Pydantic model in `types.py` holds all fields. Optional fields (e.g., `next_earnings_date`) use `Optional[...]` with `None` defaults. Frozen model, same pattern as `SeedEvent`.
- **D-04:** News headlines are **deferred to Phase 18**. DATA-03 compliance is achieved in Phase 18 when the prompt template is designed and token budget is enforced. Phase 17 ships price + fundamentals only.

### Fetch Architecture
- **D-05:** New module `src/alphaswarm/market_data.py` owns all fetching logic. Does not live in `seed.py` or `simulation.py` — it is a standalone data layer called from `run_simulation()` before `run_round1()`.
- **D-06:** yfinance is **not async-native** — all calls wrapped in `asyncio.to_thread()`. Per-ticker lock (`asyncio.Lock`) prevents concurrent writes to the same cache file. Tickers are fetched in parallel (one coroutine per ticker, `asyncio.TaskGroup` pattern consistent with Phase 3/7).
- **D-07:** Integration point: `run_simulation()` in `simulation.py` calls `fetch_market_data(tickers)` after seed injection completes and before `run_round1()`. The resulting `dict[str, MarketDataSnapshot]` is threaded through the simulation pipeline as a parameter.
- **D-08:** Alpha Vantage is the **fallback when yfinance fails** for a ticker. `ALPHA_VANTAGE_API_KEY` loaded via pydantic-settings from `.env`. If key is absent, AV is skipped entirely — no error. If both fail, simulation continues with a degraded `MarketDataSnapshot` (all financial fields `None`, price history empty list) and a `structlog` warning.

### Disk Cache
- **D-09:** Cache location: `data/market_cache/`. One JSON file per ticker: `data/market_cache/{SYMBOL}.json`. Consistent with `data/sec_tickers.json` from Phase 16.
- **D-10:** Cache TTL: **1 hour**. On fetch, read `cached_at` ISO timestamp from the JSON file. If age > 3600 seconds, re-fetch. If within TTL, return cached data. Cache-hit logged at INFO level (structlog, component="market_data"), visible to user per SUCCESS CRITERION 4.
- **D-11:** Cache file written with `aiofiles` (already a dependency) using atomic write (temp file + rename), same pattern as `ticker_validator.py`.

### Neo4j Ticker Nodes
- **D-12:** Phase 17 creates `Ticker` nodes in Neo4j (`symbol`, `company_name`) linked to the `Cycle` node via a `HAS_TICKER` relationship. Market data is attached as a `MarketDataSnapshot` node linked from `Ticker` via `HAS_MARKET_DATA`. This makes market data queryable for the Phase 20 report.
- **D-13:** Neo4j writes happen after successful fetch (or degraded fetch). Partial data (some fields None) is still persisted — the node schema uses nullable properties. Graph writes use the existing session-per-method + UNWIND pattern from `graph.py`.
- **D-14:** `graph.py` gains a new method `create_ticker_with_market_data(cycle_id, snapshots)` following the `create_cycle_with_seed_event()` template.

### Graceful Degradation
- **D-15:** If yfinance fails → try Alpha Vantage (if key configured) → if both fail → emit `market_data_fetch_failed` structlog warning with `ticker` and `reason` fields → store empty `MarketDataSnapshot(symbol=..., price_history=[], financials=None, ...)`. Simulation never aborts due to market data failure.
- **D-16:** Per SUCCESS CRITERION 2: the user sees a visible warning in CLI output when degraded data is used (extend `_print_injection_summary()` or add a pre-simulation status line).

### Alpha Vantage Integration
- **D-17:** `ALPHA_VANTAGE_API_KEY` added to the pydantic-settings `Settings` model (`config.py`) as `Optional[str] = None`. If `None`, AV client is not instantiated. If set, AV is used as ticker-level fallback. Uses `httpx.AsyncClient` (already a dependency) for AV REST calls.
- **D-18:** AV endpoints used for fallback: `GLOBAL_QUOTE` (price/volume) + `OVERVIEW` (financials). `NEWS_SENTIMENT` is NOT used in Phase 17 (news deferred to Phase 18).

### Claude's Discretion
- Exact `MarketDataSnapshot` field names (follow Python snake_case convention, match yfinance attribute names where possible)
- Whether `price_history` is stored as list of dicts or a compact summary (last close, % change 30d/90d, volume avg) to reduce serialization size
- Whether AV `OVERVIEW` covers all requested fundamentals or fallback is price-only
- Test fixture approach for yfinance (mock `asyncio.to_thread` or use VCR cassettes)
- Whether the `Ticker` node MERGE pattern uses `symbol` as the unique key (recommended)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/REQUIREMENTS.md` — DATA-01 (yfinance), DATA-02 (AV fallback + graceful degradation), DATA-03 (news headlines — NOTE: deferred to Phase 18), DATA-04 (disk cache TTL)
- `.planning/ROADMAP.md` — Phase 17 success criteria (4 criteria)

### Phase 16 Output (Primary — this phase consumes it)
- `src/alphaswarm/ticker_validator.py` — SEC validation, `ensure_sec_data()`, `get_ticker_validator()` — pattern for async + httpx + aiofiles data file management
- `src/alphaswarm/types.py` — `ExtractedTicker` (lines 88-95), `SeedEvent.tickers` (line 101), `ParsedSeedResult` — these are the inputs to Phase 17
- `.planning/phases/16-ticker-extraction/16-CONTEXT.md` — D-09 (Ticker nodes deferred to Phase 17), D-06/D-08 (SEC file pattern to mirror)

### Simulation Entry Point (Integration)
- `src/alphaswarm/simulation.py` — `run_simulation()` (line 718) — add market data fetch call here, before `run_round1()` at line ~763
- `src/alphaswarm/cli.py` — `_print_injection_summary()` (lines 65-107) — extend with degraded data warning display

### Graph Layer (Neo4j writes)
- `src/alphaswarm/graph.py` — `create_cycle_with_seed_event()` (lines 175-221) — template for new `create_ticker_with_market_data()` method; session-per-method + UNWIND pattern

### Config
- `src/alphaswarm/config.py` — pydantic-settings `Settings` model — add `ALPHA_VANTAGE_API_KEY: Optional[str] = None`

### Infrastructure Patterns (to mirror)
- `src/alphaswarm/batch_dispatcher.py` — `asyncio.TaskGroup` parallel dispatch pattern
- `src/alphaswarm/ticker_validator.py` — atomic write (temp + rename), aiofiles, structlog component logger

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ticker_validator.py:_download_sec_tickers()` — atomic write (tmp + rename) with `aiofiles`-adjacent `httpx` pattern; `market_data.py` cache writes mirror this
- `ticker_validator.py:get_ticker_validator()` — module-level lazy-load cache pattern; market data cache uses TTL-aware file check instead of module variable
- `batch_dispatcher.py` — `asyncio.TaskGroup` for parallel coroutines; fetch_market_data uses same pattern for per-ticker parallel fetches
- `config.py` — pydantic-settings `Settings`; add `ALPHA_VANTAGE_API_KEY: Optional[str] = None`
- `graph.py:create_cycle_with_seed_event()` — MERGE Cypher + session-per-method + UNWIND; `create_ticker_with_market_data()` follows this template exactly

### Established Patterns
- All orchestrator/external calls: `asyncio.to_thread()` for blocking libs (yfinance), `httpx.AsyncClient` for REST (Alpha Vantage)
- Pydantic frozen models for all data types (`MarketDataSnapshot` follows `SeedEvent` / `ExtractedTicker` shape)
- `structlog` component-scoped logger: `logger = structlog.get_logger(component="market_data")`
- Graceful degradation: emit warning, continue simulation — never abort (per governor, ticker_validator patterns)
- `aiofiles` for all file I/O in async context

### Integration Points
- `simulation.py:run_simulation()` (line 718) — call `fetch_market_data(tickers: list[ExtractedTicker]) -> dict[str, MarketDataSnapshot]` between seed injection and `run_round1()`
- `types.py` — add `MarketDataSnapshot` model
- `config.py` — add `ALPHA_VANTAGE_API_KEY` field
- `graph.py` — add `create_ticker_with_market_data(cycle_id, snapshots)` method
- `cli.py:_print_injection_summary()` — add degraded-data warning section
- New file: `src/alphaswarm/market_data.py` — fetcher, cache reader/writer, AV fallback client

</code_context>

<specifics>
## Specific Ideas

- Data goal is "everything that helps accuracy" — fetch the maximum available from yfinance `.info` dict (P/E, market cap, 52w range, EPS, revenue, gross margin, D/E, earnings surprise, next earnings date). Store all fields; Phase 18 selects which to inject per bracket.
- 90-day OHLCV covers a full earnings cycle — gives Quants trend context, Macro agents sector rotation signal, Insiders the pre/post-earnings move.
- Cache file naming: `{SYMBOL}_{YYYYMMDD_HH}.json` or just `{SYMBOL}.json` with `cached_at` inside the JSON — the latter is cleaner and avoids file accumulation.
- Alpha Vantage `GLOBAL_QUOTE` covers current price/volume. `OVERVIEW` covers PE ratio, market cap, 52w range, EPS, revenue, gross margin — close overlap with yfinance `.info`. If AV key exists, it fills gaps where yfinance `.info` returns None.
- News deferred to Phase 18: the `MarketDataSnapshot` model should reserve a `headlines: list[str]` field (empty list default) so Phase 18 can populate it without changing the type contract.

</specifics>

<deferred>
## Deferred Ideas

- **DATA-03 news headlines** — 10 headlines per ticker, deferred to Phase 18 when prompt engineering is done. `MarketDataSnapshot.headlines` field reserved but empty in Phase 17.
- **Cache expiry cleanup** — old cache files older than N days are not cleaned up in Phase 17. Could add a `setup-data --clean-cache` subcommand in a future phase.
- **Multi-day cache invalidation** — current TTL is 1 hour (re-fetches within a session after 1h). A 24-hour trading-day TTL with smart market-hours awareness (don't re-fetch during off-hours) is a future improvement.
- **Ticker node `MENTIONS` edges to Entity nodes** — Phase 16 deferred this as a graph enrichment. Could be added in Phase 17 alongside `Ticker` node creation, but keep out of scope to stay focused on data pipeline.
- **AV NEWS_SENTIMENT endpoint** — deferred with news headlines to Phase 18.
- **RAG knowledge base** — deferred to v3.1 per PROJECT.md.

</deferred>

---

*Phase: 17-market-data-pipeline*
*Context gathered: 2026-04-06*
