# Stack Research — v6.0 Data Enrichment & Personalized Advisory

**Domain:** Financial data ingestion + personalized advisory synthesis (additions to existing async AlphaSwarm stack)
**Researched:** 2026-04-18
**Confidence:** MEDIUM-HIGH (library versions verified via PyPI; async integration patterns verified via official docs + GitHub issues)

## Scope

This document covers **only** the net-new dependencies required for the v6.0 milestone:

1. Market data ingestion (yfinance)
2. News/headlines ingestion (NewsAPI / RSS)
3. Holdings CSV ingestion (pandas)
4. Caching layer for ingestion (aiocache)
5. Advisory report markdown generation

Existing stack (Python 3.11+, `uv`, `ollama-python>=0.6.1`, async `neo4j`, FastAPI + `uvicorn` + `httpx`, Vue 3 + D3, `pydantic`, `pydantic-settings`, `structlog`, `pytest-asyncio`) is assumed and **not re-researched**.

## Recommended Additions

### Core New Dependencies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `yfinance` | **1.3.0** (2026-04-16) | Market data: price/volume/fundamentals, optionally `AsyncWebSocket` for streaming | Ships a native `AsyncWebSocket` class (PR #2201 merged in the 1.x line) with auto-reconnect + heartbeat, removing the previous "must wrap in `run_in_executor`" caveat for streaming. REST methods (`.history`, `.info`, etc.) are **still synchronous** — see PITFALLS. No paid key needed, matches "no cloud APIs / local-first" constraint since the API is free and anonymous. |
| `pandas` | **3.0.2** (2026-03-31) | Parse holdings CSV, normalize schema, validate columns | 3.0 requires Python >=3.11 — matches our runtime. CSV parsing with typed dtypes is the fastest, best-tested option. Only used in the ingestion layer; the swarm never touches pandas DataFrames. |
| `aiocache` | **0.12.3** (2024-09-25) | TTL cache for yfinance results + news results, in-memory backend | Native asyncio API (`SimpleMemoryCache` with per-key TTL). Avoids re-hitting Yahoo's rate limiter across a 100-agent swarm that may reference the same ticker. `diskcache` is faster but sync-only (SQLite blocks event loop). Last release is ~18 months old but the 0.12 branch is stable; the 1.0 alpha exists but isn't needed. |
| `feedparser` | **6.0.12** (2025-09-10) | RSS/Atom parsing for news feeds (fallback / primary depending on source) | Industry standard for RSS. Parses RSS 0.9x–2.0, Atom 0.3/1.0, CDF. Parsing itself is sync/CPU-bound but **fast** (<50ms for typical financial RSS sizes) — we fetch the bytes via existing `httpx` and pass to `feedparser.parse()`. |
| `mistune` | **3.2.0** (2025-12-23) | Server-side markdown → HTML rendering (if needed for advisory report preview/export) | Fastest pure-Python CommonMark parser. Supports Python 3.8–3.14. **Note:** the web UI already uses `marked` + `DOMPurify` (from Phase 36 Report Viewer) client-side, so mistune is only needed if we render advisory markdown on the server (e.g., for export/download). For pure markdown **generation** we use f-strings + Jinja2-style templates — no library needed. |

### Supporting Libraries (conditional)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `newsapi-python` (mattlisiv) | 0.2.7 | Thin wrapper over NewsAPI.org REST | **Only if** we commit to NewsAPI.org. Sync-based (uses `requests`) — prefer rolling our own thin `httpx` client instead to stay 100% async. See PITFALLS. |
| `jinja2` | 3.1.x | Markdown advisory report templating | If the advisory report has complex conditional sections. Otherwise, f-strings suffice. Already transitively in FastAPI deps. |
| `tenacity` | 9.x | Declarative retry/backoff for ingestion fetches | Recommended — we already use custom exponential backoff for Ollama; `tenacity` gives the same pattern for yfinance/news fetches with cleaner decorator syntax. Pure Python, no deps. |
| `aiofiles` | 24.x | Async CSV read of holdings from disk | Already used in Phase 36 for the report viewer; reuse it for holdings CSV ingestion. Pair with `io.StringIO` + `pd.read_csv` inside `asyncio.to_thread`. |

### Development Tools (no new additions)

No new dev tooling. Existing `pytest-asyncio`, `ruff`, `mypy`, `structlog` cover all v6.0 testing/linting/logging needs.

