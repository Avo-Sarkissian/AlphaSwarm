---
phase: 18
slug: agent-context-enrichment-and-enhanced-decisions
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-06
updated: 2026-04-07
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

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 18-01-01 | 01 | 1 | DECIDE-01, DECIDE-02 | unit | `uv run pytest tests/test_types.py tests/test_parsing.py -x -q` | W0 | pending |
| 18-01-02 | 01 | 1 | ENRICH-01, ENRICH-02 | unit | `uv run pytest tests/test_enrichment.py -x -q` | W0 | pending |
| 18-02-01 | 02 | 2 | ENRICH-03 | unit | `uv run pytest tests/test_enrichment.py -x -q` | W0 | pending |
| 18-03-01 | 03 | 3 | ENRICH-01, ENRICH-02 | integration | `uv run pytest tests/test_simulation_enrichment.py -x -q` | W0 | pending |
| 18-03-02 | 03 | 3 | ENRICH-01, DECIDE-02 | integration | `uv run pytest tests/test_simulation.py tests/test_simulation_enrichment.py -x -q` | W0 | pending |

*Status: pending / green / red / flaky*

---

## Key Review Issue Coverage

| Review Issue | Blocker? | Task Addressing It | Test Coverage |
|-------------|----------|-------------------|---------------|
| Dependency bug (18-03 depends_on) | YES | 18-03 frontmatter fixed | N/A (structural) |
| Macro-agent spec mismatch | YES | 18-01-02 (enrichment.py comment + D-04 compliance) | `test_format_market_block_macro_bracket` |
| End-to-end ticker path | YES | 18-01-01 (seed.py prompt + parsing.py tickers) | `test_parse_seed_with_tickers`, `test_parse_seed_tickers_capped_at_3` |
| Parse robustness (malformed ticker_decisions) | YES | 18-01-01 (lenient parse in parsing.py) | `test_parse_malformed_ticker_decisions_*`, `test_parse_mixed_valid_invalid` |
| Headline injection budget | NO | 18-01-02 (format_market_block budget-caps headlines) | `test_headline_injection_budget_capped` |
| AV headline quota warning | NO | 18-02-01 (docstring in enrichment.py) | grep verification |
| direction field (parse_error excluded) | NO | 18-01-02 (JSON_OUTPUT_INSTRUCTIONS) | `test_json_output_instructions_direction_values` |
| Shared httpx.AsyncClient | NO | 18-02-01 (shared client parameter) | `test_enrich_snapshots_*` (mock verifies single client) |
| Lenient ticker_decisions parse | NO | 18-01-01 (_lenient_parse_ticker_decisions) | `test_parse_malformed_*`, `test_parse_mixed_*` |

---

## Wave 0 Requirements

- [ ] `tests/test_types.py` — add `TickerDecision` and `AgentDecision.ticker_decisions` stubs
- [ ] `tests/test_enrichment.py` — stubs for `format_market_block()`, `build_enriched_user_message()`, `fetch_headlines()`; bracket slice tests; headline budget tests
- [ ] `tests/test_simulation_enrichment.py` — stubs for sub-wave dispatch integration and enriched message threading
- [ ] `tests/test_parsing.py` — extend existing tests for `ticker_decisions` graceful fallback, malformed field handling, and seed ticker extraction

*Existing `pytest-asyncio` infrastructure covers framework setup.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Agent prompt contains market data block visible in logs | ENRICH-01 | Requires live Ollama + simulation run | Run `uv run python -m alphaswarm.cli` with test seed; check structlog output for `market_block` key in agent dispatch logs |
| Different brackets receive different data slices | ENRICH-02 | Requires live simulation + log inspection | Compare prompt payloads for Quant vs Macro vs Insider bracket agents in debug logs |
| `time_horizon` accepted as free string in output | DECIDE-02 | Requires live LLM inference | Run simulation; inspect `AgentDecision.ticker_decisions[].time_horizon` in raw output |
| Orchestrator extracts tickers from seed rumor | ENRICH-01 | Requires live Ollama | Run injection with "Apple acquiring Tesla" seed; check parsed_result.seed_event.tickers |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 20s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
