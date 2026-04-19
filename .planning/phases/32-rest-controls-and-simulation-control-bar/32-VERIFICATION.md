---
phase: 32-rest-controls-and-simulation-control-bar
verified: 2026-04-14T00:00:00Z
status: human_needed
score: 13/13 automated must-haves verified
human_verification:
  - test: "Open app in browser. Idle state: control bar visible at top, seed textarea present, Start button disabled when empty, enables when text typed. No Stop/phase/shock buttons visible."
    expected: "Control bar renders correctly in idle state with seed input and disabled Start."
    why_human: "Vue component rendering and CSS state toggling require a browser."
  - test: "With a running simulation: seed textarea disabled (opacity 0.5), Start button greyed, phase label shows 'Round 1 / 3' or 'Seeding...' (not raw enum 'round_1'). Stop button and +Inject Shock button visible."
    expected: "Active state renders correctly with formatted phase label and correct button visibility."
    why_human: "Active state requires a live simulation connected via WebSocket."
  - test: "Click Start twice rapidly (before WebSocket phase update arrives). Second click must be a no-op -- button shows 'Starting...' and is disabled."
    expected: "Double-click prevention: startPending=true keeps the button disabled until backend phase changes away from idle."
    why_human: "Race condition timing between click handler and WebSocket message requires browser interaction."
  - test: "During active simulation, click +Inject Shock. Drawer slides down below the control bar (not as modal overlay). Type text, click Inject Shock. On success, drawer closes."
    expected: "ShockDrawer animates in as a slide-down panel directly beneath the control bar, textarea auto-focuses, submit closes on success."
    why_human: "CSS Transition animation and auto-focus behavior require browser."
  - test: "In shock drawer, submit the same shock twice quickly (or after one is already queued on the backend). Inline error 'A shock is already queued.' appears in red below the textarea."
    expected: "409 error from /api/simulate/shock renders as inline text, not an alert or toast."
    why_human: "Error path requires actual backend 409 response during live simulation."
  - test: "With active simulation, scroll or resize the viewport. Force graph node area fills the space below the control bar with no overlap or clipping."
    expected: "Flex column layout: control bar at top, main-content fills remaining height with min-height: 0."
    why_human: "Layout integrity under different viewport sizes requires visual inspection."
---

# Phase 32: REST Controls and Simulation Control Bar — Verification Report

**Phase Goal:** REST simulation controls (start/stop/shock) and browser-side control bar with shock injection drawer
**Verified:** 2026-04-14
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | POST /api/simulate/start returns 202 immediately | VERIFIED | `simulate_start` handler returns `HTTP_202_ACCEPTED`; `test_simulate_start_202` passes |
| 2 | POST /api/simulate/stop returns 200 when running, 409 when not | VERIFIED | `simulate_stop` endpoint; `test_simulate_stop_200_and_409` passes |
| 3 | POST /api/simulate/shock returns 200 when queued, 409 when not running or already queued | VERIFIED | `simulate_shock` endpoint; `test_simulate_shock_queued_and_409` and `test_simulate_shock_concurrent_409` pass |
| 4 | SimulationManager lock releases on both success and failure | VERIFIED | `_on_task_done` calls `self._lock.release()` unconditionally before branching; `test_sim_manager_done_callback_releases_lock_on_exception` passes |
| 5 | Stop/cancel resets StateStore.phase to IDLE | VERIFIED | `_on_task_done` schedules `_reset_phase_to_idle()` via `asyncio.create_task` on cancel and exception; `test_sim_manager_cancellation_resets_phase_to_idle` passes |
| 6 | GET /api/replay/cycles returns 503 when Neo4j offline | VERIFIED | `replay_cycles` raises `HTTP_503_SERVICE_UNAVAILABLE` when `graph_manager is None`; `test_replay_cycles_503` passes |
| 7 | GET /api/replay/cycles only returns cycles with Round 3 decisions | VERIFIED | Delegates to `graph_manager.read_completed_cycles()` which filters by Round 3 presence; documented in docstring |
| 8 | POST /api/replay/start/{cycle_id} returns correct stub schema | VERIFIED | Returns `{status: "ok", cycle_id, round_num: 1}`; `test_replay_start_stub` passes |
| 9 | POST /api/replay/advance returns correct stub schema | VERIFIED | Returns `{status: "ok", round_num: 1}`; `test_replay_advance_stub` passes |
| 10 | ControlBar renders persistent top strip in all simulation states | VERIFIED (code) | ControlBar.vue exists (224 lines), uses `inject('snapshot')`, `isActive` computed toggling idle/active layouts |
| 11 | ShockDrawer is owned by ControlBar with no shock event emission to App.vue | VERIFIED | ControlBar imports ShockDrawer; App.vue contains only `<ControlBar />` with zero event bindings; no `defineEmits` on ControlBar |
| 12 | Submitting shock text calls POST /api/simulate/shock and closes on success | VERIFIED (code) | ShockDrawer.vue fetch call to `/api/simulate/shock`; on `res.ok`, emits `close` to ControlBar |
| 13 | 409 response from shock endpoint shows inline error text in the drawer | VERIFIED (code) | ShockDrawer renders `errorMessage` ref in `<p class="shock-drawer__error">` when non-empty; error strings `'A shock is already queued.'` and `'No simulation is running.'` mapped from `detail.error` |

