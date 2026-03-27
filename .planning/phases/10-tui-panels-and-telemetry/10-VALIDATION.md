---
phase: 10
slug: tui-panels-and-telemetry
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-27
---

# Phase 10 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-asyncio |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest tests/ -x -q --timeout=30` |
| **Full suite command** | `uv run pytest tests/ -q --timeout=60` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/ -x -q --timeout=30`
- **After every plan wave:** Run `uv run pytest tests/ -q --timeout=60`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 10-01-01 | 01 | 0 | TUI-03 | unit | `uv run pytest tests/test_rationale_sidebar.py -x -q` | ❌ W0 | ⬜ pending |
| 10-01-02 | 01 | 1 | TUI-03 | integration | `uv run pytest tests/test_rationale_sidebar.py -x -q` | ❌ W0 | ⬜ pending |
| 10-01-03 | 01 | 2 | TUI-04 | unit | `uv run pytest tests/test_telemetry_footer.py -x -q` | ❌ W0 | ⬜ pending |
| 10-01-04 | 01 | 2 | TUI-04 | integration | `uv run pytest tests/test_telemetry_footer.py -x -q` | ❌ W0 | ⬜ pending |
| 10-01-05 | 01 | 2 | TUI-05 | unit | `uv run pytest tests/test_bracket_panel.py -x -q` | ❌ W0 | ⬜ pending |
| 10-01-06 | 01 | 3 | TUI-03,TUI-04,TUI-05 | integration | `uv run pytest tests/test_dashboard_integration.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_rationale_sidebar.py` — stubs for TUI-03 (queue drain, deque render, prepend behavior)
- [ ] `tests/test_telemetry_footer.py` — stubs for TUI-04 (psutil RAM, TPS accumulation, slot count)
- [ ] `tests/test_bracket_panel.py` — stubs for TUI-05 (per-bracket sentiment summary update)
- [ ] `tests/test_dashboard_integration.py` — integration stubs for all three panels non-blocking

*Existing test infrastructure (pytest-asyncio) covers framework requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Dashboard remains responsive during peak inference | TUI-03,TUI-04,TUI-05 | Cannot assert subjective responsiveness in unit tests | Run full simulation with 100 agents active; verify TUI renders smoothly without freezes during queue drain |
| Rationale sidebar newest-at-top scrolling | TUI-03 | Visual layout validation | Start simulation, observe rationale entries appear newest-first in sidebar |
| Telemetry footer updates every 200ms | TUI-04 | Timing validation in live TUI | Run simulation, observe footer values update ~5x per second |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
