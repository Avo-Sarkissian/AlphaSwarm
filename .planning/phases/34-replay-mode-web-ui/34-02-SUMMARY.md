---
phase: 34-replay-mode-web-ui
plan: 02
subsystem: ui
tags: [vue3, replay, modal, css-tokens, force-graph, controlbar]

# Dependency graph
requires:
  - phase: 32-rest-controls-and-simulation-control-bar
    provides: ControlBar component with idle/active template, ShockDrawer, replay route stubs
  - phase: 33-web-monitoring-panels
    provides: BracketPanel, RationaleFeed, panel-strip layout in App.vue
  - phase: 34-replay-mode-web-ui/plan-01
    provides: ReplayManager backend, /api/replay/start, /api/replay/advance, /api/replay/stop endpoints
provides:
  - CyclePicker.vue modal for selecting completed cycles
  - ControlBar replay strip with REPLAY badge, Round N/3 indicator, Next/Exit buttons
  - 4 new CSS tokens for replay mode (--color-replay, --color-replay-text, --duration-modal-enter, --duration-modal-exit)
  - ForceGraph edge-clear on replay phase transition
  - App.vue CyclePicker modal wiring
affects: [34-replay-mode-web-ui/plan-03]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Modal overlay pattern: backdrop + modal card with v-if mount in App.vue"
    - "3-way ControlBar template: idle/active/replay via v-if/v-else-if chains"
    - "CyclePicker fetch-on-open pattern (D-02): lazy loading cycle list on modal mount"

key-files:
  created:
    - frontend/src/components/CyclePicker.vue
  modified:
    - frontend/src/assets/variables.css
    - frontend/src/components/ControlBar.vue
    - frontend/src/App.vue
    - frontend/src/components/ForceGraph.vue

key-decisions:
  - "CyclePicker fetches cycles on mount (not eagerly) per D-02 for lightweight idle state"
  - "isActive computed excludes replay phase to prevent replay strip from showing active-mode controls"

patterns-established:
  - "Modal overlay: fixed backdrop with centered card, Escape/backdrop dismiss, Transition name=modal"
  - "Replay mode detection: isReplay computed from snapshot.value.phase === 'replay'"

requirements-completed: [WEB-06, REPLAY-01]

# Metrics
duration: 3min
completed: 2026-04-15
---

# Phase 34 Plan 02: Frontend Replay UI Summary

**CyclePicker modal for cycle selection and ControlBar replay strip with amber REPLAY badge, round stepping, and ForceGraph edge-clear fix**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-15T03:43:52Z
- **Completed:** 2026-04-15T03:47:20Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Created CyclePicker.vue modal with cycle list fetched from /api/replay/cycles, radio selection, loading/error/empty states, Start Replay and Close Picker buttons, backdrop click and Escape key dismiss
- Updated ControlBar.vue with 3-way template: idle (seed + Start + Replay), active (phase + Stop + Shock), and replay (REPLAY badge + Round N/3 + Next + Exit)
- Added 4 new CSS tokens to variables.css for replay mode styling
- Fixed ForceGraph edge-clear watcher to include replay phase, preventing stale edges from prior simulations
- Wired CyclePicker modal mount in App.vue with showCyclePicker ref and event handlers

## Task Commits

Each task was committed atomically:

1. **Task 1: Add CSS tokens and create CyclePicker.vue modal component** - `94c2b63` (feat)
2. **Task 2: Update ControlBar with replay strip and wire App.vue + ForceGraph** - `56ec603` (feat)

## Files Created/Modified
- `frontend/src/components/CyclePicker.vue` - Modal overlay for selecting completed simulation cycles to replay (275 lines)
- `frontend/src/assets/variables.css` - 4 new CSS tokens: --color-replay, --color-replay-text, --duration-modal-enter, --duration-modal-exit
- `frontend/src/components/ControlBar.vue` - 3-way template with replay strip (REPLAY badge, Round N/3, Next/Exit buttons), isReplay computed, advanceReplay/exitReplay functions
- `frontend/src/App.vue` - CyclePicker import, showCyclePicker ref, modal mount with v-if, ControlBar open-cycle-picker event wiring
- `frontend/src/components/ForceGraph.vue` - Edge-clear watcher updated to include 'replay' phase

## Decisions Made
None - followed plan as specified. All implementation decisions were pre-locked in CONTEXT.md (D-01 through D-06) and UI-SPEC.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Worktree soft reset left staged deletions of backend files from an intermediate commit. Detected during first commit (20 files deleted unintentionally). Fixed by restoring all files from the base commit 7b5a66b and committing the restoration as a separate fix commit (1374386). No data loss; all backend files confirmed intact.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Frontend replay UI is complete and ready for integration testing with Plan 01 backend
- Plan 03 (integration wiring and end-to-end testing) can proceed
- All copy matches UI-SPEC Copywriting Contract exactly
- All CSS tokens follow the established variables.css pattern

## Self-Check: PASSED

All created files exist, all commits verified, all modified files present.

---
*Phase: 34-replay-mode-web-ui*
*Completed: 2026-04-15*
