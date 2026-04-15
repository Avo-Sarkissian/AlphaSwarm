---
phase: 34-replay-mode-web-ui
verified: 2026-04-14T00:00:00Z
status: human_needed
score: 10/10 automated must-haves verified
re_verification: false
human_verification:
  - test: "Full end-to-end replay flow in browser"
    expected: "All 7 test groups from Plan 03 pass: idle Replay button, cycle picker modal, replay start with amber REPLAY badge, round stepping (Next disabled at Round 3), force graph interaction, exit replay returns to idle, visual distinction from live simulation"
    why_human: "Force graph D3 transitions, node color updates from Neo4j state, WebSocket round-by-round delivery, and visual distinctiveness cannot be verified without a running server and Neo4j with completed cycles. Plan 03 SUMMARY records a human approval, but the verifier cannot re-run live browser tests."
---

# Phase 34: Replay Mode Web UI Verification Report

**Phase Goal:** Wire the Phase 32 replay contract stubs into a real browser replay experience — cycle picker, round-by-round stepping, and live force graph re-render from Neo4j state without new inference

**Verified:** 2026-04-14T00:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Success Criteria (from ROADMAP.md)

The ROADMAP defines 5 success criteria for Phase 34:

1. `GET /api/replay/cycles` populates a cycle picker UI; user selects a completed cycle to replay
2. `POST /api/replay/start/{cycle_id}` loads Round 1 agent states into the force graph; nodes update color and position from stored decisions
3. `POST /api/replay/advance` steps to the next round; force graph transitions to the new round state
4. Replay mode is visually distinct from live simulation (a "REPLAY" banner or header badge)
5. The force graph's node click to sidebar flow works identically in replay mode

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | POST /api/replay/start loads signals, sets round 1, broadcasts snapshot | VERIFIED | replay_manager.py lines 74-122: full Neo4j signal load, ReplayStore construction, set_round(1), bracket/rationale load, phase set to REPLAY, broadcast |
| 2 | POST /api/replay/advance increments round (max 3), broadcasts new snapshot | VERIFIED | replay_manager.py lines 124-168: round increment with guard at 3, bracket/rationale reload, broadcast |
| 3 | POST /api/replay/stop resets phase to IDLE and clears ReplayManager | VERIFIED | replay_manager.py lines 170-177: store/cycle_id/round cleared, set_phase(IDLE) called |
| 4 | Broadcaster uses replay store snapshot when replay is active | VERIFIED | broadcaster.py lines 45-47: explicit `if replay_manager is not None and replay_manager.is_active` branch returns replay store snapshot |
| 5 | Concurrent replay start returns 409; missing cycle returns 404 | VERIFIED | routes/replay.py lines 120-131: pre-lock is_active 409 guard, empty signals 404; test_replay_start_409_already_active and test_replay_start_404_cycle_not_found both present |
| 6 | Idle ControlBar shows Replay button alongside Start Simulation | VERIFIED | ControlBar.vue lines 129-150: `v-if="!isActive && !isReplay"` block renders seed textarea, Start Simulation button, and Replay ghost button |
| 7 | CyclePicker modal fetches /api/replay/cycles on open and lists cycles | VERIFIED | CyclePicker.vue lines 23-45: onMounted calls fetchCycles, GET /api/replay/cycles, populates cycles ref; loading/error/empty states all present |
| 8 | ControlBar shows replay strip with REPLAY badge, Round N/3, Next, Exit in replay mode | VERIFIED | ControlBar.vue lines 169-187: `v-else-if="isReplay"` block with amber badge, round info, Next button (disabled at Round 3), Exit button |
| 9 | ForceGraph clears edges when phase transitions to replay | VERIFIED | ForceGraph.vue lines 185-190: phase watcher includes `newPhase === 'replay'` in the edge-clear condition |
| 10 | App.vue mounts CyclePicker via v-if and wires open-cycle-picker event | VERIFIED | App.vue lines 9, 34-45, 51, 75-79: CyclePicker imported, showCyclePicker ref, open/close/start handlers, @open-cycle-picker on ControlBar, v-if CyclePicker mount |

**Score:** 10/10 automated truths verified

---

## Required Artifacts

