---
phase: 19
slug: per-stock-tui-consensus-display
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-07
---

# Phase 19 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `uv run pytest tests/test_tui.py -k "ticker_consensus" -x -q` |
| **Full suite command** | `uv run pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_tui.py -k "ticker_consensus" -x -q`
- **After every plan wave:** Run `uv run pytest tests/ -x -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 19-01-01 | 01 | 1 | DTUI-02 | — | N/A | unit | `uv run pytest tests/test_tui.py::test_ticker_consensus_panel_render_header_both_signals -xvs` | ✅ | ✅ green |
| 19-01-02 | 01 | 1 | DTUI-02 | — | N/A | unit | `uv run pytest tests/test_tui.py::test_ticker_consensus_panel_render_header_agree -xvs` | ✅ | ✅ green |
| 19-01-03 | 01 | 1 | DTUI-02 | — | N/A | unit | `uv run pytest tests/test_tui.py::test_ticker_consensus_panel_empty_state_idle -xvs` | ✅ | ✅ green |
| 19-02-01 | 02 | 1 | DTUI-01 | — | N/A | unit | `uv run pytest tests/test_tui.py::test_ticker_consensus_panel_title -xvs` | ✅ | ✅ green |
| 19-02-02 | 02 | 2 | DTUI-01 | — | N/A | unit | `uv run pytest tests/test_tui.py::test_ticker_consensus_panel_multiple_tickers -xvs` | ✅ | ✅ green |
| 19-03-01 | 03 | 2 | DTUI-03 | — | N/A | unit | `uv run pytest tests/test_tui.py::test_ticker_consensus_panel_render_bracket_bars -xvs` | ✅ | ✅ green |
| 19-03-02 | 03 | 2 | DTUI-01,DTUI-03 | — | N/A | unit | `uv run pytest tests/test_tui.py::test_ticker_consensus_panel_majority_pct_display -xvs` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_tui.py` — test methods for DTUI-01, DTUI-02, DTUI-03 (test_ticker_consensus_panel_* methods)

*Existing pytest + pytest-asyncio infrastructure already covers framework needs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| TUI panel visible and scrollable in live terminal | DTUI-01 | Textual visual rendering cannot be asserted in headless pytest | Run `uv run python -m alpha_swarm.main` with a test seed, observe consensus panel appears and scrolls |
| Bracket disagreement rows visually distinct | DTUI-03 | Color/style assertions require Textual snapshot testing not yet configured | Visually inspect that BUY brackets appear in green, SELL in red, HOLD in yellow |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved
