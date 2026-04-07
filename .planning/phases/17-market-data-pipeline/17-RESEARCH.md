# Phase 17: Market Data Pipeline - Research

**Researched:** 2026-04-06
**Domain:** Async market data fetching (yfinance + Alpha Vantage), disk caching, Neo4j graph enrichment
**Confidence:** HIGH

## Summary

Phase 17 builds a standalone data layer (`market_data.py`) that fetches 90-day OHLCV price history and financial fundamentals for each ticker in `SeedEvent.tickers` before Round 1 begins. The primary source is yfinance (unofficial Yahoo Finance scraper), with Alpha Vantage REST API as a per-ticker fallback. All data is cached to disk with 1-hour TTL and persisted as `Ticker`/`MarketDataSnapshot` nodes in Neo4j.

The core technical challenge is that yfinance is **not async-native and not thread-safe** -- it uses `requests` internally and has a known concurrency bug where shared global state can be overwritten during concurrent calls to the same ticker. The mitigation is `asyncio.to_thread()` with per-ticker `asyncio.Lock` objects to serialize access to the same symbol. Alpha Vantage is simpler -- it's a REST API consumed via `httpx.AsyncClient` (already a transitive dependency), but the free tier is severely limited at 25 calls/day and 5 calls/minute.

News headlines (DATA-03) are explicitly deferred to Phase 18 per user decision D-04. The `MarketDataSnapshot` model reserves a `headlines: list[str]` field with empty default so Phase 18 can populate it without changing the type contract.

**Primary recommendation:** Build `market_data.py` as a standalone async module following the `ticker_validator.py` pattern (structlog component logger, atomic cache writes, graceful degradation). Use `asyncio.TaskGroup` for parallel per-ticker fetching with per-symbol locks to avoid yfinance concurrency issues.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Price history window is 90 days of daily OHLCV. yfinance `Ticker.history(period="3mo")`.
- **D-02:** Financial fundamentals: P/E ratio, market cap, 52-week high/low, EPS trailing, revenue TTM, gross margin %, debt/equity ratio, earnings surprise %, next earnings date. Use max available from yfinance `.info` + `.earnings_dates`.
- **D-03:** New `MarketDataSnapshot` Pydantic model in `types.py`. Optional fields with `None` defaults. Frozen model.
- **D-04:** News headlines deferred to Phase 18. Phase 17 ships price + fundamentals only.
- **D-05:** New module `src/alphaswarm/market_data.py`. Standalone data layer called from `run_simulation()`.
- **D-06:** yfinance wrapped in `asyncio.to_thread()`. Per-ticker `asyncio.Lock`. Parallel fetch via `asyncio.TaskGroup`.
- **D-07:** Integration point: `run_simulation()` calls `fetch_market_data(tickers)` after seed injection, before `run_round1()`.
- **D-08:** Alpha Vantage fallback when yfinance fails. `ALPHA_VANTAGE_API_KEY` via pydantic-settings. If key absent, AV skipped.
- **D-09:** Cache at `data/market_cache/{SYMBOL}.json` with `cached_at` ISO timestamp.
- **D-10:** Cache TTL: 1 hour (3600 seconds). Cache-hit logged at INFO level.
- **D-11:** Atomic write via aiofiles (temp file + rename), same pattern as `ticker_validator.py`.
- **D-12:** `Ticker` nodes in Neo4j linked to `Cycle` via `HAS_TICKER`, `MarketDataSnapshot` linked from `Ticker` via `HAS_MARKET_DATA`.
- **D-13:** Neo4j writes after fetch. Nullable properties for partial data. UNWIND pattern from `graph.py`.
- **D-14:** `graph.py` gains `create_ticker_with_market_data(cycle_id, snapshots)`.
- **D-15:** Graceful degradation: yfinance fail -> try AV -> both fail -> structlog warning + empty snapshot. Never abort.
- **D-16:** Visible CLI warning for degraded data (extend `_print_injection_summary()` or add pre-simulation status line).
- **D-17:** `ALPHA_VANTAGE_API_KEY` added to `AppSettings` as `Optional[str] = None`. Uses `httpx.AsyncClient`.
- **D-18:** AV endpoints: `GLOBAL_QUOTE` (price/volume) + `OVERVIEW` (financials). `NEWS_SENTIMENT` NOT used in Phase 17.

