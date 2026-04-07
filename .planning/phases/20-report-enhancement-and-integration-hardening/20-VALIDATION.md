---
phase: 20
slug: report-enhancement-and-integration-hardening
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-07
---

# Phase 20 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 + pytest-asyncio 0.24.0+ |
| **Config file** | `pyproject.toml` (`asyncio_mode = "auto"`) |
| **Quick run command** | `uv run pytest tests/test_report.py tests/test_graph.py -x -q` |
| **Full suite command** | `uv run pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_report.py tests/test_graph.py -x -q`
- **After every plan wave:** Run `uv run pytest tests/ -x -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 20-01-01 | 01 | 0 | DRPT-01 | — | N/A | unit | `uv run pytest tests/test_report.py::TestReportAssemblerMarketContext -x` | ❌ W0 | ⬜ pending |
| 20-01-02 | 01 | 0 | DRPT-01 | — | N/A | unit | `uv run pytest tests/test_report.py::TestMarketContextTemplate -x` | ❌ W0 | ⬜ pending |
| 20-01-03 | 01 | 0 | DRPT-01 | — | N/A | unit | `uv run pytest tests/test_graph.py::TestWriteTickerConsensus -x` | ❌ W0 | ⬜ pending |
| 20-01-04 | 01 | 0 | DRPT-01 | — | N/A | unit | `uv run pytest tests/test_graph.py::TestReadMarketContext -x` | ❌ W0 | ⬜ pending |
| 20-02-01 | 02 | 1 | DRPT-01 | — | N/A | unit | `uv run pytest tests/test_graph.py::TestWriteTickerConsensus -x` | ❌ W0 | ⬜ pending |
| 20-02-02 | 02 | 1 | DRPT-01 | — | N/A | unit | `uv run pytest tests/test_graph.py::TestReadMarketContext -x` | ❌ W0 | ⬜ pending |
| 20-03-01 | 03 | 2 | DRPT-01 | — | N/A | unit | `uv run pytest tests/test_report.py::TestReportAssemblerMarketContext -x` | ❌ W0 | ⬜ pending |
| 20-03-02 | 03 | 2 | DRPT-01 | — | N/A | unit | `uv run pytest tests/test_report.py::TestMarketContextTemplate -x` | ❌ W0 | ⬜ pending |
| 20-04-01 | 04 | 3 | DRPT-01 | — | N/A | unit | `uv run pytest tests/test_report.py -x -q` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_report.py::TestReportAssemblerMarketContext` — stubs covering assembler extension with and without `market_context_data`
- [ ] `tests/test_report.py::TestMarketContextTemplate` — stubs covering `09_market_context.j2` rendering (full data, None fields, `is_degraded` marker)
- [ ] `tests/test_graph.py::TestWriteTickerConsensus` — stubs covering `write_ticker_consensus_summary()` UNWIND write (mocked session)
- [ ] `tests/test_graph.py::TestReadMarketContext` — stubs covering `read_market_context()` (mocked session, handles missing `TickerConsensusSummary`)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Full v3 CLI pipeline (inject → run → report) completes without errors | DRPT-01 SC3 | Requires live Ollama + Neo4j | Run `alphaswarm inject "Apple acquiring Tesla"`, then `alphaswarm run`, then `alphaswarm report`; confirm report file written and contains `## Market Context` heading |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
