# Project Research Summary

**Project:** AlphaSwarm v3.0 — Stock-Specific Recommendations with Live Data & RAG
**Domain:** Local-first multi-agent financial simulation with live market data grounding and vector-based historical retrieval
**Researched:** 2026-04-05
**Confidence:** HIGH

## Executive Summary

AlphaSwarm v3.0 extends an already-shipped 100-agent consensus cascade engine with three new capabilities: ticker extraction from natural-language seed rumors, live market data ingestion (yfinance + SEC EDGAR), and a RAG knowledge base (ChromaDB + nomic-embed-text) that supplies agents with historical precedents. The recommended approach builds these as a strict sequential pipeline inserted between seed injection and Round 1: tickers are extracted and validated, market data is fetched and cached, RAG context is retrieved and embedded into prompts, and only then do simulation rounds begin. This pre-simulation enrichment pattern is non-negotiable — any attempt to fetch data or run embeddings during inference rounds will degrade or crash the simulation.

The primary technical risk is Ollama's two-model limit. nomic-embed-text, though lightweight (~274MB), occupies a loaded-model slot identical to the orchestrator and worker models. Loading it at the wrong moment evicts the worker mid-simulation, cascading into parse errors and slot starvation. The solution is explicit lifecycle phasing: orchestrator loads for seed injection and ticker extraction, then unloads; embedding model loads briefly for RAG retrieval with `keep_alive=0`, then unloads; worker loads for rounds 1–3 and stays loaded through interviews. A second, equally critical risk is prompt token overflow — existing prompts already consume ~1720–2000 tokens of a 2048-token context, leaving almost no room for market data and RAG precedents. This demands a `PromptBudgetAllocator` with hard caps and pre-summarized data, not raw JSON injection.

The stack additions are minimal and well-justified: yfinance (free, no API key, wrapped in `asyncio.to_thread()` with per-ticker locking), chromadb (embedded PersistentClient, no server), and edgartools (optional SEC EDGAR depth). Everything else builds on the validated v1/v2 stack. The feature dependency chain is linear: ticker extraction unlocks market data, which unlocks context enrichment, which unlocks enhanced decisions, which unlocks per-stock TUI display. RAG is the one independent track that merges into context enrichment and can be built in parallel with the market data pipeline.

## Key Findings

### Recommended Stack

The v1/v2 stack (Python 3.11+, asyncio, ollama >=0.6.1, neo4j >=5.28, textual >=8.1.1, pydantic, structlog, psutil, httpx, backoff, jinja2, aiofiles) requires no version changes. Three new direct dependencies are added: `yfinance>=1.2.0` for free market data without an API key, `chromadb>=1.5.0,<2.0` for embedded vector storage, and `edgartools>=5.6.0` for SEC EDGAR depth (the last is optional and can be deferred if the additional 80MB of transitive deps is a concern). One new Ollama model is required: `nomic-embed-text` (137M parameters, ~274MB RAM, 768-dim embeddings). Total new disk footprint is approximately 430MB of installed packages.

**Core technologies (v3 additions):**
- **yfinance >=1.2.0**: Free market data (price history, earnings, fundamentals, news) — only option with no API key and active maintenance (v1.2.0, Feb 2026); wrap in `asyncio.to_thread()` with per-ticker `asyncio.Lock`
- **chromadb >=1.5.0,<2.0**: Embedded vector store for RAG — PersistentClient (SQLite-backed, no server process), `OllamaEmbeddingFunction` for nomic-embed-text integration; pin <2.0 to avoid breaking changes
- **edgartools >=5.6.0**: SEC EDGAR 10-K/10-Q XBRL parsing — free, no API key, supplements yfinance fundamentals; can be deferred to v3.x
- **nomic-embed-text (Ollama)**: 768-dim text embeddings for ChromaDB — 274MB, ~9000 tokens/sec on Apple Silicon; loaded only during RAG phases via `keep_alive=0` ephemeral pattern

