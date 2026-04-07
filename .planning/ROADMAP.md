# Roadmap: AlphaSwarm

## Milestones

- [x] **v1.0 Core Engine** - Phases 1-10 (shipped 2026-03-27)
- [x] **v2.0 Engine Depth** - Phases 11-15 (shipped 2026-04-02)
- [ ] **v3.0 Stock-Specific Recommendations with Live Data** - Phases 16-20 (in progress)

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

<details>
<summary>v1.0 Core Engine (Phases 1-10) - SHIPPED 2026-03-27</summary>

- [x] **Phase 1: Project Foundation** - Scaffold, configuration system, type definitions, and structured logging (completed 2026-03-24)
- [x] **Phase 2: Ollama Integration** - Async LLM client, sequential model loading, and structured output parsing (completed 2026-03-25)
- [x] **Phase 3: Resource Governance** - Dynamic concurrency control, memory monitoring, task safety, and retry logic (completed 2026-03-25)
- [x] **Phase 4: Neo4j Graph State** - Graph schema with cycle-scoped indexes and batch-writing GraphStateManager (completed 2026-03-25)
- [x] **Phase 5: Seed Injection and Agent Personas** - Orchestrator entity extraction and 100 agent personas with decision schema (completed 2026-03-26)
- [x] **Phase 6: Round 1 Standalone** - All 100 agents process a seed rumor independently in a single inference wave (completed 2026-03-26)
- [x] **Phase 7: Rounds 2-3 Peer Influence and Consensus** - Peer context injection and final consensus lock complete the 3-round cascade (completed 2026-03-26)
- [x] **Phase 8: Dynamic Influence Topology** - INFLUENCED_BY edges form from citation patterns, bracket aggregation, and Miro batcher stub (completed 2026-03-26)
- [x] **Phase 9: TUI Core Dashboard** - Agent grid, snapshot-based rendering, and simulation status display (completed 2026-03-27)
- [x] **Phase 10: TUI Panels and Telemetry** - Rationale sidebar, hardware telemetry footer, and bracket aggregation panel (completed 2026-03-27)

</details>

<details>
<summary>v2.0 Engine Depth (Phases 11-15) - SHIPPED 2026-04-02</summary>

- [x] **Phase 11: Live Graph Memory** - Real-time Neo4j rationale episodes, narrative edges, and interview context summaries written during simulation (completed 2026-03-31)
- [x] **Phase 12: Richer Agent Interactions** - Agents publish public rationale posts that peers read and react to via token-budget-aware context injection (completed 2026-04-01)
- [x] **Phase 13: Dynamic Persona Generation** - Entity-aware bracket modifiers generated from seed rumor for situation-specific agent personas (completed 2026-04-02)
- [x] **Phase 14: Agent Interviews** - Post-simulation conversational Q&A with any agent using reconstructed decision context (completed 2026-04-02)
- [x] **Phase 15: Post-Simulation Report** - ReACT agent queries Neo4j and generates structured market analysis as exportable markdown (completed 2026-04-02)

</details>

### v3.0 Stock-Specific Recommendations with Live Data (Phases 16-20)

**Milestone Goal:** Ground the consensus cascade in real market data by extracting tickers from seed rumors, fetching live price/earnings/news data, enriching agent prompts with bracket-tailored context, and surfacing per-stock consensus with confidence-weighted aggregation in the TUI and post-simulation report.

- [x] **Phase 16: Ticker Extraction** - Orchestrator extracts and validates stock ticker symbols from seed rumors as the critical-path root for all v3 features (completed 2026-04-06)
- [x] **Phase 17: Market Data Pipeline** - Async market data fetching via yfinance with Alpha Vantage fallback, disk-cached responses, Neo4j Ticker nodes, and CLI degraded-data warnings (completed 2026-04-06)
- [x] **Phase 18: Agent Context Enrichment and Enhanced Decisions** - Inject budget-capped, bracket-tailored market data into agent prompts and extend AgentDecision with ticker-specific output fields (completed 2026-04-07)
- [ ] **Phase 19: Per-Stock TUI Consensus Display** - Per-ticker consensus panel with confidence-weighted voting and bracket disagreement breakdown
- [ ] **Phase 20: Report Enhancement and Integration Hardening** - Post-simulation report includes market data context comparing agent consensus with actual market indicators

