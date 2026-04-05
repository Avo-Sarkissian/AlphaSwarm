# Architecture Research: v3.0 Stock-Specific Recommendations with Live Data & RAG

**Domain:** Local-first multi-agent financial simulation with live market data and RAG enrichment
**Researched:** 2026-04-05
**Confidence:** MEDIUM-HIGH (new external dependencies reduce confidence vs v2.0 internal-only changes)

This document maps how ticker extraction, live market data, RAG knowledge base, and enhanced agent decisions integrate with the existing AlphaSwarm architecture. It identifies new components, modification points in existing code, data flows, and a dependency-aware build order.

---

## Existing Architecture Baseline (Post-v2.0)

The v2.0 architecture is a pipeline-with-feedback-loop:

```
CLI/TUI Entry
    |
    v
AppState (DI container)
    |
    +-- settings: AppSettings
    +-- governor: ResourceGovernor (TokenPool, 5-state machine)
    +-- state_store: StateStore (mutable, snapshot-based)
    +-- ollama_client: OllamaClient (AsyncClient wrapper)
    +-- model_manager: OllamaModelManager
    +-- graph_manager: GraphStateManager (Neo4j async driver)
    +-- personas: list[AgentPersona]
    |
    v
SeedInjector (inject_seed)
    | uses orchestrator LLM (qwen3.5:32b) for entity extraction
    | calls generate_modifiers() for dynamic persona generation
    | persists Cycle + Entity nodes to Neo4j
    |
    v
SimulationEngine (run_simulation)
    | 3x rounds: dispatch_wave() -> 100 agent inferences per round
    | AgentWorker.infer() -> OllamaClient.chat() with governor semaphore
    | per-agent: StateStore updates, WriteBuffer episodes, Neo4j decisions
    |
    v
Post-Simulation (interview, report)
```

**Key integration constraints from existing code (MUST respect):**

1. **AppState is the sole DI container.** All new components must be wirable through `AppState`.
2. **StateStore.snapshot() is the only TUI data path.** New UI data goes through `StateStore`.
3. **GraphStateManager uses session-per-method pattern.** New queries add methods, not new managers.
4. **dispatch_wave() is the ONLY batch inference path.** No bare `create_task` calls.
5. **ResourceGovernor must gate ALL inference.** Embedding calls must also respect concurrency.
6. **Model lifecycle is explicit.** load_model -> use -> unload_model. Max 2 models loaded at once.
7. **Worker prompt context budget is ~4000 chars.** `_format_peer_context()` enforces this cap.
8. **yfinance is synchronous.** Must use `asyncio.to_thread()` to avoid blocking the event loop.

---

## New Components Required

### 1. TickerExtractor (`src/alphaswarm/ticker.py`)

**Purpose:** Extract stock ticker symbols from seed rumor text using the orchestrator LLM.

**Approach:** Extend the existing `inject_seed()` pipeline -- the orchestrator is already loaded and parsing entities. Add ticker extraction to the same orchestrator session to avoid an extra model load/unload cycle.

**Design:**

```python
# New type in types.py
class TickerSymbol(BaseModel, frozen=True):
    symbol: str          # e.g., "AAPL"
    company_name: str    # e.g., "Apple Inc."
    relevance: float     # 0.0-1.0, how central to the rumor
    direction_hint: str  # "bullish" | "bearish" | "neutral" from rumor context

# New type extending SeedEvent
class EnrichedSeedEvent(BaseModel, frozen=True):
    raw_rumor: str
    entities: list[SeedEntity]
    overall_sentiment: float
    tickers: list[TickerSymbol]  # NEW: extracted tickers

# In seed.py: augment ORCHESTRATOR_SYSTEM_PROMPT to also extract tickers
# "For each company entity, also provide ticker symbol if identifiable"
```

**Integration point:** Modify `inject_seed()` to request ticker extraction in the same orchestrator chat call. The JSON output schema adds a `tickers` array alongside `entities`. Parse with the existing 3-tier fallback via an extended `parse_seed_event()`.

**Validation:** After LLM extraction, validate tickers against yfinance (`yf.Ticker(symbol).info` returns empty dict for invalid symbols). This validation happens AFTER the orchestrator unloads, using `asyncio.to_thread()` since yfinance is synchronous.

**Why not a separate NLP model:** The orchestrator LLM (qwen3.5:32b) is already loaded for entity extraction and is highly capable of mapping company names to ticker symbols. A separate NLP step would add complexity and a second model load. The LLM approach is sufficient for the ~1-5 tickers per rumor.

**Confidence:** HIGH -- LLMs are excellent at company-to-ticker mapping. Validation against yfinance catches hallucinated symbols.

### 2. MarketDataProvider (`src/alphaswarm/market_data.py`)

**Purpose:** Async pipeline for fetching live market data for extracted tickers.

**Design:**

