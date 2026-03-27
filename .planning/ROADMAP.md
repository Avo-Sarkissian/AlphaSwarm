# Roadmap: AlphaSwarm

## Overview

AlphaSwarm delivers a local-first, 100-agent financial simulation engine through 10 phases that build from project foundation to full TUI dashboard. The first four phases establish infrastructure (config, Ollama, resource governance, Neo4j). Phases 5-8 build the simulation engine vertically -- seed injection, Round 1 standalone, Rounds 2-3 with peer influence, and the dynamic influence topology that is the product's primary differentiator. Phases 9-10 layer the Textual TUI dashboard on top of the completed headless engine. Every phase delivers a verifiable capability; the headless engine is fully functional after Phase 8.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Project Foundation** - Scaffold, configuration system, type definitions, and structured logging
- [ ] **Phase 2: Ollama Integration** - Async LLM client, sequential model loading, and structured output parsing
- [ ] **Phase 3: Resource Governance** - Dynamic concurrency control, memory monitoring, task safety, and retry logic
- [x] **Phase 4: Neo4j Graph State** - Graph schema with cycle-scoped indexes and batch-writing GraphStateManager (completed 2026-03-25)
- [ ] **Phase 5: Seed Injection and Agent Personas** - Orchestrator entity extraction and 100 agent personas with decision schema
- [x] **Phase 6: Round 1 Standalone** - All 100 agents process a seed rumor independently in a single inference wave (completed 2026-03-26)
- [ ] **Phase 7: Rounds 2-3 Peer Influence and Consensus** - Peer context injection and final consensus lock complete the 3-round cascade
- [x] **Phase 8: Dynamic Influence Topology** - INFLUENCED_BY edges form from citation patterns, bracket aggregation, and Miro batcher stub (completed 2026-03-26)
- [ ] **Phase 9: TUI Core Dashboard** - Agent grid, snapshot-based rendering, and simulation status display
- [ ] **Phase 10: TUI Panels and Telemetry** - Rationale sidebar, hardware telemetry footer, and bracket aggregation panel

## Phase Details

### Phase 1: Project Foundation
**Goal**: The project has a runnable scaffold with all configuration, type definitions, and logging in place so every subsequent phase builds on solid ground
**Depends on**: Nothing (first phase)
**Requirements**: CONF-01, CONF-02, INFRA-11
**Success Criteria** (what must be TRUE):
  1. Running `uv run python -m alphaswarm` starts without errors and prints a startup banner
  2. All 10 bracket archetypes are defined in config with distinct risk profiles, temperatures, system prompt templates, and agent counts totaling 100
  3. Pydantic settings model loads configuration from defaults and environment variables, with validation errors on invalid values
  4. Structured logging outputs JSON-formatted log lines with correlation ID context binding
**Plans**: 2 plans
Plans:
- [x] 01-01-PLAN.md -- Project scaffold, core types, Pydantic settings, bracket definitions, persona generation, and config/persona tests
- [x] 01-02-PLAN.md -- Structured logging, ResourceGovernor stub, StateStore stub, AppState container, entry point, logging/app tests

### Phase 2: Ollama Integration
**Goal**: The system can load models sequentially and produce structured, validated LLM outputs through an async client
**Depends on**: Phase 1
**Requirements**: INFRA-03, INFRA-04, INFRA-08
**Success Criteria** (what must be TRUE):
  1. Orchestrator model (qwen3.5:32b) loads, produces output, and unloads before worker model (qwen3.5:7b) loads -- no dual-model coexistence
  2. Ollama AsyncClient wrapper sends all requests with standardized num_ctx via Modelfiles, never per-request num_ctx
  3. Structured output parsing extracts valid Pydantic models from LLM responses, falling back through JSON mode, regex extraction, and PARSE_ERROR status
  4. A test script can run a single agent inference call and return a validated AgentDecision object
**Plans**: 3 plans
Plans:
- [x] 02-01-PLAN.md -- Domain exceptions, type additions (AgentDecision, PARSE_ERROR), config update with model aliases, governor semaphore upgrade, WorkerPersonaConfig TypedDict, Modelfiles with registration commands
- [x] 02-02-PLAN.md -- OllamaClient wrapper with backoff and RequestError boundary wrapping, OllamaModelManager with Lock serialization and scoped cleanup, parse_agent_decision 3-tier fallback with code-fence stripping
- [x] 02-03-PLAN.md -- AgentWorker context manager, AppState with OllamaClient and OllamaModelManager, graceful shutdown pattern, sequential model flow integration test, full-path inference integration tests

### Phase 3: Resource Governance
**Goal**: The system dynamically controls concurrency based on real memory pressure, preventing OOM crashes and recovering gracefully from inference failures
**Depends on**: Phase 2
**Requirements**: INFRA-01, INFRA-02, INFRA-07, INFRA-09
**Success Criteria** (what must be TRUE):
  1. ResourceGovernor starts at 8 parallel slots and can scale up to 16 based on available memory headroom
  2. At 80% memory utilization the governor throttles new inference dispatches; at 90% it pauses the task queue entirely
  3. All batch agent processing uses asyncio.TaskGroup -- no bare create_task calls that could be garbage collected
  4. Ollama failures trigger exponential backoff (1s, 2s, 4s) and batch failure rates above 20% shrink the governor's slot count
