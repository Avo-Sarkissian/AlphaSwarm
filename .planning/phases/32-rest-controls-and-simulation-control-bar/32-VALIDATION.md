---
phase: 32
slug: rest-controls-and-simulation-control-bar
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-14
---

# Phase 32 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.0+ with pytest-asyncio 0.24+ |
| **Config file** | `pyproject.toml` [tool.pytest.ini_options] asyncio_mode = "auto" |
| **Quick run command** | `uv run pytest tests/test_web.py -x` |
| **Full suite command** | `uv run pytest tests/ -x` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_web.py -x`
- **After every plan wave:** Run `uv run pytest tests/ -x`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 32-W0-01 | W0 | 0 | BE-05 | — | N/A | unit | `uv run pytest tests/test_web.py::test_simulate_start_202 -x` | ❌ W0 | ⬜ pending |
| 32-W0-02 | W0 | 0 | BE-05 | — | N/A | unit | `uv run pytest tests/test_web.py::test_sim_manager_creates_task -x` | ❌ W0 | ⬜ pending |
| 32-W0-03 | W0 | 0 | BE-06 | — | N/A | unit | `uv run pytest tests/test_web.py::test_simulate_stop_200_and_409 -x` | ❌ W0 | ⬜ pending |
| 32-W0-04 | W0 | 0 | BE-07 | — | 409 on concurrent shock | unit | `uv run pytest tests/test_web.py::test_simulate_shock_queued_and_409 -x` | ❌ W0 | ⬜ pending |
| 32-W0-05 | W0 | 0 | BE-07 | — | 409 on double pending shock | unit | `uv run pytest tests/test_web.py::test_simulate_shock_concurrent_409 -x` | ❌ W0 | ⬜ pending |
| 32-W0-06 | W0 | 0 | BE-08 | — | 503 without Neo4j | unit | `uv run pytest tests/test_web.py::test_replay_cycles_503 -x` | ❌ W0 | ⬜ pending |
| 32-W0-07 | W0 | 0 | BE-09 | — | N/A | unit | `uv run pytest tests/test_web.py::test_replay_start_stub -x` | ❌ W0 | ⬜ pending |
| 32-W0-08 | W0 | 0 | BE-10 | — | N/A | unit | `uv run pytest tests/test_web.py::test_replay_advance_stub -x` | ❌ W0 | ⬜ pending |
| 32-xx-01 | TBD | 1+ | CTL-01 | — | N/A | manual | N/A | N/A | ⬜ pending |
| 32-xx-02 | TBD | 1+ | CTL-02 | — | N/A | manual | N/A | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_web.py` — extend with tests for stop, shock, replay endpoints (file exists, add new test functions)
- [ ] `tests/test_web.py` — add `test_sim_manager_creates_task` for SimulationManager task creation
- [ ] `tests/test_web.py` — `_make_test_app()` helper must register `replay_router` when created

*Existing infrastructure (pytest-asyncio, test_web.py helpers) covers framework setup — only new test stubs needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| ControlBar renders, Start button disables while simulation active | CTL-01 | Vue component rendering requires browser | Load app, submit seed rumor, verify Start disabled while running |
| ShockDrawer opens mid-simulation, submit shows confirmation; second submit shows 409 error | CTL-02 | Requires live simulation state in browser | Start simulation, open shock drawer, submit twice rapidly |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
