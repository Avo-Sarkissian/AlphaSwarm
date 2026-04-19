---
phase: 9
slug: tui-core-dashboard
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-26
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-asyncio |
| **Config file** | pyproject.toml |
| **Quick run command** | `uv run pytest tests/ -x -q` |
| **Full suite command** | `uv run pytest tests/ -v` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/ -x -q`
- **After every plan wave:** Run `uv run pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 9-01-01 | 01 | 0 | TUI-01 | unit | `uv run pytest tests/test_tui_state.py -x -q` | ❌ W0 | ⬜ pending |
| 9-01-02 | 01 | 1 | TUI-01 | unit | `uv run pytest tests/test_tui_state.py -x -q` | ❌ W0 | ⬜ pending |
| 9-02-01 | 02 | 1 | TUI-02 | unit | `uv run pytest tests/test_tui_widgets.py -x -q` | ❌ W0 | ⬜ pending |
| 9-02-02 | 02 | 1 | TUI-02 | manual | — | N/A | ⬜ pending |
| 9-03-01 | 03 | 2 | TUI-06 | unit | `uv run pytest tests/test_tui_app.py -x -q` | ❌ W0 | ⬜ pending |
| 9-03-02 | 03 | 2 | TUI-06 | manual | — | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_tui_state.py` — stubs for TUI-01 (StateStore AgentState expansion, snapshot reads)
- [ ] `tests/test_tui_widgets.py` — stubs for TUI-02 (AgentGrid/AgentCell widget rendering, 200ms diff)
- [ ] `tests/test_tui_app.py` — stubs for TUI-06 (app launch, event loop non-blocking)
- [ ] `tests/conftest.py` — shared fixtures (mock StateStore, mock simulation, test snapshots)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Visual color rendering in terminal | TUI-02 | Terminal color output not testable with pytest assertions | Launch `python -m alphaswarm tui "test rumor"`, visually verify green/red/gray cells update |
| TUI renders without blocking sim engine | TUI-06 | Requires live asyncio + Textual event loop interaction | Run full simulation, verify rounds complete while TUI updates simultaneously |
| Header status transitions correctly | TUI-01 | State machine visual transitions require live run | Observe header through full simulation cycle: Idle → Seeding → Round 1/2/3 → Complete |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
