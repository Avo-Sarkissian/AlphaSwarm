---
phase: 34
slug: replay-mode-web-ui
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-14
---

# Phase 34 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`, `asyncio_mode = "auto"`) |
| **Quick run command** | `uv run pytest tests/test_web.py -x` |
| **Full suite command** | `uv run pytest tests/test_web.py -v` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_web.py -x`
- **After every plan wave:** Run `uv run pytest tests/test_web.py -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 34-W0-01 | W0 | 0 | WEB-06/REPLAY-01 | — | N/A | unit | `uv run pytest tests/test_web.py -k "replay" -x` | ❌ W0 | ⬜ pending |
| 34-01-01 | 01 | 1 | WEB-06/REPLAY-01 | — | ReplayManager rejects duplicate start (409) | unit | `uv run pytest tests/test_web.py -k "replay_start" -x` | ❌ W0 | ⬜ pending |
| 34-01-02 | 01 | 1 | WEB-06/REPLAY-01 | — | Missing cycle returns 404 not 500 | unit | `uv run pytest tests/test_web.py -k "cycle_not_found" -x` | ❌ W0 | ⬜ pending |
| 34-01-03 | 01 | 1 | WEB-06/REPLAY-01 | — | Broadcaster uses replay snapshot when active | unit | `uv run pytest tests/test_web.py -k "broadcaster_replay" -x` | ❌ W0 | ⬜ pending |
| 34-02-01 | 02 | 1 | WEB-06/REPLAY-01 | — | Advance increments round and broadcasts | unit | `uv run pytest tests/test_web.py -k "replay_advance" -x` | ❌ W0 | ⬜ pending |
| 34-02-02 | 02 | 1 | WEB-06/REPLAY-01 | — | Stop resets phase to IDLE | unit | `uv run pytest tests/test_web.py -k "replay_stop" -x` | ❌ W0 | ⬜ pending |
| 34-02-03 | 02 | 1 | WEB-06/REPLAY-01 | — | Replay stop route registered in production app | unit | `uv run pytest tests/test_web.py -k "replay_routes" -x` | ❌ W0 | ⬜ pending |
| 34-03-01 | 03 | 2 | WEB-06/REPLAY-01 | — | N/A — frontend only | manual | Human verification in browser | N/A | ⬜ pending |
| 34-04-01 | 04 | 2 | WEB-06/REPLAY-01 | — | N/A — frontend only | manual | Human verification in browser | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Update `_make_test_app` in `tests/test_web.py` to mount `app.state.replay_manager` (currently missing — causes `AttributeError` in new endpoint handlers)
- [ ] Add `test_replay_start_real_logic` — covers `ReplayManager.start()` with mocked `graph_manager.read_full_cycle_signals`, asserts `round_num=1`
- [ ] Add `test_replay_advance_real_logic` — covers round increment, `ReplayStore.set_round()`, broadcast call
- [ ] Add `test_replay_stop_resets_phase` — mirrors `test_sim_manager_cancellation_resets_phase_to_idle`
- [ ] Add `test_replay_start_409_already_active` — concurrency guard
- [ ] Add `test_replay_start_404_cycle_not_found` — empty signals dict → 404
- [ ] Add `test_replay_stop_route_registered` — production app route presence check
- [ ] Add `test_broadcaster_uses_replay_snapshot_when_active` — confirms broadcaster switches to `replay_manager.store.snapshot()` when `is_active`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| CyclePicker modal opens and lists cycles from `GET /api/replay/cycles` | WEB-06/REPLAY-01 | Browser DOM interaction required | Open browser, click REPLAY button, verify modal with cycle list appears |
| Selecting a cycle starts replay — Round 1 nodes load in force graph with correct colors | WEB-06/REPLAY-01 | WebSocket + D3 visual render | Select a cycle, confirm force graph nodes update colors/positions from stored decisions |
| ADVANCE step transitions force graph to next round state | WEB-06/REPLAY-01 | D3 transition animation | Click ADVANCE, confirm nodes animate to round 2 state |
| Replay mode shows REPLAY banner/badge visually distinct from live simulation | WEB-06/REPLAY-01 | Visual UI state | Verify banner appears in REPLAY mode, absent in LIVE mode |
| Force graph node click → AgentSidebar works identically in replay mode | WEB-06/REPLAY-01 | Click interaction | Click a node in replay mode, confirm sidebar populates with agent details |
| ForceGraph clears edges when phase transitions to `'replay'` | WEB-06/REPLAY-01 | D3 visual state | Start replay, confirm stale live-sim edges are cleared |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
