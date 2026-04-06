# Phase 16: Ticker Extraction - Discussion Log (Assumptions Mode)

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the analysis.

**Date:** 2026-04-05
**Phase:** 16-ticker-extraction
**Mode:** assumptions
**Areas analyzed:** Extraction Integration Point, Type Model Changes, SEC Validation Strategy, Neo4j Ticker Persistence, CLI Visibility

## Assumptions Presented

### Extraction Integration Point
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Tickers co-extracted in `inject_seed()` via single LLM call, no second model load | Confident | `seed.py:24-36` (single JSON prompt), `seed.py:98-103` (Phase 13 same-block orchestrator reuse pattern), ROADMAP Phase 16 SC-1 "single LLM call" |
| Response schema expands to include `"tickers"` array, parse path updated accordingly | Confident | `parsing.py:136-165` — tight coupling between response schema and parse keys; adding tickers requires updating `_try_parse_seed_json()` |

### Type Model Changes
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| New `ExtractedTicker` model (symbol, company_name, relevance) added to `types.py` | Likely | `types.py:79-85` `SeedEntity` as direct template; TICK-03 relevance ranking requires float score on type |
| `SeedEvent` gains `tickers: list[ExtractedTicker]` field | Likely | All downstream consumers receive full `SeedEvent`; extending it propagates without new plumbing (`simulation.py:548`, `graph.py:207`, `cli.py:69`) |
| 3-ticker cap enforced at parse time in `parse_seed_event()` | Likely | Consistent with parse-time data shaping already present (entity list construction) |

### SEC Validation Strategy
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| `company_tickers.json` loaded from disk as in-memory dict, not fetched at runtime | Likely | No HTTP client in `config.py`; CLAUDE.md "Local First" + "no blocking I/O on main event loop" constraints |
| Validation is synchronous in-memory lookup; invalid symbols warned but not abort-triggering | Likely | No prior pattern for aborting simulation on soft validation failures; structlog warning pattern matches existing error handling style |

### Neo4j Ticker Persistence
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Tickers stored as Cycle node property, not standalone `Ticker` nodes in Phase 16 | Likely | `graph.py:175-221` `create_cycle_with_seed_event()` uses node properties for simple scalar/list data; `Ticker` nodes become justified only when Phase 17 attaches market data |

### CLI Visibility
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Ticker result displayed by extending `_print_injection_summary()` in `cli.py` | Likely | `cli.py:65-90` tabular entity display is trivially extended; ROADMAP SC-3 "user can see which tickers were selected in the simulation output" — injection summary is the natural trigger point |

## Corrections Made

No corrections — all assumptions confirmed by user.

## External Research Notes

Two gaps flagged during analysis (resolved as design decisions, no external research spawned):

1. **SEC `company_tickers.json`** — Schema is `{cik: {"ticker": "AAPL", "title": "Apple Inc."}}`, available from SEC CDN without API key. Decided: download once to `data/sec_tickers.json`, not bundled in repo.

2. **Ticker relevance score source** — Decided: LLM assigns float relevance per ticker directly (same as `SeedEntity.relevance` pattern), not derived from matched entity scores.
