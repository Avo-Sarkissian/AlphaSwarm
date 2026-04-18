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

## v5 Requirements

Requirements for v5.0 Web UI milestone. Phases 29-36.

### Web Dashboard

- [x] **WEB-01**: Vue 3 + Vite browser-based dashboard with live force-directed agent graph, color-coded by signal, WebSocket state stream
- [x] **WEB-02**: D3.js force-directed influence graph -- agent nodes colored by sentiment, INFLUENCED_BY edges as weighted Bezier curves, zoom/pan/click-to-inspect
- [x] **WEB-03**: Real-time rationale feed with animated entry transitions in the browser — Validated in Phase 33: Web Monitoring Panels
- [x] **WEB-04**: Bracket sentiment bar charts (D3 SVG) updated after each round in the browser — Validated in Phase 33: Web Monitoring Panels
- [x] **WEB-05**: FastAPI backend serving REST endpoints for simulation status, agent states, rationale, brackets, graph data, and simulation controls
- [x] **WEB-06**: Post-simulation views -- agent interview panel, report viewer, replay mode

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

## v6 Requirements

Requirements for v6.0 Data Enrichment & Personalized Advisory milestone. Phases 37–43.

**Architecture principle (Option A — locked):** ingestion layer fetches data → swarm consumes frozen `ContextPacket` only → orchestrator synthesizes advisory from holdings + swarm output. Holdings never enter any worker prompt, log, Neo4j node, or WebSocket frame.

### Isolation Foundation (Phase 37)

- [ ] **ISOL-01**: `Holding` and `PortfolioSnapshot` frozen dataclasses in `alphaswarm/holdings/types.py` with zero I/O
- [ ] **ISOL-02**: `ContextPacket`, `MarketSlice`, `NewsSlice` frozen pydantic models in `alphaswarm/ingestion/types.py` with `extra="forbid"` and zero holdings fields
- [ ] **ISOL-03**: `importlinter` contract in `pyproject.toml` forbidding `alphaswarm.holdings` imports from simulation, worker, ingestion, seed, and parsing modules; enforced in CI
- [ ] **ISOL-04**: structlog PII redaction processor installed globally before any holdings code is written
- [ ] **ISOL-05**: `MarketDataProvider` and `NewsProvider` Protocol definitions (no implementations yet)
- [ ] **ISOL-06**: `pytest-socket` in CI blocks outbound network calls during test runs
- [ ] **ISOL-07**: Canary test scaffold (`test_holdings_isolation.py`) with sentinel ticker/cost-basis fixtures (trivially passes until advisory phase activates the join point)

### Market Data + News Ingestion (Phase 38)

- [ ] **INGEST-01**: `AsyncTTLCache` (dict + asyncio.Lock, ~30 LOC) with market-hours-aware TTL
- [ ] **INGEST-02**: `YFinanceProvider` — `asyncio.to_thread` wrapper over `yfinance 1.3.0`, bulk fetch via `yf.download()`, 4-worker bounded semaphore
- [ ] **INGEST-03**: `tenacity` exponential backoff on 429; graceful degradation (packet carries `{data: null, staleness: "fetch_failed"}` rather than crashing)
- [ ] **INGEST-04**: Staleness metadata present on every market data field (timestamp + source + freshness flag)
- [ ] **INGEST-05**: `RSSProvider` — primary news source; httpx async byte fetch + feedparser parse, 72h freshness window, 2-items-per-source-per-entity cap, content-hash dedup
- [ ] **INGEST-06**: `NewsAPIProvider` available behind `settings.news.newsapi_enabled` feature flag as optional enrichment (default off — matches local-first constraint)
- [ ] **INGEST-07**: Unit tests use `FakeMarketDataProvider` / `FakeNewsProvider`; VCR cassettes for provider contracts; full test suite runs offline

### Holdings CSV Ingestion (Phase 39)

- [ ] **HOLD-01**: Broker adapter pattern with fingerprint dispatch — Schwab adapter, Fidelity adapter, generic column-mapping adapter (covers Robinhood + long-tail)
- [ ] **HOLD-02**: `HoldingsLoader` uses pandas inside `asyncio.to_thread`; BOM stripping; SHA256 account-number hashing (raw account numbers never stored)
- [ ] **HOLD-03**: `HoldingsStore` singleton on `app.state` — in-memory only, cleared on shutdown, never serialized to Neo4j or disk
- [ ] **HOLD-04**: Pydantic validation with row-level error messages surfaced to UI
- [ ] **HOLD-05**: `POST /api/holdings/upload` and `GET /api/holdings/status` REST endpoints
- [ ] **HOLD-06**: `HoldingsUploader.vue` — drag-drop upload, post-parse preview table, explicit "Confirm" gate before `HoldingsStore` commits
- [ ] **HOLD-07**: Generic column-mapping UI for unknown broker fingerprints (user maps columns manually, no crash)
- [ ] **HOLD-08**: Neo4j schema assertion test — no `:Holding` or `:Position` labels ever exist in the graph

