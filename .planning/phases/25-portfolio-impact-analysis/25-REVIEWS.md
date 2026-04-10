---
phase: 25
reviewers: [gemini, codex]
reviewed_at: 2026-04-10T00:00:00Z
plans_reviewed: [25-01-PLAN.md, 25-02-PLAN.md]
---

# Cross-AI Plan Review — Phase 25

## Gemini Review

This review evaluates **Plan 01 (Portfolio Data Layer)** and **Plan 02 (CLI Wiring and HTML Integration)** for Phase 25 of the AlphaSwarm project.

### Summary
The proposed plans are exceptionally well-architected, specifically in how they balance the flexibility of a ReACT-based LLM orchestrator with the need for deterministic report generation. By choosing to "pre-seed" the portfolio impact as a `ToolObservation`, the system guarantees that critical financial data appears in the final report even if the LLM's reasoning path fluctuates. The attention to detail regarding Schwab's specific CSV quirks (BOM, metadata rows, currency formatting) and the privacy-conscious logging demonstrates a high level of engineering maturity.

### Strengths
- **Deterministic Reliability:** The "pre-seeded observation" strategy elegantly solves the non-determinism inherent in ReACT agents. It ensures `PORTFOLIO-04` is met without risking "hallucinated" omissions where the LLM simply forgets to call the tool.
- **Robust Data Ingestion:** Dynamic header detection and UTF-8-sig support are critical for real-world CSV handling, especially for exports from financial institutions like Schwab which often include metadata headers.
- **Privacy-First Design:** Explicitly excluding position values from logs while maintaining counts for debugging (`D-05`, `Plan 01`) aligns with financial software best practices.
- **False-Positive Mitigation:** Using word-boundary regex for the Ticker-to-Entity bridge (e.g., preventing `ARM` from matching `ALARM`) is a sophisticated touch that prevents misleading consensus mapping.
- **Fail-Fast CLI:** Validating the CSV path before the simulation begins (Plan 02) prevents wasting expensive inference cycles on a report that would ultimately fail to render the portfolio section.

### Concerns
- **TypedDict Key Inconsistency (MEDIUM):** As noted in the review instructions, `ExcludedHolding` in Plan 01 lacks `market_value_display`, whereas Plan 02 or the template logic likely expects it for "Coverage Gaps." Since `PortfolioGap` is the union of unmatched equities and excluded holdings, the internal `PortfolioParseResult` must ensure all fields required for the final `PortfolioGap` are either present or computed during the bridge phase.
- **Async CSV Parsing (LOW):** Plan 01 specifies a `parse_schwab_csv_async` function. Python's standard `csv` module is blocking/synchronous. While CSVs are small, for strict adherence to "100% async," this should be wrapped in `asyncio.to_thread` or `run_in_executor` to avoid blocking the event loop during file I/O and CPU-bound parsing.
- **Static Mapping Fragility (LOW):** `TICKER_ENTITY_MAP` is hardcoded to 25 equities. While sufficient for the "Seed Rumor" scope, if a user provides a portfolio with "NVDA" but the Neo4j entity is stored as "Nvidia Corp" (and not in the map), it becomes a coverage gap despite being simulated. The plan relies heavily on the manual completeness of this 25-ticker map.

### Suggestions
- **Unified Display Helper:** Create a single utility function for currency/float-to-string conversion to ensure `market_value_display` is consistent across `MatchedPortfolioTicker` and `PortfolioGap`.
- **Schema Validation:** In Plan 01, add a check that ensures the "Asset Type" column actually exists after the dynamic header detection. If Schwab changes their export format, a clear "Missing 'Asset Type' column" error is better than a generic `KeyError`.
- **LLM Context Awareness:** Ensure the `build_react_system_prompt` explicitly tells the LLM: *"You have been provided with an initial observation containing portfolio impact data. Use this to synthesize your narrative."* This prevents the LLM from trying to "find" the data if it doesn't realize it's already in the history.
- **Aggregation Logic:** Explicitly define the "Majority Signal" logic for cases of a tie (e.g., 50 BUY mentions, 50 HOLD mentions). A stable fallback (e.g., preferring "HOLD" or "NEUTRAL") should be documented.

### Risk Assessment: LOW
The risk is low because the implementation path is highly decoupled. The data layer (Plan 01) can be fully verified with unit tests before being wired into the CLI. The deterministic seeding approach removes the primary failure mode of agentic workflows (task omission). The most significant "risk" is simply the manual effort required to maintain the `TICKER_ENTITY_MAP`, which is mitigated by the clear success criteria of 25 specific equities.

---

## Codex Review

### Plan 01: Portfolio Data Layer

**Summary**
Plan 01 is a solid foundation for the portfolio feature and mostly aligns with PORTFOLIO-01 through PORTFOLIO-03. The parser and bridge are intentionally testable, privacy-aware, and scoped around in-memory data. The main risk is that the plan slightly expands beyond the stated user decisions by preserving and reporting non-equity holdings, while D-03 says ETFs and money market positions are excluded. The word-boundary matching is a good quality improvement over raw substring matching, but it should be reconciled with D-07 and carefully tested against real entity names.

**Strengths**
- Clean separation of concerns: parser, ticker mapping, impact builder, and template are isolated from CLI/runtime wiring.
- In-memory-only portfolio handling directly supports PORTFOLIO-01 and the privacy requirement.
- Duplicate ticker aggregation is important and practical for Schwab exports.
- Currency parsing edge cases are well identified, including negatives, blanks, and placeholder values.
- Dynamic header detection plus UTF-8 BOM handling should make the parser resilient to real Schwab CSVs.
- Explicit `TypedDict` contracts improve implementation clarity between data layer, reports, and tests.
- Privacy logging rule is appropriate: counts and paths only, no shares or market values.
- Majority signal and confidence computation are deterministic and easy to test.
- Template-render tests are a good guardrail because this feature spans data and presentation.

**Concerns**
- **HIGH:** Non-equity handling may conflict with D-03. The decision says "Filter to Asset Type == Equity rows only — ETFs and money market excluded." Plan 01 preserves non-equities and emits them as `gap_tickers` with `reason="non_equity"`. That may surprise users because excluded holdings become visible in the portfolio impact report.
- **HIGH:** The plan modifies `src/alphaswarm/report.py` only for registry/template order, but `portfolio_impact` is supposed to be available to the ReACT tool system only when `--portfolio` is provided. Tool registration and template registration need to be clearly separated.
- **MEDIUM:** Word-boundary regex improves false-positive safety, but it diverges from D-07, which explicitly says case-insensitive substring matching. This is probably a good deviation, but it should be documented as an intentional refinement.
- **MEDIUM:** Multi-word and punctuation-heavy entity names can make regex matching fragile. Examples: `Hims & Hers`, `Taiwan Semiconductor Manufacturing`, `Charles Schwab`, ADR names, or entity strings with suffixes like `Inc.`, `Corp`, `Co.`.
- **MEDIUM:** `build_portfolio_impact()` depends on Neo4j-backed `read_entity_impact()` results. The plan should specify the exact async dependency shape, for example whether it receives `GraphMemory`, `cycle_id`, or pre-fetched entity impacts.
- **MEDIUM:** Async file parsing must avoid blocking the event loop. CSV parsing and file reads should be done with `asyncio.to_thread()` or an async file strategy.
- **MEDIUM:** `PortfolioGap.asset_type` is required, but unmatched equities may not naturally have a distinct asset type if `Holding` omits it. Either include `asset_type` in `Holding` or ensure it is always set to `"Equity"` for equity gaps.
- **LOW:** "25+ unit tests required" may be excessive for a data-layer slice unless the tests are well grouped. The quality bar matters more than the count.
- **LOW:** The map says 25 equities, but the list contains exactly 25 only if counted carefully. Tests should assert the expected ticker set so drift is obvious.
- **LOW:** `market_value_display` appears in matched/gap output but not in `Holding` or `ExcludedHolding`; that is fine if display formatting is output-only, but Plan 02 must not expect it earlier.

**Suggestions**
- Decide whether non-equities should appear in reports. If they should not, keep `excluded_holdings` for diagnostics/tests only and omit them from `gap_tickers`. If they should appear, update the requirement language because this changes user-facing behavior.
- Add `asset_type: str` to `Holding`, or define that equity gaps always emit `asset_type="Equity"`.
- Make the match strategy explicit: `TICKER_ENTITY_MAP[ticker]` values are regex-escaped canonical substrings matched case-insensitively with boundary-like guards.
- Prefer a safer regex than plain `\b` for entity phrases, such as negative lookaround: `(?<![A-Za-z0-9])...(?![A-Za-z0-9])`.
- Add tests for problematic matching cases: `ARM` vs `ALARM`, `HIMS` vs `Hims & Hers`, `SCHW` vs `Charles Schwab`, `TSM` vs `Taiwan Semiconductor`, and company suffix variants.
- Ensure the async parser performs file I/O and CSV parsing off the main loop.
- Add malformed CSV behavior: missing headers, missing required columns, invalid numeric values, duplicate rows with one malformed row, and empty equity set.
- Keep template rendering tolerant of missing optional fields to reduce report fragility.

**Risk Assessment: MEDIUM**
The core data-layer design is sound, but the non-equity reporting decision and matching semantics need clarification before implementation. The feature touches privacy-sensitive local portfolio data, report rendering, and Neo4j-derived simulation output, so small schema mismatches could propagate into Plan 02.

---

### Plan 02: CLI Wiring and HTML Integration

**Summary**
Plan 02 correctly identifies the biggest architectural risk: relying on the ReACT loop to call `portfolio_impact` would make PORTFOLIO-04 nondeterministic. Precomputing the portfolio impact and injecting it as a pre-seeded observation is the right direction for deterministic markdown/HTML output. However, the plan needs tighter contract handling between the pre-seeded observation, ReACT tool availability, report assembly, and HTML template expectations.

**Strengths**
- Deterministic pre-seeding directly addresses PORTFOLIO-04: the portfolio narrative/report data exists even if the LLM never calls the tool.
- Idempotent tool closure is a good compromise: the LLM can still reason over `portfolio_impact`, but the report does not depend on the call happening.
- `--portfolio` preserving current behavior when absent is the correct compatibility goal.
- Prompt/tool consistency tests are important because stale prompt/tool mismatches are common in ReACT systems.
- Fail-fast behavior for bad paths is user-friendly and avoids wasting a simulation run.
- HTML escaping test is a good security check, especially because CSV values and Neo4j-derived names may be user-controlled or model-influenced.
- De-duplication with pre-seeded observations winning is the right default if the LLM calls the tool again.
- Explicit test for deterministic section rendering is essential.

