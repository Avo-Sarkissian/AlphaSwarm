# Milestones

Project-level shipping history. Each entry is created when a milestone is archived.

---

## v3.0 — Stock-Specific Recommendations with Live Data

**Shipped:** 2026-04-08
**Phases:** 16-23 (8 phases, 16 plans)
**Requirements:** 16/16 v3 requirements complete
**Timeline:** 2026-04-05 → 2026-04-08 (3 days)
**Git range:** feat(16-01) → docs(23)
**Source LOC:** ~10,075 Python (src/)

### Delivered

Ground the consensus cascade in real market data — live ticker extraction, yfinance market data pipeline, bracket-tailored agent enrichment, per-stock TUI consensus panel, and a market context report section that compares 100-agent consensus with actual market indicators.

### Key Accomplishments

1. **SEC-Validated Ticker Extraction** — Orchestrator co-extracts stock tickers with entities in a single LLM call; symbols are validated against SEC company_tickers.json; top-3 by relevance kept
2. **Async Market Data Pipeline** — yfinance with Alpha Vantage fallback, 1-hour disk cache, atomic writes, Neo4j Ticker nodes, and graceful degradation with visible CLI warnings
3. **Bracket-Tailored Agent Enrichment** — 100 agent prompts enriched pre-Round 1 with bracket-specific market data slices (Quant/Technical, Macro/Insider, Default) within strict token budgets
4. **TickerDecision Structured Output** — All agents produce per-ticker direction, expected_return_pct, and time_horizon alongside standard signal/confidence/sentiment
5. **Per-Ticker TUI Consensus Panel** — TickerConsensusPanel shows confidence-weighted voting vs majority vote and bracket disagreement bars per ticker in real time
6. **Market Context Report Section** — Post-simulation report compares agent consensus vs live price/earnings/news indicators per ticker (09_market_context.j2)

### Gap-Closing Work

Three phases were added after the mid-milestone audit to close identified gaps:
- **Phase 21**: Restored ticker_validator.py and dropped_tickers tracking (deleted in Phase 17 worktree merge)
- **Phase 22**: Fixed REACT_SYSTEM_PROMPT tool names (pre-existing mismatch causing report sections to fail)
- **Phase 23**: Reconciled VALIDATION.md files and added full v3 requirements traceability

### Archives

- Roadmap: `.planning/milestones/v3.0-ROADMAP.md`
- Requirements: `.planning/milestones/v3.0-REQUIREMENTS.md`
- Audit: `.planning/milestones/v3.0-MILESTONE-AUDIT.md`

---

## v2.0 — Engine Depth

**Shipped:** 2026-04-02
**Phases:** 11-15 (5 phases)
**Timeline:** 2026-03-31 → 2026-04-02

### Delivered

Post-simulation capabilities: Live Graph Memory, Richer Agent Interactions, Dynamic Persona Generation, Agent Interviews, Post-Simulation Report (ReACT agent querying Neo4j).

---

## v1.0 — Core Engine

**Shipped:** 2026-03-27
**Phases:** 1-10 (10 phases)
**Timeline:** 2026-03-24 → 2026-03-27

### Delivered

Full simulation engine: async Ollama inference with ResourceGovernor, Neo4j graph state, 100-agent 3-round cascade, dynamic influence topology, Textual TUI dashboard with agent grid, rationale sidebar, telemetry footer, and bracket aggregation panel.