```python
@dataclass(frozen=True)
class MarketSnapshot:
    """Immutable container for all market data about a single ticker."""
    symbol: str
    current_price: float | None
    price_change_1d: float | None
    price_change_5d: float | None
    price_change_30d: float | None
    market_cap: float | None
    pe_ratio: float | None
    volume_avg: float | None
    recent_earnings_surprise: float | None  # % surprise vs estimate
    sector: str | None
    news_headlines: tuple[str, ...]  # last 5 relevant headlines
    fetched_at: float  # time.time() for staleness checks

class MarketDataProvider:
    """Async market data aggregator. Uses asyncio.to_thread for sync APIs."""

    async def fetch_snapshot(self, symbol: str) -> MarketSnapshot: ...
    async def fetch_all(self, symbols: list[str]) -> dict[str, MarketSnapshot]: ...
```

**Data sources (priority order):**

| Source | Data Type | Async Strategy | Rate Limits | API Key? |
|--------|-----------|---------------|-------------|----------|
| yfinance | Price history, fundamentals, earnings | `asyncio.to_thread()` (yfinance is sync, NOT thread-safe for same ticker) | Yahoo unofficial API, no hard limit but ~2000 req/hour practical | No |
| SEC EDGAR (data.sec.gov) | 10-K/10-Q filings, earnings | `httpx.AsyncClient` (RESTful JSON API) | 10 req/second | No (User-Agent required) |
| NewsAPI | Financial news headlines | `httpx.AsyncClient` | 100 req/day (free), 1000/day (developer) | Yes |
| Alpha Vantage | Earnings calendar, fundamentals | `httpx.AsyncClient` via `alpha_vantage.async_support` | 25 req/day (free), 75 req/min (premium) | Yes |

**Critical design decision:** yfinance is the primary data source because it requires no API key and provides comprehensive data (price history, fundamentals, earnings, news). Alpha Vantage and NewsAPI are supplementary -- used when yfinance data is insufficient or for richer news coverage. SEC EDGAR is used for authoritative earnings data.

**Thread safety:** yfinance's `download()` is NOT thread-safe for the same ticker. Each ticker fetch must be serialized or use separate `Ticker()` instances. Use `asyncio.to_thread()` with a single-ticker function, not a shared download call.

**Memory concern:** yfinance returns pandas DataFrames. For 1-5 tickers with 30 days of history, memory usage is negligible (~1-5 MB). Do NOT fetch multi-year history -- cap at 90 days maximum.

**Integration:** MarketDataProvider is a new attribute on AppState. Called AFTER ticker extraction completes (during the seed injection phase, but after orchestrator unloads). Data is stored in-memory as `dict[str, MarketSnapshot]` and passed through the pipeline.

**Confidence:** MEDIUM-HIGH -- yfinance is well-established but is an unofficial API subject to breakage. Alpha Vantage free tier is very limited (25 req/day). The design should gracefully degrade when any source fails.

### 3. RAGKnowledgeBase (`src/alphaswarm/rag.py`)

**Purpose:** ChromaDB vector store with Ollama embeddings for historical earnings reactions and market patterns.

**Design:**

```python
@dataclass(frozen=True)
class RAGDocument:
    """A single document in the knowledge base."""
    doc_id: str
    content: str
    metadata: dict[str, str | float]  # ticker, event_type, date, sector, etc.

@dataclass(frozen=True)
class RAGResult:
    """A single retrieval result."""
    content: str
    score: float
    metadata: dict[str, str | float]

class RAGKnowledgeBase:
    """ChromaDB-backed knowledge base with Ollama embeddings."""

    def __init__(self, persist_dir: str, ollama_base_url: str): ...
    async def initialize(self) -> None: ...  # Create/load collection
    async def add_documents(self, docs: list[RAGDocument]) -> None: ...
    async def query(self, query_text: str, n_results: int = 5,
                    where: dict | None = None) -> list[RAGResult]: ...
    async def close(self) -> None: ...
```

**Technology choice:** ChromaDB PersistentClient (embedded mode, no server) + OllamaEmbeddingFunction with nomic-embed-text model.

**Why ChromaDB PersistentClient (not AsyncHttpClient):**
- Embedded mode means no Docker container beyond Neo4j. Local-first philosophy.
- PersistentClient stores to disk at a path. Data survives process restarts.
- The async concern: ChromaDB's PersistentClient is synchronous. Wrap operations in `asyncio.to_thread()` -- same pattern as yfinance.
- For AlphaSwarm's scale (~100-1000 documents, 1-5 queries per simulation), async performance of the vector store is NOT a bottleneck. Each query takes <100ms locally.

**Why NOT AsyncHttpClient:**
- Requires running a separate ChromaDB server (Docker or standalone process).
- Adds operational complexity for marginal performance gain at our scale.
- Recent bugs reported with AsyncHttpClient in ChromaDB 1.x (HTTP 422 errors, auth issues).
- PersistentClient + `asyncio.to_thread()` is simpler and more reliable.

