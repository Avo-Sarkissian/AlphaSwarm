# Pitfalls Research: v3.0 Stock-Specific Recommendations with Live Data & RAG

**Domain:** Adding live market data fetching, RAG/embedding pipelines, and ticker-specific analysis to an existing memory-constrained local multi-agent financial simulation engine (M1 Max 64GB, Ollama, Neo4j, Textual TUI)
**Researched:** 2026-04-05
**Confidence:** HIGH (verified against existing codebase architecture, Ollama model loading behavior, ChromaDB docs, yfinance issues, API rate limit documentation, and prior governor deadlock analysis)

---

## Critical Pitfalls

Mistakes that cause OOM kills, simulation hangs, or require architectural rewrites when adding v3 features to the existing engine.

---

### Pitfall 1: Embedding Model Evicts Inference Models -- The Third Model Problem

**What goes wrong:** The existing system enforces `OLLAMA_MAX_LOADED_MODELS=2` (orchestrator + worker). Adding `nomic-embed-text` for RAG embeddings introduces a third model. Ollama counts embedding models toward the loaded model limit identically to chat/generate models. When the embedding model loads, Ollama's scheduler evicts the least-recently-used model to make room. If this happens mid-simulation (e.g., embedding a query for RAG retrieval while agents are inferring), the worker model (`qwen3.5:7b`) gets unloaded. The next agent inference request triggers a cold-reload of the worker model (15-30 seconds on M1 Max), during which the `keep_alive="5m"` timer on the other loaded model continues ticking. This cascading eviction was the exact root cause of Bug 7 in the governor deadlock analysis: model loaded too early, timer burns while sitting idle.

The problem is worse than simple latency. When Ollama unloads a model mid-wave, all `OLLAMA_NUM_PARALLEL=16` in-flight requests to that model fail simultaneously. The batch dispatcher catches these as `OllamaInferenceError`, converts them to `PARSE_ERROR` decisions, and the governor's `report_wave_failures()` triggers a slot shrink. The simulation degrades from 16 parallel slots down to 1 within two waves, then crawls through the remaining agents at single-concurrency.

**Why it happens:** Developers assume embedding models are "lightweight" and do not compete with inference models for loaded slots. While `nomic-embed-text` is small (~274MB), Ollama's model scheduler does not distinguish between model types -- embedding models and chat models occupy the same slot pool. GitHub issue #12247 confirms this: embedding requests unload LLM models even when VRAM is available.

**How to avoid:**
1. Never run embeddings during simulation rounds. All embedding operations (populating ChromaDB, querying for RAG context) must complete BEFORE `dispatch_wave()` is called. The pipeline becomes: fetch market data -> embed into ChromaDB -> query ChromaDB for relevant context -> unload embedding model -> load worker model -> run simulation
2. Increase `OLLAMA_MAX_LOADED_MODELS=3` only if memory math works. `nomic-embed-text` is ~274MB. `qwen3.5:7b` with 16 parallel slots and 2048 context uses ~8-10GB. `qwen3.5:32b` orchestrator uses ~20-22GB. Total: ~30-32GB. On 64GB unified memory with Neo4j JVM (~2GB), ChromaDB (~1-2GB), Python process (~1GB), and OS overhead (~4GB), this leaves ~24-26GB headroom. Three models fit but leave no room for the governor's memory pressure thresholds (80% throttle = 51.2GB, 90% pause = 57.6GB). At 32GB model load, psutil reads ~50% before any simulation work begins, and the governor enters THROTTLED state immediately
3. The correct approach: use explicit model lifecycle phases. Load embedding model -> do all embedding work -> unload with `keep_alive=0` -> load inference models -> run simulation. The existing `OllamaModelManager` already has `load_model()` and `unload_model()` -- extend it with an `embedding_phase()` context manager that guarantees the embedding model is loaded and unloaded cleanly
4. For RAG queries during post-simulation (report generation, interviews), serialize: unload inference models first, load embedding model, query ChromaDB, unload embedding model, reload inference model for report/interview

**Warning signs:**
- Governor enters THROTTLED or PAUSED state before any agent inference begins (embedding model consuming memory)
- First wave of agents has 50%+ `PARSE_ERROR` results (worker model was evicted and reloading)
- Ollama logs show `unloading model` followed by `loading model` for the worker mid-simulation
- Embedding calls return within 100ms but the next chat call takes 15-30 seconds (cold reload)

**Phase to address:** RAG Knowledge Base phase -- embedding model lifecycle must be the first design decision, not an afterthought

---

### Pitfall 2: Market Data Fetching During Simulation Rounds Creates Unbounded Latency and Event Loop Blocking

**What goes wrong:** yfinance, the primary market data library, is synchronous and not thread-safe. Calling `yfinance.download()` directly in the asyncio event loop blocks all concurrent agent inference, TUI rendering (200ms tick), governor memory monitoring (2s tick), and Neo4j writes. The entire system freezes until the HTTP request completes (1-5 seconds per ticker, longer if rate-limited).

Even wrapping yfinance in `asyncio.to_thread()` is dangerous: yfinance uses a shared global dictionary internally, so concurrent calls to `yfinance.download()` with different tickers or date ranges can silently overwrite each other's results (confirmed in GitHub issue #2557). This means you cannot safely parallelize multiple ticker fetches using `asyncio.gather()` with `to_thread()`.

