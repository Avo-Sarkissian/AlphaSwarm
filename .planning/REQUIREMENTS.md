# Requirements: AlphaSwarm

**Defined:** 2026-03-24
**Core Value:** The 3-round consensus cascade must produce believable, diverse market reactions from 100 agents with dynamic influence topology

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Simulation Engine

- [x] **SIM-01**: Orchestrator LLM (qwen3:32b) parses a seed rumor and extracts named entities (companies, sectors, people, sentiment cues) as structured JSON
- [x] **SIM-02**: 100 agents across 10 bracket archetypes (Quants, Degens, Sovereigns, Macro, Suits, Insiders, Agents, Doom-Posters, Policy Wonks, Whales) each have distinct risk profiles, information biases, and decision heuristics
- [x] **SIM-03**: Each agent produces a structured decision per round: signal (BUY/SELL/HOLD), confidence (0.0-1.0), sentiment (-1.0 to 1.0), rationale (text), and cited_agents (list)
- [x] **SIM-04**: Round 1 (Initial Reaction) -- all 100 agents process the seed rumor independently with no peer context
- [x] **SIM-05**: Round 2 (Peer Influence) -- agents receive top-5 influential peer decisions from Round 1 and re-evaluate their position
- [x] **SIM-06**: Round 3 (Final Consensus Lock) -- agents receive updated peer decisions from Round 2 and produce final locked positions
- [x] **SIM-07**: Dynamic influence topology -- INFLUENCED_BY edges in Neo4j form and shift weight based on citation/agreement patterns within the current cycle, not predefined hierarchies
- [x] **SIM-08**: Bracket-level sentiment aggregation computed after each round (e.g., "Quants are 80% bearish")

### Infrastructure

- [x] **INFRA-01**: ResourceGovernor implements dynamic concurrency control via asyncio token-pool pattern, starting at 8 parallel slots (adjustable up to 16)
- [x] **INFRA-02**: psutil + macOS `memory_pressure` command monitors system memory; ResourceGovernor throttles at 80% utilization and pauses task queue at 90%
- [x] **INFRA-03**: Sequential model loading -- orchestrator model (qwen3:32b) loads for seed injection, unloads, then worker model (qwen3.5:4b) loads for agent inference
- [x] **INFRA-04**: Ollama AsyncClient wrapper with standardized num_ctx via Modelfiles (no per-request num_ctx to avoid silent model reloads)
- [x] **INFRA-05**: Neo4j graph schema with cycle-scoped composite indexes on (Agent.id, INFLUENCED_BY.cycle_id) for sub-5ms peer decision reads
- [x] **INFRA-06**: GraphStateManager with session-per-coroutine pattern and UNWIND batch writes (100 decisions per transaction, not 100 transactions)
- [x] **INFRA-07**: All agent batch processing uses asyncio.TaskGroup (no bare create_task) to prevent silent task garbage collection
- [x] **INFRA-08**: Structured output parsing via Pydantic models with multi-tier fallback (JSON mode -> regex extraction -> PARSE_ERROR status)
- [x] **INFRA-09**: Exponential backoff for Ollama failures (1s, 2s, 4s; shrink governor on >20% batch failure rate)
- [x] **INFRA-10**: Miro API batcher stubbed with 2s buffer and bulk payload interface (no live API calls in v1)
- [x] **INFRA-11**: structlog-based logging with per-agent correlation IDs via context binding

### TUI Dashboard

- [x] **TUI-01**: Textual app with 10x10 agent grid where each cell represents one agent, color-coded by current sentiment (green=bullish, red=bearish, gray=neutral/pending)
- [x] **TUI-02**: Snapshot-based rendering -- agents write to shared StateStore, TUI reads immutable snapshots on 200ms set_interval timer, only updating changed cells
- [x] **TUI-03**: Rationale sidebar streams the most impactful agent reasoning outputs (asyncio.Queue, drains up to 5 entries per tick)
- [x] **TUI-04**: Telemetry footer displays live RAM usage, tokens-per-second, API queue depth, and active ResourceGovernor slots
- [x] **TUI-05**: Bracket aggregation panel shows per-bracket sentiment summary updated after each round
- [x] **TUI-06**: Header displays global simulation status (Idle, Seeding, Round 1/2/3, Complete) and elapsed time