**Plans**: 2 plans
Plans:
- [x] 03-01-PLAN.md -- MemoryMonitor (psutil + sysctl dual-signal), TokenPool (Queue-based dynamic concurrency), ResourceGovernor rewrite with 5-state machine, GovernorSettings extensions, GovernorCrisisError
- [x] 03-02-PLAN.md -- BatchDispatcher (TaskGroup dispatch with jitter and failure tracking), worker.py success flag, StateStore GovernorMetrics data contract, AppState wiring

### Phase 4: Neo4j Graph State
**Goal**: Agent decisions and influence relationships persist in Neo4j with sub-5ms read performance and safe concurrent access
**Depends on**: Phase 1
**Requirements**: INFRA-05, INFRA-06
**Success Criteria** (what must be TRUE):
  1. Neo4j Docker container starts with the graph schema applied, including composite indexes on (Agent.id, cycle_id)
  2. GraphStateManager writes 100 agent decisions in a single UNWIND batch transaction, not 100 individual transactions
  3. Session-per-coroutine pattern prevents corrupted reads when multiple agents query peer decisions concurrently
  4. Peer decision reads for top-5 influential agents complete in under 5ms with composite index hits
**Plans**: 2 plans
Plans:
- [x] 04-01-PLAN.md -- Docker compose, neo4j dependency, error types, GraphStateManager with ensure_schema/seed_agents/create_cycle/close, unit tests
- [x] 04-02-PLAN.md -- write_decisions (UNWIND batch), read_peer_decisions (top-N by influence), AppState wiring, integration tests

### Phase 5: Seed Injection and Agent Personas
**Goal**: A seed rumor is parsed into structured entities and 100 distinct agent personas are ready to produce structured decisions
**Depends on**: Phase 2, Phase 4
**Requirements**: SIM-01, SIM-02, SIM-03
**Success Criteria** (what must be TRUE):
  1. Orchestrator LLM parses a natural-language seed rumor and returns structured JSON with named entities (companies, sectors, people) and sentiment cues
  2. All 100 agents across 10 brackets are instantiated with their archetype-specific risk profiles, information biases, and decision heuristics loaded from config
  3. Each agent can produce a structured decision containing signal (BUY/SELL/HOLD), confidence (0.0-1.0), sentiment (-1.0 to 1.0), rationale (text), and cited_agents (list)
  4. A CLI command runs seed injection end-to-end and writes the parsed SeedEvent to Neo4j
**Plans**: 2 plans
Plans:
- [x] 05-01-PLAN.md -- Domain types (SeedEvent, SeedEntity, EntityType), parse_seed_event() 3-tier fallback, enriched persona system prompts with personality modifiers and JSON output instructions
- [x] 05-02-PLAN.md -- Graph Entity persistence (write_seed_event), seed injection pipeline (seed.py), CLI module with inject subcommand, __main__.py refactor

### Phase 6: Round 1 Standalone
**Goal**: All 100 agents independently process a seed rumor in batched inference waves, producing their initial reactions without any peer context
**Depends on**: Phase 3, Phase 5
**Requirements**: SIM-04
**Success Criteria** (what must be TRUE):
  1. All 100 agents process the seed rumor in Round 1 with zero peer context -- each decision is purely independent
  2. Batched inference dispatches 8-16 concurrent agent calls through the ResourceGovernor without memory exhaustion or dropped tasks
  3. All 100 Round 1 decisions are persisted to Neo4j and queryable by bracket, signal, and confidence
  4. A CLI command runs a full Round 1 and reports bracket-level signal distribution (e.g., "Quants: 7 SELL, 2 HOLD, 1 BUY")
**Plans**: 1 plan
Plans:
- [x] 06-01-PLAN.md -- Simulation pipeline (run_round1), CLI run subcommand with bracket report and notable decisions, unit tests

### Phase 7: Rounds 2-3 Peer Influence and Consensus
**Goal**: Agents receive peer decisions from prior rounds and iteratively shift their positions, completing the full 3-round consensus cascade
**Depends on**: Phase 6
**Requirements**: SIM-05, SIM-06
**Success Criteria** (what must be TRUE):
  1. In Round 2, each agent receives the top-5 most influential peer decisions from Round 1 as context and re-evaluates their position
  2. In Round 3, agents receive updated Round 2 peer decisions and produce final locked positions that cannot change
  3. A full 3-round simulation runs end-to-end from seed injection through consensus lock, with all decisions persisted per round in Neo4j
  4. Observable opinion shifts occur between rounds -- at least some agents change signal or shift confidence after receiving peer context
  5. The simulation engine state machine transitions cleanly through Seeding, Round 1, Round 2, Round 3, and Complete states
