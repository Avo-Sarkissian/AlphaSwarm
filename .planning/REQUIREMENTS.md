# Requirements: AlphaSwarm

**Defined:** 2026-03-24
**Core Value:** The 3-round consensus cascade must produce believable, diverse market reactions from 100 agents with dynamic influence topology

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Simulation Engine

- [ ] **SIM-01**: Orchestrator LLM (qwen3:32b) parses a seed rumor and extracts named entities (companies, sectors, people, sentiment cues) as structured JSON
- [ ] **SIM-02**: 100 agents across 10 bracket archetypes (Quants, Degens, Sovereigns, Macro, Suits, Insiders, Agents, Doom-Posters, Policy Wonks, Whales) each have distinct risk profiles, information biases, and decision heuristics
- [ ] **SIM-03**: Each agent produces a structured decision per round: signal (BUY/SELL/HOLD), confidence (0.0-1.0), sentiment (-1.0 to 1.0), rationale (text), and cited_agents (list)
- [ ] **SIM-04**: Round 1 (Initial Reaction) — all 100 agents process the seed rumor independently with no peer context
- [ ] **SIM-05**: Round 2 (Peer Influence) — agents receive top-5 influential peer decisions from Round 1 and re-evaluate their position
- [ ] **SIM-06**: Round 3 (Final Consensus Lock) — agents receive updated peer decisions from Round 2 and produce final locked positions
- [ ] **SIM-07**: Dynamic influence topology — INFLUENCED_BY edges in Neo4j form and shift weight based on citation/agreement patterns within the current cycle, not predefined hierarchies
- [ ] **SIM-08**: Bracket-level sentiment aggregation computed after each round (e.g., "Quants are 80% bearish")

### Infrastructure

- [ ] **INFRA-01**: ResourceGovernor implements dynamic concurrency control via asyncio token-pool pattern, starting at 8 parallel slots (adjustable up to 16)
- [ ] **INFRA-02**: psutil + macOS `memory_pressure` command monitors system memory; ResourceGovernor throttles at 80% utilization and pauses task queue at 90%
- [ ] **INFRA-03**: Sequential model loading — orchestrator model (qwen3:32b) loads for seed injection, unloads, then worker model (qwen3.5:4b) loads for agent inference
- [ ] **INFRA-04**: Ollama AsyncClient wrapper with standardized num_ctx via Modelfiles (no per-request num_ctx to avoid silent model reloads)
- [ ] **INFRA-05**: Neo4j graph schema with cycle-scoped composite indexes on (Agent.id, INFLUENCED_BY.cycle_id) for sub-5ms peer decision reads
- [ ] **INFRA-06**: GraphStateManager with session-per-coroutine pattern and UNWIND batch writes (100 decisions per transaction, not 100 transactions)
- [ ] **INFRA-07**: All agent batch processing uses asyncio.TaskGroup (no bare create_task) to prevent silent task garbage collection
- [ ] **INFRA-08**: Structured output parsing via Pydantic models with multi-tier fallback (JSON mode → regex extraction → PARSE_ERROR status)
- [ ] **INFRA-09**: Exponential backoff for Ollama failures (1s, 2s, 4s; shrink governor on >20% batch failure rate)
- [ ] **INFRA-10**: Miro API batcher stubbed with 2s buffer and bulk payload interface (no live API calls in v1)
- [ ] **INFRA-11**: structlog-based logging with per-agent correlation IDs via context binding

### TUI Dashboard

- [ ] **TUI-01**: Textual app with 10x10 agent grid where each cell represents one agent, color-coded by current sentiment (green=bullish, red=bearish, gray=neutral/pending)
- [ ] **TUI-02**: Snapshot-based rendering — agents write to shared StateStore, TUI reads immutable snapshots on 200ms set_interval timer, only updating changed cells
- [ ] **TUI-03**: Rationale sidebar streams the most impactful agent reasoning outputs (asyncio.Queue, drains up to 5 entries per tick)
- [ ] **TUI-04**: Telemetry footer displays live RAM usage, tokens-per-second, API queue depth, and active ResourceGovernor slots
- [ ] **TUI-05**: Bracket aggregation panel shows per-bracket sentiment summary updated after each round
- [ ] **TUI-06**: Header displays global simulation status (Idle, Seeding, Round 1/2/3, Complete) and elapsed time

### Configuration

- [x] **CONF-01**: Pydantic-based settings model for all configurable parameters (model tags, parallelism limits, memory thresholds, Neo4j connection, bracket definitions)
- [x] **CONF-02**: Agent persona definitions for all 10 brackets stored as structured config (name, count, risk_profile, temperature, system_prompt template, influence_weight_base)

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

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
| Real market data feeds | Simulation-only engine, no live API integrations |
| Trade execution | No real money, no broker integration |
| Historical backtesting | Forward simulation only for v1 |
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
| INFRA-11 | Phase 1: Project Foundation | Pending |
| INFRA-03 | Phase 2: Ollama Integration | Pending |
| INFRA-04 | Phase 2: Ollama Integration | Pending |
| INFRA-08 | Phase 2: Ollama Integration | Pending |
| INFRA-01 | Phase 3: Resource Governance | Pending |
| INFRA-02 | Phase 3: Resource Governance | Pending |
| INFRA-07 | Phase 3: Resource Governance | Pending |
| INFRA-09 | Phase 3: Resource Governance | Pending |
| INFRA-05 | Phase 4: Neo4j Graph State | Pending |
| INFRA-06 | Phase 4: Neo4j Graph State | Pending |
| SIM-01 | Phase 5: Seed Injection and Agent Personas | Pending |
| SIM-02 | Phase 5: Seed Injection and Agent Personas | Pending |
| SIM-03 | Phase 5: Seed Injection and Agent Personas | Pending |
| SIM-04 | Phase 6: Round 1 Standalone | Pending |
| SIM-05 | Phase 7: Rounds 2-3 Peer Influence and Consensus | Pending |
| SIM-06 | Phase 7: Rounds 2-3 Peer Influence and Consensus | Pending |
| SIM-07 | Phase 8: Dynamic Influence Topology | Pending |
| SIM-08 | Phase 8: Dynamic Influence Topology | Pending |
| INFRA-10 | Phase 8: Dynamic Influence Topology | Pending |
| TUI-01 | Phase 9: TUI Core Dashboard | Pending |
| TUI-02 | Phase 9: TUI Core Dashboard | Pending |
| TUI-06 | Phase 9: TUI Core Dashboard | Pending |
| TUI-03 | Phase 10: TUI Panels and Telemetry | Pending |
| TUI-04 | Phase 10: TUI Panels and Telemetry | Pending |
| TUI-05 | Phase 10: TUI Panels and Telemetry | Pending |

**Coverage:**
- v1 requirements: 27 total
- Mapped to phases: 27
- Unmapped: 0

---
*Requirements defined: 2026-03-24*
*Last updated: 2026-03-24 after roadmap creation*
