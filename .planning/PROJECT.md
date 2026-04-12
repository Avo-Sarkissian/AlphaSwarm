# AlphaSwarm

## What This Is

A localized, multi-agent financial simulation engine that ingests a single "Seed Rumor" and simulates cascading market reactions across 100 distinct AI personas. The system runs a 3-round iterative consensus cascade on local hardware (M1 Max 64GB), visualizing real-time agent state via a Textual TUI dashboard, persisting interaction history in Neo4j, and now supporting mid-simulation shock injection, HTML report export with Schwab portfolio overlay, and full simulation replay from stored state.

## Core Value

The 3-round consensus cascade must produce believable, diverse market reactions from 100 agents with dynamic influence topology — the simulation engine is the product.

## Requirements

### Validated

- ✓ Async batched Ollama inference with adaptive ResourceGovernor (psutil-driven semaphore) — v1.0
- ✓ Exponential backoff for Ollama retries — v1.0
- ✓ Memory pressure monitoring with automatic concurrency throttling — v1.0
- ✓ Neo4j GraphRAG for cycle-scoped sentiment storage and peer decision reads — v1.0
- ✓ Seed rumor injection with entity extraction via orchestrator LLM — v1.0
- ✓ 100-agent swarm across 10 bracket archetypes with distinct risk profiles — v1.0
- ✓ 3-round iterative cascade (Initial Reaction → Peer Influence → Final Consensus Lock) — v1.0
- ✓ Dynamic influence topology — INFLUENCED_BY edges from citation/agreement patterns — v1.0
- ✓ Textual TUI: 10x10 agent grid, snapshot-based rendering, bracket panel, rationale sidebar, telemetry footer — v1.0
- ✓ Live graph memory — WriteBuffer captures per-agent RationaleEpisode nodes with REFERENCES edges — v2.0
- ✓ Richer agent interactions — agents publish rationale posts that peers read via token-budget-aware context injection — v2.0
- ✓ Dynamic persona generation — entity-aware bracket modifiers from seed rumor, prompt injection sanitized — v2.0
- ✓ Agent interviews — post-simulation click-to-Q&A with any agent using full 3-round Neo4j context — v2.0
- ✓ Post-simulation report — ReACT agent + Jinja2 templates + CLI export via aiofiles — v2.0
- ✓ HTML report export with SVG pygal charts and Schwab portfolio overlay — v4.0
- ✓ Mid-simulation shock injection — ShockInputScreen modal, governor suspend/resume, StateStore shock bridge — v4.0
- ✓ Shock impact analysis — bracket delta mode, read_shock_impact Cypher, Jinja2 shock template — v4.0
- ✓ Simulation replay — CLI `replay` subcommand, CyclePickerScreen, TUI replay mode from Neo4j state — v4.0

### Active

- [ ] Miro API v2 live network visualization with spatial layout (VIS-01, VIS-02) — deferred
- [ ] Web dashboard (Vue 3 + FastAPI) for browser-based simulation monitoring (WEB-01 through WEB-06)

### Out of Scope

- Real market data feeds — simulation-only engine, no live API integrations
- Multi-user / network mode — single-operator local-first design
- Historical backtesting — forward simulation only
- GPU inference — Ollama CPU/Metal only on M1 Max
- Cloud APIs or hosted services — all inference and state local
- RL-based adaptive agents — LLM inference only, not reinforcement learning
- Trade execution — no real money, no broker integration

## Context

- **Hardware:** Apple M1 Max, 64GB unified memory — all inference local via Ollama
- **LLM Strategy:** `llama4:70b` for orchestration (seed parsing), `qwen3.5:7b` for 100 worker agents
- **Ollama Constraints:** `OLLAMA_NUM_PARALLEL=16` baseline, dynamically governed. `OLLAMA_MAX_LOADED_MODELS=2`
- **Codebase:** ~21,870 LOC Python across `src/alphaswarm/` and `tests/`
- **Test suite:** 530+ unit tests, integration tests require live Neo4j
- **Shipped milestones:** v1.0 (core engine), v2.0 (engine depth), v3.0 (stock recommendations), v4.0 (interactive analysis)
- **Agent Brackets:** Quants (10), Degens (20), Sovereigns (10), Macro (10), Suits (10), Insiders (10), Agents (15), Doom-Posters (5), Policy Wonks (5), Whales (5)

## Constraints

- **Hardware**: M1 Max 64GB — all inference local, no cloud APIs. Memory pressure is the primary bottleneck.
- **Ollama**: Max 2 models loaded simultaneously, 16 parallel baseline (dynamically adjusted). Cold-loading a 70B model takes ~30s.
- **Miro API**: 2-second minimum buffer between POST/PATCH. Bulk operations only. 429 handling mandatory.
- **Concurrency**: All LLM calls and API interactions must be async (asyncio). No blocking I/O on the main event loop.
- **Python**: 3.11+ required. Strong typing throughout.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Dynamic asyncio.Semaphore over hardcoded parallelism | VRAM ceiling unknown during peak context loads; psutil monitoring at 90% threshold | ✓ TokenPool (Queue-based) with 5-state governor machine, dual-signal monitoring — Phase 03 |
| Snapshot-based TUI rendering (200ms tick) | 100 async agents would freeze Textual if pushing per-agent updates | ✓ StateStore.snapshot() + set_interval, diff-based AgentCell updates — Phase 09 |
| Cycle-scoped Neo4j edges (cycle_id on relationships) | Fast current-cycle reads without full history scans; composite index keeps queries under 5ms | ✓ Composite index on (cycle_id, round), UNWIND batch writes — Phase 04 |
| Dynamic influence topology | Edges from citation/agreement patterns, not static bracket hierarchies | ✓ INFLUENCED_BY edges from cited_agents — Phase 08 |
| WriteBuffer with drop-oldest queue | Real-time episode writes without blocking simulation dispatch; bounded memory footprint | ✓ asyncio.Queue, flush-per-round, test-verified no-loss — Phase 11 |
| Prompt-based ReACT tool dispatching (no native tools) | Ollama native tool support inconsistent across models; prompt-based more portable | ✓ Thought-Action-Observation loop with 8-10 iteration cap — Phase 15 |
| SVG charts via pygal (not Plotly) | HTML reports under 1MB vs 15MB+ with Plotly | ✓ pygal with TUI color theme — Phase 24 |
| Schwab CSV loaded in-memory only | Portfolio data never persisted to Neo4j or cache — simulation stays uncontaminated | ✓ CSV read at report time only — Phase 25 |
| Governor suspend/resume at callee (governor.py) | Prevents TOCTOU race vs caller-side check; resume() memory-pressure guard self-contained | ✓ governor.resume() guards against high-RAM resume — Phase 26 |
| ReplayStore separate from StateStore | StateStore's destructive drain and timer would corrupt replay; clean separation required | ✓ ReplayStore with no-drain snapshot semantics — Phase 28 |
| _replay_store set before phase change | Prevents _poll_snapshot race — store availability gates TUI branching, not phase enum | ✓ Explicit ORDERING comment in _enter_replay — Phase 28 |

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
*Last updated: 2026-04-12 after v4.0 milestone — Interactive Simulation & Analysis*
