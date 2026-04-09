# Requirements: AlphaSwarm

**Defined:** 2026-04-09
**Core Value:** The 3-round consensus cascade must produce believable, diverse market reactions from 100 agents with dynamic influence topology — grounded in real market data, the simulation engine is the product.

## v4 Requirements

Requirements for v4.0 Interactive Simulation & Analysis. Each maps to roadmap phases.

### Shock Injection

- [ ] **SHOCK-01**: User can inject a breaking event between simulation rounds via TUI input widget
- [ ] **SHOCK-02**: Injected shock text is visible to all 100 agents in the next round's prompt context
- [ ] **SHOCK-03**: ShockEvent is persisted to Neo4j with cycle linkage and `injected_before_round` metadata
- [ ] **SHOCK-04**: User can see before/after consensus comparison quantifying how the swarm shifted due to the shock
- [ ] **SHOCK-05**: Post-simulation report includes a shock impact section showing agent pivots and bracket-level shifts

### Simulation Replay

- [ ] **REPLAY-01**: User can list past simulations from Neo4j with seed rumor, date, and round count
- [ ] **REPLAY-02**: User can select a past simulation and reconstruct all per-round agent decisions from Neo4j
- [ ] **REPLAY-03**: Reconstructed simulation displays in TUI round-by-round via ReplayStore
- [ ] **REPLAY-04**: User can control replay speed (step-through, 0.5x, 1x, 2x) during TUI playback

### HTML Export

- [ ] **EXPORT-01**: User can export a simulation report as a self-contained single HTML file
- [ ] **EXPORT-02**: HTML report includes inline SVG charts (consensus bars, signal timelines, bracket distributions) via pygal
- [ ] **EXPORT-03**: HTML report uses a dark theme matching the TUI's minimalist aesthetic

### Portfolio Impact Analysis

- [ ] **PORTFOLIO-01**: System parses Schwab CSV holdings from `schwab/holdings.csv` — in-memory only, never persisted to Neo4j or disk cache
- [ ] **PORTFOLIO-02**: Post-simulation analysis maps swarm consensus signals to user's held tickers
- [ ] **PORTFOLIO-03**: Holdings not covered by the simulation are flagged as coverage gaps
- [ ] **PORTFOLIO-04**: Orchestrator LLM generates a natural-language portfolio narrative comparing swarm consensus against user positions

## Future Requirements

Deferred to v4.1+. Tracked but not in current roadmap.

### Replay Extensions

- **REPLAY-05**: Side-by-side comparison of two simulations (same seed, different shocks or market conditions)

### Portfolio Extensions

- **PORTFOLIO-05**: Unrealized P&L impact projection (hypothetical portfolio impact if tickers move as swarm suggests)
- **PORTFOLIO-06**: Multi-account support (Individual vs Roth IRA grouping from Schwab exports)

### Visualization

- **VIS-01**: Miro API v2 post-simulation graph export (influence network spatial layout)

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Mid-round shock injection | Breaks batch atomicity — agents in same round would see inconsistent information |
| Additional rounds after shock (Round 4+) | 3-round cascade is hardcoded invariant; memory pressure limits on M1 Max |
| PDF export | Heavy system deps (WeasyPrint/wkhtmltopdf), loses chart interactivity; users can print-to-PDF from browser |
| Live Dash/Flask report server | Violates local-first design; single-file HTML is sufficient |
| Automated trade recommendations | Regulatory minefield; simulation produces analysis, not financial advice |
| Schwab API real-time sync | OAuth2 scope creep; manual CSV export takes 30 seconds |
| RAG vector retrieval layer | 2-model limit blocks embedding model; Neo4j Cypher sufficient for corpus |
| Miro real-time visualization | TUI is better for real-time; 2s rate limit impractical for 100-agent updates |
| Portfolio persistence to Neo4j | Privacy requirement — holdings stay in-memory only during report step |
| Historical portfolio tracking | Out of scope per PROJECT.md — forward simulation only |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| SHOCK-01 | — | Pending |
| SHOCK-02 | — | Pending |
| SHOCK-03 | — | Pending |
| SHOCK-04 | — | Pending |
| SHOCK-05 | — | Pending |
| REPLAY-01 | — | Pending |
| REPLAY-02 | — | Pending |
| REPLAY-03 | — | Pending |
| REPLAY-04 | — | Pending |
| EXPORT-01 | — | Pending |
| EXPORT-02 | — | Pending |
| EXPORT-03 | — | Pending |
| PORTFOLIO-01 | — | Pending |
| PORTFOLIO-02 | — | Pending |
| PORTFOLIO-03 | — | Pending |
| PORTFOLIO-04 | — | Pending |

**Coverage:**
- v4 requirements: 16 total
- Mapped to phases: 0
- Unmapped: 16 ⚠️

---
*Requirements defined: 2026-04-09*
*Last updated: 2026-04-09 after initial definition*
