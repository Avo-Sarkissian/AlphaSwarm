# Stack Research: v3.0 Stock-Specific Recommendations with Live Data & RAG

**Domain:** Multi-agent financial simulation -- ticker extraction, live market data, RAG knowledge base, enhanced agent decisions, improved TUI results
**Researched:** 2026-04-05
**Confidence:** HIGH (existing stack validated through v2.0; additions are incremental and well-understood)

## Scope

This document covers ONLY the stack additions and changes needed for v3.0 features. The validated v1+v2 stack (Python 3.11+, asyncio, ollama >=0.6.1, neo4j >=5.28, textual >=8.1.1, pydantic, structlog, psutil, httpx, backoff, jinja2, aiofiles) is NOT re-evaluated. See prior STACK.md research for rationale on existing dependencies.

## Critical Finding: yfinance Is Synchronous and Not Thread-Safe

**Impact:** All market data fetching must be async. yfinance blocks the event loop and its `download()` function uses a shared global dictionary that is not thread-safe for concurrent calls with different parameters.

**Resolution:** Use `asyncio.to_thread()` to run yfinance calls in a thread pool, but serialize calls per-ticker to avoid the thread-safety issue. Wrap yfinance behind a `MarketDataFetcher` class with an `asyncio.Lock` per ticker symbol. This is preferable to switching to an async-native alternative because:
1. yfinance is actively maintained (v1.2.0, Feb 2026), well-documented, and requires no API key
2. Alternatives like `pstock` and `yahoo-finance-async` are unmaintained with tiny communities
3. The `asyncio.to_thread()` wrapper is 10-15 lines of code vs. adopting an unfamiliar library
4. Market data fetching happens once per simulation (during seed injection), not 100 times -- serialization cost is negligible