## Phase Details

### Phase 16: Ticker Extraction
**Goal**: The orchestrator resolves specific stock tickers from natural-language seed rumors, giving the entire v3 pipeline concrete symbols to fetch data for and track consensus against
**Depends on**: Phase 15 (v2 complete)
**Requirements**: TICK-01, TICK-02, TICK-03
**Success Criteria** (what must be TRUE):
  1. User enters a seed rumor mentioning companies (e.g., "Apple is acquiring Tesla") and the orchestrator extracts ticker symbols (AAPL, TSLA) alongside existing entity extraction in a single LLM call
  2. Extracted tickers are validated against the SEC company_tickers.json symbol table, and invalid symbols are rejected with a warning before simulation proceeds
  3. When more than 3 tickers are extracted, only the top 3 by relevance score are kept, and the user can see which tickers were selected in the simulation output
**Plans**: 3 plans
Plans:
- [x] 16-01-PLAN.md -- Ticker extraction prompt and LLM call
- [x] 16-02-PLAN.md -- SEC validation and ticker cap
- [x] 16-03-PLAN.md -- CLI display and integration

### Phase 17: Market Data Pipeline
**Goal**: Before Round 1 begins, the system has fetched and cached live market data (price history, financials, earnings) for every extracted ticker, available as structured snapshots for downstream consumption
**Depends on**: Phase 16
**Requirements**: DATA-01, DATA-02, DATA-03, DATA-04
**Success Criteria** (what must be TRUE):
  1. User can run a simulation and see that price history, financial metrics, and earnings data have been fetched for each extracted ticker before any agent inference begins
  2. When yfinance is unavailable or fails for a ticker, the system falls back to Alpha Vantage and continues gracefully; when both fail, the simulation proceeds with degraded data and a visible warning
  3. Each ticker has a news headlines field reserved for Phase 18 (DATA-03 deferred)
  4. Running the same simulation twice within the cache TTL window does not re-fetch from external APIs -- disk-cached responses are reused, and the user sees cache-hit indicators in logs
**Plans**: 3 plans
Plans:
- [x] 17-01-PLAN.md -- Install yfinance, define MarketDataSnapshot model, config, test scaffolds
- [x] 17-02-PLAN.md -- Core market_data.py module (yfinance fetch, cache, AV fallback, tests)
- [x] 17-03-PLAN.md -- Integration wiring (simulation.py, graph.py, cli.py)

### Phase 18: Agent Context Enrichment and Enhanced Decisions
**Goal**: Every agent receives bracket-appropriate market data in its prompt before inference, and produces ticker-specific decisions with direction, expected return, and time horizon
**Depends on**: Phase 17
**Requirements**: ENRICH-01, ENRICH-02, ENRICH-03, DECIDE-01, DECIDE-02
**Success Criteria** (what must be TRUE):
  1. All market data fetching completes before Round 1, and each agent's prompt includes a formatted market data block that stays within a strict token budget preventing context window overflow
  2. Different bracket archetypes receive different data slices -- Quants see price/volume/technicals, Macro agents see Earnings/Insider slice data (earnings surprises, EPS, headlines per D-04), Insiders see earnings surprises -- visible by inspecting agent prompts or rationale output
  3. Agent decisions include ticker, direction, expected_return_pct, and time_horizon fields in their structured output
  4. The 3-tier parse fallback handles new fields gracefully -- agents that fail to produce new fields get backward-compatible None defaults without triggering PARSE_ERROR status
**Plans**: 3 plans
Plans:
- [x] 18-01-PLAN.md -- TickerDecision model, enrichment module with bracket formatting, JSON schema update
- [x] 18-02-PLAN.md -- AV NEWS_SENTIMENT headline fetch and snapshot enrichment
- [x] 18-03-PLAN.md -- Simulation sub-wave dispatch wiring and integration tests

