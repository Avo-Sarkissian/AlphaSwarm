# Roadmap: AlphaSwarm

## Milestones

- ✅ **v1.0 Core Engine** — Phases 1-10 (shipped 2026-03-27)
- ✅ **v2.0 Engine Depth** — Phases 11-15 (shipped 2026-04-02)
- ✅ **v3.0 Stock-Specific Recommendations with Live Data** — Phases 16-23 (shipped 2026-04-08)
- :construction: **v4.0 Interactive Simulation & Analysis** — Phases 24-29 (in progress)

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

<details>
<summary>✅ v1.0 Core Engine (Phases 1-10) — SHIPPED 2026-03-27</summary>

- [x] Phase 1: Project Foundation (2/2 plans) — completed 2026-03-24
- [x] Phase 2: Ollama Integration (3/3 plans) — completed 2026-03-25
- [x] Phase 3: Resource Governance (2/2 plans) — completed 2026-03-25
- [x] Phase 4: Neo4j Graph State (2/2 plans) — completed 2026-03-25
- [x] Phase 5: Seed Injection and Agent Personas (2/2 plans) — completed 2026-03-26
- [x] Phase 6: Round 1 Standalone (1/1 plan) — completed 2026-03-26
- [x] Phase 7: Rounds 2-3 Peer Influence and Consensus (2/2 plans) — completed 2026-03-26
- [x] Phase 8: Dynamic Influence Topology (3/3 plans) — completed 2026-03-26
- [x] Phase 9: TUI Core Dashboard (2/2 plans) — completed 2026-03-27
- [x] Phase 10: TUI Panels and Telemetry (2/2 plans) — completed 2026-03-27

</details>

<details>
<summary>✅ v2.0 Engine Depth (Phases 11-15) — SHIPPED 2026-04-02</summary>

- [x] Phase 11: Live Graph Memory (3/3 plans) — completed 2026-03-31
- [x] Phase 12: Richer Agent Interactions (2/2 plans) — completed 2026-04-01
- [x] Phase 13: Dynamic Persona Generation (2/2 plans) — completed 2026-04-02
- [x] Phase 14: Agent Interviews (2/2 plans) — completed 2026-04-02
- [x] Phase 15: Post-Simulation Report (2/2 plans) — completed 2026-04-02

</details>

<details>
<summary>✅ v3.0 Stock-Specific Recommendations with Live Data (Phases 16-23) — SHIPPED 2026-04-08</summary>

- [x] Phase 16: Ticker Extraction (3/3 plans) — completed 2026-04-06
- [x] Phase 17: Market Data Pipeline (3/3 plans) — completed 2026-04-06
- [x] Phase 18: Agent Context Enrichment and Enhanced Decisions (3/3 plans) — completed 2026-04-07
- [x] Phase 19: Per-Stock TUI Consensus Display (2/2 plans) — completed 2026-04-07
- [x] Phase 20: Report Enhancement and Integration Hardening (2/2 plans) — completed 2026-04-08
- [x] Phase 21: Restore Ticker Validation and Tracking (1/1 plan) — completed 2026-04-08
- [x] Phase 22: Fix Report Tool Name Mismatch (1/1 plan) — completed 2026-04-08
- [x] Phase 23: Validation Tracking and Requirements Traceability (1/1 plan) — completed 2026-04-08

</details>

### :construction: v4.0 Interactive Simulation & Analysis (In Progress)

**Milestone Goal:** Make the simulation interactive, replayable, shareable, and personally relevant.

- [x] **Phase 24: HTML Report Export** - Self-contained HTML reports with inline SVG charts and dark theme (completed 2026-04-10)
- [ ] **Phase 25: Portfolio Impact Analysis** - Map swarm consensus against Schwab holdings with LLM narrative
- [ ] **Phase 26: Shock Injection Core** - Governor suspend/resume, inter-round shock queue, agent prompt propagation, Neo4j persistence
- [ ] **Phase 27: Shock Analysis and Reporting** - Before/after consensus comparison and shock impact report section
- [ ] **Phase 28: Replay Data Layer** - Cycle listing, full-cycle Neo4j reads, ReplayStore with random-access snapshots
- [ ] **Phase 29: Replay TUI Playback** - Round-by-round TUI replay with speed control and navigation

## Phase Details

### Phase 24: HTML Report Export
**Goal**: Users can export simulation results as self-contained, shareable HTML files with professional visualizations
**Depends on**: Nothing (first v4.0 phase — builds on existing report pipeline)
**Requirements**: EXPORT-01, EXPORT-02, EXPORT-03
**Success Criteria** (what must be TRUE):
  1. User can run a CLI command with `--format html` and receive a single `.html` file that opens in any browser without network access
  2. HTML report contains inline SVG charts showing consensus bars, signal timelines, and bracket distributions — not static text
  3. HTML report uses a dark color scheme that visually matches the TUI's minimalist aesthetic
  4. Generated HTML file is under 1MB total size (validates SVG-first strategy over Plotly)
**Plans:** 2 plans
Plans:
- [x] 24-01-PLAN.md — pygal dependency, chart style, chart builder functions (EXPORT-02, EXPORT-03)
- [x] 24-02-PLAN.md — HTML template, assemble_html(), CLI --format flag, integration tests (EXPORT-01, EXPORT-02, EXPORT-03)

