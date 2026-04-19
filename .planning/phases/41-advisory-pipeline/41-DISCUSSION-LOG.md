# Phase 41: Advisory Pipeline - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-19
**Phase:** 41-advisory-pipeline
**Areas discussed:** Ticker-entity correlation, Synthesis approach, Endpoint response pattern, Advisory panel layout

---

## Ticker-Entity Correlation

| Option | Description | Selected |
|--------|-------------|----------|
| ContextPacket tickers | Match holdings against tickers already fetched by Phase 40 providers | ✓ |
| Global consensus for all holdings | Apply same BUY/SELL/HOLD uniformly to every holding | |
| Entity name fuzzy match | Query Neo4j Entity nodes and fuzzy-match against ticker metadata | |
| Holdings not in simulation → no signal | Only show holdings with explicit entity matches | |

**User's choice:** ContextPacket tickers as primary scope signal

| Unmatched holding option | Selected |
|--------------------------|----------|
| Global consensus fallback | ✓ |
| Omit from results | |
| Neutral / no signal marker | |

**Notes:** LLM makes the final impact determination; programmatic matching is just a scope hint.

---

## Synthesis Approach

| Option | Description | Selected |
|--------|-------------|----------|
| Rationale text per holding | Data join + per-holding LLM call for rationale_summary | |
| Single synthesis pass over all holdings | One LLM call with full portfolio + signals | ✓ (evolved) |
| Full ReACT loop like the report | ReACT engine with portfolio context | |

**User's choice (free text):** The orchestrator should take into account what everyone in the swarm is saying. Not every rumor or piece of news or earnings impacts every stock held. It should decide and report recommendations on impacted holdings. It should have a very thorough, well put together report.

**Interpretation applied:** Pre-fetch all Neo4j swarm data (bracket_summary, entity_impact, bracket_narratives, round_timeline), feed full context + portfolio to orchestrator in one prompt, LLM decides impact and writes both structured AdvisoryItem list and portfolio_outlook narrative.

| Output format | Selected |
|---------------|----------|
| Structured JSON + narrative | ✓ |
| Markdown report (like Report Viewer) | |

| Ranking | Selected |
|---------|----------|
| Signal × exposure score | ✓ |
| Position exposure first | |
| Signal confidence first | |

---

## Endpoint Response Pattern

| Endpoint behavior | Selected |
|-------------------|----------|
| Async 202 + polling | ✓ |
| Synchronous POST | |

| Persistence | Selected |
|-------------|----------|
| Write to disk (advisory/ directory) | ✓ |
| Memory only | |

**Notes:** Mirrors the report pattern exactly (POST triggers, GET reads, done_callback captures failures).

---

## Advisory Panel Layout

| Layout | Selected |
|--------|----------|
| Full-screen modal | ✓ |
| Inline side panel | |

**User's choice:** Full-screen modal matching ReportViewer chrome, with ControlBar "Advisory" button in the complete-phase strip alongside "Report".

| Unaffected holdings | Selected |
|---------------------|----------|
| Hide (show "N of M positions affected") | ✓ |
| Show all, mark unaffected | |

**Notes:** Modal content: portfolio_outlook narrative (top) → divider → ranked table (TICKER, SIGNAL, CONF, EXPOSURE, RATIONALE). Signal color coding: BUY = accent, SELL = destructive, HOLD = secondary.

---

## Claude's Discretion

- Exact LLM prompt template for advisory synthesis call
- JSON parsing/validation strategy for LLM structured output
- Cypher query shape for prefetched Neo4j data (reuse existing graph methods)
- `portfolio_outlook` prose typography in the modal
- Whether `advisory_task` is a single slot or cycle-keyed dict on `app.state`

## Deferred Ideas

- Per-bracket breakdown table in the advisory panel
- Advisory history across multiple cycles
- Export to PDF/CSV
- Re-fetch live market prices at advisory time