**Score:** 13/13 truths verified (automated); 6 items requiring human browser verification

---

### Required Artifacts

| Artifact | Min Lines | Actual | Status | Key Evidence |
|----------|-----------|--------|--------|--------------|
| `src/alphaswarm/web/simulation_manager.py` | — | 161 | VERIFIED | `create_task`, `_on_task_done`, `stop()`, `inject_shock()`, `consume_shock()`, `_reset_phase_to_idle()`, manual `lock.acquire()` |
| `src/alphaswarm/web/routes/simulation.py` | — | 128 | VERIFIED | `simulate_stop`, `simulate_shock`, `SimulateStopResponse`, `SimulateShockRequest`, `SimulateShockResponse` |
| `src/alphaswarm/web/routes/replay.py` | — | 110 | VERIFIED | `replay_cycles`, `replay_start`, `replay_advance`, `CycleItem`, `ReplayCyclesResponse`, `ReplayStartResponse`, `ReplayAdvanceResponse` |
| `src/alphaswarm/web/app.py` | — | 94 | VERIFIED | `replay_router` imported and registered; `SimulationManager(app_state, brackets)` |
| `frontend/src/components/ControlBar.vue` | 80 | 224 | VERIFIED | Full idle/active state logic, `startPending` double-click guard, `phaseLabel` map, ShockDrawer child |
| `frontend/src/components/ShockDrawer.vue` | 60 | 179 | VERIFIED | Fetch to `/api/simulate/shock`, error mapping, Transition animation, discard/submit buttons |
| `frontend/src/App.vue` | — | 142 | VERIFIED | Flex column layout, `import ControlBar`, `<ControlBar />` with no event wiring, `.main-content { flex: 1; min-height: 0 }` |
| `frontend/src/assets/variables.css` | — | 81 | VERIFIED | `--control-bar-height: 48px`, `--duration-drawer-enter: 200ms`, `--duration-drawer-exit: 150ms`, `--color-accent-hover`, `--color-destructive-hover` |
| `tests/test_web.py` | — | 756 | VERIFIED | All 32 tests present and passing |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `routes/simulation.py` | `simulation_manager.py` | `sim_manager.stop()` and `sim_manager.inject_shock()` | WIRED | Lines 89-90, 112-113; both catch `NoSimulationRunningError` |
| `simulation_manager.py` | `simulation.py` | `asyncio.create_task(self._run(seed))` in `start()` | WIRED | `_run()` calls `run_simulation(...)`; lock acquired before task creation |
| `routes/replay.py` | `graph.py` | `graph_manager.read_completed_cycles()` | WIRED | Line 76 in replay.py; method exists at line 1845 in graph.py |
| `app.py` | `routes/replay.py` | `app.include_router(replay_router, prefix="/api")` | WIRED | Lines 20 and 83 in app.py |
| `ControlBar.vue` | `/api/simulate/start` | `fetch('/api/simulate/start', ...)` | WIRED | Line 65 in ControlBar.vue |
| `ControlBar.vue` | `/api/simulate/stop` | `fetch('/api/simulate/stop', ...)` | WIRED | Line 84 in ControlBar.vue |
| `ShockDrawer.vue` | `/api/simulate/shock` | `fetch('/api/simulate/shock', ...)` | WIRED | Line 23 in ShockDrawer.vue |
| `ControlBar.vue` | `ShockDrawer.vue` | `import ShockDrawer` + `<ShockDrawer :open="showDrawer" @close="closeDrawer" />` | WIRED | Lines 4 and 129 in ControlBar.vue |
| `App.vue` | `ControlBar.vue` | `import ControlBar` + `<ControlBar />` | WIRED | Lines 6 and 33 in App.vue |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|-------------------|--------|
| `ControlBar.vue` | `snapshot.value.phase` | `inject('snapshot')` from App.vue; populated by WebSocket via `useWebSocket()` | Yes — WebSocket state stream from backend StateStore | FLOWING |
| `replay_cycles` endpoint | `raw_cycles` | `graph_manager.read_completed_cycles()` — real Cypher query in graph.py | Yes — Neo4j DB query (503 guard when offline) | FLOWING |
| `replay_start` / `replay_advance` | N/A | Intentional contract stubs; return hardcoded schema | No — by design (Phase 34 fills logic) | STATIC (intentional, documented) |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All 32 backend web tests pass | `uv run pytest tests/test_web.py -x -q` | `32 passed in 0.76s` | PASS |
| Production app registers replay routes | `test_replay_routes_registered_in_production_app` | Routes `/api/replay/cycles`, `/api/replay/start/{cycle_id}`, `/api/replay/advance` confirmed | PASS |
| SC-3 edges endpoint regression | `test_edges_endpoint_regression_sc3` | Returns 503 with `graph_unavailable` error — Phase 31 endpoint still works after Phase 32 router additions | PASS |
| Lock lifecycle (manual acquire, not async-with) | grep `await self._lock.acquire` + `self._lock.release` in simulation_manager.py | Lock acquired at line 72, released only inside `_on_task_done` at line 111 — no `async with self._lock` present | PASS |
| Frontend components compile (vue-tsc) | `cd frontend && npx vue-tsc --noEmit` | Per 32-03-SUMMARY: "vue-tsc --noEmit passes clean"; pre-existing ForceGraph/useWebSocket errors from Phase 31 not introduced by Phase 32 | PASS (with note) |

