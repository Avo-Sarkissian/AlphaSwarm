---
phase: 19
slug: per-stock-tui-consensus-display
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-07
---

# Phase 19 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-asyncio |
| **Config file** | pytest.ini / pyproject.toml |
| **Quick run command** | `uv run pytest tests/ -x -q` |
| **Full suite command** | `uv run pytest tests/ -v` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/ -x -q`
- **After every plan wave:** Run `uv run pytest tests/ -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 19-01-01 | 01 | 1 | DTUI-02 | — | N/A | unit | `uv run pytest tests/test_consensus.py::test_compute_ticker_consensus -xvs` | ❌ W0 | ⬜ pending |
| 19-01-02 | 01 | 1 | DTUI-02 | — | N/A | unit | `uv run pytest tests/test_consensus.py::test_weighted_vs_majority -xvs` | ❌ W0 | ⬜ pending |
| 19-01-03 | 01 | 1 | DTUI-02 | — | N/A | unit | `uv run pytest tests/test_consensus.py::test_division_by_zero_guard -xvs` | ❌ W0 | ⬜ pending |
| 19-02-01 | 02 | 1 | DTUI-01 | — | N/A | unit | `uv run pytest tests/test_tui.py::test_ticker_consensus_panel_render -xvs` | ❌ W0 | ⬜ pending |
| 19-02-02 | 02 | 2 | DTUI-01 | — | N/A | integration | `uv run pytest tests/test_tui.py::test_ticker_consensus_panel_scroll -xvs` | ❌ W0 | ⬜ pending |
| 19-03-01 | 03 | 2 | DTUI-03 | — | N/A | unit | `uv run pytest tests/test_tui.py::test_bracket_disagreement_display -xvs` | ❌ W0 | ⬜ pending |
| 19-03-02 | 03 | 2 | DTUI-01,DTUI-03 | — | N/A | integration | `uv run pytest tests/test_simulation.py::test_consensus_wired_end_to_end -xvs` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_consensus.py` — stubs for DTUI-02 (compute_ticker_consensus unit tests)
- [ ] `tests/test_tui.py` — stubs for DTUI-01, DTUI-03 (TickerConsensusPanel render/scroll/bracket tests)
- [ ] `tests/test_simulation.py` — stubs for end-to-end wiring test

*Existing pytest + pytest-asyncio infrastructure already covers framework needs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| TUI panel visible and scrollable in live terminal | DTUI-01 | Textual visual rendering cannot be asserted in headless pytest | Run `uv run python -m alpha_swarm.main` with a test seed, observe consensus panel appears and scrolls |
| Bracket disagreement rows visually distinct | DTUI-03 | Color/style assertions require Textual snapshot testing not yet configured | Visually inspect that BUY brackets appear in green, SELL in red, HOLD in yellow |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
