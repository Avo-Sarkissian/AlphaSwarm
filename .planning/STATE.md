---
gsd_state_version: 1.0
milestone: v6.0
milestone_name: Real Data + Advisory
status: executing
stopped_at: "41.1-02 complete (Task 3 adaa938 + SUMMARY) — Wave 1 scaffold done; next: Plans 03/04 in parallel worktrees"
last_updated: "2026-04-20T16:54:51Z"
last_activity: 2026-04-20
progress:
  total_phases: 7
  completed_phases: 5
  total_plans: 20
  completed_plans: 17
  percent: 85
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-18)

**Core value:** The 3-round consensus cascade must produce believable, diverse market reactions from 100 agents with dynamic influence topology — grounded in real market data, the simulation engine is the product
**Current focus:** Phase 41.1 — ui-port-wire-replace-vue-frontend-with-claude-design-ui-reac

## Current Position

Phase: 41.1 (ui-port-wire-replace-vue-frontend-with-claude-design-ui-reac) — EXECUTING
Plan: 3 of 5 (Wave 1 complete — Plans 03/04 next in parallel worktrees)
Status: Plan 02 complete (Task 3 adaa938 + SUMMARY)
Last activity: 2026-04-20

Progress: [████████▌░] 85% (5/7 phases, 17/20 plans)

## Performance Metrics

**All-time:**

- Total phases completed: 27 (v1.0 + v2.0 + v4.0 + v5.0 + Phase 37)
- Total plans completed: 85
- Total milestones shipped: 4 (v1.0, v2.0, v4.0, v5.0)

**Per-plan:**

| Phase | Plan | Duration | Tasks | Files |
|-------|------|----------|-------|-------|
| 41.1  | 01   | 4m       | 3     | 17    |
| 41.1  | 02   | ~90m     | 3     | 37    |

## Accumulated Context

### Roadmap Evolution

- Phase 28 added: Simulation Replay (REPLAY-01 — re-render past cycle from Neo4j without re-inference)
- Phase 35.1 inserted after Phase 35: Shock Injection Wiring (URGENT — unblocks Phase 36 report shock-impact; see BUGFIX-CONTEXT.md B1)
- Phase 41.1 inserted after Phase 41: UI port & wire — replace Vue frontend with Claude Design UI React assets and wire WebSocket live data (URGENT)

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
- [Phase 41.1]: Pinned @vitejs/plugin-react ^5.2.0 instead of ^6.0.1 because plugin-react@6 requires Vite ^8; preserves Plan's Vite 6 mandate (41.1-01 deviation, Rule 3)

### Pending Todos

None.

### Blockers/Concerns

- Phase 28 (Replay): read_full_cycle() Cypher query needs performance profiling for COLLECT aggregation across 600+ nodes

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260416-lan | Delete macOS Finder-duplicate files (space-2 suffix) | 2026-04-16 | d2c5e60 | [260416-lan-delete-macos-finder-duplicate-files-spac](./quick/260416-lan-delete-macos-finder-duplicate-files-spac/) |
| 260416-lpb | Tier 0 steps 2-4: frontend noEmit, CLAUDE.md/AGENTS.md rewrite, ROADMAP Phase 36 fix | 2026-04-16 | 81c73db | [260416-lpb-tier-0-steps-2-4-frontend-noemit-claude-](./quick/260416-lpb-tier-0-steps-2-4-frontend-noemit-claude-/) |
| 260416-m8x | Tier 1 surgical bug fixes (B4 replay/live guard, B7 writer leak, B8 phase race, B9 replay lock, B10 dupe COMPLETE) | 2026-04-16 | 73b7b9d | [260416-m8x-tier-1-surgical-bug-fixes-b4-replay-live](./quick/260416-m8x-tier-1-surgical-bug-fixes-b4-replay-live/) |
| 260416-trw | Tier 0 cleanup: delete Finder duplicate files B2, add noEmit to tsconfig B5-B6, add useWebSocket teardown B11 | 2026-04-17 | 10d739e | [260416-trw-tier-0-cleanup-delete-finder-duplicate-f](./quick/260416-trw-tier-0-cleanup-delete-finder-duplicate-f/) |

## Session Continuity

Last session: 2026-04-20T16:18:57.259Z
Stopped at: 41.1-02 Task 2 committed (6daf397) — shared wiring infra complete; Task 3 (App.tsx provider tree) + SUMMARY pending
Next action: /gsd:complete-milestone or /gsd:new-milestone for v3.0
