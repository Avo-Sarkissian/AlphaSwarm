# Feature Research: v3.0 Stock-Specific Recommendations with Live Data & RAG

**Domain:** Multi-agent LLM-powered financial simulation with live market data grounding and RAG retrieval
**Researched:** 2026-04-05
**Confidence:** HIGH (stack components verified via official docs and multiple sources)
**Scope:** v3.0 milestone features ONLY. v1 (Phases 1-10) and v2 (Phases 11-15) features are validated and shipped.

## Existing Foundation (Already Built -- Not Re-Researched)

Listed to establish dependency roots for v3 features.

- 100-agent swarm across 10 bracket archetypes with distinct risk profiles
- 3-round iterative cascade (Initial Reaction, Peer Influence, Final Consensus Lock)
- Dynamic influence topology via INFLUENCED_BY edges from citation/agreement patterns
- Textual TUI: 10x10 agent grid, rationale sidebar, telemetry footer, bracket panel
- Neo4j graph state with cycle-scoped indexes and batch writing
- Seed rumor injection with entity extraction via orchestrator LLM (EntityType: COMPANY, SECTOR, PERSON)
- ResourceGovernor with TokenPool and 5-state governor machine
- StateStore bridge (simulation writes, TUI reads snapshots at 200ms tick)
- Live graph memory: RationaleEpisode nodes with REFERENCES edges, decision_narrative on Agent nodes
- Social-style rationale posts consumed by peers, implicit reactions via CITED edges
- Dynamic persona generation: entity-aware modifier injection per bracket
- Agent interviews: post-sim multi-turn Q&A with reconstructed context
- Post-simulation reports: ReACT agent with Cypher tools + Jinja2 templates

---

## Feature Landscape

### Table Stakes (Users Expect These for v3)

Features that a "stock-specific with live data" milestone MUST deliver. Without these, v3 is a prompt engineering exercise, not data-grounded analysis.

