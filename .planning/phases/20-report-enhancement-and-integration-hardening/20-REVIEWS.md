---
phase: 20
reviewers: [gemini]
reviewed_at: 2026-04-07T00:00:00Z
plans_reviewed: [20-01-PLAN.md, 20-02-PLAN.md]
---

# Cross-AI Plan Review — Phase 20

> **Reviewers attempted:** Gemini ✓, Codex ✗ (silent failure in non-interactive mode), Claude skipped (current runtime).

---

## Gemini Review

### Summary
The plan is a well-structured extension of the existing ReACT-based reporting system. By opting for an "assembler-injection" path rather than forcing the LLM to process raw market data via tools, the design maintains system stability and minimizes token usage. The use of the `UNWIND` pattern for Neo4j persistence aligns with the project's performance requirements, and the template-based approach ensures a consistent, professional output. The strategy for handling "degraded data" and null values is robust and defensive.

### Strengths
- **Architectural Consistency**: Leveraging the `UNWIND` batch pattern for Neo4j and Jinja2 for templating follows established codebase patterns, reducing the learning curve for future maintenance.
- **Decoupled Logic**: Injecting market data directly into the `ReportAssembler` (Decision D-01) avoids complex prompt engineering and the potential for LLM hallucination regarding financial figures.
- **Defensive Query Design**: The use of `OPTIONAL MATCH` and `collect(tcs)[0]` in the Cypher query correctly handles historical cycles that lack consensus data without breaking the report generation.
- **Granular Persistence**: Wiring persistence into each of the three simulation rounds ensures that even if a simulation crashes in Round 3, the report can still provide insights from Round 2.
- **Type Safety**: The plan maintains strict typing and adheres to the `asyncio`-only requirement for all I/O operations.

### Concerns
- **Code Duplication in `simulation.py` (MEDIUM)**: The plan suggests adding the same four lines of persistence logic to three separate locations in `simulation.py`. While functional, this increases the risk of future logic drift.
- **Test Cleanup Leakage (MEDIUM)**: The research findings mention that `conftest.py` cleanup might miss `TickerConsensusSummary` nodes. If not addressed, this will lead to "ghost" data in test environments and potential query pollution.
- **Markdown Table Width (LOW)**: The proposed table in `09_market_context.j2` has 8 columns. In a standard terminal or narrow markdown viewer, this may wrap or become difficult to read, especially with "Confidence" and "52w Range" fields.
- **Graph Manager Availability (LOW)**: The plan assumes `graph_manager` is always available. While generally true in the current architecture, a check similar to `if graph_manager:` (consistent with `state_store`) would be safer.

### Suggestions
- **Refactor Simulation Wiring**: Create a private helper method in `SimulationEngine` (e.g., `_persist_round_consensus(cycle_id, round_num, consensus)`) to encapsulate the dual-write to both `state_store` and `graph_manager`.
- **Explicit Test Cleanup**: Update the `clear_graph` fixture in `tests/conftest.py` to explicitly delete `TickerConsensusSummary` nodes: `MATCH (n:TickerConsensusSummary) DETACH DELETE n`.
- **Table Formatting Optimization**: Consider merging "Consensus" and "Confidence" into a single column (e.g., `Bullish (0.85)`) to save horizontal space in the markdown report.
- **Graceful Degraded Handling**: In the template, consider adding a brief footnote explaining what `[degraded data]` means (e.g., "stale or incomplete market snapshot") to improve user clarity.

### Risk Assessment: LOW
The plan is low risk because it avoids modifying the core ReACT orchestration loop or system prompts. It treats the report enhancement as a "side-car" data injection. The hardware constraints (M1 Max memory) are respected as the market data retrieval happens post-simulation when agent memory load has decreased. The primary risks are purely operational (test data leakage) rather than architectural.

---

## Consensus Summary

Only one external reviewer (Gemini) completed successfully. Codex produced no output in non-interactive mode. Consensus below reflects Gemini's findings cross-referenced against the research and plan self-identified pitfalls.

### Agreed Strengths

- **Assembler-injection architecture** is the right call — avoids LLM hallucination on financial figures, maintains ReACT loop stability (confirmed by both plan rationale and Gemini)
- **OPTIONAL MATCH** is mandatory and correctly specified — cycles before Phase 20 would return no results with a plain MATCH (flagged in both RESEARCH.md pitfalls and Gemini review)
- **UNWIND batch pattern** is consistent with project standards — no architectural deviation needed

### Agreed Concerns

| Concern | Severity | Source |
|---------|----------|--------|
| conftest.py cleanup missing TickerConsensusSummary nodes | MEDIUM | Both RESEARCH.md (Pitfall 5) and Gemini |
| 3 duplicated write-blocks in simulation.py (no abstraction) | MEDIUM | Gemini |
| Markdown table width (8 columns) may be hard to read | LOW | Gemini |
| graph_manager assumed always non-None (no guard) | LOW | Gemini |

### Divergent Views

No second reviewer to compare against. The following items from the plan's own research were **not flagged** by Gemini and appear low-risk:
- Ticker node missing when writing consensus (RESEARCH.md Pitfall 3) — the `if ticker_consensus:` guard handles this; Gemini did not raise it
- `compute_ticker_consensus()` double-compute risk — plan addresses it by storing to local variable; Gemini noted the code duplication concern but not the double-compute specifically

### Priority Action Items Before Execution

1. **(MEDIUM) Add `TickerConsensusSummary` cleanup to `conftest.py`** — prevents test pollution across runs. Affects: `tests/conftest.py`. Add: `await session.run("MATCH (n:TickerConsensusSummary) DETACH DELETE n")` to the teardown fixture.
2. **(MEDIUM) Consider a helper for round consensus persistence** — `_persist_round_consensus(cycle_id, round_num, consensus)` reduces the 3 identical blocks to 1. Risk of drift is real over future refactors. However, the plan's explicit inline approach is also defensible for clarity.
3. **(LOW) Template column count** — 8 columns is on the wide side. Consider consolidating "Consensus" + "Confidence" columns if readability is a concern in practice.
