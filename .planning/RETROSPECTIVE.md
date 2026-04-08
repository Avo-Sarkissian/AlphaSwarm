# Retrospective: AlphaSwarm

Living retrospective — one section per milestone, most recent first.

---

## Milestone: v3.0 — Stock-Specific Recommendations with Live Data

**Shipped:** 2026-04-08
**Phases:** 8 (Phases 16-23) | **Plans:** 16
**Timeline:** 2026-04-05 → 2026-04-08 (3 days)
**Commits:** ~85 (feat + docs)

### What Was Built

- Phase 16: LLM ticker co-extraction + SEC validation + top-3 cap + CLI display
- Phase 17: Async yfinance market data pipeline, Alpha Vantage fallback, 1-hour disk cache, Neo4j Ticker nodes
- Phase 18: Bracket-tailored agent enrichment (3 slices), AV NEWS_SENTIMENT headlines, TickerDecision structured output
- Phase 19: TickerConsensusPanel TUI widget — confidence-weighted + majority voting, bracket disagreement bars
- Phase 20: 09_market_context.j2 report section, Neo4j ticker consensus persistence, market context assembly
- Phase 21: Restored ticker_validator.py and dropped_tickers tracking (gap closure)
- Phase 22: Fixed REACT_SYSTEM_PROMPT tool name mismatch (gap closure)
- Phase 23: Reconciled VALIDATION.md files and added v3 requirements traceability (doc gap closure)

### What Worked

- **Audit-driven gap closure was effective.** Running `/gsd-audit-milestone` mid-milestone caught the deleted ticker_validator.py (7ba7efa) and the pre-existing report tool name mismatch before archival. Adding gap-closing phases 21, 22, 23 was the right call — cleaner than accepting known gaps.
- **Strict critical path (16→17→18→19→20) kept dependencies clear.** No phase could ambiguously start early; each had a clear "what this provides to the next."
- **Lenient parse fallback design (ENRICH-03).** Defaulting new structured fields to `[]` rather than making them required prevented the enrichment work from breaking the existing 3-tier parse chain.
- **Pre-simulation enrichment pattern.** Completing all market data fetching before Round 1 was the right architecture — consistent context across all 3 rounds, no mid-simulation fetch complexity.
- **Atomic disk cache writes.** The temp-file-rename pattern for the market data cache prevented partial-write corruption with no extra complexity.

### What Was Inefficient

- **Worktree merge deleted Phase 16 work.** Commit 7ba7efa (Phase 17-01) deleted ticker_validator.py, both Phase 16 ticker test files, and all ticker_validator wiring from seed.py/parsing.py. A scoped Phase 17 commit shouldn't have touched Phase 16 files. This required an entire remediation phase (21) and extended the milestone by ~1 day.
- **REACT_SYSTEM_PROMPT mismatch was pre-existing.** The tool name mismatch in report.py (consensus_summary vs bracket_summary) existed since Phase 15 but wasn't caught until the v3.0 audit. Earlier verification or an integration test checking tool name consistency would have caught it.
- **REQUIREMENTS.md traceability stopped at Phase 15.** v3 requirements were never added to REQUIREMENTS.md during phase execution — discovered as a gap in Phase 23. This should happen at roadmap creation time, not as remediation at milestone close.
- **VALIDATION.md files drifted from actual test names.** Tracking files for phases 17, 19, 20 referenced test methods that didn't exist in the test suite. Tests passed, but the Nyquist tracking was stale. This creates false confidence during audits.

### Patterns Established

- **Gap-closing phases use (INSERTED) marker.** Phases 21, 22, 23 added post-audit — clear precedent for inserting remediation work between existing phases.
- **Validator callback injection via kwarg (None-safe pass-through).** parse_seed_event() accepts ticker_validator kwarg — None when CDN unreachable, validation skips gracefully. Good pattern for optional external dependencies.
- **Phase commits should not touch files from previous phases.** Violation (7ba7efa) caused a remediation phase. Phase commits should be scoped to the files listed in the plan's key_files.
- **v3 requirements should be added to REQUIREMENTS.md at roadmap creation**, not during gap-closing documentation phases at milestone close.

### Key Lessons

1. **Audit early, not just at milestone close.** Running `/gsd-audit-milestone` with phases 18 or 19 complete would have caught the ticker_validator deletion while it was cheap to fix — not a full phase later.
2. **Worktree merges need review before commit.** A git diff review comparing scoped plan files against what was actually staged would have caught the Phase 16 file deletions in 7ba7efa.
3. **Add requirements to REQUIREMENTS.md when you add them to ROADMAP.md.** Don't let traceability drift — update both files together at roadmap time.
4. **Integration tests for tool registries pay off.** A test asserting that all tool names in REACT_SYSTEM_PROMPT exist in the runtime tools dict would have caught the mismatch at Phase 15, not Phase 22.
5. **VALIDATION.md tracking files should be updated immediately after test runs**, not reconstructed from memory at milestone close. A post-plan hook that updates VALIDATION.md from pytest output would eliminate drift.

### Cost Observations

- Model mix: quality profile — claude-opus-4-6 for research/planning agents, claude-sonnet-4-6 for execution
- Sessions: ~6 sessions over 3 days
- Notable: 3 gap-closing phases = ~20% overhead vs original 5-phase scope. Audit-driven remediation is efficient but gaps from sloppy worktree merges are avoidable.

---

## Milestone: v2.0 — Engine Depth

**Shipped:** 2026-04-02
**Phases:** 5 (Phases 11-15) | **Plans:** 11

### What Was Built

Live Graph Memory (real-time Neo4j RationaleEpisode writes), Richer Agent Interactions (social rationale posts), Dynamic Persona Generation (entity-aware bracket modifiers), Agent Interviews (post-simulation in-character Q&A), Post-Simulation Report (ReACT agent + Cypher tools + markdown output).

### Key Lessons

- ReACT-style agent with prompt-dispatched tools (no native Ollama tools) is portable and debuggable.
- WriteBuffer pattern for real-time Neo4j writes without blocking simulation throughput.
- Dynamic persona modifiers generated in a single LLM call — no per-agent inference overhead.

---

## Milestone: v1.0 — Core Engine

**Shipped:** 2026-03-27
**Phases:** 10 (Phases 1-10) | **Plans:** 21

### What Was Built

Full simulation engine: async Ollama inference pipeline with ResourceGovernor (5-state governor machine, dual-signal monitoring), Neo4j graph schema, 100-agent 3-round cascade, dynamic INFLUENCED_BY topology, Textual TUI with agent grid/rationale sidebar/telemetry footer/bracket panel.

### Key Lessons

- Queue-based token pool (TokenPool) outperforms asyncio.Semaphore for VRAM-constrained workloads — allows yielding rather than blocking.
- Snapshot-based TUI rendering (200ms tick) is the correct pattern for decoupling 100 async agents from Textual's render cycle.
- UNWIND batch writes + session-per-coroutine isolation keeps Neo4j writes under 5ms per 100-decision batch.

---

## Cross-Milestone Trends

| Metric | v1.0 | v2.0 | v3.0 |
|--------|------|------|------|
| Phases | 10 | 5 | 8 |
| Plans | 21 | 11 | 16 |
| Days | 3 | 2 | 3 |
| Gap-closing phases | 0 | 0 | 3 |
| Audit used? | No | No | Yes |

**Observation:** Audit-driven development in v3.0 surfaced real gaps (not hypothetical ones). The 3 gap-closing phases represent genuine scope recovery, not gold-plating. Running audits earlier in future milestones is the highest-leverage process improvement.