**Embedding model:** `nomic-embed-text` via Ollama.
- 768-dimension embeddings, 8192 token context window.
- Runs locally via Ollama -- no cloud API needed.
- ChromaDB's `OllamaEmbeddingFunction` wraps this cleanly.
- **Memory concern:** nomic-embed-text is ~270MB. It can be loaded alongside the worker model, but the 2-model limit means it CANNOT be loaded simultaneously with both orchestrator AND worker. Embedding calls must happen when the orchestrator is NOT loaded (i.e., after seed injection unloads the orchestrator, before worker model loads for Round 1).

**Embedding lifecycle and ResourceGovernor:**
- Embedding is a lightweight operation (~50ms per document, ~100ms per query).
- nomic-embed-text loads into Ollama as a separate model. It counts toward the 2-model limit.
- Strategy: Load nomic-embed-text -> embed documents -> query for context -> unload -> load worker model.
- Alternative: Set `keep_alive=0` on embedding calls so Ollama auto-unloads immediately after use.

**Knowledge base content (seeded offline, enriched at runtime):**

| Content Type | Source | When Ingested | Example |
|-------------|--------|---------------|---------|
| Historical earnings reactions | Pre-built dataset (CSV/JSON) | App startup / first run | "AAPL Q3 2025: +8% earnings surprise, stock rose 3.2% next day" |
| Sector pattern templates | Pre-built dataset | App startup | "Semiconductor shortages historically lead to 15-20% sector premium" |
| Previous simulation results | Post-simulation export | After each simulation run | "Simulation 2026-04-01: 72% BUY consensus on NVDA earnings beat rumor" |
| Live news context | NewsAPI/yfinance during runtime | During market data fetch | "Breaking: Fed signals rate pause, tech stocks rally" |

**Integration:** RAGKnowledgeBase is a new attribute on AppState. Initialized at startup with `PersistentClient(path=".chromadb")`. Queried during the context enrichment phase (between seed injection and Round 1 dispatch).

**Confidence:** MEDIUM -- ChromaDB PersistentClient + OllamaEmbeddingFunction is a well-documented pattern, but the model loading choreography with the 2-model limit needs careful testing. The `asyncio.to_thread()` wrapping of synchronous ChromaDB operations is standard but adds complexity.

### 4. ContextEnricher (`src/alphaswarm/context.py`)

**Purpose:** Assembles enriched context for agent prompts by combining live market data and RAG-retrieved precedents.

**Design:**

```python
@dataclass(frozen=True)
class EnrichedContext:
    """Complete context package injected into agent prompts."""
    market_data_section: str   # Formatted market data for prompt
    rag_section: str           # Formatted RAG results for prompt
    total_chars: int           # For budget tracking

class ContextEnricher:
    """Assembles market data + RAG into prompt-ready context sections."""

    def __init__(self, market_provider: MarketDataProvider,
                 rag_kb: RAGKnowledgeBase): ...

    async def build_context(
        self,
        seed_event: EnrichedSeedEvent,
        market_snapshots: dict[str, MarketSnapshot],
        query_text: str,
        budget: int = 2000,  # chars, to stay within worker prompt limits
    ) -> EnrichedContext: ...
```

**Prompt budget management (CRITICAL):**

The existing worker prompt is already substantial:
- System prompt template: ~200-300 words (~1500 chars)
- Agent header + modifier: ~50 words (~300 chars)
- JSON output instructions: ~40 words (~250 chars)
- Peer context (Rounds 2-3): up to 4000 chars
- **Available for enrichment: ~2000 chars**

The enriched context must fit within ~2000 characters to avoid context window overflow on qwen3.5:7b (default ~4K tokens). This means:
- Market data section: ~800 chars (price, key metrics, earnings surprise)
- RAG section: ~800 chars (2-3 most relevant historical precedents)
- Buffer: ~400 chars

**Format for prompt injection:**

```
MARKET DATA (as of {timestamp}):
{symbol}: ${price} ({change}% 30d), P/E: {pe}, Earnings surprise: {surprise}%
[Repeat for each ticker, max 3 tickers]

HISTORICAL PRECEDENTS:
1. {rag_result_1_summary}
2. {rag_result_2_summary}

Use the above data to inform your analysis. Your independent judgment takes priority.
```

**Integration point:** The `ContextEnricher.build_context()` output is injected as a system message between the persona system prompt and the user message (seed rumor) in `AgentWorker.infer()`. This requires modifying the worker to accept an optional `enriched_context: str` parameter.

**Confidence:** HIGH -- this is pure Python string formatting and prompt engineering. No external dependencies.

### 5. Enhanced AgentDecision (`types.py` modification)

**Purpose:** Extend AgentDecision with ticker-specific fields.

**Design:**

