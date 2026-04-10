---
phase: 25
slug: portfolio-impact-analysis
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-09
---

# Phase 25 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio |
| **Config file** | `pytest.ini` / `pyproject.toml` |
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
| 25-01-01 | 01 | 1 | PORTFOLIO-01 | — | No portfolio data persisted to disk or Neo4j | unit | `uv run pytest tests/test_report.py -k portfolio -x -q` | ❌ W0 | ⬜ pending |
| 25-01-02 | 01 | 1 | PORTFOLIO-01 | — | Schwab CSV parsed correctly inc. edge cases | unit | `uv run pytest tests/test_report.py -k schwab -x -q` | ❌ W0 | ⬜ pending |
| 25-01-03 | 01 | 2 | PORTFOLIO-02 | — | Consensus signals mapped to held tickers | unit | `uv run pytest tests/test_report.py -k consensus_map -x -q` | ❌ W0 | ⬜ pending |
| 25-01-04 | 01 | 2 | PORTFOLIO-03 | — | Coverage gaps explicitly listed | unit | `uv run pytest tests/test_report.py -k coverage_gaps -x -q` | ❌ W0 | ⬜ pending |
| 25-01-05 | 01 | 3 | PORTFOLIO-04 | — | LLM narrative generated and appears in markdown + HTML | unit | `uv run pytest tests/test_report.py -k narrative -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_report.py` — add portfolio test stubs (parse, map, gaps, narrative)
- [ ] `tests/conftest.py` — add Schwab CSV fixture with real-world edge cases

*Existing pytest + pytest-asyncio infrastructure is already in place.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| LLM narrative quality | PORTFOLIO-04 | Cannot assert quality of free-text LLM output | Run simulation with `--portfolio`, read narrative section for coherence |
| HTML report rendering | PORTFOLIO-04 | Visual check needed | Open HTML report in browser, verify portfolio section renders correctly |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