### Configuration

- [x] **CONF-01**: Pydantic-based settings model for all configurable parameters (model tags, parallelism limits, memory thresholds, Neo4j connection, bracket definitions)
- [x] **CONF-02**: Agent persona definitions for all 10 brackets stored as structured config (name, count, risk_profile, temperature, system_prompt template, influence_weight_base)

## v2 Requirements

Requirements for v2.0 Engine Depth milestone. Each maps to roadmap phases.

### Live Graph Memory

- [x] **GRAPH-01**: Agent decisions are written to Neo4j individually in real time during simulation (per-agent immediate writes via write-behind buffer, not batch-per-round)
- [x] **GRAPH-02**: RationaleEpisode nodes link Agent -> Round -> Rationale with timestamps, peer context received, and signal flip detection
- [x] **GRAPH-03**: Narrative REFERENCES edges connect Decision nodes to Entity nodes via keyword matching against extracted entities

### Post-Simulation Report

- [x] **REPORT-01**: ReACT-style agent (Thought-Action-Observation loop) queries Neo4j after simulation ends using prompt-based tool dispatching (no Ollama native tools)
- [x] **REPORT-02**: Cypher query tools for bracket summaries, influence topology analysis, entity-level trends, and signal flip metrics
- [x] **REPORT-03**: Structured markdown report output with CLI `report` subcommand and file export via aiofiles

### Agent Interviews

- [x] **INT-01**: Agent context reconstruction from Neo4j -- full persona, all 3 rounds of decisions, peer influences received, rationale history
- [x] **INT-02**: Conversational interview loop using worker LLM with the agent's original system prompt restored, answering in character
- [x] **INT-03**: TUI interview mode -- click any agent in the grid post-simulation to open an interactive Q&A panel

### Richer Agent Interactions

- [x] **SOCIAL-01**: Agents produce a "public rationale post" as part of their decision output, stored as Post nodes in Neo4j (zero extra inference calls)
- [x] **SOCIAL-02**: Top-K ranked posts (by influence weight) injected into peer context for Rounds 2-3 with token budget management

### Dynamic Persona Generation

- [x] **PERSONA-01**: Orchestrator LLM generates entity-specific bracket modifiers from SeedEvent entities in a single JSON call
- [x] **PERSONA-02**: Entity-aware modifiers injected into generate_personas() pipeline, preserving 10-bracket structure and 100-agent count

## v3 Requirements

Requirements for v3.0 Stock-Specific Recommendations with Live Data & RAG milestone. Each maps to roadmap phases.

### Ticker Extraction

- [ ] **TICK-01**: Orchestrator extracts stock tickers from seed rumor text alongside existing entity extraction
- [ ] **TICK-02**: Extracted tickers are validated against SEC company_tickers.json symbol table before use
- [ ] **TICK-03**: Simulation caps at 3 tickers per run, ranked by relevance score from extraction

### Market Data Pipeline

- [ ] **DATA-01**: User can run a simulation that fetches live price history, financials, and earnings data per ticker via async-wrapped yfinance
- [ ] **DATA-02**: Market data pipeline falls back to Alpha Vantage when yfinance fails, with graceful degradation if both sources are unavailable
- [ ] **DATA-03**: Recent news headlines per ticker are fetched and included in the market context (5-10 headlines)
- [ ] **DATA-04**: API responses are cached to disk with TTL to avoid rate limit exhaustion on re-runs

### Agent Context Enrichment

