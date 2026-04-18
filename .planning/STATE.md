---
gsd_state_version: 1.0
milestone: v6.0
milestone_name: Data Enrichment & Personalized Advisory
status: roadmap_ready
stopped_at: Phase 37 — Isolation Foundation & Provider Scaffolding
last_updated: "2026-04-18T00:00:00.000Z"
last_activity: 2026-04-18
progress:
  total_phases: 7
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-18)

**Core value:** The 3-round consensus cascade must produce believable, diverse market reactions from 100 agents with dynamic influence topology — the simulation engine is the product.
**Current focus:** v6.0 Data Enrichment & Personalized Advisory — roadmap approved, ready to plan Phase 37

## Current Position

Phase: Phase 37 — Isolation Foundation & Provider Scaffolding
Plan: —
Status: Ready to plan
Last activity: 2026-04-18 — Roadmap for v6.0 (Phases 37-43) written and approved

Progress: [░░░░░░░░░░] 0%

**v6.0 phase queue (integer order):**
1. Phase 37 — Isolation Foundation & Provider Scaffolding (ISOL-01..07)
2. Phase 38 — Market Data + News Ingestion (INGEST-01..07)
3. Phase 39 — Holdings CSV Ingestion (HOLD-01..08)
4. Phase 40 — Context Packet Assembly & Swarm Injection (CTX-01..08)
5. Phase 41 — Advisory Pipeline (Orchestrator Synthesis) (ADV-01..13)
6. Phase 42 — Advisory Web UI (ADVUI-01..06)
7. Phase 43 — v6 E2E & Carry-Forward Validation (V6UAT-01..08)

## Performance Metrics

**All-time:**

- Total phases completed: 29 (v1.0 + v2.0 + v3.0 + v4.0 + v5.0)
- Total plans completed: 65+
- Total milestones shipped: 4 (v1.0, v2.0, v4.0, v5.0)

## Accumulated Context

### Roadmap Evolution

- Phase 28 added: Simulation Replay (REPLAY-01 — re-render past cycle from Neo4j without re-inference)
- Phase 35.1 inserted after Phase 35: Shock Injection Wiring (URGENT — unblocks Phase 36 report shock-impact; see BUGFIX-CONTEXT.md B1)
- v6.0 phases 37-43 added 2026-04-18 — synthesizer-approved 7-phase structure aligning architecture (9-phase plan), pitfalls (7-phase plan), and user spec

### Decisions

- Swarm stays uncontaminated by portfolio data — orchestrator reads consensus + holdings post-simulation only
- Schwab CSV loaded in-memory only during report step, never persisted to Neo4j or cache
- SVG charts via pygal (not Plotly) — keeps HTML reports under 1MB vs 15MB+
- Governor suspend/resume must be first deliverable in shock phase — prevents false THROTTLED states (SHIPPED Phase 26)
- ReplayStore is separate from StateStore — destructive snapshot drain and timer corruption make reuse unsafe
- resume() memory-pressure guard lives at the CALLEE (governor.py), not the caller (simulation.py) — eliminates TOCTOU race
- _collect_inter_round_shock uses nested try/finally: inner finally for close_shock_window, outer finally for governor.resume()
- ShockInputScreen edge latch (_shock_window_was_open) prevents re-pushing on consecutive _poll_snapshot ticks
- SHOCK_TEXT_MAX_LEN = 4096 caps prompt injection size across 100 agents (M1 memory constraint)
- **v6.0 Option A (LOCKED):** ingestion → ContextPacket → swarm → orchestrator synthesis-only. Holdings never enter any worker prompt, Neo4j node, log, or WebSocket frame
- **v6.0 defense-in-depth isolation (all three required):** importlinter forbidden_modules contract + pydantic `extra="forbid"` ContextPacket + runtime canary test with sentinel ticker
- **v6.0 news:** RSS primary, NewsAPI optional behind feature flag (matches local-first constraint — no mandatory cloud API)
- **v6.0 Robinhood:** generic column-mapping UI (no native adapter); Robinhood users map columns manually
- **v6.0 advisory language:** qualitative only ("Review / Monitor / No action indicated") — no Buy/Sell, no price targets, no trade orders
- **v6.0 advisory temperature:** orchestrator at `temperature=0.1`, `top_p=0.8` for grounding; rumor parsing stays at existing higher temp
- **v6.0 token budget:** `MAX_WORKER_CONTEXT_TOKENS = 2000` enforced at packet assembly (guard against bug_governor_deadlock re-emergence)

### Pending Todos

- [ ] Plan Phase 37 — Isolation Foundation & Provider Scaffolding (`/gsd:plan-phase 37`)

### Blockers/Concerns

- Phase 28 (Replay) carry-forward: read_full_cycle() Cypher query needs performance profiling for COLLECT aggregation across 600+ nodes
- Phase 38 empirical tuning: yfinance concurrency semaphore (start 4, may drop to 2 based on 429 response under 100-ticker load)
- Phase 40 empirical tuning: `MAX_WORKER_CONTEXT_TOKENS` may land between 1200-3000 depending on qwen3.5:7b quality vs. context size calibration
- Phase 41 prompt engineering: synthesis prompt requires 2-3 iteration cycles for weak-signal and empty-holdings edge cases
- v5.0 carry-forward debt (resolves in Phase 43): Phase 29 planning artifact backfill; Nyquist VALIDATION.md backfills for 29/31/35.1; 9 human UAT items across phases 32/34/36

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260416-lan | Delete macOS Finder-duplicate files (space-2 suffix) | 2026-04-16 | d2c5e60 | [260416-lan-delete-macos-finder-duplicate-files-spac](./quick/260416-lan-delete-macos-finder-duplicate-files-spac/) |
| 260416-lpb | Tier 0 steps 2-4: frontend noEmit, CLAUDE.md/AGENTS.md rewrite, ROADMAP Phase 36 fix | 2026-04-16 | 81c73db | [260416-lpb-tier-0-steps-2-4-frontend-noemit-claude-](./quick/260416-lpb-tier-0-steps-2-4-frontend-noemit-claude-/) |
| 260416-m8x | Tier 1 surgical bug fixes (B4 replay/live guard, B7 writer leak, B8 phase race, B9 replay lock, B10 dupe COMPLETE) | 2026-04-16 | 73b7b9d | [260416-m8x-tier-1-surgical-bug-fixes-b4-replay-live](./quick/260416-m8x-tier-1-surgical-bug-fixes-b4-replay-live/) |
| 260416-trw | Tier 0 cleanup: delete Finder duplicate files B2, add noEmit to tsconfig B5-B6, add useWebSocket teardown B11 | 2026-04-17 | 10d739e | [260416-trw-tier-0-cleanup-delete-finder-duplicate-f](./quick/260416-trw-tier-0-cleanup-delete-finder-duplicate-f/) |

## Session Continuity

Last session: 2026-04-18
Stopped at: v6.0 roadmap approved — Phases 37-43 written, 57/57 v6 requirements mapped
Next action: `/gsd:plan-phase 37` — plan Phase 37 (Isolation Foundation & Provider Scaffolding)
