---
phase: 28-simulation-replay
plan: 02
subsystem: cli, tui, state
tags: [textual, asyncio, replay, cli, argparse, timer, overlay, screen]

# Dependency graph
requires:
  - phase: 28-simulation-replay
    plan: 01
    provides: SimulationPhase.REPLAY, ReplayStore, GraphStateManager replay read methods
  - phase: 10-tui-panels-and-telemetry
    provides: AlphaSwarmApp, HeaderBar, TelemetryFooter, BracketPanel, RationaleSidebar, StateStore
provides:
  - CLI alphaswarm replay --cycle <id> subcommand with _handle_replay handler
  - CyclePickerScreen overlay (OptionList-based, Up/Down/Enter/Esc navigation)
  - AlphaSwarmApp replay mode: _enter_replay, _load_replay_round_data, _advance_replay_round
  - HeaderBar.render_replay_header (amber REPLAY badge, round/mode display)
  - TelemetryFooter.render_replay_footer (key hints: Space/Right/P/Esc)
  - Replay key bindings: r (start), p (toggle), space/right (next round), escape (exit)
  - _poll_snapshot ReplayStore branch with sidebar dedup (Review #2)
  - All 12 locked decisions (D-01 through D-12) implemented
affects: [28-simulation-replay-plan-03]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CLI replay handler is synchronous (like _handle_tui) not async — Textual owns the event loop"
    - "ReplayStore set BEFORE any phase change to prevent _poll_snapshot race (RESEARCH Pitfall 3)"
    - "Sidebar dedup: _replay_last_rendered_round tracks rendered round; sidebar cleared+rebuilt on round change only"
    - "Stale load guard: round_num != self._replay_round checked after each await in _load_replay_round_data (Review #11)"
    - "CLI vs in-app exit: replay_cli_mode flag drives self.exit() vs StateStore restore (Review #3)"
    - "Escape handled via key_escape override not BINDINGS — avoids conflict with Screen escape bindings"
    - "Auto-advance timer stopped before _replay_store cleared (Pitfall 2 mitigation)"
    - "read_completed_cycles(limit=1) used in _handle_replay, NOT read_latest_cycle_id() (Review #4)"

key-files:
  created:
    - .planning/phases/28-simulation-replay/28-02-SUMMARY.md
  modified:
    - src/alphaswarm/cli.py
    - src/alphaswarm/tui.py

key-decisions:
  - "key_escape override instead of BINDINGS entry for escape: avoids Textual BINDINGS conflict with Screen overlays (RumorInputScreen, InterviewScreen already handle escape via BINDINGS)"
  - "_poll_snapshot sentinel+delta-mode checks guarded by replay_store is None: prevents unnecessary file I/O and state transitions during replay"
  - "No shock gate needed: action_open_shock_window does not exist in this worktrees tui.py (Phase 26 shock methods absent from worktree base commit)"

# Metrics
duration: 9min
completed: 2026-04-12
---

# Phase 28 Plan 02: CLI + TUI Replay Wiring Summary

**CLI alphaswarm replay subcommand + full TUI replay mode: CyclePickerScreen overlay, r/p/space/right/escape bindings, 3s auto-advance timer, sidebar dedup, stale-load guard, CLI vs in-app exit differentiation**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-04-12T20:19:30Z
- **Completed:** 2026-04-12T20:28:45Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

### Task 1: CLI replay subcommand

- Added `_handle_replay(cycle_id: str | None) -> None` synchronous handler after `_handle_report` in `cli.py`
- Handler creates `AppState` with `with_ollama=False` (no inference needed for replay)
- Resolves default cycle via `gm.read_completed_cycles(limit=1)` — NOT `read_latest_cycle_id()` — ensuring only completed cycles (with Round 3 data) are selected (Review #4)
- Sets `tui_app.replay_cycle_id` and `tui_app.replay_cli_mode = True` before `.run()` (Review #3)
- Wraps `tui_app.run()` in `try/finally` block to guarantee `gm.close()` on any exit path (Review #12)
- Added `replay_parser = subparsers.add_parser("replay", ...)` with `--cycle` arg
- Added `elif args.command == "replay":` dispatch block in `main()`

### Task 2: TUI replay mode

- **Imports**: Added `Timer`, `OptionList`, `Option` from textual; `ReplayStore` from `alphaswarm.state`
- **CyclePickerScreen**: New `Screen[str | None]` overlay with `OptionList` for cycle selection — formatted as `{date} -- {short_id}  (latest)`, dismiss returns full cycle_id
- **HeaderBar.render_replay_header**: Amber `REPLAY -- Cycle {id}` badge with Round X/3 and `[AUTO]`/`[PAUSED]`/`[DONE]` mode indicator
- **TelemetryFooter.render_replay_footer**: Replay-specific footer with Space/Right/P/Esc key hints
- **AgentCell.on_click gate**: Explicit replay check with `"Interviews unavailable during replay"` notification (Review #8)
- **AlphaSwarmApp BINDINGS**: Added `r`/`p`/`space`/`right` bindings; escape handled via `key_escape` override
- **Replay instance vars**: `replay_cycle_id`, `replay_cli_mode`, `_replay_store`, `_replay_timer`, `_replay_round`, `_replay_auto`, `_replay_done`, `_replay_cycle_short_id`, `_replay_last_rendered_round`
- **on_mount**: Detects `self.replay_cycle_id is not None` → starts poll interval + enters replay directly (CLI mode)
- **action_save_results gate**: `"Save unavailable during replay"` notification guard at top
- **_enter_replay**: Loads `read_full_cycle_signals`, creates `ReplayStore`, sets round 1, loads on-demand data, starts 3s timer. Store set BEFORE any phase change (Pitfall 3)
- **_load_replay_round_data**: Loads bracket narratives and rationale entries per-round. Double stale-load guard (`round_num != self._replay_round`) after each await (Review #11)
- **_advance_replay_round**: Timer callback advancing round 1→2→3, stops timer at Round 3 with `[DONE]` notification
- **action_start_replay**: COMPLETE-phase gate → `_start_replay_picker` worker
- **_start_replay_picker**: Uses `read_completed_cycles(limit=10)` — auto-selects if single cycle, else shows `CyclePickerScreen` (Review #4)
- **action_toggle_replay_mode**: Pauses/resumes timer, toggles `_replay_auto`, notifies mode
- **action_replay_next_round**: Manual-mode only gate, calls `_advance_replay_round`
- **action_exit_replay**: Stops timer first (Pitfall 2), clears all replay state, then: CLI mode → `self.exit()`; in-app mode → clears sidebar + calls `_bracket_panel.reset_delta_mode()` (Review #3)
- **key_escape override**: Exits replay if `_replay_store is not None`, no-op otherwise
- **_poll_snapshot replay branch**: Reads `_replay_store.snapshot()` instead of `state_store.snapshot()`. Sidebar dedup: clears and rebuilds only when `_replay_round != _replay_last_rendered_round` (Review #2). Replay header/footer rendered every tick. Sentinel file check and delta-mode check skipped during replay.

## Task Commits

1. **Task 1: CLI replay subcommand** - `6894c3c` (feat)
2. **Task 2: TUI replay mode** - `4881452` (feat)

## Files Created/Modified

- `src/alphaswarm/cli.py` - Added `_handle_replay()`, `replay_parser`, `elif args.command == "replay"` dispatch
- `src/alphaswarm/tui.py` - Added `CyclePickerScreen`, replay action methods, `render_replay_header`, `render_replay_footer`, updated `_poll_snapshot`, `AgentCell.on_click`, `action_save_results`

## Decisions Made

- **key_escape override vs BINDINGS**: Escape added as `key_escape()` method override rather than a BINDINGS entry. `RumorInputScreen` and `InterviewScreen` both define `("escape", ...)` in their own BINDINGS — adding escape to the App-level BINDINGS would conflict. The override approach lets replay intercept escape only when `_replay_store is not None`.
- **_poll_snapshot sentinel/delta guards**: The Phase 15 sentinel file check and Phase 27 delta-mode check are both wrapped in `if self._replay_store is None:` — avoids unnecessary file I/O and prevents `_check_bracket_delta_mode` from mis-firing during a replay session.
- **No shock gate implemented**: `action_open_shock_window` does not exist in this worktree's `tui.py` baseline (Phase 26 shock methods are in the main repo's later commits, not present at the ba53aeb base). No gate needed for methods that don't exist.

## Deviations from Plan

### Auto-fixed Issues

None.

### Scope Adjustments

**1. [Rule 1 - No shock gate needed] action_open_shock_window absent from worktree**

- **Found during:** Task 2, Part H
- **Issue:** Plan instructs gating `action_open_shock_window` with `_replay_store is not None`. This method does not exist in the `tui.py` at the ba53aeb base commit (Phase 26 shock code is not present in this worktree).
- **Resolution:** No gate added — method doesn't exist. Documented in decisions.
- **Impact:** None — replay cannot trigger shock injection because the method is absent.

## Known Stubs

None. All replay logic is fully implemented and connected to the data layer (Plan 01 ReplayStore + graph read methods). No placeholder values, TODO markers, or hardcoded empty returns.

## Test Results

- 531 tests pass (excludes pre-existing failures: `test_report.py` 19 failures, `test_graph_integration.py` 1 error requiring live Neo4j)
- Zero regressions introduced
- All Plan 01 baseline tests (100) still pass

## Self-Check: PASSED

- `src/alphaswarm/cli.py` — contains `def _handle_replay`, `replay_parser`, `elif args.command == "replay"`
- `src/alphaswarm/tui.py` — contains all 12 replay methods/classes verified
- Commit `6894c3c` exists: `feat(28-02): add CLI replay subcommand and _handle_replay handler`
- Commit `4881452` exists: `feat(28-02): implement TUI replay mode — CyclePickerScreen, bindings, auto-advance, guards`

---
*Phase: 28-simulation-replay*
*Completed: 2026-04-12*