---

### Requirements Coverage

The BE-* and CTL-* requirement IDs referenced in the Phase 32 plans are **phase-internal codes** defined in `32-VALIDATION.md` — they are not listed in the project-level `REQUIREMENTS.md`, which only tracks v1/v2 milestone requirements (SIM-*, INFRA-*, TUI-*, etc.). Phase 32 is part of the v5.0 web UI direction not yet reflected in the main requirements document.

| Requirement ID | Plan | Description (from VALIDATION.md) | Status | Evidence |
|---------------|------|----------------------------------|--------|----------|
| BE-05 | 32-01 | POST /api/simulate/start returns 202; SimulationManager.start() fires create_task | SATISFIED | `test_simulate_start_202`, `test_sim_manager_start_creates_task` pass |
| BE-06 | 32-01 | POST /api/simulate/stop returns 200/409 | SATISFIED | `test_simulate_stop_200_and_409` passes |
| BE-07 | 32-01 | POST /api/simulate/shock queues text; 409 guards (not running, already queued) | SATISFIED | `test_simulate_shock_queued_and_409`, `test_simulate_shock_concurrent_409` pass |
| BE-08 | 32-02 | GET /api/replay/cycles returns 503 without Neo4j | SATISFIED | `test_replay_cycles_503` passes |
| BE-09 | 32-02 | POST /api/replay/start/{cycle_id} returns stub schema | SATISFIED | `test_replay_start_stub` passes |
| BE-10 | 32-02 | POST /api/replay/advance returns stub schema | SATISFIED | `test_replay_advance_stub` passes |
| CTL-01 | 32-03, 32-04 | ControlBar renders in idle and active states; Start button disables correctly | NEEDS HUMAN | Code verified; rendering requires browser |
| CTL-02 | 32-03, 32-04 | ShockDrawer opens mid-simulation, submits, handles 409 errors inline | NEEDS HUMAN | Code verified; live simulation state requires browser |

