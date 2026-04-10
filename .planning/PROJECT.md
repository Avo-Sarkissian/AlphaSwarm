# AlphaSwarm

## What This Is

A localized, multi-agent financial simulation engine that ingests a single "Seed Rumor" and simulates cascading market reactions across 100 distinct AI personas. The system runs a 3-round iterative consensus cascade on local hardware (M1 Max 64GB), visualizing real-time agent state via a Textual TUI dashboard and persisting interaction history in Neo4j.

## Current Milestone: v2.0 Engine Depth

**Goal:** Deepen the simulation engine with post-simulation capabilities, richer agent behavior, and dynamic persona generation — building the full data model before the web dashboard.

**Target features:**
- Agent Interviews — post-simulation live Q&A with any agent using full persona and decision context
- Live Graph Memory — real-time Neo4j updates during simulation with rationale episodes and narrative edges
- Post-Simulation Report — ReACT agent queries Neo4j and generates structured market analysis
- Richer Agent Interactions — agents publish rationale posts that peers read and react to
- Dynamic Persona Generation — extract entities from seed rumor to generate situation-specific agent personas

## Core Value

The 3-round consensus cascade must produce believable, diverse market reactions from 100 agents with dynamic influence topology — the simulation engine is the product.

## Requirements

### Validated

- [x] Async batched Ollama inference with adaptive ResourceGovernor (psutil-driven semaphore) — Validated in Phase 02: ollama-integration
- [x] Exponential backoff for Ollama retries — Validated in Phase 02: ollama-integration
- [x] Memory pressure monitoring with automatic concurrency throttling at 90% utilization — Validated in Phase 03: resource-governance
- [x] Neo4j GraphRAG for cycle-scoped sentiment storage and peer decision reads — Validated in Phase 04: neo4j-graph-state
- [x] Seed rumor injection with entity extraction via orchestrator LLM — Validated in Phase 05: seed-injection-and-agent-personas
- [x] 100-agent swarm across 10 bracket archetypes with distinct risk profiles — Validated in Phase 05: seed-injection-and-agent-personas
- [x] Round 1 standalone pipeline (seed → dispatch → persist) with CLI run command — Validated in Phase 06: round-1-standalone
- [x] 3-round iterative cascade (Initial Reaction → Peer Influence → Final Consensus Lock) — Validated in Phase 07: rounds-2-3-peer-influence-and-consensus

### Validated

- [x] Dynamic influence topology — INFLUENCED_BY edges form from citation/agreement patterns — Validated in Phase 08: dynamic-influence-topology

### Validated

- [x] Textual TUI: 10x10 agent grid with HSL color-coded cells and HeaderBar — Validated in Phase 09: tui-core-dashboard
- [x] Snapshot-based TUI rendering (200ms tick, diff-only cell updates, non-blocking Textual Worker) — Validated in Phase 09: tui-core-dashboard

### Validated

- [x] TUI panels: RationaleSidebar (agent reasoning stream), TelemetryFooter (RAM/TPS/Queue/Slots), BracketPanel (10-bracket signal bars) — Validated in Phase 10: tui-panels-and-telemetry
- [x] StateStore data layer extensions: rationale queue, TPS accumulation from Ollama eval metadata, bracket summary storage — Validated in Phase 10: tui-panels-and-telemetry

### Active
- [ ] Async batched Ollama inference with adaptive ResourceGovernor (psutil-driven semaphore)
- [ ] Miro API v2 batcher (stubbed for v1, full implementation deferred)
- [ ] Exponential backoff for Ollama retries and Miro 429 handling

### Validated

- [x] Live graph memory — WriteBuffer captures per-agent RationaleEpisode nodes (rationale, flip_type, peer_context) with REFERENCES edges to Entity nodes and decision_narrative on Agent nodes — Validated in Phase 11: live-graph-memory

### Planned (v2)