```python
class EnhancedAgentDecision(BaseModel, frozen=True):
    """Extended decision output with ticker-specific analysis."""
    signal: SignalType
    confidence: float = Field(ge=0.0, le=1.0)
    sentiment: float = Field(ge=-1.0, le=1.0, default=0.0)
    rationale: str = ""
    cited_agents: list[str] = Field(default_factory=list)
    # NEW v3.0 fields:
    ticker: str | None = None           # Primary ticker for this decision
    expected_return: float | None = None # Expected return % (e.g., 5.0 = +5%)
    time_horizon: str | None = None     # "1d" | "1w" | "1m" | "3m"

# JSON output instructions updated:
JSON_OUTPUT_INSTRUCTIONS_V3 = (
    '\n\nRespond ONLY with a JSON object:\n'
    '{"signal": "buy"|"sell"|"hold", "confidence": 0.0-1.0, '
    '"sentiment": -1.0 to 1.0, "rationale": "brief reasoning", '
    '"cited_agents": [], '
    '"ticker": "SYMBOL or null", "expected_return": float or null, '
    '"time_horizon": "1d"|"1w"|"1m"|"3m" or null}'
)
```

**Backward compatibility approach:** Keep the existing `AgentDecision` type and create `EnhancedAgentDecision` that extends it (or add optional fields with None defaults to the existing type). The `parse_agent_decision()` function already handles missing/extra fields gracefully via Pydantic's model_validate. Adding new fields with `None` defaults to the existing `AgentDecision` is the cleanest approach -- no separate type needed.

**Integration:** Modify `parse_agent_decision()` to handle the new optional fields. If the LLM returns them, they're captured. If not (fallback), they default to None. No breakage.

**Confidence:** HIGH -- adding optional fields to an existing Pydantic model with None defaults is non-breaking.

---

## Existing Components Requiring Modification

### 1. `types.py` -- Add TickerSymbol, Extend AgentDecision and SeedEvent

**Changes:**
- Add `TickerSymbol` model
- Add optional fields to `AgentDecision`: `ticker`, `expected_return`, `time_horizon`
- Add optional `tickers: list[TickerSymbol] = []` to `SeedEvent` (or create `EnrichedSeedEvent` subclass)

**Risk:** LOW -- all new fields have None/empty defaults.

### 2. `seed.py` -- Augment Orchestrator Prompt for Ticker Extraction

**Changes:**
- Extend `ORCHESTRATOR_SYSTEM_PROMPT` to request ticker symbols in the JSON output
- Modify the response parsing to extract `tickers` array
- Add ticker validation step (yfinance lookup via `asyncio.to_thread()`)

**Risk:** MEDIUM -- changing the orchestrator prompt could affect entity extraction quality. Must test that existing entity extraction still works correctly with the augmented prompt.

### 3. `parsing.py` -- Parse Ticker and Enhanced Decision Fields

**Changes:**
- Extend `parse_seed_event()` to handle `tickers` array in JSON output
- Extend `parse_agent_decision()` to handle new optional fields
- Both use 3-tier fallback; new fields simply default to None on parse failure

**Risk:** LOW -- additive parsing, existing fallback handles missing fields.

### 4. `worker.py` -- Accept Enriched Context

**Changes:**
- `AgentWorker.infer()` gains optional `market_context: str | None = None` parameter
- Insert market_context as a system message between persona prompt and user message
- Budget cap enforcement: truncate market_context if it exceeds 2000 chars

```python
async def infer(
    self,
    user_message: str,
    peer_context: str | None = None,
    market_context: str | None = None,  # NEW: live data + RAG context
) -> AgentDecision:
    messages: list[dict[str, str]] = [
        {"role": "system", "content": self._persona["system_prompt"]},
    ]
    if market_context:
        messages.append({"role": "system", "content": market_context})
    if peer_context:
        messages.append({"role": "system", "content": f"Peer context:\n{peer_context}"})
    messages.append({"role": "user", "content": user_message})
```

**Risk:** LOW -- optional parameter, no change to existing call sites that don't use it.

### 5. `config.py` -- New Settings and Updated JSON Instructions

**Changes:**
- Add `MarketDataSettings` model (API keys, cache durations, enabled sources)
- Add `RAGSettings` model (persist_dir, embedding model, collection name)
- Add both to `AppSettings`
- Update `JSON_OUTPUT_INSTRUCTIONS` to include new fields when v3 mode is enabled

**Risk:** LOW -- new settings with defaults. Existing config is untouched unless v3 features are enabled.

### 6. `simulation.py` -- Context Enrichment Phase

**Changes:**
- `run_simulation()` gains a new phase between seed injection and Round 1:
  1. Seed injection (existing) -> returns tickers
  2. **NEW: Market data fetch** -> MarketDataProvider.fetch_all(tickers)
  3. **NEW: RAG query** -> RAGKnowledgeBase.query(rumor + tickers)
  4. **NEW: Context assembly** -> ContextEnricher.build_context()
  5. Round 1 dispatch with enriched context (modified)
  6. Rounds 2-3 (existing, but with enriched context passed through)