### Context Packet Assembly (Phase 40)

- [ ] **CTX-01**: `ContextAssembler.build(seed) -> ContextPacket` — pure function, produces frozen packet with market + news slices per entity
- [ ] **CTX-02**: `slice_for(bracket) -> ArchetypeSlice` — filter-not-expand projection; initial split: Quants get fundamentals + technicals, Degens get volume ratio + 52-week range + headline count
- [ ] **CTX-03**: `MAX_WORKER_CONTEXT_TOKENS = 2000` budget enforced at packet assembly; calibrated empirically during phase validation
- [ ] **CTX-04**: `count_tokens(prompt) <= budget` assertion in every `build_agent_prompt()` unit test
- [ ] **CTX-05**: `simulation.py` accepts optional `context_packet` parameter — backward-compatible (None → existing behavior unchanged)
- [ ] **CTX-06**: `worker.py` Jinja template references `{{ context_slice }}` when packet present; no template change when absent
- [ ] **CTX-07**: `SimulationPhase.INGESTING` enum value emitted via `state_store.set_phase()` and surfaced through broadcaster
- [ ] **CTX-08**: Scale smoke test — 100 agents × full packet runs without ResourceGovernor pause (regression guard for `bug_governor_deadlock.md`)

### Advisory Pipeline (Phase 41)

- [ ] **ADV-01**: `AdvisoryPipeline.generate(sim_result, portfolio, context_packet)` — the ONLY function in the codebase receiving both holdings and swarm output simultaneously
- [ ] **ADV-02**: Orchestrator LLM invoked at `temperature=0.1`, `top_p=0.8` via existing `OllamaModelManager`
- [ ] **ADV-03**: Jinja prompt templates with explicit system / instruction / user section separation (guards against prompt injection from seed rumor text)
- [ ] **ADV-04**: Closed-universe grounding constraint in synthesis prompt (`"You may ONLY reference tickers from: {ticker_allowlist}"`)
- [ ] **ADV-05**: Post-synthesis validator extracts uppercase tickers via regex; rejects any not in `holdings_tickers ∪ swarm_entities`; regenerates up to 2 times; persistent failure produces explicit validation error
- [ ] **ADV-06**: Explicit abstention — empty holdings or weak-signal consensus → "No actionable signal" (never fabricated)
- [ ] **ADV-07**: Cited-position advisory — references specific `RationaleEpisode` rationale snippets (reuses v2 live-graph-memory infrastructure)
- [ ] **ADV-08**: Advisory written to `reports/{cycle_id}/advisory.md` via aiofiles
- [ ] **ADV-09**: `SimulationPhase.ADVISING` enum value emitted between Round 3 consensus and COMPLETE
- [ ] **ADV-10**: `SimulationManager._run` invokes `AdvisoryPipeline.generate()` after `run_simulation()` returns, gated on `holdings_store.has_portfolio`
- [ ] **ADV-11**: Advisory fully disableable via `settings.advisory.enabled = False` — pure rumor engine (v5.0 behavior) still works
- [ ] **ADV-12**: SEC-style plain-English methodology disclaimer block rendered as non-optional boilerplate in every advisory report
- [ ] **ADV-13**: Advisory report uses qualitative language only ("Review / Monitor / No action indicated") — no Buy/Sell, no price targets, no trade orders

### Advisory Web UI (Phase 42)

- [ ] **ADVUI-01**: `POST /api/advisory/generate` and `GET /api/advisory/{cycle_id}` routes (mirror Phase 36 report route pattern, non-blocking 202 Accepted)
- [ ] **ADVUI-02**: `AdvisoryPanel.vue` — markdown viewer via marked + DOMPurify, persistent "Simulation output — not investment advice" banner, staleness chip on every data point
- [ ] **ADVUI-03**: `AdvisoryReportPublic` pydantic model for WebSocket payloads — zero holdings fields, aggregate stats only
- [ ] **ADVUI-04**: Explicit allowlist serializer `snapshot_to_ws_payload()` — adding any new field requires modifying this function (catches accidental drift at code-review time)
- [ ] **ADVUI-05**: WebSocket contract test — sentinel ticker inserted into fixture holdings must never appear in any WS frame across a full simulation
- [ ] **ADVUI-06**: Advisory panel gated on presence of generated advisory; clean "no advisory yet" empty state