The deeper failure mode: if market data is fetched lazily during simulation (e.g., an agent requests price data for a ticker it extracted), the simulation becomes non-deterministic. Agent A might get fresh data while Agent B gets stale cached data, or Agent A's fetch might block Agent B's inference. The 3-round consensus cascade assumes all agents in a round see the same information -- lazy fetching violates this invariant.

**Why it happens:** Developers reach for yfinance because it is the most popular Python finance library. Its synchronous, thread-unsafe design is not documented prominently. The natural impulse is to add `await get_market_data(ticker)` in the agent prompt builder, which either blocks the loop or introduces race conditions.

**How to avoid:**
1. All market data must be fetched in a dedicated pre-simulation phase, before any agent inference begins. The pipeline: seed rumor -> extract tickers -> fetch ALL market data for ALL tickers -> cache locally -> start simulation. No network calls during rounds
2. Wrap yfinance calls in `asyncio.to_thread()` with a `threading.Lock` to serialize access. Do NOT use concurrent yfinance downloads. Fetch tickers sequentially within the thread: `for ticker in tickers: data[ticker] = yf.download(ticker, ...)`
3. Cache fetched data in a `MarketDataCache` dataclass (frozen, immutable) that is passed to the simulation pipeline. Agents read from the cache, never from the network. The cache becomes part of the `SimulationContext` alongside `SeedEvent`
4. For Alpha Vantage (25 requests/day free tier) and NewsAPI (100 requests/day free tier), implement a local disk cache with TTL. If data for a ticker was fetched within the last hour, serve from cache. This prevents burning API quota on repeated simulation runs during development
5. Add a timeout to all market data fetches: `asyncio.wait_for(asyncio.to_thread(yf.download, ...), timeout=30.0)`. If a ticker fetch times out, continue with partial data rather than blocking the entire pipeline

**Warning signs:**
- TUI freezes for 2-5 seconds during simulation start (synchronous fetch blocking the event loop)
- Agent decisions reference different price data for the same ticker (race condition in concurrent fetches)
- yfinance returns `YFRateLimitError` mid-simulation, crashing the pipeline
- Governor memory monitor misses a check cycle (blocked event loop prevented `asyncio.sleep` from completing)

**Phase to address:** Live Market Data Pipeline phase -- must be the first phase, completed and tested before any agent code touches market data

---

### Pitfall 3: RAG Context Injection Overflows Agent Prompt Token Budget

**What goes wrong:** The existing agent prompt is already packed tight. Current budget analysis from the codebase:
- System prompt (bracket template + modifier + JSON instructions): ~250-350 words (~350-500 tokens)
- Seed rumor: ~50-150 words (~70-200 tokens)
- Peer context (Round 2-3, up to 5 peers): ~400 tokens
- Social posts context: ~300 tokens (budgeted in v2 Pitfall 4)
- Response headroom: ~600 tokens
- **Total existing budget: ~1720-2000 tokens** (against 2048 `num_ctx`)

Adding market data context (price history, earnings, fundamentals) and RAG-retrieved historical precedents pushes this well beyond the 2048 limit. A minimal market data injection (current price, 52-week range, P/E ratio, recent earnings) is ~100-150 tokens. RAG-retrieved precedents (2-3 historical scenarios with outcomes) add ~200-400 tokens. Total addition: 300-550 tokens, exceeding the 2048 cap by 20-50%.

When the prompt exceeds `num_ctx`, Ollama silently truncates from the beginning. The system prompt -- containing the agent's bracket personality, decision heuristics, and JSON output format -- gets dropped first. Every agent produces the same generic, personality-less response. The simulation's core value proposition (diverse bracket-specific reactions) collapses.

Research confirms this is not just a truncation problem. LLM performance degrades significantly even at 50% context utilization due to "context rot" -- accuracy drops 30%+ for information in mid-window positions. Packing the full 2048 tokens degrades response quality even if nothing is truncated.

**Why it happens:** The v2 token budget was designed without accounting for market data or RAG context. Developers add "just a few more lines" of market data to the prompt without re-auditing the total token count. The degradation is invisible in testing with short seed rumors but catastrophic with real market data payloads.

**How to avoid:**
1. Redesign the token budget to accommodate market data and RAG. New budget: system prompt = 400 tokens (non-negotiable, never truncated), market data summary = 150 tokens, RAG precedents = 150 tokens, seed rumor = 150 tokens, peer context = 200 tokens, social posts = 150 tokens, response headroom = 600 tokens. Total = 1800 tokens. This requires aggressively compressing every component
2. Increase `num_ctx` to 4096 in the worker Modelfile. Memory impact: at 16 parallel slots, KV cache grows from ~2GB (2048 ctx) to ~4GB (4096 ctx). This is manageable if the embedding model lifecycle is properly sequenced (Pitfall 1). Recalculate governor thresholds accordingly
3. Build a `PromptBudgetAllocator` class that accepts all prompt components and a total token cap, then allocates space proportionally with priority ordering: system prompt (never cut) > seed rumor (cut last) > market data (summarize) > RAG precedents (top-K reduce) > peer context (reduce peers) > social posts (cut first)
4. Market data must be pre-summarized into a compact format before injection. Not raw JSON or tabular data. Example: "AAPL: $187.32 (+2.1% 1d), P/E 29.8, beat Q3 EPS by 8%, 52w range $142-$199" (~30 tokens vs ~200 for raw data)
5. RAG retrieval should return pre-compressed summaries, not raw documents. Store the summary at embedding time, not at retrieval time. This moves compute to the ingest pipeline (run once) rather than the inference pipeline (run 100x per round)