| Feature | Why Expected | Complexity | Dependencies on Existing | Notes |
|---------|--------------|------------|--------------------------|-------|
| **Ticker extraction from seed rumors** | The existing entity extraction (Phase 5) produces EntityType.COMPANY/SECTOR/PERSON but no stock tickers. A rumor like "Apple is acquiring Tesla's battery division" needs to resolve to AAPL and TSLA before any market data can be fetched. Every financial analysis system (TradingAgents, P1GPT, AlphaAgents) starts with ticker identification. Without this, there is nothing to query market APIs for. | LOW | Extends `inject_seed()` in seed.py. Extends the orchestrator system prompt to also return tickers. Adds `ticker` field to `SeedEntity` model. Consumes existing 3-tier parse fallback. | Two approaches: (1) LLM-native extraction -- extend the ORCHESTRATOR_SYSTEM_PROMPT to also return `"ticker": "AAPL"` per entity. This is the right first step because the orchestrator is already loaded and entity extraction is already happening. (2) Validation lookup -- after LLM extraction, validate tickers against a static symbol table (SEC company_tickers.json, 13K entries, 2MB file). The validation step catches hallucinated tickers. Use sec-cik-mapper or a cached SEC tickers JSON for the lookup, not a runtime API call. |
| **Live market data fetching (price + fundamentals)** | Once tickers are extracted, agents need actual market data to ground their analysis. Without real data, a rumor about Apple still produces the same "generic bullish/bearish" outputs as v2. TradingAgents, P1GPT, and every serious financial agent framework injects real market data. This is the core value proposition of v3 -- grounding simulation in reality. | HIGH | New module (e.g., `market_data.py`). Must be fully async (asyncio + httpx). Called between seed injection and Round 1 dispatch. Data stored in a `MarketContext` Pydantic model consumed by agent prompt builder. Respects existing governor memory monitoring. | yfinance is the right primary source: free, no API key, covers price history + financials + earnings + news headlines. yfinance v1.0 (Jan 2026) is stable. BUT yfinance is synchronous and uses requests internally -- must wrap in `asyncio.to_thread()` or use httpx directly against Yahoo Finance endpoints. Alpha Vantage is the right supplementary source for earnings surprise data (reported vs estimated EPS) -- free tier: 500 calls/day, 5/minute, has native async support since v2.2.0. Aggregate data from multiple sources into a single `MarketContext` per ticker. |
| **Agent context enrichment with structured data** | Fetching market data is pointless unless agents actually receive it. The existing worker prompt pipeline (system_prompt + optional peer_context + user_message) must be extended with a structured data block. Without data injection, agents hallucinate financial metrics. TradingAgents provides each analyst role with different data slices (fundamentals for fundamental analyst, sentiment scores for sentiment analyst). | MEDIUM | Extends `AgentWorker.infer()` and `_format_peer_context()` in simulation dispatch. Adds a new `market_context` parameter to the worker inference path. Modifies prompt assembly in `worker.py`. Must stay within Ollama context window limits. | The design: inject a `[MARKET DATA]` block into the user message before the rumor text. Format as structured but readable text, not raw JSON -- agents parse natural language better than raw numbers. Different brackets should receive different data emphasis: Quants get price/vol/technicals, Macro gets sector/index correlations, Insiders get earnings surprise data. Keep total injected data under 500 tokens per agent to avoid context window pressure (qwen3.5:7b has 32K context, but 100-agent throughput matters more than max context usage). |
| **Enhanced AgentDecision output** | v2 AgentDecision has: signal (BUY/SELL/HOLD), confidence (0-1), sentiment (-1 to 1), rationale (text), cited_agents (list). For stock-specific analysis, agents must also emit: ticker, direction (more nuanced than BUY/SELL), expected_return_pct, and time_horizon. Without these, the "stock-specific" promise is broken -- you just get generic signals with no actionable specificity. | LOW | Extends `AgentDecision` Pydantic model in types.py. Extends `JSON_OUTPUT_INSTRUCTIONS` in config.py. Extends `parse_agent_decision()` in parsing.py with new field handling. Must preserve backward compatibility (new fields optional with defaults). | Add fields: `ticker: str = ""`, `expected_return_pct: float = 0.0`, `time_horizon: str = ""` (e.g., "1w", "1m", "3m"). Keep signal as BUY/SELL/HOLD for TUI color mapping compatibility. The 3-tier parse fallback already handles missing fields gracefully via Pydantic defaults. Extend the JSON output instruction string to include the new fields. |
| **Per-stock consensus display in TUI** | The existing TUI shows a flat 10x10 grid and per-bracket summary bars. With multi-ticker support, users need to see which stocks the swarm is bullish/bearish on. Without per-stock breakdown, the TUI shows the same aggregate view as v2 -- the live data investment is invisible to the user. | MEDIUM | Extends `StateStore` with per-ticker aggregation data. Extends `StateSnapshot` with ticker summary fields. New TUI widget (or extends `BracketPanel`) for ticker-level consensus. Uses existing 200ms snapshot polling -- no new render architecture. | Design: a new `TickerPanel` widget showing each extracted ticker with its consensus signal, confidence-weighted vote, and bracket disagreement indicator. Keep it minimal -- 1-2 lines per ticker, not a full financial dashboard. The BracketPanel already demonstrates the pattern: compute summaries after each round, store in StateStore, render in TUI via snapshot. Apply the same pattern for ticker summaries. |

### Differentiators (Competitive Advantage)

Features that set AlphaSwarm v3 apart from TradingAgents, P1GPT, and AlphaAgents. Not required for a complete v3, but high-value.