### Phase 19: Per-Stock TUI Consensus Display
**Goal**: Users see the payoff of live data grounding -- per-ticker consensus breakdown in the TUI showing which stocks agents are bullish/bearish on, how confident they are, and where brackets disagree
**Depends on**: Phase 18
**Requirements**: DTUI-01, DTUI-02, DTUI-03
**Success Criteria** (what must be TRUE):
  1. After simulation completes, the TUI displays a per-ticker consensus panel showing each ticker symbol, aggregate signal (BUY/SELL/HOLD), aggregate confidence, and vote distribution
  2. Consensus aggregation uses confidence-weighted voting (confidence multiplied by influence_weight) alongside the discrete majority vote, and both are visible in the display
  3. For each ticker, the user can see which brackets are bullish versus bearish, making inter-bracket disagreement visually clear
**Plans**: 2 plans
Plans:
- [ ] 19-01-PLAN.md -- TickerConsensus data model, StateStore extension, compute_ticker_consensus() with simulation wiring
- [ ] 19-02-PLAN.md -- TickerConsensusPanel TUI widget, compose/poll wiring, visual verification

### Phase 20: Report Enhancement and Integration Hardening
**Goal**: The post-simulation report synthesizes market data context with agent consensus, giving users a complete picture of how 100 agents interpreted real market conditions
**Depends on**: Phase 19
**Requirements**: DRPT-01
**Success Criteria** (what must be TRUE):
  1. The post-simulation markdown report includes a market data context section showing the live data that was available to agents (price trends, key financials, recent news)
  2. The report compares agent consensus with actual market indicators -- e.g., "Agents reached 72% bearish consensus on TSLA while the stock is trading at 52-week highs with declining volume"
  3. Running a full v3 simulation end-to-end (seed with tickers, market data fetch, enriched 3-round cascade, TUI display, report generation) completes without errors under normal conditions
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 16 -> 17 -> 18 -> 19 -> 20

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Project Foundation | v1.0 | 2/2 | Complete | 2026-03-24 |
| 2. Ollama Integration | v1.0 | 3/3 | Complete | 2026-03-25 |
| 3. Resource Governance | v1.0 | 2/2 | Complete | 2026-03-25 |
| 4. Neo4j Graph State | v1.0 | 2/2 | Complete | 2026-03-25 |
| 5. Seed Injection and Agent Personas | v1.0 | 2/2 | Complete | 2026-03-26 |
| 6. Round 1 Standalone | v1.0 | 1/1 | Complete | 2026-03-26 |
| 7. Rounds 2-3 Peer Influence and Consensus | v1.0 | 2/2 | Complete | 2026-03-26 |
| 8. Dynamic Influence Topology | v1.0 | 3/3 | Complete | 2026-03-26 |
| 9. TUI Core Dashboard | v1.0 | 2/2 | Complete | 2026-03-27 |
| 10. TUI Panels and Telemetry | v1.0 | 2/2 | Complete | 2026-03-27 |
| 11. Live Graph Memory | v2.0 | 3/3 | Complete | 2026-03-31 |
| 12. Richer Agent Interactions | v2.0 | 2/2 | Complete | 2026-04-01 |
| 13. Dynamic Persona Generation | v2.0 | 2/2 | Complete | 2026-04-02 |
| 14. Agent Interviews | v2.0 | 2/2 | Complete | 2026-04-02 |
| 15. Post-Simulation Report | v2.0 | 2/2 | Complete | 2026-04-02 |
| 16. Ticker Extraction | v3.0 | 3/3 | Complete | 2026-04-06 |
| 17. Market Data Pipeline | v3.0 | 3/3 | Complete | 2026-04-06 |
| 18. Agent Context Enrichment and Enhanced Decisions | v3.0 | 3/3 | Complete   | 2026-04-07 |
| 19. Per-Stock TUI Consensus Display | v3.0 | 0/2 | Not started | - |
| 20. Report Enhancement and Integration Hardening | v3.0 | 0/? | Not started | - |