## Installation (uv)

```bash
# Core v6.0 additions
uv add yfinance==1.3.0 pandas==3.0.2 aiocache==0.12.3 feedparser==6.0.12

# If we do server-side markdown rendering for advisory export
uv add mistune==3.2.0

# Retry/backoff (recommended)
uv add tenacity

# No news client library — we roll our own httpx-based client (see below)
```

## Architecture Integration Notes

### yfinance + asyncio (CRITICAL)

yfinance's REST methods (`Ticker().history()`, `.info`, `.financials`, `.download()`) are **synchronous** and internally do blocking HTTP calls. They will freeze the FastAPI event loop if called directly from a coroutine.

**Pattern to use:**

```python
# alphaswarm/ingestion/market_data.py
import asyncio
import yfinance as yf
from aiocache import Cache
from aiocache.serializers import PickleSerializer

cache = Cache(Cache.MEMORY, ttl=300, serializer=PickleSerializer())

async def fetch_ticker_history(symbol: str, period: str = "1mo") -> pd.DataFrame:
    cached = await cache.get(f"hist:{symbol}:{period}")
    if cached is not None:
        return cached
    # Offload blocking yfinance call
    df = await asyncio.to_thread(lambda: yf.Ticker(symbol).history(period=period))
    await cache.set(f"hist:{symbol}:{period}", df, ttl=300)
    return df
```

- `asyncio.to_thread` is the Python 3.9+ equivalent of `loop.run_in_executor(None, fn)` and is the idiomatic choice for Python 3.11+.
- Dedicate a bounded `ThreadPoolExecutor` (e.g., 4 workers) to yfinance calls so concurrent ticker fetches from the swarm don't spawn unbounded threads.
- yfinance also exposes `AsyncWebSocket` (native asyncio) for **streaming** quotes — only adopt if v6.0 actually needs live intraday price updates in the swarm context (probably not for MVP; defer to v7.0).

### News ingestion: roll our own over httpx

**Verdict: avoid `newsapi-python` library; build a ~50-line async client on top of existing `httpx.AsyncClient`.**

Reasons:
1. `newsapi-python` wraps `requests` — adding it forces us to `asyncio.to_thread` every call, which defeats the point of a thin client.
2. We already have `httpx` in the stack (used for existing outbound calls).
3. NewsAPI.org's free "Developer" tier is **dev-only** (100 req/day, 24h article delay, localhost-only) per their ToS — this is fine for local simulation but we must explicitly gate it.
4. For production, `feedparser` + Yahoo Finance/Bloomberg/Reuters RSS endpoints is **free, no key, no ToS risk**, and suits the "local-first" constraint better.

**Recommended approach:** Dual-source with RSS as primary and NewsAPI as optional enrichment.

```python
# Primary: RSS (free, unlimited, no key)
async with httpx.AsyncClient(timeout=10) as client:
    resp = await client.get(f"https://finance.yahoo.com/rss/headline?s={symbol}")
    feed = feedparser.parse(resp.text)  # CPU-bound but fast

# Optional: NewsAPI (dev-local only)
async with httpx.AsyncClient(...) as client:
    resp = await client.get(
        "https://newsapi.org/v2/everything",
        params={"q": symbol, "apiKey": settings.news_api_key, "pageSize": 20},
    )
```

### Holdings CSV ingestion

```python
# alphaswarm/ingestion/holdings.py
import io, asyncio
import aiofiles
import pandas as pd
from pydantic import BaseModel, field_validator

class Holding(BaseModel):
    symbol: str
    shares: float
    cost_basis: float | None = None

    @field_validator("symbol")
    @classmethod
    def _upper(cls, v: str) -> str: return v.strip().upper()

async def load_holdings(path: str) -> list[Holding]:
    async with aiofiles.open(path, "r") as f:
        raw = await f.read()
    df = await asyncio.to_thread(
        pd.read_csv, io.StringIO(raw),
        dtype={"symbol": str, "shares": float, "cost_basis": float},
    )
    return [Holding(**row) for row in df.to_dict(orient="records")]
```

