# Phase 25: Portfolio Impact Analysis - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the discussion.

**Date:** 2026-04-09
**Phase:** 25-portfolio-impact-analysis
**Mode:** discuss
**Areas discussed:** CSV format target, Ticker-entity bridge, Narrative model, CLI trigger shape

## Gray Areas Presented

All four areas selected by user for discussion.

### CSV Format Target
| Option | Description |
|--------|-------------|
| Raw Schwab export (chosen) | Parse actual Schwab export; skip 2 metadata rows; filter to Equity |
| Simplified holdings.csv | Pre-cleaned CSV; faster but requires manual re-export processing |
| Support both with auto-detect | Doubles parser surface area |

### Ticker-Entity Bridge
| Option | Description |
|--------|-------------|
| Static lookup table (chosen) | Hardcoded TICKER_ENTITY_MAP constant; deterministic; zero extra LLM calls |
| Fuzzy match on CSV description | Brittle for ADRs and ETFs |
| LLM-assisted mapping | Accurate but adds latency and model call overhead |

### Narrative Model
| Option | Description |
|--------|-------------|
| Orchestrator via ReACT loop (chosen) | portfolio_impact tool in tool registry; orchestrator synthesizes naturally |
| Direct worker model call (post-assembly) | Simpler but worker not loaded during report; separate lifecycle needed |

### CLI Trigger Shape
| Option | Description |
|--------|-------------|
| Flag on report subcommand (chosen) | `report --portfolio /path`; same model lifecycle; no duplication |
| New portfolio subcommand | Standalone but duplicates cycle resolution and model lifecycle |

## Corrections Made

No corrections — all recommended options accepted.

## Prior Decisions Applied

From STATE.md accumulated context:
- Schwab CSV in-memory only, never persisted → confirmed, implemented via tool closure pattern
- Swarm uncontaminated by portfolio data → confirmed, portfolio parsed post-simulation during report step only