### Phase 25: Portfolio Impact Analysis
**Goal**: Users can see how swarm consensus maps to their personal Schwab holdings with coverage gaps and a natural-language narrative
**Depends on**: Phase 24 (uses HTML template infrastructure for portfolio section)
**Requirements**: PORTFOLIO-01, PORTFOLIO-02, PORTFOLIO-03, PORTFOLIO-04
**Success Criteria** (what must be TRUE):
  1. User can point the CLI at a Schwab CSV file and the system parses holdings without persisting any portfolio data to Neo4j or disk
  2. Post-simulation output shows which held tickers the swarm has consensus signals for, and maps those signals to the user's positions
  3. Held tickers not covered by the simulation are explicitly listed as coverage gaps
  4. An LLM-generated narrative compares swarm consensus against user positions in natural language, appearing in both markdown and HTML reports
**Plans:** 2 plans
Plans:
- [ ] 25-01-PLAN.md — portfolio.py module, TICKER_ENTITY_MAP, build_portfolio_impact, 10_portfolio_impact.j2 template, report.py registry (PORTFOLIO-01, PORTFOLIO-02, PORTFOLIO-03, PORTFOLIO-04)
- [ ] 25-02-PLAN.md — --portfolio CLI flag, _handle_report wiring, dynamic REACT system prompt, HTML section cards, integration tests (PORTFOLIO-01, PORTFOLIO-02, PORTFOLIO-03, PORTFOLIO-04)

### Phase 26: Shock Injection Core
**Goal**: Users can inject breaking events between simulation rounds and see all agents react to the new information
**Depends on**: Nothing (independent of Phases 24-25, but ordered after them to defer simulation.py modification)
**Requirements**: SHOCK-01, SHOCK-02, SHOCK-03
**Success Criteria** (what must be TRUE):
  1. User can type a breaking event into a TUI input widget between rounds and submit it
  2. All 100 agents in the next round's batch receive the shock text in their prompt context
  3. ShockEvent is persisted to Neo4j with the cycle ID and `injected_before_round` metadata, queryable after simulation ends
  4. Governor does not enter false THROTTLED/PAUSED states during the inter-round shock pause (suspend/resume validated)
**Plans**: TBD
**UI hint**: yes

### Phase 27: Shock Analysis and Reporting
**Goal**: Users can quantify how the swarm shifted due to an injected shock and review the impact in the post-simulation report
**Depends on**: Phase 26 (requires ShockEvent data and shock-aware simulation runs)
**Requirements**: SHOCK-04, SHOCK-05
**Success Criteria** (what must be TRUE):
  1. User can see a before/after consensus comparison in the TUI or report showing how signals, confidence, and bracket distributions shifted after the shock
  2. Post-simulation report includes a dedicated shock impact section showing which agents pivoted, which held firm, and bracket-level shift aggregations
**Plans**: TBD

### Phase 28: Replay Data Layer
**Goal**: Users can browse past simulations and the system can reconstruct full per-round agent state from Neo4j
**Depends on**: Phase 26 (ReplayStore must handle ShockEvent schema from shock-affected simulations)
**Requirements**: REPLAY-01, REPLAY-02
**Success Criteria** (what must be TRUE):
  1. User can run a CLI subcommand and see a list of past simulations showing seed rumor, date, and round count
  2. User can select a past simulation and the system reconstructs all per-round agent decisions from Neo4j into a ReplayStore (not the live StateStore)
  3. Full-cycle reconstruction completes in under 2 seconds for a 100-agent, 3-round simulation (validates COLLECT aggregation query, avoids N+1)
**Plans**: TBD

### Phase 29: Replay TUI Playback
**Goal**: Users can watch past simulations play back in the TUI with round-by-round navigation and speed control
**Depends on**: Phase 28 (requires ReplayStore with reconstructed simulation data)
**Requirements**: REPLAY-03, REPLAY-04
**Success Criteria** (what must be TRUE):
  1. User can select a past simulation and watch it play back in the TUI round-by-round, with the agent grid, rationale sidebar, and bracket panel updating as if live
  2. User can control replay speed (step-through, 0.5x, 1x, 2x) during playback
  3. TUI displays a "REPLAY" badge in the header bar to distinguish replay mode from live simulation
  4. Replay mode requires zero LLM calls — all data comes from Neo4j
**Plans**: TBD
**UI hint**: yes

## Progress

**Execution Order:**
Phases 24-29 execute in numeric order. Phases 24-25 (post-sim paths) ship first, then 26-27 (shock), then 28-29 (replay).

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
| 18. Agent Context Enrichment and Enhanced Decisions | v3.0 | 3/3 | Complete | 2026-04-07 |
| 19. Per-Stock TUI Consensus Display | v3.0 | 2/2 | Complete | 2026-04-07 |
| 20. Report Enhancement and Integration Hardening | v3.0 | 2/2 | Complete | 2026-04-08 |
| 21. Restore Ticker Validation and Tracking | v3.0 | 1/1 | Complete | 2026-04-08 |
| 22. Fix Report Tool Name Mismatch | v3.0 | 1/1 | Complete | 2026-04-08 |
| 23. Validation Tracking and Requirements Traceability | v3.0 | 1/1 | Complete | 2026-04-08 |
| 24. HTML Report Export | v4.0 | 2/2 | Complete | 2026-04-10 |
| 25. Portfolio Impact Analysis | v4.0 | 0/0 | Not started | - |
| 26. Shock Injection Core | v4.0 | 0/0 | Not started | - |
| 27. Shock Analysis and Reporting | v4.0 | 0/0 | Not started | - |
| 28. Replay Data Layer | v4.0 | 0/0 | Not started | - |
| 29. Replay TUI Playback | v4.0 | 0/0 | Not started | - |