- CSV is read via `aiofiles`, parsed in a worker thread, validated by pydantic.
- **Never persisted to Neo4j.** Holdings live only in the orchestrator's memory for the duration of a simulation run.
- Info-isolation enforcement: the context-packet builder and any prompt renderer must be pure functions of `(market_data, news, archetype)` — holdings must not be reachable from that call tree. Enforce via:
  - Unit test: import holdings module → assert no import from `packet_builder` module.
  - Runtime: pass `ContextPacket` dataclass frozen (via `pydantic.BaseModel(frozen=True)` or `dataclass(frozen=True)`) into swarm prompts; holdings live in a separate `Portfolio` dataclass only reachable from orchestrator.

### Advisory report generation

- Generate markdown with **f-strings + Python string templates** (or Jinja2 if branching grows) — no generator library needed.
- If export (HTML/PDF) is in scope: `mistune.html(markdown_text)` for server-side render; client-side Vue already has the `marked` + `DOMPurify` pipeline from Phase 36, so reuse that for in-UI viewing.
- Advisory report can be written to disk via `aiofiles` (same as the Phase 36 post-simulation report pattern) so it integrates naturally with the existing `/api/report/{cycle_id}` endpoint family.

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| `yfinance` 1.3.0 | `yahooquery` | Use if yfinance rate-limiting becomes blocking. `yahooquery` uses official endpoints, more stable, but less ergonomic. Swap is non-trivial (different API). |
| `yfinance` 1.3.0 | Alpaca / Finnhub / EODHD | Only if we abandon "no cloud APIs" — all require signed-up API keys. Out of scope per CLAUDE.md hard constraint #2 ("Local First"). |
| Roll-own httpx NewsAPI client | `newsapi-python` (mattlisiv) | Never — sync `requests`-based, stale. |
| Roll-own httpx NewsAPI client | Finlight.me / Newsdata.io | If NewsAPI free tier is insufficient and budget allows; both offer better free tiers. Defer unless actually blocked. |
| `feedparser` | `atoma-api` | If benchmarks show feedparser is a bottleneck (unlikely — RSS feeds rarely exceed 100 entries). |
| `aiocache` (memory) | `diskcache` | If we need persistent cache across simulation restarts. Sync-only, needs `asyncio.to_thread` wrapper — more machinery than we need for TTL of 5–15 min. |
| `aiocache` (memory) | `aiocache` + Redis backend | If multi-process ingestion is needed later. Requires Redis in Docker Compose — adds infra weight. Start with memory backend. |
| `mistune` (server markdown) | `markdown-it-py` | Equivalent quality, slightly slower. Either works; mistune has plugin ecosystem. |
| f-strings for markdown generation | `jinja2` | If advisory report gets conditional sections, loops over holdings, archetype-specific blocks. Likely needed — preemptively add to the planner's option list. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `newsapi-python` (mattlisiv) | Wraps `requests` (sync). Forces `asyncio.to_thread` per call for no ergonomic gain. Last update ages ago. | Thin async client over existing `httpx.AsyncClient` (~50 LOC). |
| `pandas-datareader` | Multiple data sources deprecated; Yahoo support is indirect and less reliable than yfinance direct. | `yfinance` 1.3.0. |
| Calling `yf.Ticker(...).history()` directly from an async function | Blocks the FastAPI event loop — will stall WebSocket broadcaster and Ollama batcher. | `await asyncio.to_thread(yf.Ticker(sym).history, ...)` with a bounded executor. |
| `requests` for news/data | Sync only. We already have `httpx`. Adding `requests` creates two HTTP clients with different config/timeouts. | `httpx.AsyncClient` (already in stack). |
| `aiohttp` | Faster than httpx but adds a second async HTTP client to the codebase. httpx already handles FastAPI's outbound needs and supports both sync + async with HTTP/2. | `httpx.AsyncClient`. |
| Persisting holdings in Neo4j | Violates the v6.0 information-isolation architecture (Option A). Any Cypher write of Holdings creates a leak vector into swarm queries. | In-memory `Portfolio` dataclass, scoped to a single orchestrator run. Enforce with unit test + log-grep. |
| `diskcache` in async path without wrapping | SQLite-backed, blocks event loop. Acceptable only inside `asyncio.to_thread`. | `aiocache` SimpleMemoryCache — native async, TTL built-in. |
| yfinance streaming WebSocket for MVP | Complex to test; adds reconnect/heartbeat state machine. Simulation is "snapshot of the world at T=0" — streaming is a v7.0 concern. | Batch fetch once per simulation, cache in aiocache for the run's duration. |
| Storing NewsAPI key in `.env` committed to repo | ToS + security. | `pydantic-settings` reads from environment; `.env` stays gitignored (already true in the repo). |
| Calling yfinance from inside a swarm agent | Violates Option A architecture — ingestion is its own layer. Agents consume pre-built context packets. | Ingestion service builds `ContextPacket`; swarm only receives packets. |

