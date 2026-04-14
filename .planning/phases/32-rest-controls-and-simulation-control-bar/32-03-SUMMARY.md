---
phase: 32-rest-controls-and-simulation-control-bar
plan: 03
subsystem: ui
tags: [vue3, control-bar, shock-drawer, rest-wiring, flex-layout, css-tokens]

# Dependency graph
requires:
  - phase: 32-01
    provides: POST /api/simulate/start, POST /api/simulate/stop, POST /api/simulate/shock endpoints
  - phase: 32-02
    provides: Replay endpoints registered in app.py
  - phase: 31-vue-spa-and-force-directed-graph
    provides: App.vue with provide/inject, ForceGraph, AgentSidebar, variables.css tokens, types.ts
provides:
  - ControlBar.vue persistent top strip with idle/active states and double-click prevention
  - ShockDrawer.vue slide-down panel with inline 409 error display
  - Flex column App.vue layout with ControlBar above main content
  - New CSS design tokens for control bar height, drawer animation, hover states
affects: [32-04, 33-monitoring-panels, 34-replay-mode-web-ui]

# Tech tracking
tech-stack:
  added: []
  patterns: [control-bar-owns-drawer, double-click-prevention-via-pending-ref, phase-label-formatting-map]

key-files:
  created:
    - frontend/src/components/ControlBar.vue
    - frontend/src/components/ShockDrawer.vue
  modified:
    - frontend/src/App.vue
    - frontend/src/assets/variables.css

key-decisions:
  - "ControlBar fully owns ShockDrawer as direct child -- no shock event emission to App.vue (review concern #3)"
  - "Double-click prevention via startPending ref cleared by WebSocket phase watcher, not fetch response (review concern #6)"
  - "Phase labels mapped from raw enum to human-readable format like 'Round 2 / 3' (review concern #7)"
  - "isIdle includes 'complete' state so empty-state shows after simulation ends (user can start new sim)"

patterns-established:
  - "Drawer ownership: ControlBar manages showDrawer ref internally, ShockDrawer receives :open prop and emits @close"
  - "Double-click guard: startPending ref set on click, cleared by watch on snapshot.phase change (not fetch callback)"
  - "Phase label map: Record<string, string> maps raw enum values to formatted display text"
  - "Flex column layout: app-root flex column, main-content flex:1 with min-height:0 for correct graph sizing"

requirements-completed: [CTL-01, CTL-02]

# Metrics
duration: 3min
completed: 2026-04-14
---

# Phase 32 Plan 03: Control Bar and Shock Drawer Summary

**Vue ControlBar with idle/active states, double-click prevention, ShockDrawer slide-down panel with 409 error handling, and flex column App.vue layout**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-14T14:54:12Z
- **Completed:** 2026-04-14T14:58:01Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- ControlBar.vue renders persistent top strip with seed textarea + Start (idle) and Stop + phase label + Inject Shock (active)
- ShockDrawer.vue slides down below control bar, POSTs to /api/simulate/shock, displays inline 409 errors
- App.vue restructured to flex column layout with ControlBar at top and main-content filling remaining space
- Double-click prevention on Start button via startPending ref cleared by WebSocket phase change watcher
- Phase labels formatted as "Round 2 / 3", "Seeding...", "Complete" instead of raw enum strings

## Task Commits

Each task was committed atomically:

1. **Task 1: Add design tokens and create ControlBar.vue** - `8af1f68` (feat)
2. **Task 2: Create ShockDrawer.vue and restructure App.vue** - `4e88e1e` (feat)

## Files Created/Modified
- `frontend/src/components/ControlBar.vue` - Persistent top strip: idle state (seed textarea + Start), active state (Stop + phase label + Inject Shock), owns ShockDrawer as child
- `frontend/src/components/ShockDrawer.vue` - Slide-down panel: textarea, Submit (POST /api/simulate/shock), Discard, inline 409 error messages
- `frontend/src/App.vue` - Flex column layout with ControlBar above main-content, isIdle includes 'complete' state
- `frontend/src/assets/variables.css` - Added --control-bar-height, --duration-drawer-enter/exit, --color-accent-hover, --color-destructive-hover

## Decisions Made
- ControlBar fully owns ShockDrawer as a direct child component. No `defineEmits` on ControlBar, no shock event wiring in App.vue. This addresses review concern #3 about drawer ownership.
- startPending ref is cleared by watching `snapshot.value.phase` change away from idle (via WebSocket), not by the fetch response callback. This ensures the button stays disabled until the backend actually transitions state, preventing double-clicks even if the fetch returns before the WebSocket update.
- Phase labels use a `Record<string, string>` map to convert raw enum values like `round_2` to formatted display text like `Round 2 / 3`. Fallback shows the raw phase string for unknown values.
- isIdle computed now includes `complete` state in addition to `idle`, so the empty-state message shows after simulation completes (allowing user to start a new simulation).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## Known Stubs

None - all components are fully wired to REST endpoints with real error handling.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Control bar and shock drawer are fully functional and wired to backend endpoints from Plans 01-02
- Ready for Phase 32-04: integration verification across all Phase 32 components
- Ready for Phase 33: monitoring panels can be added below control bar in the main-content area
- Ready for Phase 34: replay mode UI can reuse the control bar state management pattern

## Self-Check: PASSED

- FOUND: frontend/src/components/ControlBar.vue (224 lines, min 80)
- FOUND: frontend/src/components/ShockDrawer.vue (179 lines, min 60)
- FOUND: frontend/src/App.vue (contains ControlBar import and flex column layout)
- FOUND: frontend/src/assets/variables.css (contains --control-bar-height: 48px)
- FOUND: commit 8af1f68 (Task 1)
- FOUND: commit 4e88e1e (Task 2)
- vue-tsc --noEmit passes clean

---
*Phase: 32-rest-controls-and-simulation-control-bar*
*Completed: 2026-04-14*