**Concerns**
- **HIGH:** Pre-seeding structured `portfolio_impact` guarantees deterministic data rendering, but it does not by itself guarantee an LLM-authored narrative unless the report engine deterministically asks the model to synthesize one using that observation. PORTFOLIO-04 requires an LLM-generated narrative in both markdown and HTML.
- **HIGH:** There is a possible ordering issue in `_handle_report()`: `build_portfolio_impact(parse_result, gm, cycle_id)` requires simulation consensus data from Neo4j. If `cycle_id` or entity impact data is only available after `engine.run()`, the portfolio impact cannot be computed before the engine run unless this report command is strictly post-simulation.
- **HIGH:** If the pre-seeded observation is inserted into `observations` but the ReACT prompt never processes it, the model may not incorporate it into the final narrative. The plan needs a defined mechanism for pre-seeded observations to enter the LLM context.
- **MEDIUM:** "No --portfolio = byte-identical to pre-phase-25 behavior" may be brittle. Even harmless prompt-builder refactoring or ordering differences can break byte identity. A behavioral equivalence test may be more maintainable unless exact output stability is a project requirement.
- **MEDIUM:** `build_react_system_prompt(include_portfolio: bool)` replacing a constant can create subtle prompt regressions. Tests should snapshot or assert the important tool instructions.
- **MEDIUM:** HTML template gets two section cards, but markdown template from Plan 01 creates one `10_portfolio_impact.j2`. The relationship between markdown sections, HTML sections, and observation names needs to be explicit.
- **MEDIUM:** TypedDict mismatch risk: Plan 02 appears to need display-ready values for HTML, but Plan 01's `ExcludedHolding` does not include `market_value_display`. Either HTML should consume `PortfolioGap`, not `ExcludedHolding`.
- **MEDIUM:** The plan says `portfolio_impact` tool is added only when `--portfolio` is provided, but Plan 01 says it registers the tool in `TOOL_TO_TEMPLATE` and `SECTION_ORDER`. Static report template registration is fine; runtime tool registration must remain conditional.
- **MEDIUM:** Bad path and malformed CSV are different failure modes. The plan mentions missing/malformed path, but malformed content should also fail cleanly with a concise error.
- **LOW:** "Two `.section` cards" is a fragile HTML test if class names change. Prefer testing semantic headings or data attributes.
- **LOW:** Logging privacy should include not logging the raw CSV path if the path can reveal account details or user names. Logging basename or a redacted path may be safer.

**Suggestions**
- Add an explicit narrative generation step after `portfolio_impact` is built. For example: render deterministic structured tables from `portfolio_impact`, then call the local orchestrator model with a constrained prompt to produce `portfolio_narrative`.
- Store narrative separately from structured data:
  ```python
  class PortfolioImpact(TypedDict):
      matched_tickers: list[MatchedPortfolioTicker]
      gap_tickers: list[PortfolioGap]
      coverage_summary: CoverageSummary
      narrative: str
  ```
  Or use a separate `portfolio_impact_narrative` observation if that fits the report system better.
- Clarify whether `_handle_report()` runs after a completed simulation or starts the report engine against an existing `cycle_id`. If consensus is generated during `engine.run()`, move portfolio impact construction after entity impact exists.
- Ensure pre-seeded observations are included in the ReACT conversation context before the first model call, not only appended to returned observations.
- Make de-duplication deterministic by keying on `tool_name`, with `portfolio_impact` pre-seeded result winning and duplicate LLM calls discarded.
- Keep runtime `tools` conditional on `--portfolio`, but allow static template registration so old reports can still render observations if present.
- Add an integration test where the model never calls tools but the final markdown and HTML still contain the structured portfolio section and the LLM narrative.
- Add an integration test where the model does call `portfolio_impact`; assert only one final section appears and the precomputed result wins.
- Define the template input contract clearly: HTML should consume `PortfolioImpact.gap_tickers`, not `ExcludedHolding`.
- Consider redacting the portfolio path in logs, or logging only `portfolio_file_provided=True` and aggregate counts.

**Risk Assessment: MEDIUM-HIGH**
The deterministic pre-seeding idea is strong, but there is still a critical ambiguity around when consensus data exists and how the LLM-authored narrative is guaranteed. If those are resolved, the implementation risk drops to medium. Without that clarification, the feature may render structured tables reliably while still failing PORTFOLIO-04's narrative requirement.

### Cross-Plan Findings (Codex)
- `ExcludedHolding` lacks `market_value_display`, while Plan 02's HTML/report path may expect display-ready values. Acceptable only if templates receive `PortfolioGap`, not raw `ExcludedHolding`.
- `PortfolioGap.asset_type` is required, but `Holding` omits `asset_type`. Equity gaps need a guaranteed value.
- `PortfolioImpact` currently has no narrative field, despite PORTFOLIO-04 requiring an LLM-authored narrative. Add one or define a separate observation/template contract.
- Plan 01 must land before Plan 02. Plan 02 depends on existing report lifecycle details: whether `cycle_id` and `read_entity_impact()` data already exist before `_handle_report()` starts the ReACT report engine.
- Pre-seeding satisfies deterministic availability of structured portfolio impact data but does not fully satisfy "LLM-generated narrative" unless the pre-seeded observation is passed into a local LLM narrative synthesis step.

**Overall Recommendation:** Proceed with Plan 01 after clarifying non-equity behavior and match semantics. Proceed with Plan 02 only after defining the lifecycle of consensus data and adding an explicit local LLM narrative generation contract.

---

## Consensus Summary

### Agreed Strengths
- **Deterministic pre-seeding** is the right architectural decision — both reviewers validate that pre-calling `build_portfolio_impact()` and injecting a `ToolObservation` removes the key failure mode of ReACT non-determinism
- **Word-boundary regex** matching is well-motivated (prevents `ARM` matching `ALARM`) — both reviewers praised this as a meaningful improvement over naive substring
- **Dynamic header detection + UTF-8-sig encoding** — both reviewers called this out as critical for real-world Schwab CSV resilience
- **Privacy-conscious logging** — counts and paths only, never position values — both reviewers affirmed this as appropriate for financial software
- **Fail-fast CLI** validation before the engine run — both reviewers agreed this prevents wasted inference on a doomed report
- **Async event-loop safety**: Both reviewers flagged that `parse_schwab_csv_async` must wrap synchronous `csv` work in `asyncio.to_thread()` (Codex MEDIUM, Gemini LOW)

### Agreed Concerns
1. **(MEDIUM, consensus)** **TypedDict key inconsistency**: `ExcludedHolding` lacks `market_value_display`; templates and HTML path must consume `PortfolioGap`, not raw `ExcludedHolding`. Only safe if the bridge converts all excluded holdings to `PortfolioGap` before any display path touches them.
2. **(MEDIUM, consensus)** **Async CSV parsing must use `asyncio.to_thread`**: `parse_schwab_csv_async` is backed by the synchronous `csv` module; wrapping in `asyncio.to_thread` is required for "100% async" compliance.
3. **(HIGH, Codex / implicit Gemini)** **PORTFOLIO-04 narrative guarantee**: Pre-seeding the structured `portfolio_impact` observation does NOT by itself guarantee an LLM-authored narrative. Gemini suggests adding explicit LLM context-awareness language in `build_react_system_prompt`; Codex recommends a deterministic post-processing LLM call or a `narrative: str` field in `PortfolioImpact`. Both agree the narrative cannot be left entirely to emergent ReACT behavior.
4. **(MEDIUM, consensus)** **`PortfolioGap.asset_type` for unmatched equities**: `Holding` omits `asset_type`, but equity gaps must emit `asset_type="Equity"`. The bridge code must explicitly hardcode this constant for unmatched equity rows.

### Divergent Views
- **Overall risk level**: Gemini rates Phase 25 as **LOW** risk because the deterministic seeding architecture removes the primary failure mode. Codex rates Plan 01 as **MEDIUM** and Plan 02 as **MEDIUM-HIGH**, citing PORTFOLIO-04 narrative ambiguity and the consensus-data ordering question. Worth investigating: confirm that `alphaswarm report` is always strictly post-simulation (i.e., `cycle_id` is from an existing completed simulation in Neo4j, not the current `engine.run()` cycle), which would resolve Codex's HIGH ordering concern.
- **Non-equity in gap_tickers**: Codex rates D-03 expansion as HIGH concern; Gemini did not flag it. The behavior (showing ETFs/money market as `non_equity` gaps) is arguably a UX improvement over silently dropping them, but it diverges from the literal text of D-03. User should confirm whether this behavior is intended.
- **Regex boundary approach**: Codex suggests `(?<![A-Za-z0-9])...(?![A-Za-z0-9])` lookaround as safer than `\b` for multi-word entity names with punctuation (`Hims & Hers`). Gemini did not raise this. Worth testing against actual Neo4j entity name corpus.