```python
async def run_simulation(..., market_provider=None, rag_kb=None):
    # 1. Seed injection (existing)
    cycle_id, parsed_result, modifier_result = await inject_seed(...)

    # 2. NEW: Fetch market data for extracted tickers
    market_snapshots = {}
    if market_provider and parsed_result.seed_event.tickers:
        symbols = [t.symbol for t in parsed_result.seed_event.tickers]
        market_snapshots = await market_provider.fetch_all(symbols)

    # 3. NEW: Query RAG knowledge base
    rag_context = ""
    if rag_kb:
        enricher = ContextEnricher(market_provider, rag_kb)
        enriched = await enricher.build_context(
            parsed_result.seed_event, market_snapshots, rumor
        )
        rag_context = enriched.market_data_section + enriched.rag_section

    # 4. Round 1 dispatch with enriched context
    # Pass rag_context to dispatch_wave -> worker.infer(market_context=rag_context)
```

**Risk:** MEDIUM -- this is the most complex modification. The new phase must not block the event loop and must handle failures gracefully (if market data fetch fails, proceed without it).

### 7. `batch_dispatcher.py` -- Thread Market Context Through

**Changes:**
- `dispatch_wave()` gains optional `market_context: str | None = None` parameter
- Threads it through to `_safe_agent_inference()` -> `AgentWorker.infer()`

**Risk:** LOW -- optional parameter passthrough.

### 8. `state.py` -- Extended StateSnapshot for TUI

**Changes:**
- Add to `StateSnapshot`: `market_data: dict[str, MarketSnapshot] | None = None`
- Add to `StateSnapshot`: `extracted_tickers: tuple[str, ...] = ()`
- Add to `BracketSummary`: optional per-ticker consensus fields

**Risk:** LOW -- additive fields with None/empty defaults.

### 9. `app.py` -- Wire New Components into AppState

**Changes:**
- Add `market_provider: MarketDataProvider | None = None` to AppState
- Add `rag_kb: RAGKnowledgeBase | None = None` to AppState
- Extend `create_app_state()` with `with_market_data: bool = False` and `with_rag: bool = False`

**Risk:** LOW -- follows existing pattern (cf. `with_ollama`, `with_neo4j`).

### 10. `tui.py` -- Display Enhanced Results

**Changes:**
- Add a market data panel (or extend HeaderBar) showing extracted tickers and live prices
- Extend BracketPanel to show per-ticker consensus when available
- Extend RationaleSidebar to show ticker + direction in entries

**Risk:** MEDIUM -- TUI changes require careful layout management. The existing CSS and widget structure must accommodate new panels without breaking the 10x10 grid layout.

### 11. `graph.py` -- Store Ticker and Market Context

**Changes:**
- Extend `create_cycle_with_seed_event()` to store TickerSymbol nodes linked to Cycle
- Add new node type: `:Ticker {symbol, company_name}` with `:MENTIONS` edge from Cycle
- Extend Decision nodes with optional ticker field
- New query methods for per-ticker consensus aggregation (used by report engine)

**Risk:** LOW-MEDIUM -- new node types and relationships follow existing patterns. Must add schema constraints for Ticker.symbol uniqueness.

---

## Data Flow: Complete v3.0 Pipeline

```
User enters seed rumor
        |
        v
[1] inject_seed() ─── Orchestrator LLM ─── Parse entities + tickers
        |                                        |
        | cycle_id, SeedEvent w/ tickers         | persist to Neo4j
        v                                        v
[2] Validate tickers ── asyncio.to_thread(yfinance) ── filter invalid symbols
        |
        v
[3] Fetch market data ── asyncio.to_thread(yfinance) + httpx(EDGAR/NewsAPI)
        |                     |
        | MarketSnapshot(s)   | (parallel per ticker, ~2-5 seconds)
        v                     v
[4] Load nomic-embed-text ── Ollama embed ── Query ChromaDB
        |                                       |
        | RAGResult(s)                           | (top 3-5 precedents)
        v                                       v
[5] ContextEnricher ── assemble prompt sections ── budget cap 2000 chars
        |
        | EnrichedContext
        v
[6] Unload nomic-embed-text (or keep_alive=0) ── Load worker model
        |
        v
[7] dispatch_wave() Round 1 ── 100 agents with enriched context
        |
        v
[8] dispatch_wave() Round 2 ── peer context + enriched context
        |
        v
[9] dispatch_wave() Round 3 ── peer context + enriched context
        |
        v
[10] Post-simulation: per-ticker consensus aggregation, report, interview
```

**Timing estimates for new phases (M1 Max 64GB):**

| Phase | Estimated Duration | Blocking? |
|-------|-------------------|-----------|
| Ticker validation (yfinance) | 1-3 seconds | No (to_thread) |
| Market data fetch (yfinance + APIs) | 2-8 seconds | No (to_thread + httpx async) |
| Embedding model load | 2-5 seconds | No (Ollama async) |
| RAG query (ChromaDB) | 0.1-0.5 seconds | No (to_thread) |
| Context assembly | <0.01 seconds | No |