### Plan 01 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/alphaswarm/web/replay_manager.py` | ReplayManager class with start/advance/stop lifecycle | VERIFIED | 177 lines; exports ReplayManager, ReplayAlreadyActiveError, NoReplayActiveError; full asyncio.Lock lifecycle |
| `src/alphaswarm/web/routes/replay.py` | Real replay_start, replay_advance + new replay_stop endpoint | VERIFIED | 192 lines; all 4 endpoints present including replay_stop with ReplayStopResponse model |
| `src/alphaswarm/web/broadcaster.py` | Replay-aware snapshot_to_json checking replay_manager.is_active | VERIFIED | Lines 45-47: explicit is_active branch; replay_manager passed as optional parameter throughout |
| `tests/test_web.py` | 7+ new replay tests covering all backend paths | VERIFIED | 39 total tests; 11 replay-specific tests (10 in replay_ prefix + 1 broadcaster replay test) covering start/409/404/503/advance/stop/routes registration/broadcaster |

### Plan 02 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/components/CyclePicker.vue` | Modal overlay, cycle list, radio selection, Start Replay + Close Picker, min 80 lines | VERIFIED | 275 lines; all states (loading/error/empty/list), radio selection, both buttons, backdrop/Escape dismiss, Transition animation |
| `frontend/src/components/ControlBar.vue` | 3-way v-if/v-else-if template; contains isReplay | VERIFIED | 341 lines; isReplay computed at line 14; 3-way template (idle/active/replay) at lines 129-187 |
| `frontend/src/components/ForceGraph.vue` | Edge clear on replay phase; contains replay | VERIFIED | Line 186: `newPhase === 'replay'` in phase watcher edge-clear condition |
| `frontend/src/App.vue` | CyclePicker mount via v-if, showCyclePicker ref | VERIFIED | CyclePicker import at line 9, showCyclePicker ref at line 34, v-if mount at line 75 |
| `frontend/src/assets/variables.css` | 4 new CSS tokens including --color-replay | VERIFIED | Lines 66-69: --color-replay: #f59e0b, --color-replay-text: #0f1117, --duration-modal-enter: 200ms, --duration-modal-exit: 150ms |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| ControlBar.vue | /api/replay/advance | fetch in advanceReplay | WIRED | Line 105: `fetch('/api/replay/advance', { method: 'POST' })` with advancePending guard and response handling |
| ControlBar.vue | /api/replay/stop | fetch in exitReplay | WIRED | Line 117: `fetch('/api/replay/stop', { method: 'POST' })` |
| CyclePicker.vue | /api/replay/cycles | fetch in onMounted/fetchCycles | WIRED | Lines 36-44: `fetch('/api/replay/cycles')`, response parsed and assigned to cycles.value |
| CyclePicker.vue | /api/replay/start/{cycle_id} | fetch in startReplay | WIRED | Lines 52-60: fetch with template literal, handles 404 and generic errors, emits start-replay on success |
| App.vue | CyclePicker.vue | v-if mount with showCyclePicker ref | WIRED | Lines 75-79: `<CyclePicker v-if="showCyclePicker" @start-replay="onStartReplay" @close="onCloseCyclePicker" />` |
| routes/replay.py | replay_manager.py | request.app.state.replay_manager | WIRED | Lines 110, 155, 183 in routes/replay.py access app.state.replay_manager |
| broadcaster.py | replay_manager.py | replay_manager.is_active check | WIRED | Lines 45-47: explicit is_active check before falling through to live StateStore path |
| app.py | replay_manager.py | ReplayManager created in lifespan, mounted on app.state | WIRED | app.py line 43: `replay_manager = ReplayManager(app_state)`, line 48: `app.state.replay_manager = replay_manager`, line 54: passed to start_broadcaster |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|-------------------|--------|
| CyclePicker.vue | cycles (ref) | GET /api/replay/cycles → graph_manager.read_completed_cycles() | Yes — Cypher query filters cycles with Round 3 decisions; 503 returned when Neo4j unavailable | FLOWING |
| ControlBar.vue | replayRound | snapshot.value.round_num (computed) | Yes — round_num set by ReplayManager.advance() and broadcast via WebSocket | FLOWING |
| broadcaster.py | replay store snapshot | ReplayManager.store.snapshot() → ReplayStore loaded with Neo4j signals | Yes — signals loaded via read_full_cycle_signals; bracket/rationale per-round | FLOWING |

---

## Behavioral Spot-Checks