### Claude's Discretion
- Exact `MarketDataSnapshot` field names (follow Python snake_case, match yfinance attribute names where possible)
- Whether `price_history` is stored as list of dicts or a compact summary
- Whether AV `OVERVIEW` covers all requested fundamentals or fallback is price-only
- Test fixture approach for yfinance (mock `asyncio.to_thread` or use VCR cassettes)
- Whether the `Ticker` node MERGE pattern uses `symbol` as the unique key

### Deferred Ideas (OUT OF SCOPE)
- DATA-03 news headlines (deferred to Phase 18)
- Cache expiry cleanup (old files)
- Multi-day/market-hours-aware cache TTL
- Ticker node `MENTIONS` edges to Entity nodes
- AV `NEWS_SENTIMENT` endpoint
- RAG knowledge base (v3.1)

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DATA-01 | Fetch live price history, financials, and earnings data per ticker via async-wrapped yfinance | yfinance 1.2.0 verified installed; `.history(period="3mo")` returns DataFrame with OHLCV columns; `.info` dict contains all target financial fields; `.earnings_dates` returns DataFrame with EPS Estimate, Reported EPS, Surprise(%); must wrap in `asyncio.to_thread()` with per-ticker locks |
| DATA-02 | Fall back to Alpha Vantage when yfinance fails, graceful degradation if both fail | AV `GLOBAL_QUOTE` provides current price/volume/change; AV `OVERVIEW` provides PE, market cap, 52w range, EPS, revenue, gross profit, profit margin; free tier: 25 calls/day, 5/min; httpx 0.28.1 available as transitive dep |
| DATA-03 | Recent news headlines per ticker (5-10 headlines) | **DEFERRED to Phase 18** per D-04. `MarketDataSnapshot.headlines` reserved as `list[str]` with empty default |
| DATA-04 | Disk cache with TTL to avoid rate limit exhaustion on re-runs | Cache at `data/market_cache/{SYMBOL}.json` with `cached_at` ISO timestamp; 1-hour TTL; atomic write pattern from `ticker_validator.py`; aiofiles 25.1.0 available |

</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| yfinance | 1.2.0 | Price history, financial fundamentals, earnings dates | User-locked decision. Most widely used free Yahoo Finance API wrapper. Already installed on system Python (NOT in project venv -- must be added to pyproject.toml) |
| httpx | 0.28.1 | Alpha Vantage REST API calls | Already a transitive dep of ollama. `AsyncClient` used in `ticker_validator.py`. Consistent with project patterns |
| aiofiles | 25.1.0 | Async file I/O for cache writes | Already a direct dependency in pyproject.toml. Used in `report.py` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pydantic | 2.12.5 | `MarketDataSnapshot` frozen model | All data types in this project use frozen Pydantic models |
| structlog | 25.5.0 | Component-scoped logging (`component="market_data"`) | Existing project convention |
| neo4j | 5.28.x | Async driver for Ticker/MarketDataSnapshot graph writes | Existing graph layer |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| yfinance | yahooquery | yahooquery is more stable but less widely documented; user locked yfinance |
| yfinance DataFrame output | Store raw pandas DataFrame | Too heavy for JSON cache; convert to list of dicts |
| aiofiles for cache | synchronous Path.write_text in to_thread | aiofiles is already a dep and consistent with D-11 |

**Installation:**
```bash
uv add yfinance>=1.2.0
```

**Version verification:** yfinance 1.2.0 is the latest release (Feb 2026). httpx 0.28.1 is current (transitive dep). aiofiles 25.1.0 is current (already in pyproject.toml).

**CRITICAL: yfinance is NOT currently in pyproject.toml.** It must be added as a direct dependency. It pulls in 18 transitive dependencies including pandas, numpy, requests, beautifulsoup4, protobuf, websockets. This is a significant footprint but unavoidable given the user decision.

## Architecture Patterns

