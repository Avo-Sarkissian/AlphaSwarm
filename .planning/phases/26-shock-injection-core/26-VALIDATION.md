---
phase: 26
slug: shock-injection-core
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-10
---

# Phase 26 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio >= 0.24.0 |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` — `asyncio_mode = "auto"`, `testpaths = ["tests"]` |
| **Quick run command** | `uv run pytest tests/test_governor.py tests/test_state.py tests/test_graph.py tests/test_tui.py tests/test_simulation.py -x` |
| **Full suite command** | `uv run pytest -x` |
| **Estimated runtime** | ~15 seconds (quick), ~60 seconds (full) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_governor.py tests/test_state.py tests/test_graph.py tests/test_tui.py tests/test_simulation.py -x`
- **After every plan wave:** Run `uv run pytest -x`
- **Before `/gsd-verify-work`:** Full suite must be green + `uv run mypy src/alphaswarm/` green
- **Max feedback latency:** ~15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 26-01-01 | 01 | 0 | SHOCK-01, SHOCK-02, SHOCK-03 | — | N/A | unit stubs | `uv run pytest tests/test_governor.py tests/test_state.py tests/test_graph.py tests/test_tui.py tests/test_simulation.py -x` | ❌ W0 | ⬜ pending |
| 26-02-01 | 02 | 1 | SHOCK-02 | — | suspend() does not modify state machine or TokenPool | unit | `uv run pytest tests/test_governor.py::TestSuspendResume -x` | ❌ W0 | ⬜ pending |
| 26-02-02 | 02 | 1 | SHOCK-02 | — | suspend() blocks acquire(); resume() unblocks it | unit | `uv run pytest tests/test_governor.py::TestSuspendResume::test_suspend_blocks_acquire tests/test_governor.py::TestSuspendResume::test_resume_unblocks_acquire -x` | ❌ W0 | ⬜ pending |
| 26-03-01 | 03 | 1 | SHOCK-03 | — | shock_queue put/get roundtrip; shock_window event reflects state | unit | `uv run pytest tests/test_state.py::test_shock_queue_roundtrip tests/test_state.py::test_shock_window_event_reflects_state -x` | ❌ W0 | ⬜ pending |
| 26-04-01 | 04 | 1 | SHOCK-03 | — | write_shock_event creates ShockEvent node and HAS_SHOCK edge | unit | `uv run pytest tests/test_graph.py::test_write_shock_event_creates_node_and_edge tests/test_graph.py::test_write_shock_event_returns_uuid -x` | ❌ W0 | ⬜ pending |
| 26-04-02 | 04 | 1 | SHOCK-03 | — | write_shock_event wraps Neo4jError; ensure_schema includes shock index | unit | `uv run pytest tests/test_graph.py::test_write_shock_event_wraps_driver_errors tests/test_graph.py::test_ensure_schema_includes_shock_cycle_index -x` | ❌ W0 | ⬜ pending |
| 26-05-01 | 05 | 2 | SHOCK-01 | — | ShockInputScreen Enter dismisses with text; Esc dismisses with None | unit | `uv run pytest tests/test_tui.py::test_shock_input_screen_enter_dismisses_with_text tests/test_tui.py::test_shock_input_screen_esc_dismisses_with_none -x` | ❌ W0 | ⬜ pending |
| 26-05-02 | 05 | 2 | SHOCK-01 | — | _poll_snapshot pushes ShockInputScreen exactly once per window (edge-latch) | unit | `uv run pytest tests/test_tui.py::test_poll_snapshot_pushes_shock_screen_on_window_open tests/test_tui.py::test_shock_screen_pushed_once_per_window -x` | ❌ W0 | ⬜ pending |
| 26-06-01 | 06 | 2 | SHOCK-02 | — | run_simulation passes [BREAKING] prefix to Round 2 when shock submitted | unit | `uv run pytest tests/test_simulation.py::test_shock_injected_into_round2_user_message tests/test_simulation.py::test_round2_unchanged_when_no_shock -x` | ❌ W0 | ⬜ pending |
| 26-06-02 | 06 | 2 | SHOCK-02 | — | shock does not mutate base rumor; no-state_store path skips window | unit | `uv run pytest tests/test_simulation.py::test_shock_does_not_mutate_base_rumor tests/test_simulation.py::test_run_simulation_without_state_store_skips_shock -x` | ❌ W0 | ⬜ pending |
| 26-07-01 | 07 | 3 | SHOCK-01, SHOCK-02, SHOCK-03 | — | end-to-end: TUI submit → simulation reads queue → round 2 dispatch → Neo4j write | integration | `uv run pytest tests/test_simulation.py::test_end_to_end_shock_round2 -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_governor.py` — new `TestSuspendResume` class with 4 test stubs: `test_suspend_blocks_acquire`, `test_resume_unblocks_acquire`, `test_suspend_does_not_touch_state_machine`, `test_monitor_loop_continues_during_suspend`
- [ ] `tests/test_state.py` — 2 test stubs: `test_shock_queue_roundtrip`, `test_shock_window_event_reflects_state`
- [ ] `tests/test_graph.py` — 4 test stubs: `test_write_shock_event_creates_node_and_edge`, `test_write_shock_event_returns_uuid`, `test_write_shock_event_wraps_driver_errors`, `test_ensure_schema_includes_shock_cycle_index`
- [ ] `tests/test_tui.py` — 5 test stubs via `Pilot` + fake StateStore fixture: `test_shock_input_screen_enter_dismisses_with_text`, `test_shock_input_screen_esc_dismisses_with_none`, `test_poll_snapshot_pushes_shock_screen_on_window_open`, `test_shock_screen_pushed_once_per_window`
- [ ] `tests/test_simulation.py` — 6 test stubs: `test_shock_injected_into_round2_user_message`, `test_round2_unchanged_when_no_shock`, `test_run_simulation_without_state_store_skips_shock`, `test_shock_does_not_mutate_base_rumor`, `test_end_to_end_shock_round2`
- [ ] `tests/conftest.py` — `mock_state_store` fixture (if not already present)
- [ ] No new framework install required — pytest, pytest-asyncio, and textual.run_test already in use

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| ShockInputScreen appears in TUI between rounds during a live simulation run | SHOCK-01 | Requires full live Ollama + Neo4j + TUI process; Pilot tests cover widget logic but not live integration | Run `uv run python -m alphaswarm.main` with a multi-round scenario; confirm modal appears between Round 1 and Round 2 |
| Notification "Shock registered" appears in TUI after submission | SHOCK-01 | Textual `notify()` requires running app context; covered by Pilot test but verify visually once | Same as above — observe the notification bar after submitting text |
| Governor stays in RUNNING state during inter-round shock pause | SHOCK-02 | Requires live governor monitoring loop; automated test covers unit behavior | Run live simulation, observe TUI status panel shows RUNNING (not THROTTLED/PAUSED) during shock window |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
