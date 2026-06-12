---
gsd_state_version: 1.0
milestone: v6.0
milestone_name: Real Data + Advisory
status: executing
stopped_at: Phase 41.6 W2 polish complete (quick 260510-fdo); backend agent_states emission fixed (R1+R2 commits fe366ce, 1da741e, bd682df). Live UAT pending; W4 next.
last_updated: "2026-05-10T15:36:09.102Z"
last_activity: 2026-05-10
progress:
  total_phases: 10
  completed_phases: 6
  total_plans: 31
  completed_plans: 25
  percent: 81
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-18)

**Core value:** The 3-round consensus cascade must produce believable, diverse market reactions from 100 agents with dynamic influence topology — grounded in real market data, the simulation engine is the product
**Current focus:** Phase 41.6 — ui-revamp-alphaswarm-2-quant-terminal-port-and-wire

## Current Position

Phase: 999.1
Plan: Not started
Status: Executing Phase 41.6
Last activity: 2026-06-11 - Completed quick task 260611-rlx: Fix advisory synthesis timeout (think=False) and chain report auto-generation after advisory

Progress: [█████████░] 90% (5/7 phases, 19/20 plans)

## Performance Metrics

**All-time:**

- Total phases completed: 27 (v1.0 + v2.0 + v4.0 + v5.0 + Phase 37)
- Total plans completed: 89
- Total milestones shipped: 4 (v1.0, v2.0, v4.0, v5.0)

**Per-plan:**

| Phase | Plan | Duration | Tasks | Files |
|-------|------|----------|-------|-------|
| 41.1  | 01   | 4m       | 3     | 17    |
| 41.1  | 02   | ~90m     | 3     | 37    |
| 41.1  | 03   | ~32m     | 3     | 8     |
| 41.1  | 04   | ~48m     | 4     | 12    |

## Accumulated Context

### Roadmap Evolution

- Phase 28 added: Simulation Replay (REPLAY-01 — re-render past cycle from Neo4j without re-inference)
- Phase 35.1 inserted after Phase 35: Shock Injection Wiring (URGENT — unblocks Phase 36 report shock-impact; see BUGFIX-CONTEXT.md B1)
- Phase 41.1 inserted after Phase 41: UI port & wire — replace Vue frontend with Claude Design UI React assets and wire WebSocket live data (URGENT)
- Phase 41.5 inserted after Phase 41: advisory redesign — visual hero, KPI strip, and per-holding decision table grounded in swarm bracket signals (URGENT — current AdvisoryModal is plaintext narrative; user wants report-style visual contract with explicit per-position recommendations)

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
| 260506-qmn | Bug A — Vite WS proxy missing changeOrigin (frontend/vite.config.ts) | 2026-05-06 | 45508dd | [260506-qmn-bug-a-vite-ws-proxy-missing-changeorigin](./quick/260506-qmn-bug-a-vite-ws-proxy-missing-changeorigin/) |
| 260507-19f | Gate Personalized Report button — pure viewer mode + portfolio_outlook schema fix | 2026-05-07 | 09231ad+eca6e04 | [260507-19f-gate-personalized-report-button-auto-fir](./quick/260507-19f-gate-personalized-report-button-auto-fir/) |
| 260507-wln | Restore live citation edges + rationale feed (peer-context agent_id + adapter field rename) | 2026-05-08 | 861009c+44fc27e | [260507-wln-restore-live-citation-edges-rationale-fe](./quick/260507-wln-restore-live-citation-edges-rationale-fe/) |
| 260510-fdo | Polish W2 visual gaps: BracketList all-zero empty state + AdvisoryV2 polling-exhausted error UI + useCurrentCycle dedupe (8x → 1x replay/cycles on mount) | 2026-05-10 | 1be286e+181b170+0a4f0b8 | [260510-fdo-polish-w2-visual-gaps-bracket-bars-empty](./quick/260510-fdo-polish-w2-visual-gaps-bracket-bars-empty/) |
| 260512-jqn | 6 post-run follow-ups: InterviewV2/Onboarding/BracketDeepDive CSS + /api/edges Cypher fix + governor slots (KR-41.1-05) + rationale sliding window + live SignalWire audit + advisory items+sector enrichment | 2026-05-12 | 41d8d4c+890a220+de31313+0003375+fc7a568+4234035 | [260512-jqn-address-6-post-run-follow-ups-interviewv](./quick/260512-jqn-address-6-post-run-follow-ups-interviewv/) |
| 260611-rlx | Fix advisory synthesis timeout (think=False in _infer_with_retry) + chain report auto-generation off advisory success + ReportModal copy update | 2026-06-11 | 2a87620+bbb12eb+a10ce09 | [260611-rlx-fix-advisory-synthesis-timeout-think-fal](./quick/260611-rlx-fix-advisory-synthesis-timeout-think-fal/) |

## Session Continuity

Last session: 2026-05-12T22:30:00.000Z (session-end snapshot before /clear)
Stopped at: All 7 tracked post-run follow-ups closed + 6 takeover CSS-gap patches + UX polish (idle "Browse previous runs", report probe-then-trigger, formatted cycle dates, settings takeover). Final commit on master: e14ba29. All gates green throughout (npm check + build green, pytest green for touched modules). Backend RESTART required to pick up Python-side changes (uvicorn doesn't hot-reload). Browser hard-refresh picks up frontend.
Resume protocol: Read .planning/SESSION-2026-05-12-HANDOFF.md FIRST. It has the full commit ledger, file map, UAT checklist, and resume protocol. Then run the stack readiness check (curl /api/holdings + /api/health + /5173 + /11434, docker ps neo4j). If everything green, trigger a fresh sim to UAT the changes; if broken, check uvicorn cwd is project root (not frontend/).
Next action: User will trigger next sim after /clear. Watch list per HANDOFF UAT table — top 5: (1) live mid-round rationale feed, (2) PARALLEL SLOTS non-zero, (3) advisory items[] non-empty with per-holding sector reasoning, (4) live WIRE ticker (real provider calls, not mock seed), (5) post-cycle OUT-DEGREE flip + active-edges count.