**Confidence:** HIGH -- verified yfinance thread-safety issue via [GitHub #2557](https://github.com/ranaroussi/yfinance/issues/2557). `asyncio.to_thread()` is stdlib (Python 3.9+).

## Critical Finding: ChromaDB PersistentClient Is Synchronous

**Impact:** ChromaDB's `PersistentClient` (embedded SQLite mode) is synchronous. The `AsyncHttpClient` requires running a separate ChromaDB server process, adding Docker complexity.

**Resolution:** Use `PersistentClient` wrapped in `asyncio.to_thread()` for the few operations that touch ChromaDB (add documents, query). This is the correct approach because:
1. ChromaDB operations in our use case are infrequent -- bulk-add historical data at startup, query 3-5 times per simulation (one per round context enrichment)
2. Running a separate ChromaDB server adds Docker compose complexity, port management, and a network hop for minimal benefit
3. The `PersistentClient` stores data to disk at `./data/chromadb/`, surviving restarts without needing a server process
4. nomic-embed-text embeddings are ~274MB in memory (trivial on 64GB M1 Max) and compute in <1ms per embedding via Ollama

**Confidence:** HIGH -- verified via [ChromaDB docs](https://docs.trychroma.com/reference/python/client) and [Chroma Cookbook](https://cookbook.chromadb.dev/core/clients/).

## Critical Finding: nomic-embed-text Memory Is Negligible

**Impact:** Running a third model alongside the simulation models could strain the 64GB memory budget.

**Finding:** nomic-embed-text v1.5 is a 137M parameter model requiring ~274MB RAM (F16 quantization). This is negligible compared to the worker model (~4-8GB) and orchestrator (~18GB). However, Ollama's `OLLAMA_MAX_LOADED_MODELS=2` constraint means we cannot have 3 models loaded simultaneously.

**Resolution:** Use ChromaDB's built-in `OllamaEmbeddingFunction` which calls the Ollama `/api/embeddings` endpoint on-demand. This means:
1. nomic-embed-text loads/unloads per embedding batch (cold load <2s for a 137M model)
2. Pre-compute all embeddings during a dedicated "RAG ingestion" phase before simulation starts, when no other models are loaded
3. During simulation, only query ChromaDB (which uses pre-computed embeddings stored on disk) -- no embedding model needed
4. For query-time embeddings (searching ChromaDB), briefly load nomic-embed-text, embed the query, unload -- this takes <3s total

**Confidence:** HIGH -- verified model size via [Ollama registry](https://ollama.com/library/nomic-embed-text:v1.5) and [HuggingFace discussions](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5/discussions/15).

## Recommended Stack Additions

### New Dependencies

| Library | Version | Purpose | Why Recommended | Feature |
|---------|---------|---------|-----------------|---------|
| yfinance | >=1.2.0 | Stock price history, earnings, fundamentals | Free, no API key required, actively maintained (v1.2.0, Feb 2026). Provides `Ticker.history()`, `.earnings`, `.financials`, `.info`, `.news` in one library. Covers 80% of market data needs without API key management. Wrap in `asyncio.to_thread()` for async safety. | Live market data pipeline |
| chromadb | >=1.5.0,<2.0 | Vector database for RAG knowledge base | Lightweight embedded vector DB with built-in Ollama integration via `OllamaEmbeddingFunction`. `PersistentClient` stores to local SQLite -- no server process needed. HNSW index provides sub-millisecond similarity search. ChromaDB 1.x is current stable (v1.5.5, March 2026). Pin <2.0 to avoid future breaking changes. | RAG knowledge base |
| edgartools | >=5.6.0 | SEC EDGAR financial filings | Free, no API key, no rate limits. Parses 10-K, 10-Q, 8-K XBRL data into Python objects. v5.28.3 (April 2026) is actively maintained. Provides `Company("AAPL").get_filings()` API for structured financial statements. Use for earnings history and fundamental data that yfinance may not cover in depth. | Live market data pipeline |

**That's three new dependencies.** Everything else leverages the existing stack.

### Why NOT More Dependencies

| Avoided | Why Not |
|---------|---------|
| alpha_vantage | Requires a free API key (rate-limited to 25 requests/day on free tier). yfinance covers the same data (price history, fundamentals) without API key management. Alpha Vantage's Python lib (v3.0.0) uses `requests` (sync) and hasn't been updated since July 2024. If we later need higher-quality earnings/economic data, add it as an optional data source behind an API key config flag. |
| newsapi-python / asyncnewsapi | Requires API key. yfinance's `.news` property returns recent news for any ticker without authentication. For v3.0, yfinance news is sufficient. If deeper news analysis is needed later, add as optional source. |
| LangChain / LlamaIndex | Same reasoning as v2 -- massive dependency trees, wrong abstraction. Our RAG is straightforward: embed documents into ChromaDB, query with cosine similarity, inject results into prompts. This is 50 lines of code, not a framework. |
| sentence-transformers | Unnecessary. ChromaDB's `OllamaEmbeddingFunction` calls Ollama's embedding endpoint directly. No need for a separate embedding library when we already have Ollama running. |
| numpy / scipy | ChromaDB handles similarity search internally via HNSW. No need for manual cosine similarity calculations. If we need NumPy for other purposes, it's already a transitive dependency of chromadb. |
| pandas | yfinance returns pandas DataFrames by default, and pandas is a transitive dependency of yfinance. Do NOT add it as a direct dependency -- use it where yfinance provides it, but convert to dicts/Pydantic models at the boundary. |
| pytickersymbols | Ticker extraction from rumor text is an LLM task, not a lookup table. The orchestrator already extracts entities with type="company" -- extend it to also extract ticker symbols. A static ticker list would miss context (e.g., "the fruit company" -> AAPL). |
| pstock / yahoo-finance-async | Unmaintained async alternatives to yfinance. `pstock` last commit 2023. `yahoo-finance-async` explicitly targets a "deprecated" Yahoo API. yfinance + `asyncio.to_thread()` is safer. |
| sec-api | Paid service (free tier exists but rate-limited). edgartools provides the same data from the free SEC EDGAR API with no API key. |

### Existing Dependencies -- No Version Updates Needed

| Library | Current Pin | Recommendation | Reason |
|---------|-------------|----------------|--------|
| ollama | >=0.6.1 | **Keep as-is** | AsyncClient.embed() for generating embeddings is available in 0.6.1. ChromaDB's OllamaEmbeddingFunction calls the Ollama REST API directly, bypassing the Python library for embeddings. No new ollama features needed. |
| neo4j | >=5.28,<6.0 | **Keep as-is** | All v3 graph operations (ticker nodes, market data nodes, enriched decisions) are pure Cypher. No 6.x features needed. |
| textual | >=8.1.1 | **Keep as-is** | DataTable widget (for per-stock results), existing RichLog, Screen modes -- all available in 8.1.1+. Latest 8.2.1 is auto-resolved by uv. |
| pydantic | >=2.12.5 | **Keep as-is** | Extended AgentDecision model (add ticker, direction, expected_return, time_horizon fields) uses standard Pydantic v2 features. |
| httpx | (transitive) | **Keep as-is** | Used by ollama-python internally. Not needed directly for v3 -- yfinance handles its own HTTP, edgartools handles its own HTTP, ChromaDB handles its own HTTP. |
| jinja2 | >=3.1.6 | **Keep as-is** | Report templates for enhanced per-stock analysis sections. No changes needed. |
| aiofiles | >=25.1.0 | **Keep as-is** | Async file I/O for report export and RAG data caching. No changes needed. |

### Docker Compose -- One Addition

Add ChromaDB data persistence volume to `docker-compose.yml`. ChromaDB runs embedded (no server container), but its SQLite data directory should be mounted for persistence:

```yaml
# No new containers needed. ChromaDB runs embedded in the Python process.
# Just ensure ./data/chromadb/ is in .gitignore and persists across runs.
```

### Ollama Model -- One Addition

Pull `nomic-embed-text` for embedding generation:

```bash
ollama pull nomic-embed-text
```

Model specs: 137M parameters, 768-dim embeddings, 2048 context length, ~274MB memory, ~9,000 tokens/sec on Apple Silicon.

## Feature-by-Feature Stack Mapping

### Ticker Extraction from Seed Rumors

**No new dependencies. Extends existing orchestrator LLM pipeline.**

| Component | Technology | Integration Point |
|-----------|-----------|-------------------|
| Ticker extraction | Orchestrator LLM (qwen3.5:35b) | Extend `ORCHESTRATOR_SYSTEM_PROMPT` in `seed.py` to also extract ticker symbols. Current entity extraction already finds companies -- add a `ticker: str | None` field to `SeedEntity`. The LLM maps "Apple" -> "AAPL", "Tesla" -> "TSLA" in the same inference call. |
| Ticker validation | yfinance `Ticker.info` | After LLM extraction, validate each ticker exists by calling `yfinance.Ticker(symbol).info`. Invalid tickers (LLM hallucination) are filtered out. Wrapped in `asyncio.to_thread()`. |
| Ticker model | Pydantic | New `TickerEntity` model extending `SeedEntity` with `ticker: str`, `exchange: str | None`, `sector: str | None`. Populated by combining LLM extraction + yfinance validation. |
| Graph persistence | Neo4j via existing driver | New `:Ticker` node type linked to `:Entity` nodes via `[:HAS_TICKER]` edge. Stored during `create_cycle_with_seed_event()`. |

**Key design decision:** Ticker extraction is an LLM task, not a regex/lookup task. "The fruit company's stock will plummet" requires understanding context. The orchestrator model (35b) is more than capable. Validate with yfinance afterwards to catch hallucinated tickers.

### Live Market Data Pipeline

**New dependencies: yfinance, edgartools.**

| Component | Technology | Integration Point |
|-----------|-----------|-------------------|
| Price history | yfinance `Ticker.history()` | Fetch 6-month daily OHLCV for each extracted ticker. Returns pandas DataFrame. Convert to a `PriceHistory` Pydantic model at the boundary. |
| Earnings data | yfinance `Ticker.earnings` + edgartools | Recent quarterly earnings (EPS, revenue, surprise %). yfinance for quick access, edgartools for detailed 10-Q/10-K XBRL data if deeper analysis needed. |
| Fundamentals | yfinance `Ticker.info` | Market cap, P/E ratio, sector, industry, 52-week range, average volume. Single dict per ticker. |
| News | yfinance `Ticker.news` | Recent news headlines and summaries. Returns list of dicts with title, link, publisher. No API key needed. |
| SEC filings | edgartools `Company(ticker).get_filings()` | 10-K, 10-Q, 8-K filings for deeper fundamental context. Parse financial statements into structured data. |
| Async wrapper | `asyncio.to_thread()` + `asyncio.Lock` | All yfinance/edgartools calls wrapped in `asyncio.to_thread()` with per-ticker locking to avoid yfinance's thread-safety issue. |
| Data caching | `aiofiles` + JSON | Cache fetched market data to `./data/market_cache/{ticker}_{date}.json`. Avoid re-fetching during the same day. Check cache first, fetch on miss. |
| Data aggregation | Custom `MarketContext` Pydantic model | Aggregate all data sources into a single `MarketContext` per ticker: price summary, earnings summary, key fundamentals, recent news headlines. This is what gets injected into agent prompts. |

**Async pattern for yfinance:**

```python
import asyncio
from typing import Any

import yfinance as yf


class MarketDataFetcher:
    """Async wrapper around yfinance with per-ticker serialization."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, ticker: str) -> asyncio.Lock:
        if ticker not in self._locks:
            self._locks[ticker] = asyncio.Lock()
        return self._locks[ticker]

    async def fetch_price_history(self, ticker: str, period: str = "6mo") -> Any:
        async with self._get_lock(ticker):
            return await asyncio.to_thread(
                lambda: yf.Ticker(ticker).history(period=period)
            )

    async def fetch_info(self, ticker: str) -> dict[str, Any]:
        async with self._get_lock(ticker):
            return await asyncio.to_thread(
                lambda: dict(yf.Ticker(ticker).info)
            )
```

**Data fetch timing:** All market data is fetched AFTER ticker extraction, BEFORE simulation rounds begin. This is a new pipeline stage between seed injection and Round 1:

```
Seed Injection -> Ticker Extraction -> Market Data Fetch -> RAG Context Build -> Round 1
```

### RAG Knowledge Base (ChromaDB + nomic-embed-text)

**New dependency: chromadb. New Ollama model: nomic-embed-text.**

| Component | Technology | Integration Point |
|-----------|-----------|-------------------|
| Vector store | ChromaDB `PersistentClient` | Embedded SQLite mode at `./data/chromadb/`. No server process. One collection per data type: `earnings_reactions`, `market_patterns`, `sector_analysis`. |
| Embedding function | ChromaDB `OllamaEmbeddingFunction` | Wraps Ollama's `/api/embeddings` endpoint. Model: `nomic-embed-text`. 768-dim embeddings. Configured once, passed to collection creation. |
| Document ingestion | Custom `RAGIngestionPipeline` | At startup (or via CLI command), ingest historical earnings reaction data, market pattern documents, and sector analysis into ChromaDB. Each document is chunked, embedded, and stored with metadata (ticker, date, event_type). |
| Query interface | Custom `RAGQueryEngine` | Given a ticker + rumor context, query relevant collections for similar historical precedents. Returns top-K documents with similarity scores. Wrapped in `asyncio.to_thread()` for async safety. |
| Context formatting | Jinja2 template | Format RAG results into a structured context block injected into agent prompts: "Historical precedents: [1] When X happened to Y, the stock moved Z% over N days..." |
| Model lifecycle | Ollama model management | nomic-embed-text loaded during RAG ingestion and query phases only. Auto-unloads via Ollama's `keep_alive` timeout. Never loaded simultaneously with both worker + orchestrator. |

**ChromaDB collection schema:**

```python
import chromadb
from chromadb.utils.embedding_functions import OllamaEmbeddingFunction

ef = OllamaEmbeddingFunction(
    model_name="nomic-embed-text",
    url="http://localhost:11434/api/embeddings",
)

client = chromadb.PersistentClient(path="./data/chromadb")

earnings_collection = client.get_or_create_collection(
    name="earnings_reactions",
    embedding_function=ef,
    metadata={"hnsw:space": "cosine"},
)
```

**Memory budget for RAG:**
- ChromaDB PersistentClient: ~50-100MB base RAM (SQLite + HNSW index for <10K documents)
- nomic-embed-text when loaded: ~274MB (only during ingestion/query, not during simulation)
- HNSW index for 10K documents with 768-dim embeddings: ~30MB
- Total additional memory during simulation: <150MB (ChromaDB index in RAM, no embedding model)
- Total additional memory during ingestion: ~400MB (ChromaDB + embedding model)

This is well within the 64GB budget alongside the simulation models.

### Agent Context Enrichment

**No new dependencies. Extends existing prompt pipeline.**

| Component | Technology | Integration Point |
|-----------|-----------|-------------------|
| Context builder | Custom `ContextEnrichmentService` | For each agent inference call, build enriched context: base persona + rumor + market data + RAG precedents. Replaces the current rumor-only context in `worker.py`. |
| Market data injection | Jinja2 template | Template: `"Current market data for {{ticker}}: Price ${{price}}, 52w range ${{low}}-${{high}}, P/E {{pe}}, recent earnings {{eps_surprise}}%"` |
| RAG precedent injection | Jinja2 template | Template: `"Historical precedents:\n{% for p in precedents %}{{loop.index}}. {{p.summary}} ({{p.date}}, {{p.outcome}})\n{% endfor %}"` |
| Token budget | Custom trimming | Agent prompts now include market data + RAG context (~500-800 tokens). Monitor total prompt length against worker model context window. Trim RAG precedents first if over budget. |

**Prompt structure per agent:**

```
[System] You are {persona.name}, a {persona.bracket} with risk profile {persona.risk_profile}...
[System] Current market context for {ticker}:
  - Price: $XXX, Change: +X.X% (1mo)
  - P/E: XX.X, Market Cap: $XXXB
  - Recent earnings: +X.X% surprise
  - News: "Headline 1", "Headline 2"
[System] Historical precedents:
  1. Similar event in 2023: Stock moved +15% over 2 weeks
  2. Sector-wide impact: Tech sector dropped 3% on similar news
[User] Seed rumor: "..."
[User] Peer decisions (Round 2+): ...
```

### Enhanced AgentDecision Output

**No new dependencies. Extends existing Pydantic model.**

| Component | Technology | Integration Point |
|-----------|-----------|-------------------|
| Extended model | Pydantic `AgentDecision` | Add fields: `ticker: str`, `direction: Literal["long", "short", "neutral"]`, `expected_return_pct: float`, `time_horizon_days: int`, `rationale_tags: list[str]`. Frozen model, backward-compatible (all new fields have defaults). |
| JSON schema update | Pydantic JSON schema generation | Worker prompt instructs model to output the extended JSON. Parsing uses existing 3-tier fallback in `parsing.py`. |
| Graph persistence | Neo4j via existing driver | Extended `Decision` node properties. Add ticker, direction, expected_return, time_horizon to the existing UNWIND batch write. |
| Aggregation | Custom `ConsensusAggregator` | New aggregation logic: per-ticker consensus (not just per-simulation). Group decisions by ticker, compute confidence-weighted mean expected return, majority direction, time horizon distribution. |

**Extended AgentDecision model:**

```python
class AgentDecision(BaseModel, frozen=True):
    """Structured decision output from an agent inference call."""
    # Existing fields (backward-compatible)
    signal: SignalType
    confidence: float = Field(ge=0.0, le=1.0)
    sentiment: float = Field(ge=-1.0, le=1.0, default=0.0)
    rationale: str = ""
    cited_agents: list[str] = Field(default_factory=list)
    # v3 additions
    ticker: str = ""
    direction: str = ""  # "long", "short", "neutral"
    expected_return_pct: float = 0.0
    time_horizon_days: int = 0
```

### Improved TUI Results Display

**No new dependencies. Extends existing Textual TUI.**

| Component | Technology | Integration Point |
|-----------|-----------|-------------------|
| Per-stock breakdown | Textual `DataTable` widget | After simulation, push a `ResultsScreen` with a DataTable showing: ticker, consensus direction, mean expected return, confidence, bracket breakdown. Each row is one ticker. |
| Bracket disagreement | Textual `Static` + Rich renderables | Bar chart showing per-bracket signal distribution for each ticker. Use Rich `Bar` and `Table` renderables within a Textual container. |
| Confidence heatmap | Existing `AgentGrid` | Color-code agent cells by confidence AND direction (green=long, red=short, yellow=neutral, brightness=confidence). Extend the existing HSL color mapping. |
| Consensus summary | Textual `RichLog` | Final consensus text rendered in the existing `RationaleSidebar` or a dedicated results panel: "AAPL: 73 agents LONG (avg +12.3% over 14d, confidence 0.78)" |
| Export | aiofiles + Jinja2 | Enhanced report template includes per-stock analysis sections. No new deps needed. |

## Installation

```bash
# New v3 dependencies (add to existing pyproject.toml)
uv add "yfinance>=1.2.0" "chromadb>=1.5.0,<2.0" "edgartools>=5.6.0"

# Pull embedding model
ollama pull nomic-embed-text

# Create data directories
mkdir -p data/chromadb data/market_cache

# Dev dependencies (no changes)
# Existing: pytest, pytest-asyncio, pytest-cov, ruff, mypy
```

Updated `pyproject.toml` dependencies section:

```toml
dependencies = [
    "pydantic>=2.12.5",
    "pydantic-settings>=2.13.1",
    "structlog>=25.5.0",
    "psutil>=7.2.2",
    "ollama>=0.6.1",
    "backoff>=2.2.1",
    "neo4j>=5.28,<6.0",
    "textual>=8.1.1",
    "jinja2>=3.1.6",
    "aiofiles>=25.1.0",
    # v3 additions: live market data & RAG
    "yfinance>=1.2.0",
    "chromadb>=1.5.0,<2.0",
    "edgartools>=5.6.0",
]
```

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| alpha_vantage | Requires API key (25 req/day free tier). Sync-only (`requests`). Last updated July 2024. yfinance covers same data without authentication. | yfinance for price/earnings/fundamentals |
| newsapi-python | Requires API key. Rate-limited. yfinance `.news` provides recent headlines per ticker without authentication. | yfinance `Ticker.news` |
| LangChain / LlamaIndex | Framework overhead for a simple embed-store-query pattern. ChromaDB + Ollama embeddings + our existing OllamaClient handles the full RAG pipeline in ~50 LOC. | Direct ChromaDB + OllamaEmbeddingFunction |
| sentence-transformers | Heavy dep (~2GB of PyTorch). Ollama already serves nomic-embed-text via its API. ChromaDB's OllamaEmbeddingFunction wraps this cleanly. | Ollama embeddings via ChromaDB integration |
| FAISS / Qdrant / Weaviate / Milvus | Over-engineered for our scale (<10K documents). FAISS lacks persistence without extra code. Qdrant/Weaviate/Milvus require separate server processes. ChromaDB's embedded PersistentClient is the right tool for local-first, small-scale RAG. | ChromaDB PersistentClient |
| pandas (as direct dep) | Already a transitive dep of yfinance. Don't add it directly -- use it where yfinance provides DataFrames, convert to Pydantic at boundaries. Adding it directly couples us to DataFrame patterns. | Pydantic models at service boundaries |
| pytickersymbols | Static ticker lookup table. Misses context-dependent extraction ("the fruit company" -> AAPL). LLM-based extraction is more robust and we already have the orchestrator doing entity extraction. | Extend orchestrator entity extraction prompt |
| pstock / yahoo-finance-async | Unmaintained. pstock last commit 2023. yahoo-finance-async targets deprecated Yahoo API. | yfinance + asyncio.to_thread() |
| sec-api | Paid service. edgartools provides same SEC EDGAR data for free without API key. | edgartools |
| nomic-embed-text-v2-moe | Newer MoE model, but larger and multilingual-focused. v1.5 is sufficient for English financial text and has well-tested Ollama/ChromaDB integration. Upgrade later if embedding quality is insufficient. | nomic-embed-text (v1.5) |
| ChromaDB AsyncHttpClient | Requires running a separate ChromaDB server process. Adds Docker complexity for minimal benefit at our scale. PersistentClient + asyncio.to_thread() is simpler. | ChromaDB PersistentClient + asyncio.to_thread() |

## Simulation Pipeline Extension

The v3 pipeline adds three new stages between seed injection and Round 1:

```
[Existing] Seed Injection (orchestrator: extract entities + sentiment)
    |
    v
[NEW] Ticker Extraction (orchestrator: extract ticker symbols from entities)
    |
    v
[NEW] Market Data Fetch (yfinance + edgartools: price, earnings, fundamentals, news)
    |
    v
[NEW] RAG Context Build (ChromaDB: query historical precedents for each ticker)
    |
    v
[Existing] Round 1 (workers: now with enriched context)
    |
    v
[Existing] Round 2 (workers: peer influence + enriched context)
    |
    v
[Existing] Round 3 (workers: final consensus + enriched context)
    |
    v
[Existing] Post-simulation (interviews, report -- now with per-stock analysis)
```

## Model Strategy for v3 Features

| Feature | Model | Why | Memory Impact |
|---------|-------|-----|---------------|
| Ticker extraction | Orchestrator (qwen3.5:35b) | Extension of existing seed parsing. Same inference call, extended JSON output schema. | None (runs during existing orchestrator phase) |
| Market data fetch | N/A (API calls) | yfinance/edgartools are HTTP clients, no LLM needed. | ~50MB for yfinance/pandas in-process |
| RAG ingestion | nomic-embed-text (137M) | Embedding model for ChromaDB document ingestion. Run before simulation when no other models loaded. | ~274MB during ingestion only |
| RAG query | nomic-embed-text (137M) | Brief load to embed query text for ChromaDB similarity search. | ~274MB, loaded/unloaded in <3s |
| Agent context enrichment | N/A (prompt construction) | Pure Python string/template operations. No LLM needed. | Negligible |
| Enhanced decisions | Worker (qwen3.5:9b) | Same model, extended JSON output. Slightly more output tokens per agent (~50 more tokens for new fields). | ~5% more inference time per agent |
| TUI results | N/A (UI rendering) | Textual widget rendering. No LLM needed. | Negligible |

**Model lifecycle for v3 simulation:**

1. Load orchestrator -> Seed injection + ticker extraction -> Unload orchestrator
2. Load nomic-embed-text -> RAG query for precedents -> Unload nomic-embed-text
3. Fetch market data (no model needed, API calls only)
4. Load worker -> Rounds 1-3 with enriched context -> Keep worker loaded
5. Offer agent interviews (worker still loaded)
6. Unload worker -> Load orchestrator -> Generate report -> Unload orchestrator

## Version Compatibility Matrix

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| yfinance >=1.2.0 | Python >=3.6, pandas (transitive) | No conflicts with existing stack. pandas is not a direct dependency of AlphaSwarm. |
| chromadb >=1.5.0,<2.0 | Python >=3.9 | Brings numpy, onnxruntime as transitive deps. onnxruntime is only used for ChromaDB's default embedding function -- we use OllamaEmbeddingFunction instead. May add ~200MB to installed package size. |
| edgartools >=5.6.0 | Python >=3.10 | Brings lxml, pyarrow as transitive deps. These are isolated -- no conflicts with existing stack. |
| nomic-embed-text (Ollama) | Ollama >=0.1.26 | We run Ollama >=0.6.1. Fully compatible. |
| chromadb + neo4j | No conflicts | ChromaDB uses SQLite, Neo4j uses its own storage. Completely independent data stores serving different purposes (vector similarity vs. graph traversal). |

## Dependency Weight Analysis

Concern: chromadb and edgartools bring significant transitive dependency trees. Here's the impact:

| New Direct Dep | Transitive Deps Added | Disk Size | RAM Impact | Justification |
|---------------|----------------------|-----------|------------|---------------|
| yfinance | pandas, requests, lxml, beautifulsoup4, html5lib | ~50MB | ~30MB (pandas import) | Essential -- no lighter alternative for free market data |
| chromadb | numpy, onnxruntime, tokenizers, tqdm, httpx, grpcio | ~300MB | ~100MB (client + HNSW index) | Essential -- vector search for RAG. Alternatives (FAISS, manual cosine) are more code for less capability |
| edgartools | lxml (shared with yfinance), pyarrow, httpx (shared with existing) | ~80MB | ~20MB | Optional but valuable -- enriches fundamentals data beyond yfinance. Can defer if dependency weight is concerning |

**Total new disk footprint:** ~430MB of installed packages. Acceptable for a development machine targeting M1 Max 64GB.

**If dependency weight is a concern:** edgartools can be deferred to a later phase. yfinance covers basic earnings and fundamentals. edgartools adds depth (10-K/10-Q XBRL parsing, historical filings) but is not strictly required for v3 MVP.

## Sources

- [yfinance PyPI (v1.2.0)](https://pypi.org/project/yfinance/) -- latest version, Feb 2026
- [yfinance GitHub](https://github.com/ranaroussi/yfinance) -- actively maintained
- [yfinance thread-safety issue #2557](https://github.com/ranaroussi/yfinance/issues/2557) -- confirmed download() is not thread-safe
- [ChromaDB PyPI (v1.5.5)](https://pypi.org/project/chromadb/) -- latest version, March 2026
- [ChromaDB Ollama integration docs](https://docs.trychroma.com/integrations/embedding-models/ollama) -- OllamaEmbeddingFunction usage
- [ChromaDB PersistentClient docs](https://docs.trychroma.com/reference/python/client) -- embedded SQLite mode
- [ChromaDB migration guide](https://docs.trychroma.com/docs/overview/migration) -- 0.x to 1.x breaking changes
- [ChromaDB resource requirements](https://cookbook.chromadb.dev/core/resources/) -- memory/disk estimates
- [edgartools PyPI (v5.28.3)](https://pypi.org/project/edgartools/) -- latest version, April 2026
- [edgartools documentation](https://edgartools.readthedocs.io/) -- Complete Guide to SEC Filings in Python
- [nomic-embed-text Ollama registry](https://ollama.com/library/nomic-embed-text) -- model specs
- [nomic-embed-text-v1.5 memory requirements](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5/discussions/15) -- ~274MB RAM
- [Ollama embedding models blog](https://ollama.com/blog/embedding-models) -- embedding API usage
- [Ollama Python library (v0.6.1)](https://pypi.org/project/ollama/) -- AsyncClient.embed() API
- [Textual DataTable widget](https://textual.textualize.io/widgets/data_table/) -- table display for results
- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) -- free, no-auth API

---
*Stack research for: AlphaSwarm v3.0 Stock-Specific Recommendations with Live Data & RAG*
*Researched: 2026-04-05*
*Builds on: v2.0 stack research from 2026-03-31*