- [ ] **ENRICH-01**: Each agent receives a formatted market data block injected into their prompt before inference, with all data fetching completed before Round 1
- [ ] **ENRICH-02**: Injected data is tailored per bracket archetype (Quants get technicals, Macro gets sector data, Insiders get earnings surprises, etc.)
- [ ] **ENRICH-03**: Total injected market context stays within a strict token budget that prevents context window overflow

### Enhanced Decisions

- [ ] **DECIDE-01**: AgentDecision output includes ticker, direction, expected_return_pct, and time_horizon fields
- [ ] **DECIDE-02**: The 3-tier parse fallback handles new fields gracefully with backward-compatible defaults

### TUI Display

- [ ] **DTUI-01**: User can see per-stock consensus breakdown in the TUI (ticker symbol, signal, confidence, vote distribution)
- [ ] **DTUI-02**: Consensus aggregation uses confidence-weighted voting (confidence x influence_weight) alongside discrete majority vote
- [ ] **DTUI-03**: Bracket disagreement is visible per ticker (which brackets are bullish vs bearish)

### Report Enhancement

- [ ] **DRPT-01**: Post-simulation report includes market data context, comparing agent consensus with actual market indicators

## Future Requirements

Deferred to future milestones. Tracked but not in current roadmap.

### RAG Knowledge Base (v3.1)

- **RAG-01**: ChromaDB + nomic-embed-text via Ollama for historical earnings reactions and market patterns
- **RAG-02**: Pre-seeded knowledge base with curated historical data (earnings reactions, sector correlations, crisis patterns)
- **RAG-03**: RAG-retrieved precedents injected into agent prompts alongside live market data

### Web Dashboard

- **WEB-01**: Vue 3 + Vite browser-based dashboard with live 10x10 agent grid, color-coded by signal (BUY/SELL/HOLD), polling agent state every 2s
- **WEB-02**: D3.js force-directed influence graph -- agent nodes colored by sentiment, INFLUENCED_BY edges as weighted Bezier curves, zoom/pan/click-to-inspect
- **WEB-03**: Real-time rationale feed with animated entry transitions, cursor-based incremental fetching
- **WEB-04**: Bracket sentiment bar charts (D3 SVG) updated after each round
- **WEB-05**: FastAPI backend serving REST endpoints for simulation status, agent states, rationale, brackets, and graph data
- **WEB-06**: Post-simulation views -- agent interview panel, report viewer, results export

### Visualization

- **VIS-01**: Miro API v2 live network visualization with spatial layout algorithm mapping agent sentiment to node color
- **VIS-02**: Dynamic Miro connectors between agents when one cites another's rationale

### Replay & Export

- **REPLAY-01**: Simulation replay from stored Neo4j state (re-render without re-inference)
- **REPLAY-02**: Exportable markdown/HTML simulation report with per-round sentiment evolution
- **REPLAY-03**: Mid-simulation shock injection (dynamic events injected during Round 2)

### Scalability

- **SCALE-01**: Configurable agent count (parameterize beyond hardcoded 100/10)
- **SCALE-02**: Multiple simultaneous simulations with isolated cycle namespaces

## Out of Scope

