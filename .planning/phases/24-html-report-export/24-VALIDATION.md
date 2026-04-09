---
phase: 24
slug: html-report-export
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-09
---

# Phase 24 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.0+ with pytest-asyncio 0.24.0+ |
| **Config file** | `pyproject.toml` ([tool.pytest.ini_options]) |
| **Quick run command** | `uv run pytest tests/test_report.py -x -q` |
| **Full suite command** | `uv run pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_report.py -x -q`
- **After every plan wave:** Run `uv run pytest tests/ -x -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 24-01-01 | 01 | 1 | EXPORT-01 | — | N/A | unit | `uv run pytest tests/test_report.py::TestHtmlAssembler -x` | ❌ W0 | ⬜ pending |
| 24-01-02 | 01 | 1 | EXPORT-01 | — | N/A | unit | `uv run pytest tests/test_report.py::TestHtmlSelfContained -x` | ❌ W0 | ⬜ pending |
| 24-01-03 | 01 | 1 | EXPORT-01 | — | N/A | unit | `uv run pytest tests/test_report.py::TestHtmlFileSize -x` | ❌ W0 | ⬜ pending |
| 24-01-04 | 01 | 1 | EXPORT-02 | — | N/A | unit | `uv run pytest tests/test_report.py::TestChartRenderers::test_consensus_bar -x` | ❌ W0 | ⬜ pending |
| 24-01-05 | 01 | 1 | EXPORT-02 | — | N/A | unit | `uv run pytest tests/test_report.py::TestChartRenderers::test_round_timeline -x` | ❌ W0 | ⬜ pending |
| 24-01-06 | 01 | 1 | EXPORT-02 | — | N/A | unit | `uv run pytest tests/test_report.py::TestChartRenderers::test_bracket_charts -x` | ❌ W0 | ⬜ pending |
| 24-01-07 | 01 | 1 | EXPORT-02 | — | N/A | unit | `uv run pytest tests/test_report.py::TestChartRenderers::test_ticker_mini_charts -x` | ❌ W0 | ⬜ pending |
| 24-01-08 | 01 | 1 | EXPORT-03 | — | N/A | unit | `uv run pytest tests/test_report.py::TestChartStyle -x` | ❌ W0 | ⬜ pending |
| 24-01-09 | 01 | 1 | EXPORT-03 | — | N/A | unit | `uv run pytest tests/test_report.py::TestHtmlDarkTheme -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_report.py::TestChartRenderers` — covers EXPORT-02 (chart generation functions)
- [ ] `tests/test_report.py::TestHtmlAssembler` — covers EXPORT-01 (assemble_html method)
- [ ] `tests/test_report.py::TestHtmlSelfContained` — covers EXPORT-01 (no external references)
- [ ] `tests/test_report.py::TestHtmlFileSize` — covers EXPORT-01 (under 1MB)
- [ ] `tests/test_report.py::TestChartStyle` — covers EXPORT-03 (dark theme colors in SVG)
- [ ] `tests/test_report.py::TestHtmlDarkTheme` — covers EXPORT-03 (dark theme in HTML body)
- [ ] `pyproject.toml` dependency: `pygal>=3.1.0` must be added

*If none: "Existing infrastructure covers all phase requirements."*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| HTML opens in browser without network | EXPORT-01 | Requires real browser + offline mode | Open generated .html in browser with network disabled; all charts render |
| Dark theme visually matches TUI | EXPORT-03 | Visual comparison | Compare HTML report side-by-side with TUI screenshot |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
