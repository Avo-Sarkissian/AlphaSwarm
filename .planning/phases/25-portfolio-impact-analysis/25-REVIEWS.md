---
phase: 25
reviewers: [gemini, codex]
reviewed_at: 2026-04-09T00:00:00Z
plans_reviewed:
  - 25-01-PLAN.md
  - 25-02-PLAN.md
---

# Cross-AI Plan Review — Phase 25

## Gemini Review

# Phase 25: Portfolio Impact Analysis - Plan Review

## 1. Summary
The implementation plans for Phase 25 are high-quality, architecturally sound, and strictly adhere to the technical constraints of the AlphaSwarm project. The strategy of decoupling the data parsing (Plan 25-01) from the ReACT orchestration (Plan 25-02) is excellent. By injecting the portfolio analysis as a dynamic "Tool" within the ReACT engine, the system leverages the LLM's reasoning capabilities to generate the narrative (PORTFOLIO-04) without adding redundant specialized LLM calls. The use of `asyncio.to_thread` for CSV processing and the strict "in-memory only" approach for sensitive financial data demonstrate a strong understanding of both performance and privacy requirements.

## 2. Strengths
- **Decoupled Architecture:** Separating the Schwab-specific parsing logic into a standalone `portfolio.py` ensures the core simulation engine remains agnostic to specific brokerage formats.
- **ReACT Tool Injection:** Using a tool closure for `portfolio_impact` is a sophisticated way to provide the LLM with context-on-demand, preventing context window bloat by only providing the data if the LLM decides to perform the analysis.
- **Async Compliance:** Wrapping synchronous file I/O in `to_thread` prevents the main event loop from blocking during CSV parsing, which is critical for maintaining TUI responsiveness.
- **Privacy-First Design:** Adherence to D-05 (no persistence to Neo4j or disk) is a key safety feature for a local-first financial tool.
- **Dynamic Prompting:** The refactoring of `REACT_SYSTEM_PROMPT` into a factory function is a necessary and well-spotted requirement for expanding the agent's toolset.

## 3. Concerns

- **Ticker Substring Collision (MEDIUM):** D-07 specifies "case-insensitive substring match." Short tickers (e.g., "ARM", "VRT") might accidentally match unrelated entities in the swarm (e.g., "ARM" matching "AL**ARM**" or "VRT" matching "AD**VRT**ISEMENT"). Risk: Incorrect consensus signals mapped to user positions.
- **CSV Header Fragility (LOW):** Schwab's export format can vary slightly by region or account type. Relying on "Row 3" as a hardcoded header start (D-02) is a common point of failure for CSV parsers. Risk: Parser failure if Schwab updates their export template.
- **LLM "Lazy Tooling" (MEDIUM):** In Plan 25-02 Task 2, the tool is added to the engine. However, if the `FINAL ANSWER` is generated without the LLM explicitly calling the `portfolio_impact` tool, the narrative will be missing. Risk: Inconsistent report generation where the portfolio section is empty because the LLM chose a different reasoning path.
- **Encoding Issues (LOW):** Financial CSVs sometimes use `utf-8-sig` (BOM) or `latin-1`. Risk: `UnicodeDecodeError` when reading the user's file.

## 4. Suggestions

- **Refine Ticker Matching:** Use word boundaries or strict equality for the ticker mapping. Instead of a simple `in` check, use a regex like `fr"\b{ticker}\b"` or ensure the `TICKER_ENTITY_MAP` values are sufficiently unique to prevent partial-word collisions.
- **Header Detection:** Instead of strictly skipping 2 rows, implement a simple "header finder" that searches the first 5 rows for the string "Symbol" or "Asset Type" to identify the correct header row dynamically.
- **Prompt Coercion:** In `build_react_system_prompt()`, when `include_portfolio=True` is passed, add a specific instruction to the LLM: *"If portfolio data is available via the portfolio_impact tool, you MUST include a summary of swarm consensus vs. user positions in your FINAL ANSWER."* This ensures PORTFOLIO-04 is consistently met.
- **Currency Parsing Robustness:** Ensure the stripping logic (D-04) handles parentheses for negative values (e.g., `($1,000.00)`), which is common in financial exports.
- **Explicit Encoding:** Default to `encoding='utf-8-sig'` in `aiofiles.open` or `open` to handle potential Byte Order Marks (BOM) from Excel-generated CSVs.

## 5. Risk Assessment: LOW

The plans are very low risk. They do not modify the core simulation logic, do not impact the Neo4j schema, and do not introduce new external dependencies. The primary risks are "soft" failures (mis-mapping a ticker or the LLM failing to write a good narrative), which do not crash the system or corrupt data. The implementation uses established patterns (Jinja2, ReACT tools) already present in the codebase.

---

## Codex Review

## Overall Summary

The two-plan split is sensible: Plan 25-01 isolates parsing and portfolio-impact construction, while Plan 25-02 handles runtime wiring, prompt behavior, CLI integration, and HTML output. The main risks are not scope size but ambiguity: what counts as "not persisted," whether non-equity holdings should truly be excluded or reported as gaps, and whether relying on the ReACT loop to voluntarily call `portfolio_impact` is deterministic enough to satisfy the reporting requirements. With a few clarifications and stronger tests around malformed CSVs, privacy, and tool invocation, the phase looks achievable.

## Plan 25-01: Data Layer

### Summary

Plan 25-01 has a good boundary: parse Schwab holdings, map them to existing entity-impact output, and register a report section without pulling in CLI or LLM orchestration concerns. The design is mostly appropriate for Wave 1, but it needs sharper data contracts, explicit privacy semantics, and better handling of excluded/non-equity holdings before implementation.

### Strengths

- Clean separation between pure data handling and runtime integration.
- `parse_schwab_csv_async()` using `asyncio.to_thread()` is acceptable for avoiding blocking file I/O on the main event loop.
- Static `TICKER_ENTITY_MAP` is simple and matches the user decision.
- `build_portfolio_impact()` depending on `read_entity_impact()` keeps the bridge aligned with existing simulation output.
- Adding tests at this layer is the right move because CSV parsing and ticker matching are easy to regress.
- No Neo4j writes and no additional persistence are consistent with the local-first/privacy intent.

### Concerns

- **HIGH:** There is a contradiction around non-equity rows. D-03 says filter to `Asset Type == "Equity"` only, but also says ETFs and money market positions "appear as coverage gaps." If the parser drops them entirely, they cannot appear as gaps.
- **HIGH:** "Holdings never written to Neo4j or disk" conflicts with adding markdown/HTML report templates that may write holdings-derived data to report files. The plan needs to define whether generated reports are an allowed exception.
- **MEDIUM:** `dict[str, dict]` is weak for a strict-typing Python project. Portfolio rows and impact results should use `TypedDict`, dataclasses, or Pydantic models.
- **MEDIUM:** Currency parsing needs more edge cases than `$26,416.56`: blanks, `N/A`, negative values, accounting negatives like `($1,234.56)`, zeroes, and quoted fields.
- **MEDIUM:** Duplicate tickers are unspecified. If a Schwab export contains multiple rows for the same ticker, the parser needs to aggregate, reject, or deterministically choose one.
- **MEDIUM:** Case-insensitive substring matching can create false positives if entity names are broad. The map should probably support aliases and deterministic tie-breaking.
- **MEDIUM:** `build_portfolio_impact()` needs behavior for empty entity impact results, malformed graph-memory results, and graph-memory read failures.
- **LOW:** Markdown table output needs escaping for pipes, newlines, and unusual ticker/description values.
- **LOW:** The coverage summary shape should be specified precisely, including counts and possibly percentages.

### Suggestions

- Define explicit data models: `Holding`, `MatchedPortfolioTicker`, `PortfolioGap`, `PortfolioImpact`.
- Use `Decimal` for money fields rather than `float`.
- Clarify non-equity handling: equity_holdings (eligible for matching), excluded_holdings (ETFs, money market, options), gap_tickers (unmatched equities + optionally excluded holdings with a `reason`).
- Clarify privacy persistence: either generated reports are an intentional user-requested output target, or portfolio report sections should redact position values.
- Add parser tests for BOM/header quirks, missing required columns, empty files, malformed currency, quoted commas, duplicate tickers, non-equity rows.
- Consider changing `TICKER_ENTITY_MAP` values from a single substring to aliases: `dict[str, tuple[str, ...]]`.

### Risk Assessment: MEDIUM

The data-layer scope is manageable, but unresolved semantics around excluded holdings and report persistence could cause the implementation to satisfy the code plan while missing the actual product requirement.

## Plan 25-02: Integration Layer

### Summary

Plan 25-02 targets the right integration points: CLI argument, async parsing in `_handle_report()`, dynamic ReACT prompt construction, conditional tool registration, and HTML output. The biggest weakness is determinism. If the portfolio narrative and report sections depend on the LLM choosing to call `portfolio_impact`, the feature may be flaky even when the data layer works perfectly.

### Strengths

- Dynamic `build_react_system_prompt(include_portfolio: bool)` directly addresses the known prompt/tool mismatch risk.
- Keeping `REACT_SYSTEM_PROMPT = build_react_system_prompt()` preserves compatibility for existing call sites.
- Conditional tool registration avoids exposing unavailable tools when `--portfolio` is not provided.
- Parsing the portfolio before constructing the `ReportEngine` keeps the runtime state simple.
- Falling back to no-portfolio behavior protects existing report generation when the flag is omitted.

### Concerns

- **HIGH:** Relying on the ReACT loop to "naturally" call `portfolio_impact` is fragile. PORTFOLIO-04 requires narrative output in markdown and HTML; optional tool use may not satisfy that reliably.
- **HIGH:** Falling back silently or semi-silently on missing/unreadable portfolio paths may hide user mistakes. If the user explicitly passes `--portfolio`, failing fast is probably safer than producing a report without portfolio analysis.
- **HIGH:** `assemble_html()` depending on `sections` containing `portfolio_impact` "if called" repeats the determinism problem. If the model skips the tool, HTML sections disappear.
- **MEDIUM:** Tool observation shape must be well-defined. If ReACT stores tool outputs as strings, JSON blobs, markdown, or dicts inconsistently, HTML rendering will become brittle.
- **MEDIUM:** Prompt/tool consistency needs tests in both directions: portfolio absent means no tool description and no tool registration; portfolio present means both are enabled.
- **MEDIUM:** Privacy-sensitive portfolio data may be included in LLM prompts, logs, and report files. Local Ollama is acceptable, but logs and report files need explicit handling.
- **MEDIUM:** `ReportEngine.__init__` changes may affect every call site. The plan should include a compatibility audit.
- **LOW:** CLI ergonomics: `Path` handling, helpful error messages, relative path resolution.

### Suggestions

- Make portfolio analysis deterministic: when `--portfolio` is provided, call `portfolio_impact` once before or during report assembly and inject the observation into the report context. The ReACT narrative can still synthesize from that observation.
- If keeping ReACT-only approach, update the system prompt to say the model **must** call `portfolio_impact` when available, and add an integration test with a fake model/tool recorder.
- Treat explicit `--portfolio` failures as errors by default. Missing file, unreadable file, malformed required columns, or zero parseable holdings should produce a clear CLI error.
- Ensure no portfolio contents are logged. Log only path-level errors and aggregate counts.
- HTML should render structured portfolio data with escaping, not raw model text. Use Jinja autoescape or explicit `|e`.
- Add integration tests for: no `--portfolio` regression, with `--portfolio` registers tool, unreadable path behavior, output in markdown and HTML, LLM receives context only when requested, no Neo4j writes attempted.

### Risk Assessment: MEDIUM-HIGH

The integration design is directionally right, but the current plan leaves too much to probabilistic ReACT behavior. For a reporting feature, deterministic portfolio-section generation is important.

---

## Consensus Summary

### Agreed Strengths

- **Decoupled data layer** (Plan 01 is side-effect-free, Plan 02 wires) — both reviewers praised the separation
- **`asyncio.to_thread` for CSV I/O** — both confirmed this is the correct async pattern
- **No-persistence design** for raw holdings — both praised as privacy-correct
- **Dynamic `build_react_system_prompt()`** refactor — both identified this as a necessary and well-spotted requirement

### Agreed Concerns (Highest Priority)

1. **ReACT tool non-determinism (MEDIUM–HIGH):** Both reviewers flagged that the LLM may skip calling `portfolio_impact` entirely, leaving the portfolio section empty or absent from the report. PORTFOLIO-04 requires narrative in both markdown AND HTML — leaving this to probabilistic tool use is risky. **Fix:** Add a mandatory instruction in `build_react_system_prompt(include_portfolio=True)` stating the model MUST call `portfolio_impact` when it is available, or pre-call the tool and inject the result directly into `assemble()` / `assemble_html()`.

2. **Ticker substring false positives (MEDIUM):** Both reviewers noted that case-insensitive substring matching (e.g., "ARM" matching "ALARM") can cause incorrect consensus signals. **Fix:** Use word-boundary matching (`\bARM\b`) or ensure `TICKER_ENTITY_MAP` values are long enough to be unambiguous.

3. **Currency parsing edge cases:** Both flagged accounting-style negative values `($1,234.56)` as a gap in the strip logic. D-04 describes stripping `$`, `,`, spaces, and parens — but the plan's acceptance criteria should include an explicit test for negative value handling.

### Divergent Views

- **Overall risk level:** Gemini rates LOW; Codex rates MEDIUM overall (MEDIUM-HIGH for Plan 02). The difference is mainly in how much weight each reviewer places on ReACT non-determinism and the non-equity gap contradiction.
- **Non-equity handling (Codex HIGH, not mentioned by Gemini):** Codex flags a real contradiction — D-03 says filter to Equity rows only, but they're also described as appearing as coverage gaps. This needs a decision: either (a) keep two separate passes (parse all rows, separate by asset type), or (b) accept that ETFs never appear in gaps (they're just silently excluded). The CONTEXT.md `<specifics>` section implies (a) is desired: "Coverage gap output should clearly distinguish: ETFs/non-equities (expected gaps) vs equities not mentioned in this simulation run."
- **Type safety (Codex MEDIUM, not mentioned by Gemini):** Codex advocates for `TypedDict`/dataclasses over raw `dict[str, dict]`. Given the project's strict typing requirement in CLAUDE.md, this is worth considering but not blocking.