| Feature | Reason |
|---------|--------|
| RAG knowledge base | Deferred to v3.1 — ship core data pipeline first, add historical pattern retrieval after it's proven stable |
| Real-time streaming price updates | Simulation analyzes a point-in-time snapshot; mid-sim price changes create agent inconsistency |
| Full technical indicator library | 3-5 key metrics sufficient for LLM grounding; 20+ indicators bloat prompts without proportional value |
| Autonomous portfolio construction | AlphaSwarm is analysis, not a trading system; no trade recommendations or allocations |
| Unlimited ticker support | Cap at 3; each ticker multiplies API calls, tokens, and TUI space |
| Paid API integrations | Violates local-first, free-to-run ethos; yfinance + Alpha Vantage + SEC EDGAR sufficient |
| LangChain/LlamaIndex dependency | Simple retrieval needs 20 lines of code, not a 50+ transitive dep framework |
| Trade execution | No real money, no broker integration |
| Historical backtesting | Forward simulation only |
| Fine-tuned LLMs | Use base Ollama models with prompt engineering |
| Multi-user / network mode | Single-operator local-first design |
| GPU / cloud inference | M1 Max Metal only, no CUDA or cloud APIs |
| Order book microstructure | Sentiment simulation, not tick-level market mechanics |
| RL-based adaptive agents | Agents use LLM inference, not reinforcement learning |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| CONF-01 | Phase 1: Project Foundation | Complete |
| CONF-02 | Phase 1: Project Foundation | Complete |
| INFRA-11 | Phase 1: Project Foundation | Complete |
| INFRA-03 | Phase 2: Ollama Integration | Complete |
| INFRA-04 | Phase 2: Ollama Integration | Complete |
| INFRA-08 | Phase 2: Ollama Integration | Complete |
| INFRA-01 | Phase 3: Resource Governance | Complete |
| INFRA-02 | Phase 3: Resource Governance | Complete |
| INFRA-07 | Phase 3: Resource Governance | Complete |
| INFRA-09 | Phase 3: Resource Governance | Complete |
| INFRA-05 | Phase 4: Neo4j Graph State | Complete |
| INFRA-06 | Phase 4: Neo4j Graph State | Complete |
| SIM-01 | Phase 5: Seed Injection and Agent Personas | Complete |
| SIM-02 | Phase 5: Seed Injection and Agent Personas | Complete |
| SIM-03 | Phase 5: Seed Injection and Agent Personas | Complete |
| SIM-04 | Phase 6: Round 1 Standalone | Complete |
| SIM-05 | Phase 7: Rounds 2-3 Peer Influence and Consensus | Complete |
| SIM-06 | Phase 7: Rounds 2-3 Peer Influence and Consensus | Complete |
| SIM-07 | Phase 8: Dynamic Influence Topology | Complete |
| SIM-08 | Phase 8: Dynamic Influence Topology | Complete |
| INFRA-10 | Phase 8: Dynamic Influence Topology | Complete |
| TUI-01 | Phase 9: TUI Core Dashboard | Complete |
| TUI-02 | Phase 9: TUI Core Dashboard | Complete |
| TUI-06 | Phase 9: TUI Core Dashboard | Complete |
| TUI-03 | Phase 10: TUI Panels and Telemetry | Complete |
| TUI-04 | Phase 10: TUI Panels and Telemetry | Complete |
| TUI-05 | Phase 10: TUI Panels and Telemetry | Complete |
| GRAPH-01 | Phase 11: Live Graph Memory | Complete |
| GRAPH-02 | Phase 11: Live Graph Memory | Complete |
| GRAPH-03 | Phase 11: Live Graph Memory | Complete |
| SOCIAL-01 | Phase 12: Richer Agent Interactions | Complete |
| SOCIAL-02 | Phase 12: Richer Agent Interactions | Complete |
| PERSONA-01 | Phase 13: Dynamic Persona Generation | Complete |
| PERSONA-02 | Phase 13: Dynamic Persona Generation | Complete |
| INT-01 | Phase 14: Agent Interviews | Complete |
| INT-02 | Phase 14: Agent Interviews | Complete |
| INT-03 | Phase 14: Agent Interviews | Complete |
| REPORT-01 | Phase 15: Post-Simulation Report | Complete |
| REPORT-02 | Phase 15: Post-Simulation Report | Complete |
| REPORT-03 | Phase 15: Post-Simulation Report | Complete |

**Coverage:**
- v1 requirements: 27 total, 27 mapped (Complete)
- v2 requirements: 13 total, 13 mapped (Complete)
- v3 requirements: 16 total, 0 mapped (Pending roadmap)
- Unmapped: 16 ⚠️

---
*Requirements defined: 2026-03-24*
*Last updated: 2026-04-05 after v3.0 milestone requirements definition*
