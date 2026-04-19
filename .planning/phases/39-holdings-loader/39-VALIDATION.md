---
phase: 39
slug: holdings-loader
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-18
---

# Phase 39 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.0 + pytest-asyncio 0.24 |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `uv run pytest tests/test_holdings_loader.py -x` |
| **Full suite command** | `uv run pytest tests/ -x` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_holdings_loader.py -x`
- **After every plan wave:** Run `uv run pytest tests/ -x`
- **Before `/gsd-verify-work`:** `uv run pytest tests/ -x && uv run lint-imports`
- **Max feedback latency:** ~10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 39-01-01 | 01 | 1 | HOLD-01 | — | N/A | unit | `uv run pytest tests/test_holdings_loader.py::test_load_returns_portfolio_snapshot -x` | ❌ W0 | ⬜ pending |
| 39-01-02 | 01 | 1 | HOLD-02 | — | account label not stored raw | unit | `uv run pytest tests/test_holdings_loader.py::test_account_hash -x` | ❌ W0 | ⬜ pending |
| 39-01-03 | 01 | 1 | HOLD-01 | — | N/A | unit | `uv run pytest tests/test_holdings_loader.py::test_cost_basis_is_total -x` | ❌ W0 | ⬜ pending |
| 39-01-04 | 01 | 1 | HOLD-01 | — | N/A | unit | `uv run pytest tests/test_holdings_loader.py::test_load_missing_file -x` | ❌ W0 | ⬜ pending |
| 39-01-05 | 01 | 1 | HOLD-01 | — | N/A | unit | `uv run pytest tests/test_holdings_loader.py::test_load_malformed_csv -x` | ❌ W0 | ⬜ pending |
| 39-02-01 | 02 | 2 | HOLD-03 | — | holdings not emitted to WS/logs | unit (TestClient) | `uv run pytest tests/integration/test_holdings_route.py::test_get_holdings_200 -x` | ❌ W0 | ⬜ pending |
| 39-02-02 | 02 | 2 | HOLD-03 | — | 503 on unavailable, no exception to WS | unit (TestClient) | `uv run pytest tests/integration/test_holdings_route.py::test_get_holdings_503 -x` | ❌ W0 | ⬜ pending |
| 39-02-03 | 02 | 2 | HOLD-03 | — | holdings module not importable from forbidden paths | invariant | `uv run lint-imports` | ✅ existing | ⬜ pending |
| 39-02-04 | 02 | 2 | SC-3 (ISOL-07) | — | sentinel strings absent from all 4 surfaces | invariant | `uv run pytest tests/invariants/test_holdings_isolation.py -x` | ✅ scaffolded | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_holdings_loader.py` — stubs for HOLD-01, HOLD-02 (HoldingsLoader unit tests)
- [ ] `tests/integration/test_holdings_route.py` — stubs for HOLD-03 (TestClient route tests)

*Existing infrastructure covers framework, asyncio_mode, socket gate, and invariant tests.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| AppSettings ALPHASWARM_HOLDINGS_CSV_PATH env var override works | HOLD-01 | Integration env setup | Set env var to alternate path, start server, GET /api/holdings, verify response reflects alternate file |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
