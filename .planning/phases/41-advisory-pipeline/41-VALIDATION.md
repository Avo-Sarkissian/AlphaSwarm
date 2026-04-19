---
phase: 41
slug: advisory-pipeline
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-19
---

# Phase 41 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| **Quick run command** | `uv run pytest tests/unit/test_advisory.py -x -q` |
| **Full suite command** | `uv run pytest tests/ -x -q` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/unit/test_advisory.py -x -q`
- **After every plan wave:** Run `uv run pytest tests/ -x -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 41-01-01 | 01 | 1 | ADVIS-01 | T-41-01 | `AdvisoryItem` fields never contain raw holdings PII | unit | `uv run pytest tests/unit/test_advisory.py::test_advisory_item_schema -x -q` | ❌ W0 | ⬜ pending |
| 41-01-02 | 01 | 1 | ADVIS-01 | T-41-02 | `synthesize()` returns ranked list ordered by signal confidence | unit | `uv run pytest tests/unit/test_advisory.py::test_synthesize_returns_ranked_list -x -q` | ❌ W0 | ⬜ pending |
| 41-01-03 | 01 | 1 | ADVIS-01 | — | Bracket consensus join: only tickers present in holdings are returned | unit | `uv run pytest tests/unit/test_advisory.py::test_ticker_join_filters_unmatched -x -q` | ❌ W0 | ⬜ pending |
| 41-01-04 | 01 | 1 | ADVIS-01 | T-41-03 | LLM validation error retries once then fails cleanly via done_callback | unit | `uv run pytest tests/unit/test_advisory.py::test_synthesize_retry_on_validation_error -x -q` | ❌ W0 | ⬜ pending |
| 41-02-01 | 02 | 2 | ADVIS-02 | T-41-04 | POST /api/advisory/{cycle_id} returns 202 with status_url when portfolio loaded | unit | `uv run pytest tests/unit/test_advisory_route.py::test_post_advisory_202 -x -q` | ❌ W0 | ⬜ pending |
| 41-02-02 | 02 | 2 | ADVIS-02 | T-41-04 | POST returns 503 when portfolio_snapshot is None | unit | `uv run pytest tests/unit/test_advisory_route.py::test_post_advisory_503_no_portfolio -x -q` | ❌ W0 | ⬜ pending |
| 41-02-03 | 02 | 2 | ADVIS-02 | T-41-05 | POST returns 409 CONFLICT when advisory_task already in-flight | unit | `uv run pytest tests/unit/test_advisory_route.py::test_post_advisory_409_conflict -x -q` | ❌ W0 | ⬜ pending |
| 41-02-04 | 02 | 2 | ADVIS-03 | T-41-06 | Canary ISOL-07 activates: synthesize() called with sentinel portfolio, no holdings leak | unit | `uv run pytest tests/invariants/test_holdings_isolation.py -x -q` | ✅ | ⬜ pending |
| 41-03-01 | 03 | 3 | ADVIS-02 | — | AdvisoryPanel.vue renders advisory items list with ticker + signal | manual | Browser: Start simulation, click Advisory button, verify panel renders | — | ⬜ pending |
| 41-03-02 | 03 | 3 | ADVIS-02 | — | ControlBar Advisory button disabled when advisory not ready | manual | Browser: Before simulation completes, verify button disabled/hidden | — | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_advisory.py` — unit stubs for ADVIS-01 synthesize() + AdvisoryItem schema tests
- [ ] `tests/unit/test_advisory_route.py` — unit stubs for ADVIS-02 route 202/503/409 tests
- [ ] `tests/invariants/test_holdings_isolation.py` — already exists (canary ISOL-07 flip required)

*Wave 0 creates the test stubs before implementation, ensuring red-first discipline.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| AdvisoryPanel renders advisory items post-simulation | ADVIS-02 | Requires real Vue frontend + browser | Start full simulation, click Advisory button in ControlBar, verify AdvisoryPanel shows ranked items with ticker, signal, confidence, rationale |
| ControlBar Advisory button state (enabled/disabled) | ADVIS-02 | Requires browser interaction timing | Verify button is disabled before simulation completes and enables after advisory is available |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