| Feature | Value Proposition | Complexity | Dependencies on Existing | Notes |
|---------|-------------------|------------|--------------------------|-------|
| **RAG knowledge base for historical precedents** | TradingAgents and P1GPT use simple web search for context. AlphaSwarm can offer deeper grounding: "The last time Apple's P/E was this high before an acquisition, the stock dropped 12% over 3 months." Historical pattern retrieval transforms agents from reactive (analyzing current data) to comparative (current data vs historical precedent). This is the differentiator that makes AlphaSwarm's consensus cascade unique -- agents argue with historical evidence, not just opinions. | HIGH | New module (e.g., `rag.py`). ChromaDB for vector storage, nomic-embed-text via Ollama for embeddings. Must manage Ollama model loading carefully -- embedding model is a 3rd model alongside orchestrator and worker. Pre-populated with earnings reaction data, sector correlation patterns, historical events. | ChromaDB runs as a local persistent SQLite-backed store (no server process needed). nomic-embed-text is only 274MB and generates 768-dim embeddings. CRITICAL CONSTRAINT: Ollama max_loaded_models=2. The embedding model must be loaded/unloaded strategically -- load for RAG retrieval before Round 1, unload before worker model loads. This adds ~10-15s for model swap. ChromaDB PersistentClient with HNSW index delivers sub-millisecond query times. Pre-seed the knowledge base with curated historical data (earnings reactions, sector correlations, crisis patterns) as a one-time setup step. |
| **Bracket-specific data slicing** | TradingAgents gives all analysts the same data. AlphaSwarm's 10 brackets have distinct analytical frameworks -- Quants care about volatility and ratios, Macro cares about sector indices and rates, Doom-Posters focus on debt levels and systemic risk. Tailoring the injected data per bracket creates more realistic, diverse reactions. Without this, all 100 agents react to the same data blob and converge faster (less interesting simulation). | MEDIUM | Extends the context enrichment pipeline. Requires a bracket-to-data-slice mapping. Modifies `_build_agent_prompt()` or equivalent in simulation dispatch. Uses existing bracket metadata from BracketConfig. | The design: define a `DataSliceConfig` per BracketType that specifies which MarketContext fields to include. Quants: price history, volatility, P/E, technical indicators. Degens: recent price momentum, options IV, social mentions. Sovereigns: market cap, dividend yield, currency exposure. Macro: sector performance, index correlation, rate sensitivity. This is a configuration-driven approach -- no extra LLM calls, just different prompt templates per bracket. |
| **News headline injection** | Beyond price and fundamentals, recent news headlines about extracted tickers add narrative context. Agents (especially Insiders and Policy Wonks) should react to news, not just numbers. TradingAgents includes a dedicated "news analyst" agent role for this. | MEDIUM | Extends `MarketContext` with a `headlines` field. yfinance provides basic news data per ticker. NewsAPI or Marketaux for richer coverage (requires API key but has free tier). Must handle async fetching with rate limits. | yfinance's `Ticker.news` property returns recent headlines -- this is the zero-config starting point. For richer data, Alpha Vantage's "Alpha Intelligence" endpoint provides sentiment-scored news. Limit to 5-10 headlines per ticker to control prompt token count. |
| **Confidence-weighted consensus aggregation** | v2 consensus is simple majority: count BUY/SELL/HOLD across all agents. v3 should weight votes by confidence score and bracket influence weight. A Sovereign at 0.9 confidence and 0.9 influence weight should matter more than a Degen at 0.3 confidence and 0.3 influence weight. This produces more nuanced, realistic consensus outcomes. | LOW | Extends `compute_bracket_summaries()` in simulation.py. Extends StateStore and TUI rendering. Pure computation -- no new infrastructure. | Formula: `weighted_signal = sum(confidence * influence_weight * signal_value) / sum(confidence * influence_weight)` where signal_value is +1 (BUY), 0 (HOLD), -1 (SELL). Display as a continuous score (-1.0 to +1.0) alongside the discrete majority vote. |
| **Multi-source data resilience** | If yfinance is down (common with unofficial APIs), fall back to Alpha Vantage. If both are down, proceed with whatever data was collected. Graceful degradation is what separates a toy from a tool. | LOW | Extends `market_data.py` with fallback chain. Uses existing error handling patterns (3-tier parse fallback as precedent). | Implement a priority-ordered source chain: yfinance (primary, no key needed) -> Alpha Vantage (secondary, free key) -> cached stale data (tertiary). Each source has a timeout. If all fail, the simulation proceeds without market data (agents analyze the rumor text only, like v2). Log which sources succeeded/failed. |
| **Post-sim report with market data context** | The existing ReACT report agent queries Neo4j for simulation data. v3 should also reference the live market data that was injected, comparing agent consensus with actual market indicators. "The swarm consensus was BULLISH on AAPL at 87% confidence, while the stock's RSI was 72 (overbought territory)." | LOW | Extends the ReACT agent's tool set with a `get_market_context` tool. MarketContext must be persisted (Neo4j or local cache) for post-sim access. | Store the fetched MarketContext as a JSON property on the Cycle node in Neo4j, or as a separate MarketData node linked to the Cycle. The report agent then has both simulation consensus AND market reality to compare. |

### Anti-Features (Commonly Requested, Explicitly Not Building)