## Stack Patterns by Variant

**If ingestion throughput becomes a bottleneck (100 agents × multiple tickers):**
- Pre-fetch all unique tickers in a single pass before dispatching the swarm cycle
- Cache all fundamental data with a longer TTL (e.g., 24h for `.info`, 5min for `.history`)
- Move to `aiocache` + Redis if multi-process workers are introduced

**If NewsAPI rate limit blocks local dev:**
- Default to RSS only (Yahoo Finance + Reuters + Bloomberg feeds)
- Treat NewsAPI as optional enrichment behind a feature flag in `pydantic-settings`

**If yfinance gets IP-banned by Yahoo mid-simulation:**
- Implement `tenacity` exponential backoff with jitter (10s → 30s → 60s → abandon)
- Log a `structlog` warning and emit a degraded `ContextPacket` with `market_data=None`
- Consider `yahooquery` as a drop-in fallback

**If the advisory report format grows complex:**
- Upgrade from f-strings to `jinja2` templates in `alphaswarm/advisory/templates/`
- Keep rendered markdown as the canonical artifact; HTML/PDF via `mistune` + weasyprint only if explicitly requested

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `pandas==3.0.2` | Python >=3.11 | Pandas 3.0 **dropped** Python 3.10 support. Our runtime is 3.11+ so safe. |
| `yfinance==1.3.0` | `pandas>=2.0`, Python 3.9+ | Returns pandas DataFrames; no incompatibility with pandas 3.x. |
| `aiocache==0.12.3` | Python >=3.6 | Older release (Sep 2024) but stable. Pure-Python, no native deps. |
| `feedparser==6.0.12` | Python >=3.6 | Pure-Python. No conflict with httpx. |
| `mistune==3.2.0` | Python 3.8–3.14 | Breaking changes in 3.x from 2.x; start fresh (no legacy 2.x code to migrate). |
| `httpx` (existing) | `yfinance.AsyncWebSocket` | Independent — yfinance WebSocket uses its own `websockets` client internally. No conflict. |
| Neo4j async driver (existing) | All v6.0 additions | No shared dependencies. Holdings never hit Neo4j by design. |

## Sources

- [yfinance 1.3.0 on PyPI](https://pypi.org/project/yfinance/) — released 2026-04-16, verified HIGH
- [yfinance AsyncWebSocket docs](https://ranaroussi.github.io/yfinance/reference/api/yfinance.AsyncWebSocket.html) — native async streaming API confirmed, HIGH
- [yfinance thread-safety issue #2557](https://github.com/ranaroussi/yfinance/issues/2557) — confirms sync REST calls need `run_in_executor`/`to_thread` wrapper, HIGH
- [pandas 3.0.2 on PyPI](https://pypi.org/project/pandas/) — released 2026-03-31, requires Python >=3.11, HIGH
- [feedparser 6.0.12 on PyPI](https://pypi.org/project/feedparser/) — released 2025-09-10, HIGH
- [mistune 3.2.0 on PyPI](https://pypi.org/project/mistune/) — released 2025-12-23, HIGH
- [aiocache 0.12.3 on PyPI](https://pypi.org/project/aiocache/) — Snyk maintenance analysis "sustainable", MEDIUM (last release ~18 months old)
- [NewsAPI.org Terms](https://newsapi.org/terms) — Developer tier is dev-only, 100 req/day, 24h article delay, HIGH
- [HTTPX vs AIOHTTP 2026 comparison](https://decodo.com/blog/httpx-vs-requests-vs-aiohttp) — confirms httpx is appropriate for existing outbound needs, MEDIUM
- [yfinance rate-limit discussion #2431](https://github.com/ranaroussi/yfinance/discussions/2431) — rate-limit behavior documented, HIGH
- [Sling Academy: yfinance rate limits](https://www.slingacademy.com/article/rate-limiting-and-api-best-practices-for-yfinance/) — best-practice patterns, MEDIUM

---
*Stack research for: v6.0 Data Enrichment & Personalized Advisory additions*
*Researched: 2026-04-18*