### Recommended Project Structure
```
src/alphaswarm/
    market_data.py        # NEW: fetcher, cache, AV fallback (D-05)
    types.py              # MODIFY: add MarketDataSnapshot model (D-03)
    config.py             # MODIFY: add ALPHA_VANTAGE_API_KEY field (D-17)
    graph.py              # MODIFY: add create_ticker_with_market_data() (D-14)
    simulation.py         # MODIFY: call fetch_market_data() in run_simulation() (D-07)
    cli.py                # MODIFY: add degraded-data warning display (D-16)
data/
    market_cache/         # NEW: cache directory for per-ticker JSON files (D-09)
tests/
    test_market_data.py   # NEW: unit tests for fetcher, cache, fallback
```

### Pattern 1: Per-Ticker Parallel Fetch with Locks
**What:** Fetch all tickers concurrently using `asyncio.TaskGroup`, but serialize access per ticker symbol via `asyncio.Lock` to prevent yfinance's known thread-safety issue.
**When to use:** Always -- this is the fetch architecture from D-06.
**Example:**
```python
# Source: Verified against yfinance issue #2557 and project batch_dispatcher.py pattern
import asyncio
from functools import partial
import yfinance as yf

_ticker_locks: dict[str, asyncio.Lock] = {}

async def _fetch_single_ticker(symbol: str) -> MarketDataSnapshot:
    if symbol not in _ticker_locks:
        _ticker_locks[symbol] = asyncio.Lock()

    async with _ticker_locks[symbol]:
        # Check cache first
        cached = await _read_cache(symbol)
        if cached is not None:
            logger.info("cache_hit", ticker=symbol)
            return cached

        # yfinance is blocking -- run in thread
        try:
            snapshot = await asyncio.to_thread(_fetch_yfinance, symbol)
        except Exception:
            snapshot = await _fetch_alpha_vantage(symbol)  # fallback

        await _write_cache(symbol, snapshot)
        return snapshot

async def fetch_market_data(
    tickers: list[ExtractedTicker],
) -> dict[str, MarketDataSnapshot]:
    results: dict[str, MarketDataSnapshot] = {}
    async with asyncio.TaskGroup() as tg:
        for ticker in tickers:
            tg.create_task(_fetch_and_store(ticker.symbol, results))
    return results
```

### Pattern 2: Disk Cache with TTL (Atomic Write)
**What:** One JSON file per ticker in `data/market_cache/`. Contains `cached_at` ISO timestamp. On read, check age against 3600s TTL.
**When to use:** Every fetch attempt checks cache first.
**Example:**
```python
# Source: Mirrors ticker_validator.py atomic write pattern
import json
from datetime import datetime, timezone
from pathlib import Path
import aiofiles

CACHE_DIR = Path("data/market_cache")
CACHE_TTL_SECONDS = 3600

async def _read_cache(symbol: str) -> MarketDataSnapshot | None:
    path = CACHE_DIR / f"{symbol}.json"
    if not path.exists():
        return None
    async with aiofiles.open(path) as f:
        data = json.loads(await f.read())
    cached_at = datetime.fromisoformat(data["cached_at"])
    age = (datetime.now(timezone.utc) - cached_at).total_seconds()
    if age > CACHE_TTL_SECONDS:
        return None  # Expired
    return MarketDataSnapshot.model_validate(data["snapshot"])

async def _write_cache(symbol: str, snapshot: MarketDataSnapshot) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "snapshot": snapshot.model_dump(mode="json"),
    }
    tmp_path = CACHE_DIR / f"{symbol}.json.tmp"
    final_path = CACHE_DIR / f"{symbol}.json"
    async with aiofiles.open(tmp_path, "w") as f:
        await f.write(json.dumps(payload, indent=2))
    tmp_path.rename(final_path)
```

### Pattern 3: Graceful Degradation Cascade
**What:** yfinance -> Alpha Vantage -> empty snapshot. Never abort simulation.
**When to use:** Always -- D-15 mandates this.
**Example:**
```python
async def _fetch_with_fallback(symbol: str, av_key: str | None) -> MarketDataSnapshot:
    # Try yfinance first
    try:
        return await asyncio.to_thread(_fetch_yfinance, symbol)
    except Exception as exc:
        logger.warning("yfinance_failed", ticker=symbol, error=str(exc))

    # Try Alpha Vantage if key configured
    if av_key is not None:
        try:
            return await _fetch_alpha_vantage(symbol, av_key)
        except Exception as exc:
            logger.warning("alpha_vantage_failed", ticker=symbol, error=str(exc))

    # Both failed -- degraded snapshot
    logger.warning("market_data_fetch_failed", ticker=symbol,
                   reason="all sources failed")
    return MarketDataSnapshot(symbol=symbol)  # All fields None/empty
```