Features that seem like natural v3 additions but create problems. These traps are especially dangerous because "live market data" opens an infinite scope surface.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Real-time streaming price updates during simulation** | If we are fetching market data, why not update it continuously during the 3 rounds? Show live price changes in the TUI. | A simulation run takes 10-20 minutes on M1 Max. Market data from simulation start is the correct analytical baseline -- mid-simulation price changes would create inconsistency between agents (early agents saw price X, late agents saw price Y). Also adds continuous API polling load alongside 100-agent inference. The simulation analyzes a point-in-time snapshot, not a live feed. | Fetch all market data once before Round 1. Freeze it as the simulation's analytical baseline. Display the fetch timestamp in the TUI. |
| **Full technical analysis indicator library** | Since we have price history, calculate RSI, MACD, Bollinger Bands, moving averages, etc. Give agents a complete technical analysis toolkit. | Calculating 20+ indicators per ticker adds complexity without proportional simulation value. Agents are LLMs parsing text -- they do not run technical analysis calculations. Providing pre-calculated indicators as numbers in prompt text is marginally more useful than raw price data. The prompt token cost of injecting 20 indicators is significant. | Inject 3-5 key metrics that bracket archetypes actually reference: current price, 52-week range, P/E ratio, recent volume vs average, and basic trend direction (up/down/flat based on 50-day MA). Enough for grounding, not enough to bloat prompts. |
| **LangChain/LlamaIndex RAG framework dependency** | LlamaIndex has VectorStoreIndex, ChromaDB integration, and query engines. LangChain has RAG chains. Using a framework would accelerate development. | Both frameworks add heavyweight dependency trees (LangChain core: 50+ transitive deps; LlamaIndex: 30+). AlphaSwarm's RAG need is simple: embed query -> retrieve top-K from ChromaDB -> format as context string. This is 20 lines of code with chromadb + ollama-python directly. The existing codebase already avoids framework dependencies (hand-rolled ReACT, direct Ollama calls). Adding a framework for simple retrieval violates the project's architectural consistency. | Direct ChromaDB Python client + Ollama embed API. `collection.query(query_embeddings=[...], n_results=5)` returns results. Format as text. Inject into prompt. No framework needed. |
| **Autonomous portfolio construction from consensus** | TradingAgents and AlphaAgents produce actual portfolio allocations (ticker, weight, entry price). AlphaSwarm should too. | AlphaSwarm is a simulation engine that analyzes market reactions to rumors, not a trading system. Producing portfolio allocations implies actionability and creates liability concerns. The value is in the consensus cascade analysis ("how would 100 diverse market participants react?"), not in a specific trade recommendation. | Enhanced AgentDecision with ticker, direction, expected_return_pct, and time_horizon. The user interprets the consensus; the system does not prescribe trades. The post-sim report synthesizes the analysis without actionable trade instructions. |
| **Unlimited ticker support per rumor** | A rumor might mention 10+ companies. Fetch data for all of them. Let agents analyze the full network. | Each additional ticker multiplies: API calls (3-5 per source per ticker), prompt tokens (300-500 tokens of data per ticker per agent), RAG queries (2-3 per ticker), and TUI display space. With 5 tickers and 100 agents, that is 50,000+ tokens of injected market data per round. Context windows fill, inference slows, API rate limits hit. | Cap at 3 tickers per simulation, ranked by relevance score from entity extraction. Display a warning if more tickers are detected. The user can re-run with a focused rumor for specific tickers. |
| **Paid API integrations (Bloomberg, Refinitiv, IEX Cloud Pro)** | Free data sources have rate limits, delays, and missing fields. Professional APIs are more reliable and comprehensive. | Violates the local-first, free-to-run ethos. Adding paid dependencies creates friction for setup and narrows the user base. The simulation does not need institutional-grade data fidelity -- it needs "good enough" data to ground LLM agent reasoning. | yfinance (free, no key) + Alpha Vantage (free tier, free key) + SEC EDGAR (free, no key). Three free sources with fallback chain provides sufficient data quality for simulation grounding. |
| **Embedding model always loaded alongside worker** | Keep nomic-embed-text loaded so RAG queries can happen during rounds, not just before. | Ollama max_loaded_models=2. Worker model + embedding model = 2, which means the orchestrator cannot be loaded for seed injection or report generation without unloading one. The model swap overhead (10-15s per swap) would occur at every phase transition, adding minutes to simulation runtime. | Load embedding model once before Round 1 for RAG retrieval. Unload before loading worker model. All RAG retrieval happens in a pre-simulation enrichment phase, not during rounds. |

## Feature Dependencies

```
[Ticker Extraction]
    |
    v
[Live Market Data Fetching] -----> [Multi-Source Resilience]
    |                                       |
    |                                       v
    |                               [News Headline Injection]
    |
    v
[Agent Context Enrichment] <------- [Bracket-Specific Data Slicing]
    |
    v
[Enhanced AgentDecision Output]
    |
    v
[Per-Stock Consensus Display (TUI)] <-- [Confidence-Weighted Consensus]
    |
    v
[Post-Sim Report with Market Context]

[RAG Knowledge Base] ----enhances----> [Agent Context Enrichment]
    (independent setup,                  (retrieved precedents
     can be built in                      injected alongside
     parallel with                        live market data)
     market data pipeline)
```