**Warning signs:**
- Agent responses lose bracket-specific personality (system prompt truncated)
- All 100 agents produce suspiciously similar responses in a round (persona instructions lost)
- Agent rationale text references market data that was not in their truncated context (hallucination filling the gap)
- Token count audit shows prompts averaging >1900 tokens (buffer zone eroded)

**Phase to address:** Agent Context Enrichment phase -- must follow market data pipeline AND RAG pipeline phases, with explicit token budget as acceptance criteria

---

### Pitfall 4: ChromaDB Memory Pressure Compounds with Ollama on Unified Memory Architecture

**What goes wrong:** M1 Max uses unified memory -- CPU, GPU, and all processes share the same 64GB pool. ChromaDB's in-process persistent client loads HNSW indices into RAM. For a collection of 10,000 documents with 768-dimensional embeddings (nomic-embed-text), the vector storage alone is: 10,000 x 768 x 4 bytes (float32) = ~30MB. But the real footprint is 3-5x larger due to HNSW graph overhead, bruteforce buffer, metadata storage, and SQLite FTS5 index. Realistic estimate: 100-200MB for a 10K document collection.

This sounds manageable in isolation, but the memory pressure math is cumulative on unified memory:
- Ollama models: ~30GB (orchestrator + worker, or worker + embedding model)
- Neo4j JVM: ~2GB (Docker container)
- ChromaDB: ~200MB-1GB (depends on collection size and access patterns)
- Python process (100 agent state, StateStore, WriteBuffer): ~500MB-1GB
- Textual TUI: ~100MB
- macOS system: ~4GB
- **Total: ~37-39GB baseline**

This puts psutil at ~58-61% before simulation begins. The governor's throttle threshold is 80% (51.2GB). During simulation, Ollama's KV cache grows by ~2-4GB (16 parallel contexts x 2048-4096 tokens), pushing to ~41-43GB (64-67%). Agent inference creates transient memory spikes. The governor oscillates between RUNNING and THROTTLED, reducing concurrency and slowing the simulation by 2-3x.

The pathological case: ChromaDB performs an HNSW index rebuild or compaction during simulation (triggered by prior updates to the collection). This is a CPU-intensive, memory-hungry operation that can spike RSS by 2-3x the collection size temporarily. Combined with Ollama inference, this pushes past the 90% pause threshold, halting the simulation.

