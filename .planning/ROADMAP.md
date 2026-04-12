# Roadmap: AlphaSwarm

## Milestones

- [x] **v1.0 Core Engine** — Phases 1-10 (shipped 2026-03-27)
- [x] **v2.0 Engine Depth** — Phases 11-15 (shipped 2026-04-02)
- [x] **v4.0 Interactive Simulation & Analysis** — Phases 24-28 (shipped 2026-04-12)

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

<details>
<summary>✅ v1.0 Core Engine (Phases 1-10) — SHIPPED 2026-03-27</summary>

- [x] **Phase 1: Project Foundation** — Scaffold, configuration system, type definitions, and structured logging (completed 2026-03-24)
- [x] **Phase 2: Ollama Integration** — Async LLM client, sequential model loading, and structured output parsing (completed 2026-03-25)
- [x] **Phase 3: Resource Governance** — Dynamic concurrency control, memory monitoring, task safety, and retry logic (completed 2026-03-25)
- [x] **Phase 4: Neo4j Graph State** — Graph schema with cycle-scoped indexes and batch-writing GraphStateManager (completed 2026-03-25)
- [x] **Phase 5: Seed Injection and Agent Personas** — Orchestrator entity extraction and 100 agent personas with decision schema (completed 2026-03-26)
- [x] **Phase 6: Round 1 Standalone** — All 100 agents process a seed rumor independently in a single inference wave (completed 2026-03-26)
- [x] **Phase 7: Rounds 2-3 Peer Influence and Consensus** — Peer context injection and final consensus lock complete the 3-round cascade (completed 2026-03-26)
- [x] **Phase 8: Dynamic Influence Topology** — INFLUENCED_BY edges form from citation patterns, bracket aggregation, and Miro batcher stub (completed 2026-03-26)
- [x] **Phase 9: TUI Core Dashboard** — Agent grid, snapshot-based rendering, and simulation status display (completed 2026-03-27)
- [x] **Phase 10: TUI Panels and Telemetry** — Rationale sidebar, hardware telemetry footer, and bracket aggregation panel (completed 2026-03-27)

See full details: `.planning/milestones/v1.0-ROADMAP.md`

</details>

<details>
<summary>✅ v2.0 Engine Depth (Phases 11-15) — SHIPPED 2026-04-02</summary>

- [x] **Phase 11: Live Graph Memory** — Real-time Neo4j rationale episodes, narrative edges, and interview context summaries written during simulation (completed 2026-03-31)
- [x] **Phase 12: Richer Agent Interactions** — Agents publish public rationale posts that peers read and react to via token-budget-aware context injection (completed 2026-04-01)
- [x] **Phase 13: Dynamic Persona Generation** — Entity-aware bracket modifiers generated from seed rumor for situation-specific agent personas (completed 2026-04-02)
- [x] **Phase 14: Agent Interviews** — Post-simulation conversational Q&A with any agent using reconstructed decision context (completed 2026-04-02)
- [x] **Phase 15: Post-Simulation Report** — ReACT agent queries Neo4j and generates structured market analysis as exportable markdown (completed 2026-04-02)

See full details: `.planning/milestones/v2.0-ROADMAP.md`

</details>

<details>
<summary>✅ v4.0 Interactive Simulation & Analysis (Phases 24-28) — SHIPPED 2026-04-12</summary>

- [x] **Phase 24: HTML Report Export** — Exportable HTML simulation reports with SVG charts and Schwab portfolio overlay (completed 2026-04-09)
- [x] **Phase 26: Shock Injection Core** — Mid-simulation shock injection with governor suspend/resume and ReplayStore isolation (completed 2026-04-10)
- [x] **Phase 27: Shock Analysis and Reporting** — Shock impact analysis with bracket delta mode, read_shock_impact, and Jinja2 shock template (completed 2026-04-11)
- [x] **Phase 28: Simulation Replay** — Re-render a past simulation cycle from stored Neo4j state without re-running inference (completed 2026-04-12)

See full details: `.planning/milestones/v4.0-ROADMAP.md`

</details>

## Progress

**Execution Order:**
Phases execute in numeric order: 1-10 (v1.0) → 11-15 (v2.0) → 16-23 (v3.0) → 24-28 (v4.0)

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
| 24. HTML Report Export | v4.0 | 2/2 | Complete | 2026-04-09 |
| 26. Shock Injection Core | v4.0 | 5/5 | Complete | 2026-04-10 |
| 27. Shock Analysis and Reporting | v4.0 | 3/3 | Complete | 2026-04-11 |
| 28. Simulation Replay | v4.0 | 3/3 | Complete | 2026-04-12 |
