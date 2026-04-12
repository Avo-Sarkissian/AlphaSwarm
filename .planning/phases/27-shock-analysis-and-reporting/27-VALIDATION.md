---
phase: 27
slug: shock-analysis-and-reporting
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-11
---

# Phase 27 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (asyncio mode) |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest tests/test_graph.py tests/test_tui.py tests/test_report.py tests/test_cli.py -q --tb=short` |
| **Full suite command** | `uv run pytest -q --tb=short` |
| **Estimated runtime** | ~8 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_graph.py tests/test_tui.py tests/test_report.py tests/test_cli.py -q --tb=short`
- **After every plan wave:** Run `uv run pytest -q --tb=short`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 27-00-01 | 00 | 0 | SHOCK-04 | — | N/A | unit stub | `uv run pytest tests/test_graph.py -q --tb=short` | ❌ W0 | ⬜ pending |
| 27-00-02 | 00 | 0 | SHOCK-05 | — | N/A | unit stub | `uv run pytest tests/test_report.py tests/test_cli.py -q --tb=short` | ❌ W0 | ⬜ pending |
| 27-00-03 | 00 | 0 | SHOCK-04 | — | N/A | unit stub | `uv run pytest tests/test_tui.py -q --tb=short` | ❌ W0 | ⬜ pending |
| 27-01-01 | 01 | 1 | SHOCK-04 | — | N/A | unit | `uv run pytest tests/test_graph.py -k shock -q --tb=short` | ✅ | ⬜ pending |
| 27-01-02 | 01 | 1 | SHOCK-04 | — | N/A | unit | `uv run pytest tests/test_tui.py -k delta -q --tb=short` | ✅ | ⬜ pending |
| 27-02-01 | 02 | 2 | SHOCK-05 | — | N/A | unit | `uv run pytest tests/test_report.py -k shock -q --tb=short` | ✅ | ⬜ pending |
| 27-02-02 | 02 | 2 | SHOCK-05 | — | N/A | unit | `uv run pytest tests/test_cli.py -k shock -q --tb=short` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_graph.py` — stubs for `read_shock_event`, `read_shock_impact` (SHOCK-04)
- [ ] `tests/test_tui.py` — stubs for `BracketPanel` delta mode (SHOCK-04)
- [ ] `tests/test_report.py` — stubs for shock impact Jinja2 section (SHOCK-05)
- [ ] `tests/test_cli.py` — stubs for pre-seeded shock_impact observation (SHOCK-05)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| TUI delta mode visually shows bracket shift colors | SHOCK-04 | Terminal rendering cannot be verified in headless pytest | Run `uv run python -m alphaswarm run` with shock injected; verify BracketPanel shows ▲/▼ delta indicators |
| HTML report shock section renders correctly in browser | SHOCK-05 | Browser rendering not testable in pytest | Open exported HTML; verify shock_impact section shows pivot table and bracket shift aggregations |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