### Expected Features

**Must have (v3.0 table stakes — without these the milestone claim is hollow):**
- **Ticker extraction from seed rumors** — LLM extraction (orchestrator, same call as entity extraction) + yfinance validation; critical path root for everything downstream
- **Live market data pipeline** — async-wrapped yfinance for price history, fundamentals, earnings; single source first; stored in `MarketSnapshot` Pydantic model; fetched once before Round 1
- **Agent context enrichment** — inject formatted market data block into agent prompts; hard cap at ~2000 chars for enriched context; pre-summarized data only (never raw JSON)
- **Enhanced AgentDecision output** — add optional `ticker`, `expected_return_pct`, `time_horizon` fields; all new fields have `None` defaults for backward compatibility
- **Per-stock TUI consensus panel** — new `TickerPanel` widget showing consensus signal, confidence, and vote distribution per extracted ticker

**Should have (v3.x differentiators — add once core pipeline is stable):**
- **RAG knowledge base** — ChromaDB + nomic-embed-text for historical earnings reactions and market patterns; requires careful model lifecycle management
- **Bracket-specific data slicing** — tailor injected data per bracket archetype (Quants get price/vol/technicals, Macro gets sector indices)
- **Confidence-weighted consensus** — weight votes by confidence score and influence_weight for more nuanced consensus
- **Multi-source data resilience** — Alpha Vantage fallback for yfinance failures; disk cache with TTL for repeated dev runs
- **News headline injection** — yfinance `.news` property for free headlines, optional NewsAPI for richer coverage

**Defer to v4+:**
- Multiple concurrent tickers per simulation with separate consensus tracks
- RAG auto-population after each simulation run
- Historical simulation comparison (current consensus vs historical outcomes)
- Sector correlation analysis and cross-ticker correlation matrices

### Architecture Approach

v3.0 inserts three new stages between the existing seed injection and Round 1 dispatch: ticker extraction (extending the orchestrator's JSON output schema), market data fetch (MarketDataProvider via `asyncio.to_thread()`), and RAG context build (RAGKnowledgeBase via ChromaDB). A new `ContextEnricher` assembles these into a budget-capped prompt block injected as a system message in `AgentWorker.infer()`. All new components wire through `AppState` (the existing DI container) as optional attributes, making RAG and market data opt-in features that degrade gracefully to v2 behavior when absent. The model loading choreography is strictly sequential to respect `OLLAMA_MAX_LOADED_MODELS=2`.

**Major components (new):**
1. **TickerExtractor** (`ticker.py`) — extends `inject_seed()` to extract ticker symbols in the same orchestrator call; validates against yfinance post-extraction
2. **MarketDataProvider** (`market_data.py`) — async aggregator wrapping yfinance (primary), EDGAR via httpx (earnings depth), and yfinance news (headlines); produces immutable `MarketSnapshot` per ticker; disk-cached with TTL
3. **RAGKnowledgeBase** (`rag.py`) — ChromaDB PersistentClient with OllamaEmbeddingFunction; pre-seeded with historical earnings reactions; queried once per simulation in batch (not per agent)
4. **ContextEnricher** (`context.py`) — assembles market data + RAG results into a 2000-char budget-capped string injected into agent prompts
5. **EnhancedAgentDecision** (extends `types.py`) — optional `ticker`, `expected_return`, `time_horizon` fields added to existing `AgentDecision` with None defaults

**Existing components requiring modification:**
- `seed.py` — augment orchestrator prompt for ticker extraction in same LLM call
- `worker.py` — accept optional `market_context: str | None` parameter
- `batch_dispatcher.py` — thread `market_context` through to agent inference
- `simulation.py` — add enrichment phase between seed injection and Round 1
- `parsing.py` — extend 3-tier fallback to handle new optional AgentDecision fields
- `state.py` — extend `StateSnapshot` with ticker and market data fields
- `tui.py` — add `TickerPanel` widget and extend bracket panel for per-ticker breakdown
- `graph.py` — add `:Ticker` node type with `:MENTIONS` edge from Cycle node

### Critical Pitfalls

1. **Embedding model evicts inference models mid-simulation** — nomic-embed-text counts toward `OLLAMA_MAX_LOADED_MODELS=2`; if loaded during rounds it evicts the worker, causing cascading PARSE_ERRORs and slot starvation. Avoid by running all embedding operations before loading the worker model; use `keep_alive=0` on embedding calls for automatic cleanup.

2. **yfinance blocks the event loop and is not thread-safe** — `yfinance.download()` blocks async context; concurrent calls silently corrupt results via a shared global dict. Avoid by wrapping all yfinance calls in `asyncio.to_thread()` with a per-ticker `asyncio.Lock`; fetch all market data in a dedicated pre-simulation phase, never during rounds.

3. **RAG context injection overflows agent prompt token budget** — existing prompts consume ~1720–2000 of 2048 available tokens; adding market data and RAG precedents overflows, causing Ollama to silently truncate the system prompt and collapse agent personas. Avoid by implementing a `PromptBudgetAllocator` with priority ordering (system prompt never cut), increasing `num_ctx` to 4096 in the worker Modelfile, and pre-summarizing all injected data to compact formats.

4. **ChromaDB memory pressure compounds with unified memory** — on M1 Max, ChromaDB HNSW index (~100–200MB for 10K docs), Ollama models (~30GB), Neo4j (~2GB), Python process (~500MB), and OS (~4GB) sum to ~37–39GB at idle; the governor oscillates into THROTTLED state before simulation begins. Avoid by profiling baseline memory with production-scale collections, capping ChromaDB at 500MB via LRU config, and adjusting governor thresholds upward by ~5% to account for the new resident footprint.

5. **API rate limits create silent data gaps** — Alpha Vantage free tier is 25 calls/day (3 calls per ticker = 8 tickers exhausts the quota); Alpha Vantage returns rate-limit errors as 200 OK with error text in the body. Avoid by using yfinance as primary (no hard daily limit), implementing disk cache with TTL, and running `DataCompleteness` validation that warns or aborts when >30% of tickers have incomplete data.

6. **Per-agent ChromaDB queries serialize the dispatch wave** — 100 synchronous ChromaDB calls through `asyncio.to_thread()` add 1–5 seconds per round due to GIL contention; HNSW cache misses add 500ms–2s each, creating a thundering herd. Avoid by pre-fetching ALL RAG context in batch before `dispatch_wave()` — one query per (ticker, bracket) pair (~10–15 queries total), then pass as static context to agents.

7. **Enhanced AgentDecision schema breaks parsing fallback paths** — doubling the JSON output schema fields increases malformed output frequency, especially from high-temperature brackets (DEGENS at temp=1.2 may have 50%+ parse failure on new fields). Avoid by making all new fields `Optional` with `None` defaults, extending the regex fallback to extract new fields independently, and testing with real model output at production temperatures before enabling v3 mode.

## Implications for Roadmap

Based on research, the feature dependency graph mandates a sequential build order with one parallel track. The critical path runs: ticker extraction → market data pipeline → context enrichment & enhanced decisions → TUI display. RAG can be developed in parallel with the market data pipeline and merges in at the context enrichment phase.

### Phase 16: Ticker Extraction

**Rationale:** The absolute critical-path root. Every downstream v3 feature requires resolved ticker symbols. No external API dependencies beyond the already-running Ollama. Lowest risk, highest leverage entry point.
**Delivers:** Orchestrator extracts `TickerSymbol` objects from seed rumors; yfinance validates against live symbol data; `:Ticker` nodes persisted to Neo4j; `EnrichedSeedEvent` replaces `SeedEvent` in the pipeline.
**Addresses:** Ticker extraction (table stakes P1)
**Avoids:** Schema regression risk — introduces the extended orchestrator JSON schema in isolation before any parsing pipeline complexity increases

### Phase 17: Live Market Data Pipeline

**Rationale:** Second in the critical path. Depends on Phase 16 for ticker symbols. Establishes the pre-simulation data fetch pattern that all subsequent phases build on. Must be fully async and disk-cached before any agent code touches it.
**Delivers:** `MarketDataProvider` with async-wrapped yfinance (primary), EDGAR httpx fetcher (earnings depth), caching with TTL, `DataCompleteness` validation, `MarketSnapshot` Pydantic model; yfinance news headlines bundled as zero-config addition.
**Uses:** yfinance >=1.2.0, edgartools >=5.6.0, existing httpx
**Implements:** MarketDataProvider architecture component
**Avoids:** Pitfall 2 (event loop blocking), Pitfall 5 (rate limit data gaps)

### Phase 18: Agent Context Enrichment & Enhanced Decisions

**Rationale:** The integration hub where market data (and later RAG) context gets injected into agent prompts. Bundles enhanced AgentDecision changes because agents need enriched context to reliably produce ticker-specific output fields.
**Delivers:** `ContextEnricher` with `PromptBudgetAllocator` (hard 2000-char cap, priority-ordered truncation), worker model `num_ctx` increased to 4096, `market_context` threaded through `batch_dispatcher.py` to `worker.py`, optional `ticker`/`expected_return_pct`/`time_horizon` fields on `AgentDecision`, extended 3-tier parse fallback.
**Implements:** ContextEnricher, EnhancedAgentDecision architecture components
**Avoids:** Pitfall 3 (prompt token overflow), Pitfall 7 (parsing regression)

### Phase 19: Per-Stock TUI Consensus Display

**Rationale:** The user-visible payoff for Phases 16–18. Depends on enhanced decisions flowing through the pipeline. Keeps TUI changes isolated from data pipeline complexity.
**Delivers:** `TickerPanel` widget with per-ticker consensus signal, confidence, and bracket breakdown; confidence-weighted aggregation alongside simple majority; market data freshness indicator in TUI header; export includes per-stock sections.
**Addresses:** Per-stock TUI panel (table stakes P1), confidence-weighted consensus (differentiator P2)
**Avoids:** UX pitfall of an invisible data pipeline with no user-facing output

### Phase 20: RAG Knowledge Base

**Rationale:** Independent of the market data critical path but merges at the context enrichment layer (Phase 18 must be complete to accept RAG context as an additional prompt section). Higher complexity and risk than Phases 16–19 due to Ollama model lifecycle constraints and ChromaDB memory implications.
**Delivers:** `RAGKnowledgeBase` (ChromaDB PersistentClient + OllamaEmbeddingFunction), `alphaswarm seed-knowledge` CLI command, pre-built dataset of ~500–1000 historical earnings reactions, batch pre-fetch pattern (~10–15 ChromaDB queries before dispatch_wave), bracket-specific data slicing as bundled differentiator.
**Uses:** chromadb >=1.5.0,<2.0, nomic-embed-text (Ollama)
**Implements:** RAGKnowledgeBase architecture component
**Avoids:** Pitfall 1 (embedding model eviction), Pitfall 4 (ChromaDB memory pressure), Pitfall 6 (per-agent RAG serialization)

### Phase 21: Post-Simulation Report & Integration Hardening

**Rationale:** Lowest dependency, natural integration checkpoint. Extends the existing ReACT report agent and validates the full v3.0 end-to-end pipeline under production conditions.
**Delivers:** Report agent extended with per-ticker Cypher tools and market context comparison; `:Ticker` Neo4j queries for consensus aggregation; simulation result export to ChromaDB knowledge base; end-to-end integration test suite; governor threshold documentation updated for v3 memory profile.
**Addresses:** Post-sim report with market context (P3), multi-source resilience polish
**Avoids:** Remaining integration gotchas (EDGAR User-Agent header, Alpha Vantage 200-OK error pattern)

### Phase Ordering Rationale

- **Linear critical path (16 → 17 → 18 → 19)** enforced by the feature dependency graph: each phase produces artifacts consumed by the next; no phase can be safely skipped or reordered.
- **RAG (Phase 20) after TUI (Phase 19)** because the core v3 value proposition (live-data-grounded consensus) is demonstrable without RAG. Shipping a functional v3.0 before tackling the highest-risk phase reduces integration surface area.
- **Report hardening last (Phase 21)** because it depends on all upstream data flowing correctly and is the easiest phase to retrofit once the pipeline is stable.
- **Enhanced decisions bundled into Phase 18** (not a separate phase) because agents only reliably emit ticker-specific fields when enriched context is already flowing into prompts; testing them in isolation produces mostly null values.
- **Bracket-specific data slicing bundled into Phase 20** because it requires the same `ContextEnricher` infrastructure used for RAG and is a configuration-layer change, not a new component.

### Research Flags

Phases requiring `/gsd:research-phase` during planning:

- **Phase 17 (Market Data Pipeline):** yfinance unofficial API is subject to Yahoo Finance endpoint changes; Alpha Vantage free-tier 25 calls/day is a severe constraint that needs integration test design; EDGAR User-Agent enforcement policy should be verified against current SEC guidelines.
- **Phase 18 (Context Enrichment):** Token budget analysis needs re-running against the actual qwen3.5:9b tokenizer (current numbers are character-count approximations); `num_ctx=4096` KV cache memory impact on governor thresholds needs profiling before committing to Modelfile changes.
- **Phase 20 (RAG Knowledge Base):** ChromaDB 1.x has a history of breaking changes in point releases; OllamaEmbeddingFunction + PersistentClient combination needs hands-on validation on M1 Max hardware; memory baseline profiling (psutil at idle with production-scale collection) is mandatory before governor threshold adjustments.

Phases with well-established patterns (skip research-phase):

- **Phase 16 (Ticker Extraction):** Purely extends existing orchestrator prompt and parsing pipeline — same patterns as existing entity extraction, same 3-tier fallback; no new external dependencies.
- **Phase 19 (TUI Display):** Textual DataTable and widget composition are well-documented; follows the existing BracketPanel pattern exactly.
- **Phase 21 (Report/Integration):** Extends existing ReACT agent toolset using established Cypher + Jinja2 patterns.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | v1/v2 stack validated in production; new deps verified against official docs (yfinance v1.2.0, chromadb v1.5.5, edgartools v5.28.3); nomic-embed-text memory verified via HuggingFace discussions |
| Features | HIGH | Feature set validated against TradingAgents (CMU 2024), P1GPT (2025), AlphaAgents (2025); table stakes / differentiator / anti-feature split is well-reasoned with explicit competitor comparisons |
| Architecture | MEDIUM-HIGH | Integration points within existing codebase are HIGH confidence (well-mapped to existing code); external API reliability (yfinance unofficial, Alpha Vantage free tier) introduces MEDIUM uncertainty; ChromaDB + Ollama model loading interaction needs hands-on validation |
| Pitfalls | HIGH | All 7 critical pitfalls verified via specific GitHub issues (yfinance #2557, Ollama #12247), official docs, and prior governor deadlock analysis; warning signs and recovery strategies are concrete and actionable |

**Overall confidence:** HIGH

### Gaps to Address

- **yfinance unofficial API stability:** Yahoo Finance has broken yfinance before. The disk cache with TTL must be implemented early in Phase 17 to decouple development velocity from API availability. A graceful fallback to stale cached data should always be available.
- **Token budget: character estimates vs tokenizer counts:** Current budget analysis uses character-count approximations (~4 chars/token). Phase 18 planning must use the actual qwen3.5:9b tokenizer to get accurate numbers before committing to `num_ctx` configuration and `PromptBudgetAllocator` constants.
- **ChromaDB memory at production scale:** The 10K-document footprint estimate (~100–200MB HNSW) is calculated from documented formulas, not measured on M1 Max. Phase 20 must begin with a memory profiling spike before building the full ingestion pipeline.
- **Alpha Vantage free-tier viability as a fallback:** 25 calls/day may be impractical during development. If the disk cache is not in place, a single morning of testing exhausts the daily quota. Treat Alpha Vantage as an optional enhancement rather than a primary fallback until caching is proven.

## Sources

### Primary (HIGH confidence)
- [yfinance PyPI v1.2.0](https://pypi.org/project/yfinance/) — version, maintenance status
- [yfinance GitHub Issue #2557](https://github.com/ranaroussi/yfinance/issues/2557) — confirmed thread-safety issue with shared global dict
- [ChromaDB PyPI v1.5.5](https://pypi.org/project/chromadb/) — version, 1.x stable release confirmation
- [ChromaDB PersistentClient docs](https://docs.trychroma.com/reference/python/client) — embedded SQLite mode, no server process
- [ChromaDB Ollama integration docs](https://docs.trychroma.com/integrations/embedding-models/ollama) — OllamaEmbeddingFunction usage
- [ChromaDB resource requirements](https://cookbook.chromadb.dev/core/resources/) — HNSW memory footprint calculation
- [edgartools PyPI v5.28.3](https://pypi.org/project/edgartools/) — version, free SEC EDGAR access
- [nomic-embed-text Ollama registry](https://ollama.com/library/nomic-embed-text) — model specs (137M params, 768-dim, ~274MB)
- [nomic-embed-text memory requirements](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5/discussions/15) — ~274MB RAM verified
- [Ollama Issue #12247](https://github.com/ollama/ollama/issues/12247) — embedding models count toward loaded model limit, evict inference models
- [Ollama FAQ — OLLAMA_MAX_LOADED_MODELS](https://docs.ollama.com/faq) — 2-model limit behavior
- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) — free, no auth, 10 req/sec, User-Agent required
- [Alpha Vantage pricing](https://www.alphavantage.co/premium/) — 25 req/day free tier confirmed
- [Alpha Vantage 200-OK error pattern](https://www.macroption.com/alpha-vantage-api-limits/) — error-as-successful-response behavior documented

### Secondary (MEDIUM confidence)
- [TradingAgents: Multi-Agents LLM Financial Trading Framework](https://arxiv.org/abs/2412.20138) — CMU Dec 2024, competitor feature analysis
- [P1GPT: Multi-Agent LLM Workflow for Financial Analysis](https://arxiv.org/html/2510.23032v1) — 2025, competitor analysis
- [AlphaAgents: LLM-based Multi-Agents for Equity Portfolio](https://arxiv.org/html/2508.11152v1) — 2025, competitor analysis
- [Context Window Overflow — Redis Blog](https://redis.io/blog/context-window-overflow/) — context rot and ~30% accuracy drop at mid-window positions
- [ChromaDB memory management — LRU cache strategy](https://cookbook.chromadb.dev/strategies/memory-management/) — configurable memory limits and segment eviction

### Tertiary (LOW confidence — needs validation during implementation)
- Governor threshold adjustments (+5% throttle, +2% pause) for ChromaDB baseline — calculated from formula, not measured; validate in Phase 20 memory profiling spike
- `num_ctx=4096` KV cache memory impact at 16 parallel contexts — estimated ~4GB; validate in Phase 18 before committing to worker Modelfile change
- edgartools classified as "optional" — based on assessment that yfinance earnings coverage is sufficient for v3 MVP; re-evaluate if yfinance fundamentals prove insufficient in Phase 17 testing

---
*Research completed: 2026-04-05*
*Ready for roadmap: yes*
