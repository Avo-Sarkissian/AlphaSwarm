# Roadmap: AlphaSwarm

## Milestones

- [x] **v1.0 Core Engine** - Phases 1-10 (shipped 2026-03-27)
- [ ] **v2.0 Engine Depth** - Phases 11-15 (in progress)

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

### v2.0 Engine Depth (Phases 11-15)

**Milestone Goal:** Deepen the simulation engine with live graph memory, richer agent behavior, dynamic persona generation, post-simulation interviews, and structured report generation -- building the full analytical data model.

- [x] **Phase 11: Live Graph Memory** - Real-time Neo4j rationale episodes, narrative edges, and interview context summaries written during simulation (completed 2026-03-31)
- [ ] **Phase 12: Richer Agent Interactions** - Agents publish public rationale posts that peers read and react to via token-budget-aware context injection
- [ ] **Phase 13: Dynamic Persona Generation** - Entity-aware bracket modifiers generated from seed rumor for situation-specific agent personas
- [ ] **Phase 14: Agent Interviews** - Post-simulation conversational Q&A with any agent using reconstructed decision context
- [ ] **Phase 15: Post-Simulation Report** - ReACT agent queries Neo4j and generates structured market analysis as exportable markdown

## Phase Details

### Phase 11: Live Graph Memory
**Goal**: Neo4j becomes a living memory that captures per-agent reasoning arcs, narrative connections, and decision context as the simulation runs -- not just a post-round data dump
**Depends on**: Phase 10 (v1 complete)
**Requirements**: GRAPH-01, GRAPH-02, GRAPH-03
**Success Criteria** (what must be TRUE):
  1. After a simulation completes, each agent has a RationaleEpisode node per round in Neo4j containing their rationale text, timestamps, peer context received, and signal flip detection
  2. Narrative REFERENCES edges connect Decision nodes to Entity nodes extracted during seed injection, queryable by entity name
  3. Running a Cypher query against a completed simulation returns a complete 3-round reasoning arc for any agent (decisions, rationale episodes, influence relationships, and entity references)
  4. Write performance remains stable -- batch UNWIND pattern keeps Neo4j transaction count under 10 per round (not 100 per-agent transactions)
**Plans**: 3 plans
Plans:
- [x] 11-01-PLAN.md -- FlipType enum, WriteBuffer module, and compute_flip_type with unit tests
- [x] 11-02-PLAN.md -- GraphStateManager extensions (4 new methods, schema, decision_id refactor)
- [x] 11-03-PLAN.md -- Simulation integration (WriteBuffer wiring, narrative generation, integration tests)

### Phase 12: Richer Agent Interactions
**Goal**: Agents influence each other through published rationale content, not just signal votes, creating observable social dynamics in the simulation graph
**Depends on**: Phase 11
**Requirements**: SOCIAL-01, SOCIAL-02
**Success Criteria** (what must be TRUE):
  1. Each agent's decision output includes a public_rationale field that is stored as a Post node in Neo4j with zero additional inference calls
  2. In Rounds 2 and 3, each agent receives top-K ranked peer rationale posts (by influence weight) as part of their prompt context, with a strict token budget preventing context window overflow
  3. READ_POST edges in Neo4j trace which agents read which posts, enabling post-simulation analysis of information flow
  4. Agent outputs in Rounds 2-3 show observable reactions to peer rationale content (citations, agreement, disagreement) compared to Round 1 baseline
**Plans**: 2 plans
Plans:
- [x] 12-01-PLAN.md -- Post node data layer (RankedPost type, write_posts, read_ranked_posts, write_read_post_edges, schema index, tests)
- [ ] 12-02-PLAN.md -- Simulation integration (budget-aware _format_peer_context, run_simulation wiring, test updates)

### Phase 13: Dynamic Persona Generation
**Goal**: The simulation generates situation-specific agent personas from the seed rumor itself, so agents have domain-relevant expertise and biases tailored to the scenario
**Depends on**: Phase 11
**Requirements**: PERSONA-01, PERSONA-02
**Success Criteria** (what must be TRUE):
  1. Given a seed rumor about a specific domain (e.g., oil markets, tech earnings), the orchestrator LLM generates entity-specific bracket modifiers in a single JSON call
  2. Generated modifiers are injected into the existing generate_personas() pipeline, producing 100 agents across 10 brackets with situation-aware system prompts while preserving the bracket structure and agent count invariant
  3. Input sanitization prevents prompt injection via adversarial seed rumor entity names -- entity text is validated, length-limited, and never concatenated raw into system prompts
**Plans**: TBD

### Phase 14: Agent Interviews
**Goal**: After simulation completes, users can select any agent and have a live multi-turn conversation about their decisions, with the agent responding in character using full decision context
**Depends on**: Phase 11
**Requirements**: INT-01, INT-02, INT-03
**Success Criteria** (what must be TRUE):
  1. Selecting an agent reconstructs their full context from Neo4j -- persona, all 3 rounds of decisions, rationale history, peer influences received, and entity references
  2. The agent responds conversationally in character using the worker LLM with their original system prompt restored, maintaining consistency with their simulation decisions across multiple exchanges
  3. Users can interview agents via the TUI by clicking any agent cell in the grid post-simulation, opening an interactive Q&A panel with clean exit back to the dashboard
  4. Interview sessions use a sliding window for conversation history to prevent context overflow during extended exchanges
**Plans**: TBD
**UI hint**: yes

### Phase 15: Post-Simulation Report
**Goal**: A ReACT agent autonomously queries the simulation graph and produces a structured market analysis report that synthesizes 300 agent decisions into actionable narrative
**Depends on**: Phase 11
**Requirements**: REPORT-01, REPORT-02, REPORT-03
**Success Criteria** (what must be TRUE):
  1. The ReACT agent completes a Thought-Action-Observation loop using prompt-based tool dispatching (no Ollama native tools), with a hard cap of 8-10 iterations and duplicate call detection
  2. Cypher query tools return structured data for bracket consensus summaries, influence topology leaders, entity-level sentiment trends, and signal flip metrics
  3. A CLI `report` subcommand generates a structured markdown report and exports it to a file via aiofiles, with the file path displayed in the TUI
  4. The report contains distinct analytical sections (consensus summary, key dissenters, bracket narratives, entity impact analysis) rendered from Jinja2 templates
  5. Report generation uses the orchestrator model with proper model lifecycle serialization -- never runs concurrently with agent interviews
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 11 -> 12 -> 13 -> 14 -> 15

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
| 11. Live Graph Memory | v2.0 | 3/3 | Complete    | 2026-03-31 |
| 12. Richer Agent Interactions | v2.0 | 1/2 | In Progress | - |
| 13. Dynamic Persona Generation | v2.0 | 0/0 | Not started | - |
| 14. Agent Interviews | v2.0 | 0/0 | Not started | - |
| 15. Post-Simulation Report | v2.0 | 0/0 | Not started | - |