**Orphaned requirements check:** No requirements in `REQUIREMENTS.md` map to Phase 32 — the BE-*/CTL-* namespace exists solely in phase-internal planning files. No orphaned items detected.

---

### Anti-Patterns Found

| File | Pattern | Classification | Impact |
|------|---------|---------------|--------|
| `src/alphaswarm/web/routes/replay.py` lines 90-108 | `replay_start` and `replay_advance` return fixed values (`round_num=1` always) | INFO — Intentional contract stub | Documented in plan (D-13, D-14) and SUMMARY Known Stubs table; Phase 34 fills the real logic |

No other anti-patterns found. The replay stubs are the only static returns in the Phase 32 codebase, and they are explicitly documented as intentional contract stubs for Phase 34.

---

### Human Verification Required

Phase 32 Plan 04 is a human-gated checkpoint. The automated checks all pass. The following browser interactions require human confirmation:

#### 1. Idle State Rendering

**Test:** Open the app at http://localhost:8000 (or Vite dev server). Verify the control bar is visible at the top of the page.
**Expected:** Dark strip (#1a1d27) with seed textarea and Start button (disabled when empty, enabled with text). No Stop/phase/shock buttons visible.
**Why human:** Vue component rendering and CSS class toggling require a live browser.

#### 2. Active State Rendering and Phase Label Format

**Test:** With a running simulation connected via WebSocket, inspect the control bar.
**Expected:** Seed textarea has opacity 0.5, Start is disabled. Phase label shows "Seeding...", "Round 1 / 3", "Round 2 / 3", or "Round 3 / 3" — never the raw enum string "round_1".
**Why human:** Active state driven by WebSocket snapshot; phase label map renders in the browser.

#### 3. Double-Click Prevention

**Test:** Click Start, then click again immediately before the WebSocket phase update arrives.
**Expected:** Second click is a no-op. Button shows "Starting..." and is disabled until backend transitions state.
**Why human:** Race condition between click handler and async WebSocket message requires browser interaction.

#### 4. Shock Drawer Animation and Auto-Focus

**Test:** During active simulation, click +Inject Shock.
**Expected:** Drawer slides down below the control bar (not as a modal overlay). Textarea auto-focuses. Discard closes without submitting.
**Why human:** CSS Transition animation and `textareaRef.value?.focus()` require browser.

#### 5. Shock Drawer 409 Inline Error

**Test:** Submit a shock, then submit again while the first is still queued.
**Expected:** Inline red text "A shock is already queued." appears below the textarea (not an alert or toast).
**Why human:** Requires real backend 409 response during live simulation.

#### 6. Force Graph Layout Integrity

**Test:** Inspect the viewport during an active simulation.
**Expected:** Force graph fills all space below the control bar with no overlap or clipping. Page does not scroll.
**Why human:** Flex column layout integrity under real content requires visual inspection.

---

### Gaps Summary

No gaps found in automated verification. All 32 backend tests pass, all 9 artifacts exist and are substantive, all key links are wired, data flows correctly for dynamic endpoints, and the intentional stubs (replay start/advance) are documented by design.

The `human_needed` status reflects that CTL-01 and CTL-02 (browser-rendered Vue components and interaction flows) cannot be verified programmatically — these were always designated as manual verification requirements in the VALIDATION.md. Plan 04 was already executed as a human checkpoint and recorded approval in its SUMMARY, but as that approval is a SUMMARY claim, it is flagged here for the user to confirm.

---

*Verified: 2026-04-14*
*Verifier: Claude (gsd-verifier)*