**Total new overhead: 5-17 seconds** before Round 1 begins. Acceptable given the 3-round simulation takes 3-10 minutes.

---

## Model Loading Choreography (CRITICAL)

The 2-model limit (`OLLAMA_MAX_LOADED_MODELS=2`) creates a strict ordering requirement:

```
Timeline:
  t0 ── Load orchestrator (qwen3.5:32b) ── seed injection + ticker extraction
  t1 ── Unload orchestrator
  t2 ── Market data fetch (no model needed, HTTP only)
  t3 ── Load nomic-embed-text ── RAG query
  t4 ── Unload nomic-embed-text (or set keep_alive=0)
  t5 ── Load worker (qwen3.5:7b) ── Rounds 1-3
  t6 ── [Worker stays loaded for interview/report]
```

**Alternative approach (simpler, slightly less optimal):**
Skip explicit nomic-embed-text management. Use ChromaDB's `OllamaEmbeddingFunction` which makes HTTP calls to Ollama's `/api/embeddings` endpoint. Ollama will auto-load nomic-embed-text on first embedding request and auto-unload based on `keep_alive`. Set `keep_alive=0` in the embedding request to force immediate unload after the batch.

This avoids adding nomic-embed-text lifecycle management to `OllamaModelManager` -- the embedding model is treated as ephemeral, not managed.

**Recommendation:** Use the alternative approach (auto-load with keep_alive=0). Simpler code, same result. The embedding model is small (~270MB) and loads in 2-3 seconds. The overhead is acceptable for a one-time per-simulation operation.

**Confidence:** HIGH -- Ollama's auto-loading behavior is well-documented. The keep_alive=0 pattern is standard.

---

## New Dependencies

| Package | Version | Purpose | Async? | Memory Impact |
|---------|---------|---------|--------|---------------|
| yfinance | >=0.2.40 | Price history, fundamentals, earnings | Sync (use asyncio.to_thread) | ~50MB + pandas DataFrames |
| chromadb | >=1.0.0 | Vector store for RAG knowledge base | Sync PersistentClient (use asyncio.to_thread) | ~100MB + stored embeddings |
| httpx | (already in deps) | Async HTTP for EDGAR, NewsAPI | Native async | Negligible |

**Why NOT these alternatives:**

| Avoided | Why Not |
|---------|---------|
| LangChain | Same rationale as v2.0 -- massive dependency tree, we have our own OllamaClient. RAG pipeline is ~100 LOC without LangChain. |
| LlamaIndex | Adds 50+ transitive deps. We need 1 ChromaDB collection and simple query/add. |
| Pinecone / Weaviate / Qdrant | Cloud-hosted or heavy server setup. ChromaDB embedded mode fits local-first philosophy. |
| alpha_vantage (pip package) | Old sync library. We can use httpx directly for Alpha Vantage REST API -- cleaner and consistent with our async patterns. |
| newsapi-python | Sync only. httpx.AsyncClient + direct API calls are simpler. |
| SEC-API (commercial) | Paid service. Official data.sec.gov REST API is free and sufficient. |

**Total new dependencies: 2** (yfinance, chromadb). Everything else uses existing httpx or is hand-rolled.

---

## ChromaDB Schema Design

**Collection:** `alphaswarm_knowledge`

**Document structure:**

```python
{
    "id": "earnings_AAPL_2025Q3",
    "document": "Apple Q3 2025 earnings: Revenue $94.8B (+8% YoY), EPS $1.40 vs $1.35 est (+3.7% surprise). Stock rose 3.2% next trading day. Market interpreted as growth acceleration in Services segment.",
    "metadata": {
        "ticker": "AAPL",
        "event_type": "earnings",      # earnings | sector_pattern | macro_event | simulation
        "date": "2025-07-28",
        "sector": "Technology",
        "surprise_pct": 3.7,
        "price_reaction_pct": 3.2,
        "source": "historical_dataset"  # historical_dataset | live_fetch | simulation_export
    }
}
```

**Query strategy:**
- Primary: Semantic similarity to seed rumor text
- Filter: `where={"ticker": {"$in": extracted_tickers}}` for ticker-specific precedents
- Fallback: Sector-level query if no ticker-specific results
- Top-K: 3-5 results per query, sorted by relevance

**Seeding strategy:**
- Ship a pre-built dataset of ~500-1000 historical earnings reactions (JSON/CSV)
- Ingest on first run via a CLI command: `alphaswarm seed-knowledge`
- Runtime enrichment: After each simulation, optionally export results to the knowledge base

---

## Configuration Schema Extension