**Why it happens:** Each component (Ollama, Neo4j, ChromaDB, Python) is individually reasonable on 64GB. But the unified memory architecture means they all compete for the same physical RAM, and macOS memory pressure signals (the governor's master signal via sysctl) reflect the aggregate pressure, not per-process pressure.

**How to avoid:**
1. Use ChromaDB's persistent client with LRU cache strategy. Configure `chroma_memory_limit_bytes` to cap ChromaDB at 500MB. When ChromaDB unloads HNSW segments not in active use, it frees memory for Ollama inference
2. Pre-populate ChromaDB BEFORE simulation and then set the collection to read-only mode (no writes during simulation). This prevents HNSW index rebuilds from triggering mid-simulation
3. Adjust governor thresholds for v3 memory profile: raise `memory_throttle_percent` from 80% to 85%, and `memory_pause_percent` from 90% to 92%. The additional 5% headroom accounts for ChromaDB's resident memory. Document the threshold change and the reasoning
4. If ChromaDB memory pressure is unacceptable, use ChromaDB's HTTP client mode (Chroma server in a separate process) instead of the in-process persistent client. This isolates ChromaDB memory from the Python process, giving the governor's psutil reading a more accurate picture of simulation-only memory. The tradeoff is added latency (~5-10ms per query) and deployment complexity (another service to manage alongside Neo4j)
5. Profile memory with a representative knowledge base before committing to a collection size. Start with 1,000 documents, measure RSS, then extrapolate. Do not assume ChromaDB memory is "just the vectors"

**Warning signs:**
- Governor enters THROTTLED state before simulation begins (ChromaDB + models consuming baseline memory)
- `psutil.virtual_memory().percent` reads >65% at idle (before any inference)
- macOS `kern.memorystatus_vm_pressure_level` reads YELLOW during RAG queries combined with inference
- ChromaDB queries that were fast (< 50ms) become slow (> 500ms) during simulation (memory pressure causing swap)

**Phase to address:** RAG Knowledge Base phase -- ChromaDB deployment mode and memory budgeting must be validated before the collection is populated

---

### Pitfall 5: API Rate Limits Create Silent Data Gaps That Corrupt Simulation Quality

**What goes wrong:** The four external data sources have dramatically different rate limits:
- **yfinance**: Unofficial Yahoo Finance scraper. No published rate limit but aggressively rate-limits at ~2000 requests/day (enforced via 429 responses and IP blocking)
- **Alpha Vantage**: Free tier = 25 requests/day, 5 requests/minute. This is absurdly low -- fetching price history, earnings, and fundamentals for a single ticker consumes 3 API calls. Multi-ticker rumors exhaust the daily quota in 8 tickers
- **NewsAPI**: Free tier = 100 requests/day. Fetching news for 5 tickers with pagination consumes 10-15 requests per simulation run
- **EDGAR/SEC**: 10 requests/second (generous but requires User-Agent header with contact email, enforced by IP blocking)

When a rate limit is hit, the failure mode varies: yfinance returns empty DataFrames or raises `YFRateLimitError`, Alpha Vantage returns a JSON object with an error message (not an HTTP error), NewsAPI returns 429, and EDGAR blocks the IP. If the market data pipeline does not detect and handle ALL of these failure modes, agents receive partial data (some tickers have full context, others have nothing). The simulation produces asymmetric results where data-rich tickers dominate agent attention and data-poor tickers get ignored -- a systematic bias invisible in the output.

**Why it happens:** Developers test with 1-2 tickers, which works within all rate limits. Production seed rumors may mention 5-10 tickers. The rate limit is hit on ticker #9, and the error handling for that specific API's failure format was never tested. Alpha Vantage's error-as-200-OK pattern is particularly insidious -- it looks like a successful response.

**How to avoid:**
1. Implement a `DataCompleteness` validation after all fetches complete. For each ticker, verify: has_price_data, has_fundamentals, has_news, has_earnings. If any ticker has <50% data coverage, log a warning. If >30% of tickers have incomplete data, abort the simulation with a clear error message rather than running with garbage
2. Use yfinance as the PRIMARY data source (price history, fundamentals, earnings). It has the highest effective rate limit and broadest coverage. Alpha Vantage is SUPPLEMENTARY -- use it only for data yfinance does not provide (e.g., detailed balance sheet, income statement)
3. Implement per-API rate limiters using `asyncio.Semaphore` with time-based release. Example: Alpha Vantage gets `Semaphore(1)` with a 12-second minimum between releases (5 calls/minute). yfinance gets `Semaphore(1)` with a 2-second minimum (conservative, avoids IP blocking)
4. Build a local disk cache (`~/.alphaswarm/market_data/`) with file-based TTL. Cache key: `{ticker}_{data_type}_{date}.json`. If data exists and is <1 hour old, serve from cache. This makes repeated simulation runs during development free
5. Alpha Vantage responses must be validated structurally, not just by HTTP status. Check for `"Error Message"` and `"Note"` keys in the JSON response body -- these indicate rate limits or invalid requests disguised as 200 OK

**Warning signs:**
- Simulation results heavily favor one ticker while ignoring others in a multi-ticker rumor (data asymmetry)
- Market data fetch phase takes >60 seconds (serial fetches hitting rate limits with backoff)
- Alpha Vantage returns identical "Thank you for using Alpha Vantage" messages instead of data
- Agent rationale mentions market data for Ticker A but not Ticker B, despite both being in the seed rumor

**Phase to address:** Live Market Data Pipeline phase -- rate limiting and data completeness validation must be built BEFORE any agent code consumes market data

---

### Pitfall 6: RAG Retrieval Latency During Prompt Construction Serializes the Dispatch Wave

**What goes wrong:** The existing `dispatch_wave()` creates 100 agent tasks via `asyncio.TaskGroup`. Each task applies jitter, acquires a governor slot, then calls `worker.infer()`. If RAG retrieval is added inside the per-agent prompt construction (e.g., each agent queries ChromaDB for historical precedents relevant to their bracket), the retrieval becomes the bottleneck.

ChromaDB's Python client is synchronous internally (uses SQLite). Even with `asyncio.to_thread()`, 100 concurrent ChromaDB queries from 100 agent tasks serialize through Python's GIL and ChromaDB's internal locks. Measured latency: ~10-50ms per query x 100 agents = 1-5 seconds of serialized ChromaDB access, added to every round. Over 3 rounds, this adds 3-15 seconds of pure retrieval overhead.

Worse: if the ChromaDB query triggers an HNSW cache miss (the segment was evicted by the LRU policy due to memory pressure), the query blocks while the index is loaded from disk. A single cache miss can add 500ms-2s, and 100 agents all triggering cache misses creates a thundering herd.

**Why it happens:** RAG tutorials show per-query retrieval as the standard pattern. In a single-agent system, 50ms per query is invisible. In a 100-agent batch system, it is the dominant latency source.

**How to avoid:**
1. Pre-fetch ALL RAG context BEFORE `dispatch_wave()`. Query ChromaDB once per ticker (not once per agent). Each bracket can get a bracket-specific RAG query, but batch these into 10 queries (one per bracket), not 100 queries (one per agent). Results are cached in a `RAGContext` dict keyed by `(ticker, bracket_type)`
2. The RAG query results become part of the `peer_contexts` list that `dispatch_wave()` already supports. Prepend RAG context to each agent's `peer_context` string. No changes to the dispatch architecture
3. Use a single `asyncio.to_thread()` call that executes all ChromaDB queries sequentially in one thread. Do not spawn 100 threads for 100 queries. Example: `rag_results = await asyncio.to_thread(batch_chromadb_query, queries)`
4. Pin the ChromaDB collection in memory during simulation by pre-warming it with a dummy query during the initialization phase. This prevents HNSW cache misses during actual retrieval
5. If retrieval latency is still problematic, pre-compute the RAG context during the embedding phase (before simulation) and store it alongside the market data cache. At simulation time, RAG results are read from the cache with zero ChromaDB overhead

**Warning signs:**
- Round completion time increases 2-5x compared to v2 despite same agent count
- Structlog shows ChromaDB query latency spikes (>200ms) interleaved with Ollama inference logs
- Governor observes long periods of no active inference (all slots idle while waiting on ChromaDB)
- CPU utilization spikes during prompt construction phase (GIL contention from 100 ChromaDB calls)

**Phase to address:** Agent Context Enrichment phase -- RAG context must be pre-fetched in batch, not queried per-agent

---

### Pitfall 7: Enhanced AgentDecision Schema Breaks the Parsing Pipeline's PARSE_ERROR Fallback

**What goes wrong:** The current `AgentDecision` has 4 fields: `signal`, `confidence`, `sentiment`, `rationale`. The v3 enhancement adds: `ticker`, `direction`, `expected_return_pct`, `time_horizon`, `confidence` (already exists). The `parse_agent_decision()` function in `parsing.py` has a 3-tier fallback (JSON parse -> regex extraction -> PARSE_ERROR default). This fallback is battle-tested for the current 4-field schema.

Adding 4 new fields to the JSON output format that agents must produce makes parsing failures much more likely. The 7B worker model already struggles with structured JSON output at low temperatures (bracket AGENTS uses temperature=0.1). Asking it to produce 8 fields instead of 4 doubles the surface area for malformed JSON. The model might produce `expected_return` instead of `expected_return_pct`, or output a string like "3 months" instead of a structured `time_horizon` value.

If the regex fallback (tier 2) does not know about the new fields, it extracts only the original 4 fields and silently produces AgentDecisions with `ticker=None, direction=None, expected_return_pct=None, time_horizon=None`. These decisions look valid (they have signal and confidence) but are missing the data that makes v3 valuable. The simulation "succeeds" but produces v2-quality output from a v3 pipeline.

**Why it happens:** Parsing is the most boring part of the pipeline and gets the least testing attention. Developers verify that happy-path JSON parsing works with the new fields, but do not test the fallback paths with malformed model output. The 7B model's output quality varies significantly across brackets (high-temperature brackets like DEGENS at 1.2 produce more parsing failures than low-temperature brackets like SUITS at 0.3).

**How to avoid:**
1. Make all new fields optional in the `AgentDecision` model with sensible defaults: `ticker: str | None = None`, `direction: str | None = None`, `expected_return_pct: float | None = None`, `time_horizon: str | None = None`. A partially-parsed decision with signal + confidence + ticker but missing expected_return is far more valuable than a PARSE_ERROR
2. Update the JSON output instructions in `config.py` (`JSON_OUTPUT_INSTRUCTIONS`) to include examples of the new fields. The current instructions show a minimal example -- add a complete example with all 8 fields
3. Implement field-level extraction, not all-or-nothing parsing. If JSON parsing fails, try to extract each field independently via regex. The existing signal/confidence regex can be extended for ticker (`"ticker"\s*:\s*"([A-Z]{1,5})"`) and direction patterns
4. Add a `parse_completeness_score` field to AgentDecision: the fraction of v3 fields that were successfully parsed (0.5 = only base fields, 1.0 = all fields). This lets downstream code (TUI, report) know when to show v3 data vs fall back to v2 display
5. Test parsing with actual model output from each bracket at each temperature. Generate 10 responses per bracket, parse them all, and verify the v3 field extraction rate. Expect DEGENS (temp=1.2) to have lower extraction rates than QUANTS (temp=0.3)

**Warning signs:**
- v3 TUI panels show "N/A" for ticker or direction on >20% of agents (fields not parsed)
- PARSE_ERROR rate increases from v2 baseline (new JSON format confuses the model)
- Regex fallback fires more frequently than JSON parse (model output is consistently malformed)
- High-temperature brackets (DEGENS, DOOM_POSTERS) produce 50%+ incomplete v3 fields

**Phase to address:** Enhanced AgentDecision Output phase -- parsing must be updated and tested with real model output BEFORE the TUI displays v3 data

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems in the v3 feature set.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Fetch market data synchronously in the main event loop | Simpler code, no thread management | Blocks TUI rendering, governor monitoring, and all async tasks for 1-5 seconds per ticker | Never -- always use `asyncio.to_thread()` |
| Use Alpha Vantage free tier without caching | No disk cache code needed | 25 calls/day exhausted in 2 simulation runs with 5 tickers. Development velocity drops to zero | Never -- disk cache is mandatory |
| Load embedding model alongside inference models (3 concurrent) | No model lifecycle management needed | Memory pressure pushes governor to THROTTLED permanently, simulation runs at 50% speed | Only during initial prototyping on smaller models (both <4GB) |
| Store raw market data in agent prompts | No summarization logic needed | 300+ tokens of raw JSON per prompt, overflow the 2048 context on every agent | Never -- always pre-summarize |
| Query ChromaDB per-agent inside dispatch_wave | Simplest RAG integration pattern | 100 serialized ChromaDB queries per round, 3-15 seconds added latency per round | Never -- always pre-fetch in batch |
| Skip data completeness validation on market data | Faster pipeline, fewer error paths | Silent data gaps create asymmetric agent context, biased simulation results | Only for initial development with hardcoded single-ticker test cases |
| Hardcode ticker extraction regex instead of using orchestrator LLM | No LLM call needed for ticker extraction | Misses implied tickers (e.g., "the iPhone maker" = AAPL), fails on non-US tickers | MVP only -- LLM extraction is required for production quality |
| Increase `num_ctx` to 8192 to "solve" prompt overflow | No prompt budgeting needed | KV cache grows to ~8GB (16 parallel x 8192), governor enters PAUSED state immediately | Never at 16 parallel. Acceptable at 4 parallel (2GB KV cache) but requires governor retuning |

## Integration Gotchas

Common mistakes when connecting v3 features to the existing v1/v2 architecture.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Market Data + OllamaModelManager | Fetching market data after loading models (models sit idle, burning `keep_alive` timer) | Fetch ALL market data BEFORE any model loading. The pipeline is: data fetch -> embedding phase -> inference phase. Models load only when needed |
| ChromaDB + ResourceGovernor | Not accounting for ChromaDB RSS in governor's memory thresholds | Profile ChromaDB memory footprint and adjust `memory_throttle_percent` and `memory_pause_percent` upward by the ChromaDB overhead percentage |
| yfinance + asyncio Event Loop | Calling `yf.download()` directly in async code, blocking the loop | Wrap in `asyncio.to_thread()` with a `threading.Lock` to serialize concurrent access. Never call yfinance from an async function without thread isolation |
| RAG Context + dispatch_wave() | Adding ChromaDB queries inside `_safe_agent_inference()`, creating per-agent retrieval in the hot loop | Pre-fetch RAG results for all tickers/brackets BEFORE dispatch_wave(). Pass as part of `peer_contexts` list (mechanism already exists) |
| Enhanced AgentDecision + parse_agent_decision() | Adding new required fields that increase PARSE_ERROR rate | All new fields must be Optional with defaults. Extend regex fallback for new field patterns. Test with real model output at each temperature |
| Market Data Cache + Simulation Pipeline | Fetching live data on every simulation run, even during development | Implement disk cache with TTL. Development runs should NEVER hit external APIs if cached data is fresh (<1 hour for dev, <15 min for production) |
| Embedding Model + Worker Model | Loading both simultaneously, exceeding `OLLAMA_MAX_LOADED_MODELS=2` | Sequential lifecycle: embedding phase (embed model loaded, others unloaded) -> inference phase (worker model loaded, embed model unloaded). Never concurrent |
| Ticker Extraction + Seed Parsing | Extracting tickers in a separate LLM call, doubling orchestrator usage | Extend existing `inject_seed()` to extract tickers alongside entities in the same LLM call. The orchestrator already parses the seed rumor -- add ticker extraction to its response schema |
| EDGAR SEC API + Request Headers | Missing required User-Agent header with contact email | EDGAR requires `User-Agent: CompanyName ContactEmail` format. Missing this results in immediate IP blocking, not a graceful error |
| Alpha Vantage + Error Handling | Checking only HTTP status code (200 = success) | Alpha Vantage returns 200 OK with error messages in the JSON body. Must parse response body for `"Error Message"` and `"Note"` keys |

## Performance Traps

Patterns that work in testing but fail at production scale.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Synchronous yfinance in event loop | TUI freezes, governor misses monitoring cycles | `asyncio.to_thread()` with threading.Lock | Any ticker fetch (blocks entire event loop) |
| Per-agent ChromaDB queries in dispatch_wave | Round time 2-5x slower than expected | Pre-fetch in batch before dispatch | >10 agents (GIL serialization + HNSW cache misses) |
| Unbounded ChromaDB collection growth | Memory pressure increases over simulation runs | Cap collection at 10K documents, use LRU eviction | >5K documents (HNSW index grows superlinearly) |
| All API calls fired concurrently with asyncio.gather | Rate limits hit immediately, data incomplete | Sequential with per-API rate limiters | >3 tickers on Alpha Vantage free tier (25/day) |
| Embedding 100 RAG documents per simulation run | 30+ second embedding phase on CPU | Pre-embed at knowledge base build time, not per-run | >50 documents to embed (nomic-embed-text on CPU: ~100ms/doc) |
| Market data JSON in prompts without compression | Token budget overflow, persona truncation | Pre-summarize to <50 tokens per ticker | >2 tickers in a single prompt |
| Neo4j storing raw market data per decision | Graph bloat, slow traversal queries | Store only ticker symbols and data version hash on Decision nodes | >3 rounds x 100 agents x full market data = 300 large nodes |

## Security Mistakes

Domain-specific security issues for a financial data pipeline.

| Mistake | Risk | Prevention |
|---------|------|------------|
| Storing Alpha Vantage API key in source code or `.env` committed to git | API key exposed in repository history | Use environment variables loaded at runtime. Add `.env` to `.gitignore`. Validate key presence at startup with clear error message |
| EDGAR requests without rate limiting | SEC blocks IP address, potentially flags for investigation | Implement 10 req/sec hard limit. Add required User-Agent header with valid contact email per SEC guidelines |
| yfinance scraping from cloud/CI environments | Yahoo blocks IP ranges associated with cloud providers (AWS, GCP, etc.) | Only fetch from local development machine. Cache data in git-ignored directory for CI use |
| Raw financial data in prompts flowing to model output | Model may reproduce copyrighted data verbatim in rationale text | Summarize data before injection. Never put raw earnings transcripts or analyst reports in prompts |
| NewsAPI content in persistent storage | News content may be copyrighted, cannot be redistributed | Store only headlines and URLs, not full article bodies. Summarize for agent context |

## UX Pitfalls

Common user experience mistakes when adding v3 features to the TUI/CLI workflow.

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| No progress indication during market data fetch | User thinks system is frozen for 10-30 seconds while tickers download | Show per-ticker progress: "Fetching AAPL (2/5)... Fetching MSFT (3/5)..." |
| Per-stock breakdown shows data-poor tickers alongside data-rich ones | User cannot distinguish between "bearish on AAPL (based on earnings data)" and "bearish on XYZ (no data, guessing)" | Display data completeness indicator per ticker in TUI results. Gray out tickers with incomplete data |
| Embedding phase has no feedback | User waits during ChromaDB population with no indication of progress | Show "Building knowledge base... (42/100 documents embedded)" |
| Market data freshness is invisible | User does not know if data is from cache (1 hour old) or live | Display "Market data as of: 2026-04-05 14:30 EST (cached)" in TUI header |
| Expected return % shown without context | "Expected return: +3.2%" means nothing without time horizon | Always pair return with horizon: "+3.2% over 3 months" |
| Confidence-weighted consensus shown as simple average | User sees "60% bullish" but does not know if that is 60 low-confidence agents or 30 high-confidence agents | Show both: "60% bullish (avg confidence: 0.71)" and bracket-level breakdown |

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces for v3 features.

- [ ] **Market Data Pipeline:** Often missing data completeness validation -- verify that a multi-ticker simulation with one API-rate-limited ticker gracefully degrades (logs warning, provides partial context) rather than silently running with empty data for that ticker
- [ ] **RAG Knowledge Base:** Often missing embedding model lifecycle management -- verify that after ChromaDB population, the embedding model is explicitly unloaded (`keep_alive=0`) BEFORE the worker model is loaded for simulation
- [ ] **Agent Context Enrichment:** Often missing token budget enforcement -- verify that the total prompt (system + market data + RAG + seed + peers + social) is counted via tokenizer and stays under `num_ctx` for EVERY agent, not just the average
- [ ] **Enhanced AgentDecision:** Often missing fallback-path testing -- verify that the regex parser (tier 2) can extract ticker and direction fields from malformed JSON, and that PARSE_ERROR decisions still have `ticker=None` (not missing attribute)
- [ ] **Ticker Extraction:** Often missing multi-ticker support -- verify that a seed rumor mentioning 3 tickers produces market data context for ALL 3, not just the first one parsed
- [ ] **Market Data Cache:** Often missing TTL enforcement -- verify that cached data older than the TTL is re-fetched, not served stale. Test by manually aging a cache file and running a simulation
- [ ] **TUI Results Panel:** Often missing v3 field display -- verify that per-stock breakdown, expected return, and time horizon are displayed in the TUI, not just logged to structlog
- [ ] **ChromaDB Memory:** Often missing governor threshold adjustment -- verify that `psutil.virtual_memory().percent` at idle (all models unloaded, ChromaDB loaded) is below 50%. If not, governor thresholds need adjustment

## Recovery Strategies

When pitfalls occur despite prevention, how to recover without a full rewrite.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Embedding model evicts inference model mid-simulation (Pitfall 1) | LOW | Add `keep_alive=0` unload call for embedding model before loading worker model. Hot-fixable in the model lifecycle manager without architecture changes |
| yfinance blocks event loop (Pitfall 2) | LOW | Wrap in `asyncio.to_thread()`. Single-line change per call site, but requires finding ALL call sites |
| Prompt token overflow (Pitfall 3) | MEDIUM | Implement `PromptBudgetAllocator` as a new module. Requires touching prompt construction in `worker.py` and `simulation.py`, but no architectural changes |
| ChromaDB memory pressure (Pitfall 4) | MEDIUM | Switch from in-process persistent client to HTTP client mode. Requires deploying Chroma server (Docker), changing client initialization, and testing latency impact |
| API rate limit data gaps (Pitfall 5) | LOW | Add `DataCompleteness` validation and disk cache. Can be added as middleware layer without changing the simulation pipeline |
| Per-agent RAG queries slow simulation (Pitfall 6) | MEDIUM | Refactor from per-agent to batch pre-fetch. Requires restructuring prompt construction but not the dispatch mechanism (peer_contexts already supports it) |
| Enhanced schema breaks parsing (Pitfall 7) | LOW | Make all new fields Optional, extend regex patterns. Changes confined to `parsing.py` and `types.py` |

## Pitfall-to-Phase Mapping

How v3 roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Embedding model eviction (Pitfall 1) | RAG Knowledge Base | Test: after ChromaDB population, verify embedding model is unloaded. Run `ollama ps` -- only worker model should be loaded during simulation |
| Event loop blocking (Pitfall 2) | Live Market Data Pipeline | Test: start TUI, trigger market data fetch, verify TUI continues rendering at 200ms tick rate during fetch (no freeze) |
| Prompt token overflow (Pitfall 3) | Agent Context Enrichment | Test: with 3 tickers, full market data, 3 RAG precedents, and 5 peer contexts, verify total prompt tokens < `num_ctx` for all 100 agents. Count with tokenizer, not character estimation |
| ChromaDB memory pressure (Pitfall 4) | RAG Knowledge Base | Test: load ChromaDB with 10K documents, load worker model, run `psutil.virtual_memory().percent`. Must be < governor's `memory_throttle_percent` at idle |
| API rate limit data gaps (Pitfall 5) | Live Market Data Pipeline | Test: simulate rate limit by setting Alpha Vantage to 1 call/day. Run 5-ticker simulation. Verify `DataCompleteness` check fires and logs warnings for rate-limited tickers |
| RAG retrieval serialization (Pitfall 6) | Agent Context Enrichment | Test: measure round completion time with RAG context vs without. Delta must be <2 seconds (batch pre-fetch) not >10 seconds (per-agent query) |
| Schema parsing regression (Pitfall 7) | Enhanced AgentDecision Output | Test: generate 10 responses per bracket at production temperatures. Parse all with updated parser. v3 field extraction rate must be >80% for low-temp brackets and >50% for high-temp brackets |

## Sources

- [Ollama FAQ -- Model Loading and OLLAMA_MAX_LOADED_MODELS](https://docs.ollama.com/faq) -- embedding models count toward loaded model limit
- [Ollama Issue #12247 -- embeddinggemma unloads LLM models](https://github.com/ollama/ollama/issues/12247) -- embedding requests evict inference models even with available VRAM
- [Ollama Embedding Models Blog](https://ollama.com/blog/embedding-models) -- nomic-embed-text usage and API
- [nomic-embed-text Ollama Library](https://ollama.com/library/nomic-embed-text) -- model size (~274MB) and 768-dimension output
- [yfinance Issue #2557 -- download not thread-safe](https://github.com/ranaroussi/yfinance/issues/2557) -- concurrent calls with different tickers overwrite results via shared global dict
- [yfinance Issue #2411 -- YFRateLimitError](https://github.com/ranaroussi/yfinance/issues/2411) -- Yahoo Finance rate limiting behavior in 2025
- [yfinance Rate Limiting Guide](https://www.slingacademy.com/article/rate-limiting-and-api-best-practices-for-yfinance/) -- best practices for avoiding 429 errors
- [Alpha Vantage Pricing](https://www.alphavantage.co/premium/) -- free tier: 25 requests/day, 5/minute
- [Alpha Vantage API Limits](https://www.macroption.com/alpha-vantage-api-limits/) -- error-as-200-OK pattern documentation
- [SEC EDGAR Rate Control Limits](https://www.sec.gov/filergroup/announcements-old/new-rate-control-limits) -- 10 requests/second, User-Agent requirement
- [ChromaDB Memory Management -- LRU Cache Strategy](https://cookbook.chromadb.dev/strategies/memory-management/) -- configurable memory limits and segment eviction
- [ChromaDB Resource Requirements](https://cookbook.chromadb.dev/core/resources/) -- memory footprint calculation including HNSW overhead
- [ChromaDB Performance Tips](https://cookbook.chromadb.dev/running/performance-tips/) -- HNSW fragmentation from updates, defragmentation
- [Neo4j Python Driver Concurrency Docs](https://neo4j.com/docs/python-manual/current/concurrency/) -- AsyncSession not concurrency-safe, session-per-task required
- [Neo4j Community -- asyncio.gather crashes](https://community.neo4j.com/t/neo4j-python-driver-with-asyncio-gather-crashes/58673) -- connection pool exhaustion with concurrent async queries
- [Context Window Overflow -- Redis Blog](https://redis.io/blog/context-window-overflow/) -- context rot and mid-window performance degradation
- [Long Context RAG Performance -- Databricks Blog](https://www.databricks.com/blog/long-context-rag-performance-llms) -- LLM accuracy drops at 50%+ context utilization
- [Context Length Alone Hurts LLM Performance](https://arxiv.org/html/2510.05381v1) -- extending input length degrades reasoning even with perfect retrieval
- [RAG Common Mistakes -- kapa.ai](https://www.kapa.ai/blog/rag-gone-wrong-the-7-most-common-mistakes-and-how-to-avoid-them) -- embedding rot, fixed-size chunking, and retrieval quality pitfalls
- [Why Multi-Agent LLM Systems Fail -- orq.ai](https://orq.ai/blog/why-do-multi-agent-llm-systems-fail) -- cascade failures from single misrouted messages
- Existing codebase analysis: `governor.py` (5-state machine, TokenPool, memory thresholds), `ollama_client.py` (backoff, num_ctx stripping), `worker.py` (keep_alive="5m", prompt construction), `config.py` (JSON_OUTPUT_INSTRUCTIONS, token budget), `batch_dispatcher.py` (TaskGroup dispatch, PARSE_ERROR fallback), `memory_monitor.py` (dual-signal psutil + sysctl)
- Prior bug analysis: Governor Deadlock Bug Analysis (7 bugs across 2 sessions, including Bug 7: model loaded too early before graph queries)

---
*Pitfalls research for: AlphaSwarm v3.0 Stock-Specific Recommendations with Live Data & RAG*
*Researched: 2026-04-05*
