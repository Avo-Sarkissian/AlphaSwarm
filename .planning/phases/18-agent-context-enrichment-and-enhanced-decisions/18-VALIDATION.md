---
phase: 18
slug: agent-context-enrichment-and-enhanced-decisions
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-06
---

# Phase 18 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-asyncio |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest tests/ -x -q --tb=short` |
| **Full suite command** | `uv run pytest tests/ -q --tb=short` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/ -x -q --tb=short`
- **After every plan wave:** Run `uv run pytest tests/ -q --tb=short`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 20 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 18-01-01 | 01 | 1 | DECIDE-01 | — | N/A | unit | `uv run pytest tests/test_types.py -x -q` | ❌ W0 | ⬜ pending |
| 18-01-02 | 01 | 1 | ENRICH-01 | — | N/A | unit | `uv run pytest tests/test_enrichment.py -x -q` | ❌ W0 | ⬜ pending |
| 18-01-03 | 01 | 1 | ENRICH-02 | — | N/A | unit | `uv run pytest tests/test_enrichment.py::test_bracket_slices -x -q` | ❌ W0 | ⬜ pending |
| 18-02-01 | 02 | 2 | ENRICH-03 | — | N/A | unit | `uv run pytest tests/test_enrichment.py::test_headlines -x -q` | ❌ W0 | ⬜ pending |
| 18-02-02 | 02 | 2 | DECIDE-02 | — | N/A | integration | `uv run pytest tests/test_simulation_enrichment.py -x -q` | ❌ W0 | ⬜ pending |
| 18-03-01 | 03 | 3 | DECIDE-01 | — | N/A | unit | `uv run pytest tests/test_parsing.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_types.py` — add `TickerDecision` and `AgentDecision.ticker_decisions` stubs
- [ ] `tests/test_enrichment.py` — stubs for `format_market_block()`, `build_enriched_user_message()`, `fetch_headlines()`; bracket slice tests
- [ ] `tests/test_simulation_enrichment.py` — stubs for sub-wave dispatch integration and enriched message threading
- [ ] `tests/test_parsing.py` — extend existing tests for `ticker_decisions` graceful fallback

*Existing `pytest-asyncio` infrastructure covers framework setup.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Agent prompt contains market data block visible in logs | ENRICH-01 | Requires live Ollama + simulation run | Run `uv run python -m alphaswarm.cli` with test seed; check structlog output for `market_block` key in agent dispatch logs |
| Different brackets receive different data slices | ENRICH-02 | Requires live simulation + log inspection | Compare prompt payloads for Quant vs Macro vs Insider bracket agents in debug logs |
| `time_horizon` accepted as free string in output | DECIDE-02 | Requires live LLM inference | Run simulation; inspect `AgentDecision.ticker_decisions[].time_horizon` in raw output |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 20s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