### Pattern 4: Neo4j Ticker Node Creation (UNWIND)
**What:** Create `Ticker` nodes linked to `Cycle` with `MarketDataSnapshot` data as properties.
**When to use:** After successful (or degraded) market data fetch.
**Example:**
```python
# Source: Mirrors graph.py create_cycle_with_seed_event() pattern
@staticmethod
async def _create_tickers_tx(
    tx: AsyncManagedTransaction,
    cycle_id: str,
    snapshots: list[dict],
) -> None:
    await tx.run(
        """
        UNWIND $snapshots AS s
        MERGE (t:Ticker {symbol: s.symbol})
        ON CREATE SET t.company_name = s.company_name
        WITH t, s
        MATCH (c:Cycle {cycle_id: $cycle_id})
        CREATE (c)-[:HAS_TICKER]->(t)
        CREATE (t)-[:HAS_MARKET_DATA]->(md:MarketDataSnapshot {
            pe_ratio: s.pe_ratio,
            market_cap: s.market_cap,
            ...
        })
        """,
        cycle_id=cycle_id,
        snapshots=snapshots,
    )
```

### Anti-Patterns to Avoid
- **Calling yfinance from the async event loop directly:** yfinance uses `requests` (blocking). MUST use `asyncio.to_thread()`.
- **Concurrent yfinance calls to the same ticker without locks:** Known thread-safety bug (GitHub issue #2557). Per-symbol `asyncio.Lock` required.
- **Storing raw pandas DataFrames in cache:** Not JSON-serializable. Convert to list of dicts immediately after fetch.
- **Making AV calls without respecting rate limits:** Free tier is 25/day, 5/min. Always check cache first. Log warnings when limits approached.
- **Aborting simulation on market data failure:** Per D-15, NEVER abort. Return degraded snapshot.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Yahoo Finance data fetching | Custom HTTP scraper for Yahoo | `yfinance` library | Yahoo's endpoints change frequently; yfinance handles cookie auth, parsing, retries |
| Financial data normalization | Manual parsing of Yahoo JSON responses | `yfinance` `.info` dict + `.history()` DataFrame | Library handles response format changes, currency normalization |
| Atomic file writes | Manual open/write/close | `aiofiles` + tmp/rename pattern | Already established in `ticker_validator.py`; prevents partial writes on crash |
| JSON serialization of Pydantic models | Manual dict construction | `model.model_dump(mode="json")` | Handles datetime, Optional, nested model serialization correctly |

**Key insight:** yfinance abstracts away Yahoo Finance's constantly-changing private API. Building a custom scraper would be fragile and require ongoing maintenance.

## Common Pitfalls

### Pitfall 1: yfinance Thread Safety
**What goes wrong:** Concurrent `yfinance.Ticker()` calls with the same symbol can overwrite each other's cached data due to shared global state.
**Why it happens:** yfinance uses a module-level cache dict that is not protected by locks.
**How to avoid:** Per-symbol `asyncio.Lock` objects. Each symbol's fetch is serialized, but different symbols run in parallel.
**Warning signs:** Intermittent KeyError or empty data when fetching the same ticker in tests.

### Pitfall 2: yfinance .info Returns Empty Dict on Failure
**What goes wrong:** `ticker.info` silently returns `{}` or a minimal dict when Yahoo Finance is unreachable or the symbol is invalid, instead of raising an exception.
**Why it happens:** yfinance swallows many HTTP errors and returns partial data.
**How to avoid:** Check for essential fields (e.g., `marketCap`) after `.info` fetch. If missing, treat as yfinance failure and trigger AV fallback.
**Warning signs:** `MarketDataSnapshot` with all `None` fundamentals despite no logged error.

### Pitfall 3: pandas DataFrame Serialization
**What goes wrong:** `ticker.history()` returns a pandas DataFrame with DatetimeIndex. Cannot be directly JSON-serialized.
**Why it happens:** pandas uses its own datetime types and numpy arrays internally.
**How to avoid:** Convert immediately: `hist.reset_index().to_dict(orient="records")`, then convert Timestamps to ISO strings. Or extract only needed fields as plain Python types.
**Warning signs:** `TypeError: Object of type Timestamp is not JSON serializable` when writing cache.

### Pitfall 4: Alpha Vantage Rate Limit Exhaustion
**What goes wrong:** Free tier allows only 25 calls/day. If yfinance fails for 3 tickers and AV is called for each with both `GLOBAL_QUOTE` + `OVERVIEW`, that's 6 calls. Multiple simulation runs in a day can exhaust the quota.
**Why it happens:** 25 calls/day is extremely limited.
**How to avoid:** Cache AV responses with the same TTL as yfinance responses. Log remaining daily quota if available. Consider AV as price-only fallback (1 call per ticker instead of 2).
**Warning signs:** HTTP 403 or `"Note": "Thank you for using Alpha Vantage! ... premium ..."` in response.

### Pitfall 5: Timezone-Aware Datetime in Cache TTL
**What goes wrong:** Cache `cached_at` uses naive datetime, comparison with `datetime.now()` across timezone boundaries gives wrong TTL.
**Why it happens:** `datetime.now()` without timezone is naive. `datetime.fromisoformat()` may return aware or naive depending on input.
**How to avoid:** Always use `datetime.now(timezone.utc)` for `cached_at`. Always store as UTC ISO format. Compare only UTC-aware datetimes.
**Warning signs:** Cache never expires or expires immediately depending on local timezone offset.

### Pitfall 6: yfinance earnings_dates Timezone-Aware Index
**What goes wrong:** `ticker.earnings_dates` returns a DataFrame with timezone-aware DatetimeIndex (`America/New_York`). Extracting the next earnings date requires careful handling.
**Why it happens:** Earnings dates are timezone-localized by Yahoo Finance.
**How to avoid:** Filter for future dates: `future = ed[ed.index > pd.Timestamp.now(tz='America/New_York')]`. Take the first one. Convert to ISO string for storage.
**Warning signs:** `TypeError` or wrong date selection when comparing naive and aware timestamps.

## Code Examples

Verified patterns from actual library behavior (tested on this machine):

### yfinance Price History Extraction
```python
# Source: Verified via live yfinance 1.2.0 call on AAPL
import yfinance as yf

def _fetch_yfinance(symbol: str) -> dict:
    """Blocking function -- MUST be called via asyncio.to_thread()."""
    ticker = yf.Ticker(symbol)

    # Price history: 90 days OHLCV
    hist = ticker.history(period="3mo")
    # hist.columns: ['Open', 'High', 'Low', 'Close', 'Volume', 'Dividends', 'Stock Splits']
    # hist.index: DatetimeIndex (timezone-aware)
    price_history = [
        {
            "date": row.Index.isoformat(),
            "open": float(row.Open),
            "high": float(row.High),
            "low": float(row.Low),
            "close": float(row.Close),
            "volume": int(row.Volume),
        }
        for row in hist.itertuples()
    ]

    # Financial fundamentals from .info
    info = ticker.info
    fundamentals = {
        "pe_ratio": info.get("trailingPE"),          # float or None
        "market_cap": info.get("marketCap"),          # int or None
        "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),  # float
        "fifty_two_week_low": info.get("fiftyTwoWeekLow"),    # float
        "eps_trailing": info.get("trailingEps"),      # float
        "revenue_ttm": info.get("totalRevenue"),      # int
        "gross_margin_pct": info.get("grossMargins"), # float (0.0-1.0)
        "debt_to_equity": info.get("debtToEquity"),   # float
        "company_name": info.get("shortName", symbol),
    }

    # Earnings dates
    try:
        ed = ticker.earnings_dates
        if ed is not None and not ed.empty:
            # Most recent earnings surprise
            reported = ed[ed["Reported EPS"].notna()]
            if not reported.empty:
                latest = reported.iloc[0]
                fundamentals["earnings_surprise_pct"] = latest.get("Surprise(%)")
            # Next earnings date (future)
            import pandas as pd
            now = pd.Timestamp.now(tz="America/New_York")
            future = ed[ed.index > now]
            if not future.empty:
                fundamentals["next_earnings_date"] = future.index[-1].isoformat()
    except Exception:
        pass  # earnings_dates can fail for some tickers

    return {"price_history": price_history, "fundamentals": fundamentals}
```

### Alpha Vantage Fallback
```python
# Source: Verified against AV demo API response (GLOBAL_QUOTE + OVERVIEW)
import httpx

AV_BASE_URL = "https://www.alphavantage.co/query"

async def _fetch_alpha_vantage(
    symbol: str, api_key: str,
) -> MarketDataSnapshot:
    """Fetch from Alpha Vantage as yfinance fallback."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        # GLOBAL_QUOTE: current price/volume
        quote_resp = await client.get(AV_BASE_URL, params={
            "function": "GLOBAL_QUOTE",
            "symbol": symbol,
            "apikey": api_key,
        })
        quote_data = quote_resp.json().get("Global Quote", {})

        # OVERVIEW: fundamentals
        overview_resp = await client.get(AV_BASE_URL, params={
            "function": "OVERVIEW",
            "symbol": symbol,
            "apikey": api_key,
        })
        overview = overview_resp.json()

    # Map AV fields to our model
    # AV GLOBAL_QUOTE keys: "01. symbol", "02. open", "03. high", "04. low",
    #   "05. price", "06. volume", "08. previous close", "09. change", "10. change percent"
    # AV OVERVIEW keys: PERatio, MarketCapitalization, 52WeekHigh, 52WeekLow,
    #   EPS, RevenueTTM, GrossProfitTTM, ProfitMargin

    def _safe_float(val: str | None) -> float | None:
        if val is None or val == "None" or val == "-":
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    return MarketDataSnapshot(
        symbol=symbol,
        company_name=overview.get("Name", symbol),
        pe_ratio=_safe_float(overview.get("PERatio")),
        market_cap=_safe_float(overview.get("MarketCapitalization")),
        fifty_two_week_high=_safe_float(overview.get("52WeekHigh")),
        fifty_two_week_low=_safe_float(overview.get("52WeekLow")),
        eps_trailing=_safe_float(overview.get("EPS")),
        revenue_ttm=_safe_float(overview.get("RevenueTTM")),
        gross_margin_pct=None,  # AV has GrossProfitTTM, not margin %
        debt_to_equity=None,    # AV OVERVIEW does NOT include D/E ratio
        # price_history from GLOBAL_QUOTE is single-day only
        price_history=[],
    )
```

### MarketDataSnapshot Model
```python
# Source: Follows SeedEvent/ExtractedTicker pattern from types.py
class MarketDataSnapshot(BaseModel, frozen=True):
    """Market data snapshot for a single ticker."""
    symbol: str
    company_name: str = ""
    # Price history (90-day OHLCV)
    price_history: list[dict[str, float | int | str]] = Field(default_factory=list)
    # Financial fundamentals
    pe_ratio: float | None = None
    market_cap: float | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None
    eps_trailing: float | None = None
    revenue_ttm: float | None = None
    gross_margin_pct: float | None = None
    debt_to_equity: float | None = None
    earnings_surprise_pct: float | None = None
    next_earnings_date: str | None = None
    # Reserved for Phase 18
    headlines: list[str] = Field(default_factory=list)
    # Degraded flag
    is_degraded: bool = False
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| yfinance 0.2.x | yfinance 1.2.0 | Feb 2026 | Major version bump; uses `curl_cffi` instead of `requests` for some endpoints; `.info` dict keys are stable |
| pandas 1.x | pandas 3.0.2 (yfinance dep) | 2025 | `to_dict(orient="records")` still works; DatetimeIndex unchanged |
| Alpha Vantage unlimited free | AV 25 calls/day free limit | 2024 | Disk caching is mandatory, not optional |

**Deprecated/outdated:**
- yfinance `Ticker.earnings` property: deprecated in favor of `Ticker.income_stmt`
- yfinance `download()` for single tickers: works but `Ticker().history()` is preferred for single-symbol use

## Open Questions

1. **Price history format: list of dicts vs compact summary?**
   - What we know: Full 90-day OHLCV as list of dicts is ~90 entries x 6 fields = ~540 values per ticker. For 3 tickers, that's ~1620 values in the JSON cache and Neo4j.
   - What's unclear: Whether Phase 18 needs raw OHLCV rows or just summary stats (last close, % change 30d/90d, avg volume).
   - Recommendation: Store full OHLCV in cache (disk is cheap), but also compute and store summary stats on the `MarketDataSnapshot` for easy access. Phase 18 can decide which to inject. Add computed fields: `last_close`, `price_change_30d_pct`, `price_change_90d_pct`, `avg_volume_30d`.

2. **Alpha Vantage OVERVIEW coverage gaps**
   - What we know: AV OVERVIEW does NOT return debt/equity ratio or gross margin percentage directly. It has `GrossProfitTTM` (absolute) and `ProfitMargin` but not `GrossMargins`.
   - What's unclear: Whether AV fallback should be considered price-only or partial-fundamentals.
   - Recommendation: AV fallback provides partial fundamentals (PE, market cap, 52w range, EPS, revenue) but leaves `gross_margin_pct` and `debt_to_equity` as None. This is acceptable per D-15 graceful degradation.

3. **Neo4j MarketDataSnapshot node: store price_history as property?**
   - What we know: Neo4j property values have a 2GB limit but storing lists of dicts as JSON strings in properties is awkward for querying.
   - What's unclear: Whether Phase 20 report queries need individual price data points from Neo4j.
   - Recommendation: Store only summary stats as MarketDataSnapshot node properties (pe_ratio, market_cap, etc.). Do NOT store full price_history array in Neo4j. The disk cache is the source of truth for raw data. This keeps graph queries fast.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| yfinance | DATA-01 (price/fundamentals) | Installed system-wide, NOT in project venv | 1.2.0 | Must `uv add` to project |
| httpx | DATA-02 (Alpha Vantage) | In project venv (transitive of ollama) | 0.28.1 | -- |
| aiofiles | DATA-04 (cache writes) | In project venv (direct dep) | 25.1.0 | -- |
| pandas | yfinance dependency | NOT in project venv | -- | Installed automatically with yfinance |
| numpy | yfinance dependency | NOT in project venv | -- | Installed automatically with yfinance |
| Neo4j | DATA-01 (graph writes) | Docker required | 5.28.x | -- |
| Internet access | yfinance + AV API calls | Required for first fetch | -- | Disk cache for re-runs |

**Missing dependencies with no fallback:**
- yfinance must be added to pyproject.toml: `uv add yfinance>=1.2.0`
- This pulls in 18 transitive dependencies (pandas, numpy, requests, beautifulsoup4, etc.)

**Missing dependencies with fallback:**
- Alpha Vantage API key is optional (fallback: yfinance-only, degraded if yfinance also fails)

## Project Constraints (from CLAUDE.md)

- **100% async (asyncio):** yfinance MUST be wrapped in `asyncio.to_thread()`. httpx `AsyncClient` for AV calls.
- **No blocking I/O on main event loop:** Cache reads/writes via aiofiles. yfinance in thread pool.
- **Local First / No cloud APIs:** yfinance and AV are free, public APIs (no cloud inference). This is data fetching, not inference.
- **Memory Safety:** 3 tickers max (Phase 16 cap) limits data volume. pandas DataFrames are short-lived (created in thread, converted to dicts, GC'd).
- **Python 3.11+ strict typing:** All functions typed. `MarketDataSnapshot` frozen Pydantic model.
- **uv package manager:** Use `uv add` for yfinance, not pip.
- **pytest-asyncio:** Tests use `asyncio_mode = "auto"`.
- **structlog:** Component-scoped logger: `structlog.get_logger(component="market_data")`.
- **pydantic / pydantic-settings:** Config model for AV API key. Frozen models for data types.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.0+ with pytest-asyncio 0.24.0+ |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest tests/test_market_data.py -x -q` |
| Full suite command | `uv run pytest tests/ -x -q` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DATA-01 | yfinance fetches OHLCV + fundamentals for a ticker | unit | `uv run pytest tests/test_market_data.py::test_fetch_yfinance_returns_snapshot -x` | Wave 0 |
| DATA-01 | fetch_market_data() calls per ticker in parallel | unit | `uv run pytest tests/test_market_data.py::test_parallel_fetch_all_tickers -x` | Wave 0 |
| DATA-01 | MarketDataSnapshot model validates with all fields | unit | `uv run pytest tests/test_market_data.py::test_snapshot_model_valid -x` | Wave 0 |
| DATA-02 | AV fallback when yfinance raises | unit | `uv run pytest tests/test_market_data.py::test_av_fallback_on_yfinance_failure -x` | Wave 0 |
| DATA-02 | Both fail -> degraded snapshot with is_degraded=True | unit | `uv run pytest tests/test_market_data.py::test_degraded_snapshot_both_fail -x` | Wave 0 |
| DATA-02 | AV skipped when no API key | unit | `uv run pytest tests/test_market_data.py::test_av_skipped_no_key -x` | Wave 0 |
| DATA-04 | Cache write creates JSON with cached_at | unit | `uv run pytest tests/test_market_data.py::test_cache_write_creates_file -x` | Wave 0 |
| DATA-04 | Cache read within TTL returns cached data | unit | `uv run pytest tests/test_market_data.py::test_cache_hit_within_ttl -x` | Wave 0 |
| DATA-04 | Cache read expired TTL re-fetches | unit | `uv run pytest tests/test_market_data.py::test_cache_miss_expired_ttl -x` | Wave 0 |
| DATA-04 | Cache-hit logged at INFO level | unit | `uv run pytest tests/test_market_data.py::test_cache_hit_logged -x` | Wave 0 |
| DATA-01 | Graph: Ticker + MarketDataSnapshot nodes created | integration | `uv run pytest tests/test_graph.py::test_create_ticker_with_market_data -x` | Wave 0 |
| DATA-01 | Simulation integration: market data fetched before round 1 | integration | `uv run pytest tests/test_simulation.py::test_market_data_fetched_before_round1 -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_market_data.py -x -q`
- **Per wave merge:** `uv run pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_market_data.py` -- covers DATA-01, DATA-02, DATA-04 (12 tests)
- [ ] Framework install: `uv add yfinance>=1.2.0` -- yfinance not in project venv
- [ ] Test fixtures: mock yfinance `Ticker` class (mock `asyncio.to_thread` to return pre-built dicts), mock httpx for AV calls (consistent with `test_ticker_validator.py` httpx mocking pattern)

*(Wave 0 test file creation and yfinance installation are prerequisites for all implementation work.)*

## Sources

### Primary (HIGH confidence)
- yfinance 1.2.0 live testing on local machine -- `.info` dict keys, `.history()` columns, `.earnings_dates` format all verified via direct Python calls
- Alpha Vantage demo API -- `GLOBAL_QUOTE` and `OVERVIEW` response fields verified via live HTTP fetch (https://www.alphavantage.co/query?function=OVERVIEW&symbol=IBM&apikey=demo)
- Existing codebase -- `ticker_validator.py`, `graph.py`, `simulation.py`, `types.py`, `config.py` patterns read and documented

### Secondary (MEDIUM confidence)
- [yfinance PyPI](https://pypi.org/project/yfinance/) -- version 1.2.0, dependency list
- [yfinance thread safety issue #2557](https://github.com/ranaroussi/yfinance/issues/2557) -- concurrent download() not thread-safe
- [Alpha Vantage API documentation](https://www.alphavantage.co/documentation/) -- endpoint format and parameters
- [Alpha Vantage rate limits](https://www.macroption.com/alpha-vantage-api-limits/) -- 25 calls/day, 5 calls/min free tier

### Tertiary (LOW confidence)
- None -- all critical claims verified via primary or secondary sources

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- yfinance 1.2.0 verified installed and tested locally; AV API tested against demo endpoint
- Architecture: HIGH -- patterns directly mirror existing `ticker_validator.py`, `batch_dispatcher.py`, `graph.py` from the codebase
- Pitfalls: HIGH -- yfinance thread-safety confirmed via GitHub issue; .info empty-dict behavior confirmed via local testing; AV rate limits confirmed via official docs

**Research date:** 2026-04-06
**Valid until:** 2026-04-20 (yfinance is an unofficial API that can break at any time; 14-day validity)