### Dependency Notes

- **Ticker Extraction is the critical path root:** Every downstream feature depends on resolved tickers. Without tickers, there is nothing to query market APIs for, nothing to display per-stock, nothing to retrieve from RAG.
- **Live Market Data Fetching requires Ticker Extraction:** Cannot call yfinance.Ticker("AAPL") without knowing "AAPL" was extracted.
- **Agent Context Enrichment requires Live Market Data:** The enrichment pipeline formats and injects the fetched data. Without data, there is nothing to enrich.
- **Enhanced AgentDecision requires Agent Context Enrichment:** Agents can only emit ticker-specific fields if they received ticker-specific data in their prompts.
- **Per-Stock TUI Display requires Enhanced AgentDecision:** The TUI widget aggregates per-ticker signals from agent decisions. Without ticker fields in decisions, there is nothing to disaggregate.
- **RAG Knowledge Base is independent of Live Market Data:** ChromaDB setup, embedding, and retrieval can be built and tested without any market API integration. It connects to the pipeline at the Agent Context Enrichment stage.
- **Bracket-Specific Data Slicing enhances Agent Context Enrichment:** This is a refinement layer -- v3 can ship with uniform data injection first, then add bracket-specific slicing as a fast follow.
- **Confidence-Weighted Consensus enhances Per-Stock TUI Display:** This is a computation refinement, not a prerequisite. Simple majority works first, weighted scoring follows.

## MVP Definition

### Launch With (v3.0 Core)

Minimum viable product for "stock-specific recommendations with live data."

- [ ] **Ticker extraction** -- Extend orchestrator prompt to emit tickers alongside entities. Validate against SEC tickers JSON. (Unlocks everything downstream.)
- [ ] **yfinance market data pipeline** -- Async-wrapped yfinance fetches for price history, financials, earnings. Single-source first, Alpha Vantage fallback later. Stored in MarketContext Pydantic model.
- [ ] **Agent context enrichment** -- Inject formatted market data block into agent prompts. Uniform data for all brackets initially (bracket-specific slicing is a differentiator, not table stakes).
- [ ] **Enhanced AgentDecision** -- Add ticker, expected_return_pct, time_horizon fields. Extend JSON output instructions and 3-tier parser.
- [ ] **Per-stock TUI panel** -- New TickerPanel widget with consensus signal per extracted ticker. Minimal: ticker symbol, signal color, confidence score, vote distribution.

### Add After Validation (v3.x)

Features to add once core pipeline is working and stable.

- [ ] **RAG knowledge base** -- ChromaDB + nomic-embed-text for historical earnings reactions and market patterns. Requires careful Ollama model lifecycle management.
- [ ] **Bracket-specific data slicing** -- Tailor injected data per bracket archetype for more diverse agent responses.
- [ ] **Alpha Vantage fallback** -- Second data source for resilience and earnings surprise data.
- [ ] **Confidence-weighted consensus** -- Weighted aggregation using confidence and influence_weight.
- [ ] **News headline injection** -- yfinance news + optional NewsAPI for narrative context.
- [ ] **Post-sim report with market context** -- Extend ReACT report agent with market data comparison tools.

### Future Consideration (v4+)

Features to defer until v3 is battle-tested.

- [ ] **Multiple concurrent tickers** -- Support 2-3 tickers per simulation with separate consensus tracks per ticker.
- [ ] **Historical simulation comparison** -- Compare current simulation consensus with historical outcomes for the same ticker.
- [ ] **RAG auto-population** -- Automatically ingest new earnings data and market events into the knowledge base after each simulation.
- [ ] **Sector correlation analysis** -- Extend market data to include sector ETF performance and cross-ticker correlation matrices.

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority | Phase Suggestion |
|---------|------------|---------------------|----------|------------------|
| Ticker extraction | HIGH | LOW | P1 | Phase 16 |
| Live market data pipeline | HIGH | HIGH | P1 | Phase 17 |
| Agent context enrichment | HIGH | MEDIUM | P1 | Phase 18 |
| Enhanced AgentDecision | HIGH | LOW | P1 | Phase 18 (bundle) |
| Per-stock TUI panel | HIGH | MEDIUM | P1 | Phase 19 |
| RAG knowledge base | MEDIUM | HIGH | P2 | Phase 20 |
| Bracket-specific data slicing | MEDIUM | MEDIUM | P2 | Phase 18 (or 20) |
| Confidence-weighted consensus | MEDIUM | LOW | P2 | Phase 19 (bundle) |
| Multi-source resilience | MEDIUM | LOW | P2 | Phase 17 (bundle) |
| News headline injection | LOW | MEDIUM | P2 | Phase 17 (bundle) |
| Post-sim report with market context | LOW | LOW | P3 | Phase 21 |