- [ ] Agent interviews — post-simulation live Q&A with any agent, using full persona and decision context (INT-01, INT-02, INT-03)
- [x] Post-simulation report — ReACT agent queries Neo4j and generates structured market analysis as markdown (REPORT-01, REPORT-02, REPORT-03) — Validated in Phase 15: post-simulation-report
- [x] Richer agent interactions — agents publish rationale posts that peers read and react to, creating social influence dynamics (SOCIAL-01, SOCIAL-02) — Validated in Phase 12: richer-agent-interactions
- [ ] Dynamic persona generation — extract entities from seed rumor to generate situation-specific agent personas (PERSONA-01, PERSONA-02)
- [ ] Miro live visualization — API v2 network visualization with spatial layout and dynamic connectors (VIS-01, VIS-02)
- [ ] Simulation replay from stored Neo4j state (REPLAY-01)
- [ ] Exportable simulation reports (REPLAY-02)
- [ ] Mid-simulation shock injection (REPLAY-03)

### Out of Scope

- Real market data feeds — simulation only, no live API integrations
- Multi-user / network mode — single-operator local-first design
- Historical backtesting — forward simulation only for v1
- GPU inference — Ollama CPU/Metal only on M1 Max
- Cloud APIs or hosted services — all inference and state local (no Zep, no OpenAI)

## Context

- **Hardware:** Apple M1 Max, 64GB unified memory — all inference runs locally via Ollama
- **LLM Strategy:** `llama4:70b` for orchestration (seed parsing, consensus aggregation), `qwen3.5:7b` for 100 worker agents
- **Ollama Constraints:** `OLLAMA_NUM_PARALLEL=16` baseline, but dynamically governed. `OLLAMA_MAX_LOADED_MODELS=2`
- **Inspiration:** OASIS/Mirofish multi-agent market simulation frameworks
- **Agent Brackets:** Quants (10), Degens (20), Sovereigns (10), Macro (10), Suits (10), Insiders (10), Agents (15), Doom-Posters (5), Policy Wonks (5), Whales (5)
- **Orchestration:** Ruflo v3.5 hierarchical swarm logic

## Constraints

- **Hardware**: M1 Max 64GB — all inference local, no cloud APIs. Memory pressure is the primary bottleneck.
- **Ollama**: Max 2 models loaded simultaneously, 16 parallel baseline (dynamically adjusted). Cold-loading a 70B model takes ~30s.
- **Miro API**: 2-second minimum buffer between POST/PATCH. Bulk operations only. 429 handling mandatory.
- **Concurrency**: All LLM calls and API interactions must be async (asyncio). No blocking I/O on the main event loop.
- **Python**: 3.11+ required. Strong typing throughout.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Dynamic asyncio.Semaphore over hardcoded parallelism | VRAM ceiling unknown during peak context loads; psutil monitoring at 90% threshold | ✓ Rewritten in Phase 03 — TokenPool (Queue-based) with 5-state governor machine, dual-signal monitoring (psutil + sysctl) |
| Snapshot-based TUI rendering (200ms tick) | 100 async agents would freeze Textual if pushing per-agent updates; decouples agent throughput from render throughput | ✓ Implemented in Phase 09 — StateStore.snapshot() + set_interval, diff-based AgentCell updates only |
| Cycle-scoped Neo4j edges (cycle_id on relationships) | Enables fast current-cycle reads without full history scans; composite index keeps queries under 5ms | ✓ Implemented in Phase 04 — composite index on (cycle_id, round), UNWIND batch writes, session-per-method isolation |
| Dynamic influence topology | Edges form from citation/agreement patterns, not static bracket hierarchies; more realistic consensus formation | — Pending |
| 3-round iterative cascade | Round 1: Initial reaction, Round 2: Peer influence, Round 3: Final consensus lock. Balances depth with compute cost | ✓ Round 1 implemented in Phase 06 — Rounds 2-3 pending |
| Miro deferred to Phase 2 | Most API-constrained component; core engine and TUI must be solid first. Batcher stubbed but not blocking | — Pending |
| Tiered backoff strategy | Ollama failures = resource exhaustion (retry 3x, shrink governor). Miro failures = rate limits (parse Retry-After + jitter) | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-01 — Phase 12 complete: richer-agent-interactions*