### v6 E2E & Carry-Forward Validation (Phase 43)

- [ ] **V6UAT-01**: Full E2E run — CSV upload → confirm → seed rumor → INGESTING → Rounds 1-3 → ADVISING → advisory panel rendered
- [ ] **V6UAT-02**: 5-run RSS telemetry plateau confirmed (no cache memory leak across repeat cycles)
- [ ] **V6UAT-03**: Final isolation audit — log-grep over full simulation log with sentinel holdings fixture (holdings never appear)
- [ ] **V6UAT-04**: Advisory abstention validated on empty holdings and on weak-consensus runs
- [ ] **V6UAT-05**: 429 graceful-degradation path validated via mocked yfinance failure
- [ ] **V6UAT-06**: Phase 29 planning artifact backfill (carry-forward v5.0 tech debt)
- [ ] **V6UAT-07**: Nyquist `VALIDATION.md` backfill for phases 29, 31, 35.1
- [ ] **V6UAT-08**: Human UAT items resolved or explicitly re-deferred for phases 32, 34, 36 (9 items from v5.0 audit)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Real market data feeds | *(Superseded v6.0: yfinance ingestion is now in scope via strict Option A isolation. Original v1 exclusion rescinded.)* |
| Trade execution | No real money, no broker integration — simulation engine only |
| Historical backtesting | Forward simulation only |
| Fine-tuned LLMs | Use base Ollama models with prompt engineering |
| Multi-user / network mode | Single-operator local-first design |
| GPU / cloud inference | M1 Max Metal only, no CUDA or cloud APIs |
| Order book microstructure | Sentiment simulation, not tick-level market mechanics |
| RL-based adaptive agents | Agents use LLM inference, not reinforcement learning |
| Real-time streaming market data | yfinance `AsyncWebSocket` exists but non-essential for MVP — defer to v7.0+ |
| SEC EDGAR filings ingestion | Stretch goal — defer to v7.0 if scope remains tight |
| Social sentiment scraping | Stretch goal — defer to v7.0 |
| Short positions / options in holdings schema | v6.0 holdings schema is long-only equities + cash — defer complex instruments to v7.0 |
| LLM-generated price targets or trade orders | Advisory is qualitative only; price targets invite liability and invite hallucination |
| Holdings persisted to Neo4j or disk | **Option A invariant** — in-memory only, cleared on shutdown. Never persisted |
| Brokerage API integration | Simulation only — no live trades, no account linking |
| Replay-compatible advisory | Replay re-renders swarm reasoning from Neo4j, not market data; advisory is a live-run artifact — defer to v7.0 |
| Robinhood-specific CSV adapter | Covered by generic column-mapping UI; native Robinhood CSV export is unavailable |

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

| WEB-01 | Phase 29: FastAPI Skeleton / Phase 31: Vue SPA | Complete |
| WEB-02 | Phase 31: Vue SPA and Force-Directed Graph | Complete |
| WEB-03 | Phase 33: Web Monitoring Panels | Complete |
| WEB-04 | Phase 33: Web Monitoring Panels | Complete |
| WEB-05 | Phase 29: FastAPI Skeleton / Phase 32: REST Controls | Complete |
| WEB-06 | Phase 34: Replay Mode Web UI / Phase 35: Agent Interviews Web UI / Phase 36: Report Viewer | Complete |

| ISOL-01..07 | Phase 37: Isolation Foundation | Pending |
| INGEST-01..07 | Phase 38: Market Data + News Ingestion | Pending |
| HOLD-01..08 | Phase 39: Holdings CSV Ingestion | Pending |
| CTX-01..08 | Phase 40: Context Packet Assembly | Pending |
| ADV-01..13 | Phase 41: Advisory Pipeline | Pending |
| ADVUI-01..06 | Phase 42: Advisory Web UI | Pending |
| V6UAT-01..08 | Phase 43: v6 E2E + Carry-Forward | Pending |

**Coverage:**
- v1 requirements: 27 total, 27 mapped (Complete)
- v2 requirements: 13 total, 13 mapped (Complete)
- v5 requirements: 6 total, 6 mapped (Complete)
- v6 requirements: 57 total, 57 mapped (Pending)
- Unmapped: 0

---
*Requirements defined: 2026-03-24*
*Last updated: 2026-04-18 after v6.0 Data Enrichment & Personalized Advisory requirements added*
