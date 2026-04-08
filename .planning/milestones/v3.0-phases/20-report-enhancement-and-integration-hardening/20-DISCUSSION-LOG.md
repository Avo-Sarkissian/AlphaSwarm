# Phase 20: Report Enhancement and Integration Hardening - Discussion Log (Assumptions Mode)

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the analysis.

**Date:** 2026-04-07
**Phase:** 20-report-enhancement-and-integration-hardening
**Mode:** assumptions
**Areas analyzed:** Market Context Section Architecture, Per-Ticker Consensus Data Source, Headlines Inclusion, E2E Integration Test Shape

## Assumptions Presented

### Market Context Section Architecture
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Market context section is assembler-injected (non-ReACT path), not a 9th ReACT tool | Likely | `report.py` MAX_ITERATIONS=10; 8 tools already fill budget; `assemble()` handles optional sections cleanly (`report.py:274`); market data is fully structured in Neo4j (`graph.py:336`) |

### Per-Ticker Consensus Data Source
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Add new Neo4j write for TickerConsensus (store per-ticker vote counts to graph) | Likely | `StateStore._ticker_consensus` is in-memory only (`state.py:133-134`); `_handle_report()` creates fresh AppState with no StateStore reference (`cli.py:682`); TickerDecision absent from graph.py decision writes |

### Headlines Inclusion in Market Context
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Headlines excluded from report; read from Neo4j only (headlines not stored in graph) | Confident | `graph.py:279-298` explicitly omits `headlines` from `snapshot_params`; `types.py:124` shows field exists in Pydantic model but was never written to Neo4j |

### E2E Integration Test Shape (SC3)
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Mocked Ollama + mocked tool calls; assert output report contains market context section | Likely | `test_report.py` uses `AsyncMock` + `_mock_ollama_response()` throughout; live Ollama/Neo4j would make CI fragile |

## Corrections Made

No corrections — all assumptions confirmed.

## External Research

None required — codebase provided sufficient evidence for all assumption areas.