**Priority key:**
- P1: Must have for v3.0 launch -- without these, the milestone claim is hollow
- P2: Should have, add when core pipeline is stable -- these are what make it good
- P3: Nice to have, rounds out the experience -- the polish layer

## Competitor Feature Analysis

| Feature | TradingAgents (CMU, 2024) | P1GPT (2025) | AlphaAgents (2025) | AlphaSwarm v3 Approach |
|---------|---------------------------|--------------|---------------------|------------------------|
| **Ticker extraction** | Assumes ticker provided as input | Multi-modal extraction from text + images | Ticker provided by user | LLM extraction from natural language rumor + SEC ticker validation. More flexible -- user provides a rumor, not a ticker. |
| **Market data** | Yahoo Finance for fundamentals + technicals | Cross-agent consensus from macro, sector, short-term data | Bloomberg terminal integration | yfinance primary + Alpha Vantage fallback. Free-tier only. Async-wrapped for non-blocking fetches. |
| **RAG / historical context** | Not used. Relies on LLM training data. | Not explicitly used. | Not used. | ChromaDB + nomic-embed-text for historical earnings reactions and market patterns. Local-first, no cloud dependencies. This is a genuine differentiator. |
| **Agent specialization** | Role-based: fundamental analyst, sentiment analyst, technical analyst, trader | Cross-agent consensus with specialized perspectives | Fundamental, sentiment, valuation agents with debate | 10 bracket archetypes with entity-aware dynamic persona generation. Most diverse agent population (100 vs 4-6 in competitors). |
| **Consensus mechanism** | Debate between bullish/bearish roles with facilitator | Cross-agent scoring with risk-reward internalization | Multi-round debate until convergence | 3-round iterative cascade: Initial Reaction -> Peer Influence (with social-style posts) -> Final Consensus Lock. Most structured cascade. |
| **Per-stock display** | Command-line output with trade decisions | Report-style output | Portfolio allocation output | Interactive Textual TUI with real-time grid, per-stock consensus panel, bracket disagreement visualization. Most visual. |
| **Output** | Trade actions (buy/sell/hold with size) | Portfolio P&L report | Portfolio with weights and allocations | Per-ticker consensus with confidence scores + narrative report. Analysis-focused, not trade-focused. |

## Sources

- [TradingAgents: Multi-Agents LLM Financial Trading Framework](https://arxiv.org/abs/2412.20138) -- CMU, Dec 2024
- [P1GPT: Multi-Agent LLM Workflow for Financial Analysis](https://arxiv.org/html/2510.23032v1) -- 2025
- [AlphaAgents: LLM-based Multi-Agents for Equity Portfolio](https://arxiv.org/html/2508.11152v1) -- 2025
- [yfinance v1.0 on PyPI](https://pypi.org/project/yfinance/) -- Jan 2026
- [Alpha Vantage API Documentation](https://www.alphavantage.co/documentation/) -- async support since v2.2.0
- [ChromaDB Official Docs](https://docs.trychroma.com/) -- PersistentClient, Ollama integration
- [nomic-embed-text on Ollama](https://ollama.com/library/nomic-embed-text) -- 274MB, 768-dim embeddings
- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) -- free, no auth
- [sec-cik-mapper on PyPI](https://pypi.org/project/sec-cik-mapper/) -- ticker/CIK/company bidirectional mapping
- [EdgarTools on GitHub](https://github.com/dgunning/edgartools) -- free Python SEC data access
- [stocksTUI on PyPI](https://pypi.org/project/stocksTUI/) -- Textual + yfinance terminal stock viewer (pattern reference)
- [Textual TUI Framework](https://textual.textualize.io/) -- reactive widgets, async-powered

---
*Feature research for: AlphaSwarm v3.0 Stock-Specific Recommendations with Live Data & RAG*
*Researched: 2026-04-05*