```python
class MarketDataSettings(BaseModel):
    """Market data provider configuration."""
    enabled: bool = True
    yfinance_enabled: bool = True
    newsapi_key: str | None = None       # Optional, falls back to yfinance news
    alpha_vantage_key: str | None = None  # Optional, falls back to yfinance
    edgar_user_agent: str = "AlphaSwarm/3.0 (research@alphaswarm.local)"
    cache_ttl_seconds: int = 300         # 5 minutes
    max_tickers: int = 5                 # Cap on extracted tickers
    fetch_timeout_seconds: float = 15.0  # Total timeout for all fetches
    history_days: int = 30               # Price history lookback

class RAGSettings(BaseModel):
    """RAG knowledge base configuration."""
    enabled: bool = True
    persist_dir: str = ".chromadb"
    embedding_model: str = "nomic-embed-text"
    collection_name: str = "alphaswarm_knowledge"
    top_k: int = 5
    min_relevance_score: float = 0.3     # Filter low-relevance results
    context_budget_chars: int = 800      # Max chars for RAG section in prompt
```

---

## Suggested Build Order (Dependency-Aware)

The new features have strict dependencies. Build order must respect them:

```
Phase 1: Ticker Extraction
    |  (no external deps beyond existing ollama)
    v
Phase 2: Market Data Pipeline
    |  (depends on Phase 1 for ticker symbols)
    v
Phase 3: RAG Knowledge Base
    |  (depends on Phase 2 for runtime document enrichment)
    |  (can be started in parallel with Phase 2 for static seeding)
    v
Phase 4: Context Enrichment & Agent Prompt Injection
    |  (depends on Phase 2 + Phase 3 for data)
    v
Phase 5: Enhanced AgentDecision & Parsing
    |  (depends on Phase 4 for context that produces richer outputs)
    |  (can be started in parallel with Phase 4)
    v
Phase 6: TUI Enhancements & Per-Ticker Consensus
    |  (depends on Phase 5 for enhanced data to display)
    v
Phase 7: Integration Testing & Report Engine Updates
```

**Detailed phase breakdown:**

### Phase 1: Ticker Extraction (Foundation)
- Modify `types.py`: Add `TickerSymbol`
- Modify `seed.py`: Augment orchestrator prompt, parse tickers
- Modify `parsing.py`: Handle `tickers` array
- New `ticker.py`: yfinance validation via `asyncio.to_thread()`
- Modify `config.py`: Add `MarketDataSettings` (even if not all used yet)
- Modify `graph.py`: Store Ticker nodes in Neo4j
- **Tests:** Orchestrator extracts tickers from known rumors, validation catches invalid symbols
- **Depends on:** Nothing new
- **Risk:** LOW

### Phase 2: Market Data Pipeline
- New `market_data.py`: `MarketDataProvider` class
- Implement yfinance fetcher (primary) via `asyncio.to_thread()`
- Implement EDGAR fetcher (httpx async) for earnings data
- Implement NewsAPI fetcher (httpx async) with graceful degradation
- Add `MarketDataProvider` to AppState
- **Tests:** Fetch snapshots for known tickers, handle API failures gracefully
- **Depends on:** Phase 1 (needs ticker symbols)
- **Risk:** MEDIUM (external API reliability)

### Phase 3: RAG Knowledge Base
- Add `chromadb` dependency
- New `rag.py`: `RAGKnowledgeBase` class with PersistentClient
- Configure `OllamaEmbeddingFunction` with nomic-embed-text
- Create seed dataset (JSON file with ~500 historical earnings reactions)
- CLI command: `alphaswarm seed-knowledge` for initial ingest
- Add `RAGKnowledgeBase` to AppState
- **Tests:** Add documents, query by text + metadata filter, persistence across restarts
- **Depends on:** Ollama running with nomic-embed-text pulled
- **Risk:** MEDIUM (ChromaDB + Ollama embedding interaction, model loading)