Step 7b skipped for frontend Vue components (no runnable entry points in test environment). Backend spot-checks run via test suite:

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| replay_start loads signals and returns round 1 | test_replay_start_real_logic (line 764) | Asserts status=ok, cycle_id, round_num=1, replay_manager.is_active=True | PASS (per 39/39 test count in SUMMARY) |
| replay_start 409 on duplicate | test_replay_start_409_already_active (line 795) | Asserts HTTP 409 with replay_already_active error | PASS |
| replay_start 404 for missing cycle | test_replay_start_404_cycle_not_found (line 820) | Asserts HTTP 404 with cycle_not_found error | PASS |
| replay_advance increments round | test_replay_advance_real_logic (line 835) | Asserts round_num=2 after advance | PASS |
| replay_stop resets to inactive | test_replay_stop_resets_phase (line 862) | Asserts is_active=False after stop | PASS |
| broadcaster uses replay snapshot | test_broadcaster_uses_replay_snapshot_when_active (line 895) | Asserts phase=replay and agent_1 in agent_states | PASS |
| All 4 replay routes registered | test_replay_routes_registered_in_production_app (line 733) | Asserts /api/replay/cycles, /api/replay/start/{cycle_id}, /api/replay/advance, /api/replay/stop in route_paths | PASS |

All 7 backend spot-checks pass per SUMMARY-01 (39/39 tests passing, commits 1a7b4e3, ef330da, 4ffbf60).

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| WEB-06 | 34-01, 34-02 | Replay mode web UI: cycle picker, round stepping, force graph re-render | SATISFIED | Backend state machine complete; frontend UI (CyclePicker, ControlBar replay strip) complete and wired; ForceGraph edge-clear fixed |
| REPLAY-01 | 34-01, 34-02 | Replay REST endpoints functional (start/advance/stop) with real Neo4j data | SATISFIED | All 3 endpoints load real data from graph_manager; broadcaster replay-aware; 11 tests cover all paths |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| App.vue | 42 | `_cycleId: string` parameter prefix — intentional unused param suppressor | Info | Not a stub; cycleId unused in handler because CyclePicker already posted the start before emitting. This is documented in the comment on line 44. No behavioral gap. |

No blocker or warning anti-patterns found. No placeholder comments, empty return stubs, or hardcoded empty arrays flow to user-visible output.

---

## Human Verification Required

### 1. End-to-End Replay Mode Browser Test

**Test:** With Neo4j running and at least one completed simulation cycle, open the browser at http://localhost:8000 and walk through all 7 test groups from Plan 03:
1. Idle state shows Replay ghost button next to Start Simulation
2. Clicking Replay opens modal with "Select a Cycle to Replay" title, cycle list, and Start Replay disabled until selection
3. Backdrop click and Escape key both dismiss the modal
4. Selecting a cycle and clicking Start Replay closes modal, transitions ControlBar to amber REPLAY badge with "Round 1 / 3"
5. Clicking Next advances rounds; force graph node colors update from stored Neo4j decisions; Next is disabled at Round 3/3
6. Agent node click opens AgentSidebar identically to live mode
7. Exit returns to idle state (seed textarea + Start Simulation + Replay buttons visible)

**Expected:** All 7 test groups pass. REPLAY badge is visually amber (#f59e0b). Force graph clears edges on replay start and loads stored round data. Round stepping transitions node colors.

**Why human:** D3 transitions, force simulation physics, node color updates from stored AgentState.signal values, WebSocket message delivery timing, and visual distinctiveness between replay and live modes cannot be verified by static code analysis. Plan 03 SUMMARY records human approval on 2026-04-15 with all 7 groups passing, but this was not independently witnessed by the verifier.

---

## Gaps Summary

No automated gaps. All 10 observable truths are verified by static code analysis. All artifacts exist, are substantive, and are wired. All key links are confirmed present in source code.

The sole remaining verification item is human-gated: the live end-to-end browser experience with D3 force graph rendering and round-by-round state transitions. Plan 03 SUMMARY (completed 2026-04-15) records human approval with all 7 test groups passing and a clean production build (313 modules, 150KB JS). The verifier flags this as human_needed because visual rendering, WebSocket delivery, and force graph interaction cannot be re-confirmed without a running environment.

---

_Verified: 2026-04-14T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