**Plans**: 2 plans
Plans:
- [x] 07-01-PLAN.md -- Core simulation engine: dispatch_wave per-agent context, ShiftMetrics, SimulationResult, _format_peer_context, _dispatch_round, run_simulation, unit tests
- [x] 07-02-PLAN.md -- CLI reporting: generalized round report, shift analysis, simulation summary with convergence, wire _run_pipeline to run_simulation

### Phase 8: Dynamic Influence Topology
**Goal**: Influence edges emerge organically from agent behavior rather than static hierarchies, and bracket-level sentiment summaries are computed after each round
**Depends on**: Phase 7
**Requirements**: SIM-07, SIM-08, INFRA-10
**Success Criteria** (what must be TRUE):
  1. INFLUENCED_BY edges in Neo4j form and shift weight based on citation and agreement patterns within the current cycle -- not from predefined bracket hierarchies
  2. Agents who are frequently cited by peers gain higher influence weight, affecting who appears in top-5 peer context for subsequent rounds
  3. Bracket-level sentiment aggregation is computed after each round (e.g., "Quants are 80% bearish, Degens are 65% bullish")
  4. Miro API batcher interface is stubbed with 2s buffer and bulk payload contract -- no live API calls, but the data shape for future visualization is defined
  5. The influence topology is queryable in Neo4j: given an agent, return who influenced them and who they influenced
**Plans**: 3 plans
Plans:
- [x] 08-01-PLAN.md -- Influence edge computation (compute_influence_edges, citation reads, INFLUENCED_BY writes), BracketSummary dataclass, compute_bracket_summaries, select_diverse_peers, unit tests
- [x] 08-02-PLAN.md -- Wire influence into run_simulation between rounds, dynamic peer selection in _dispatch_round, extend SimulationResult/RoundCompleteEvent with bracket summaries, update CLI to consume BracketSummary
- [x] 08-03-PLAN.md -- Miro batcher stub: MiroNode, MiroConnector, MiroBatchPayload Pydantic models, MiroBatcher log-only class, standalone module tests

### Phase 9: TUI Core Dashboard
**Goal**: Users observe the simulation in real time through a terminal dashboard showing agent states, round progression, and simulation status
**Depends on**: Phase 7
**Requirements**: TUI-01, TUI-02, TUI-06
**Success Criteria** (what must be TRUE):
  1. A 10x10 agent grid displays all 100 agents as color-coded cells -- green for bullish, red for bearish, gray for neutral/pending
  2. The grid updates via snapshot-based rendering on a 200ms timer, reading immutable state snapshots and only redrawing changed cells
  3. A header bar displays the current simulation status (Idle, Seeding, Round 1, Round 2, Round 3, Complete) and elapsed wall-clock time
  4. The TUI launches, connects to a running simulation, and renders live updates without blocking the simulation engine's event loop
**Plans**: 2 plans
Plans:
- [ ] 09-01-PLAN.md -- StateStore expansion (AgentState, per-agent writes, phase/round transitions, elapsed time), simulation.py wiring (state_store parameter), textual dependency
- [ ] 09-02-PLAN.md -- Textual TUI module (AlphaSwarmApp, AgentCell grid, HeaderBar, snapshot-based rendering, simulation Worker), tui CLI subcommand
**UI hint**: yes

### Phase 10: TUI Panels and Telemetry
**Goal**: The dashboard provides full operational visibility with agent reasoning, hardware metrics, and bracket-level sentiment summaries
**Depends on**: Phase 9
**Requirements**: TUI-03, TUI-04, TUI-05
**Success Criteria** (what must be TRUE):
  1. A rationale sidebar streams the most impactful agent reasoning outputs, draining up to 5 entries per 200ms tick from an asyncio.Queue
  2. A telemetry footer displays live RAM usage, tokens-per-second, API queue depth, and active ResourceGovernor slot count
  3. A bracket aggregation panel shows per-bracket sentiment summary (e.g., "Whales: 80% HOLD") updated after each round completes
  4. All TUI panels render without blocking -- the dashboard remains responsive even during peak inference load
**Plans**: TBD
**UI hint**: yes

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8 -> 9 -> 10

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Project Foundation | 2/2 | Complete | 2026-03-24 |
| 2. Ollama Integration | 0/3 | Planning complete | - |
| 3. Resource Governance | 0/2 | Planning complete | - |
| 4. Neo4j Graph State | 2/2 | Complete   | 2026-03-25 |
| 5. Seed Injection and Agent Personas | 0/2 | Planning complete | - |
| 6. Round 1 Standalone | 1/1 | Complete   | 2026-03-26 |
| 7. Rounds 2-3 Peer Influence and Consensus | 0/2 | Planning complete | - |
| 8. Dynamic Influence Topology | 3/3 | Complete   | 2026-03-26 |
| 9. TUI Core Dashboard | 0/2 | Planning complete | - |
| 10. TUI Panels and Telemetry | 0/TBD | Not started | - |