### Phase 4: Context Enrichment & Agent Prompt Injection
- New `context.py`: `ContextEnricher` class
- Modify `worker.py`: Accept `market_context` parameter
- Modify `batch_dispatcher.py`: Thread `market_context` through
- Modify `simulation.py`: Add enrichment phase between seed injection and Round 1
- Budget management: Enforce 2000-char cap on enriched context
- **Tests:** Context formatting, budget cap enforcement, integration with dispatch_wave
- **Depends on:** Phase 2 + Phase 3
- **Risk:** MEDIUM (prompt budget management, ensuring enrichment doesn't degrade agent quality)

### Phase 5: Enhanced AgentDecision & Parsing
- Modify `types.py`: Add optional fields to `AgentDecision`
- Modify `config.py`: Update `JSON_OUTPUT_INSTRUCTIONS` for v3 mode
- Modify `parsing.py`: Parse new optional fields (backward compatible)
- Modify `state.py`: Extend `BracketSummary` with per-ticker fields
- **Tests:** Parse decisions with and without new fields, backward compatibility
- **Depends on:** Phase 4 (enriched context prompts agents to produce richer output)
- **Risk:** LOW

### Phase 6: TUI Enhancements
- Modify `tui.py`: Market data panel, per-ticker consensus display
- Modify `state.py`: Extended StateSnapshot with market data
- Updated BracketPanel for per-ticker breakdown
- Updated RationaleSidebar with ticker + direction
- **Depends on:** Phase 5
- **Risk:** MEDIUM (layout management)

### Phase 7: Integration & Report Engine
- End-to-end integration testing
- Modify `report.py`: Add per-ticker analysis tools to ReACT agent
- Modify `graph.py`: Per-ticker consensus query methods
- Knowledge base enrichment: Export simulation results to ChromaDB
- **Depends on:** All prior phases
- **Risk:** LOW-MEDIUM

---

## Anti-Patterns to Avoid

### 1. Fetching Market Data During Agent Inference
**What:** Calling yfinance or APIs inside the dispatch_wave hot path
**Why bad:** 100 agents x API calls = rate limiting, massive latency, event loop blocking
**Instead:** Fetch ALL market data ONCE before Round 1. Pass as static context.

### 2. Loading Embedding Model During Inference Rounds
**What:** Loading nomic-embed-text while the worker model is processing agents
**Why bad:** Exceeds 2-model limit, causes model eviction and ~30s cold reload
**Instead:** All embedding operations happen before worker model loads.

### 3. Unbounded Context Injection
**What:** Dumping entire market data + RAG results into agent prompt without budget cap
**Why bad:** Overflows qwen3.5:7b context window (~4K tokens), produces garbage output
**Instead:** Hard cap at 2000 chars for enriched context. Truncate at content boundaries.

### 4. Synchronous yfinance in Event Loop
**What:** Calling `yf.Ticker().info` directly in async code
**Why bad:** Blocks the entire asyncio event loop for 1-3 seconds per call
**Instead:** Always wrap in `asyncio.to_thread()`.

### 5. Tight Coupling Between Market Data Sources
**What:** Hard-coding yfinance calls everywhere instead of abstracting through MarketDataProvider
**Why bad:** When yfinance breaks (Yahoo API change), every call site needs fixing
**Instead:** Single MarketDataProvider with pluggable fetchers and graceful degradation.

### 6. Making RAG a Hard Dependency
**What:** Requiring ChromaDB + nomic-embed-text for simulation to run
**Why bad:** Breaks existing non-RAG workflows, adds setup friction
**Instead:** RAG is opt-in. `rag_kb=None` means skip RAG enrichment. Simulation works without it.

---

## Scalability Considerations

| Concern | Current (100 agents, 1-5 tickers) | At 500 agents | At 10 tickers |
|---------|-----------------------------------|---------------|---------------|
| Market data fetch | 2-8s (acceptable) | Same (fetched once) | 10-20s (still acceptable) |
| Embedding overhead | <1s per query | Same (query count fixed) | 2-3s (more docs to embed) |
| Prompt context budget | 2000 chars works | Same | Must prioritize top 3 tickers, drop others |
| ChromaDB storage | <100MB | Same | ~200MB |
| Memory pressure | +150MB (yfinance + chromadb) | Same | +200MB |
| Total RAM overhead | ~64GB system with ~40GB available | Same | Same |

---

## Sources

- [yfinance GitHub](https://github.com/ranaroussi/yfinance) -- thread safety issues confirmed (#2557)
- [ChromaDB Docs - Clients](https://docs.trychroma.com/docs/run-chroma/clients) -- PersistentClient vs AsyncHttpClient
- [ChromaDB Cookbook - Ollama Integration](https://cookbook.chromadb.dev/integrations/ollama/embeddings/) -- OllamaEmbeddingFunction
- [Ollama Python Library](https://github.com/ollama/ollama-python) -- AsyncClient.embed() confirmed in v0.6.1
- [Ollama Embedding Models Blog](https://ollama.com/blog/embedding-models) -- nomic-embed-text recommended
- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) -- free RESTful API, 10 req/s
- [asyncnewsapi](https://github.com/pkpinto/asyncnewsapi) -- async NewsAPI wrapper exists but httpx is simpler
- [yfinance thread safety issue](https://github.com/ranaroussi/yfinance/issues/2557) -- confirms NOT thread-safe for same ticker
- [ChromaDB AsyncHttpClient bugs](https://github.com/chroma-core/chroma/issues/4156) -- v1.0 async client issues

**Confidence levels by source:**

| Finding | Confidence | Source |
|---------|------------|--------|
| yfinance requires asyncio.to_thread() | HIGH | Official docs + GitHub issues |
| ChromaDB PersistentClient is sync-only | HIGH | Official docs + cookbook |
| OllamaEmbeddingFunction works with nomic-embed-text | MEDIUM-HIGH | Cookbook examples (not tested locally) |
| Ollama AsyncClient has embed() method | HIGH | Official ollama-python README |
| 2-model limit managed via keep_alive=0 | MEDIUM | Ollama docs (needs local verification) |
| yfinance is NOT thread-safe for same ticker | HIGH | GitHub issue #2557 with reproduction |
| SEC EDGAR API is free, no auth | HIGH | Official SEC.gov documentation |
