---
phase: 16
slug: ticker-extraction
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-05
---

# Phase 16 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-asyncio |
| **Config file** | `pyproject.toml` (existing `[tool.pytest.ini_options]`) |
| **Quick run command** | `uv run pytest tests/test_ticker_extraction.py -x -q` |
| **Full suite command** | `uv run pytest tests/ -x -q` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_ticker_extraction.py -x -q`
- **After every plan wave:** Run `uv run pytest tests/ -x -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 16-01-01 | 01 | 1 | TICK-01 | — | N/A | unit | `uv run pytest tests/test_ticker_extraction.py::test_extracted_ticker_model -x -q` | ❌ W0 | ⬜ pending |
| 16-01-02 | 01 | 1 | TICK-01 | — | N/A | unit | `uv run pytest tests/test_ticker_extraction.py::test_parse_seed_event_with_tickers -x -q` | ❌ W0 | ⬜ pending |
| 16-01-03 | 01 | 1 | TICK-01 | — | N/A | unit | `uv run pytest tests/test_ticker_extraction.py::test_orchestrator_prompt_includes_tickers -x -q` | ❌ W0 | ⬜ pending |
| 16-02-01 | 02 | 1 | TICK-02 | — | Invalid symbols rejected with warning | unit | `uv run pytest tests/test_ticker_extraction.py::test_sec_validator_rejects_invalid -x -q` | ❌ W0 | ⬜ pending |
| 16-02-02 | 02 | 1 | TICK-02 | — | N/A | unit | `uv run pytest tests/test_ticker_extraction.py::test_sec_validator_accepts_valid -x -q` | ❌ W0 | ⬜ pending |
| 16-03-01 | 03 | 2 | TICK-03 | — | N/A | unit | `uv run pytest tests/test_ticker_extraction.py::test_ticker_cap_enforced -x -q` | ❌ W0 | ⬜ pending |
| 16-03-02 | 03 | 2 | TICK-03 | — | N/A | unit | `uv run pytest tests/test_ticker_extraction.py::test_cli_ticker_display -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_ticker_extraction.py` — stubs for TICK-01, TICK-02, TICK-03
- [ ] Existing `tests/conftest.py` — shared fixtures (may need extension for mock SEC data)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| SEC CDN download succeeds and file is written to `data/sec_tickers.json` | TICK-02 | Requires live network call to SEC CDN | Run `alphaswarm inject "Apple is acquiring Tesla"` with `data/sec_tickers.json` absent; verify file is created and logs show download success |
| End-to-end: inject rumor with 2 valid tickers, confirm both appear in Neo4j Cycle node | TICK-01, TICK-02 | Requires live Neo4j and Ollama | Run full inject, query `MATCH (c:Cycle) RETURN c.tickers` and verify expected symbols |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
