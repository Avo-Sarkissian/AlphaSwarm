---
phase: 28-simulation-replay
plan: 03
subsystem: verification
tags: [verification, tui, replay, performance, human-approved]

# Dependency graph
requires:
  - phase: 28-simulation-replay
    plan: 28-02
    provides: TUI replay mode, CLI replay subcommand
provides:
  - Human verification of TUI replay visual correctness
  - Human verification of replay interactive controls
  - Human verification of Cypher performance criterion
  - Human verification of exit behavior differentiation (CLI vs in-app)
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns: []
  removed: []

# Self-Check
self_check: PASSED

---

## Summary

Human verification checkpoint for Phase 28 simulation replay. All 7 manual test scenarios approved.

## What was verified

**Task 1 (auto): Performance instrumentation**
- `read_full_cycle_signals` contains `time.perf_counter()` at line 1752 and `duration_ms` structlog logging at line 1768
- Instrumentation logs `cycle_id`, `count`, and `duration_ms` at debug level via structlog

**Task 2 (human-verify): TUI replay interactive behavior**
Human approved all 7 test scenarios:
1. CLI replay entry — amber "REPLAY — Cycle {id}" header badge, `duration_ms < 2000` in structlog
2. Auto-advance timer — rounds step at ~3s intervals, rationale sidebar no duplicates, "[DONE]" after Round 3
3. Manual mode — P key toggles [AUTO]/[PAUSED], Space/Right advance single round
4. CLI replay exit — Esc exits app entirely (returns to terminal)
5. In-app replay exit — Esc restores COMPLETE state, grid shows final simulation state
6. Blocked interactions — agent click shows "Interviews unavailable during replay", save blocked, shock injection blocked
7. CyclePickerScreen — picker overlay appears for multiple cycles, Up/Down/Enter/Esc work correctly

## Issues

None.

## Key files verified
- `src/alphaswarm/tui.py` — replay mode visual and interactive behavior
- `src/alphaswarm/graph.py` — `read_full_cycle_signals` duration_ms < 2000ms
- `src/alphaswarm/cli.py` — `alphaswarm replay` subcommand exit behavior
