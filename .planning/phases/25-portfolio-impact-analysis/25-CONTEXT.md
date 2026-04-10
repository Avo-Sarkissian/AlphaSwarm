# Phase 25: Portfolio Impact Analysis - Context

**Gathered:** 2026-04-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Parse a Schwab holdings CSV in-memory (no persistence), match held equity tickers against swarm consensus signals from Neo4j, identify coverage gaps, and generate an LLM-authored narrative comparing user positions to consensus — appearing in both the markdown and HTML post-simulation reports. Triggered via `alphaswarm report --portfolio /path/to/schwab.csv`.

</domain>

<decisions>
## Implementation Decisions

### CSV Parsing
- **D-01:** Target the raw Schwab export format (`Individual-Positions-*.csv`) — not the simplified `holdings.csv`
- **D-02:** Skip the 2 metadata rows at the top; row 3 is the actual column header row
- **D-03:** Filter to `Asset Type == "Equity"` rows only — ETFs and money market rows are excluded from matching (they will automatically appear as coverage gaps)
- **D-04:** Parse currency-formatted values (e.g., `"$26,416.56"`) by stripping `$`, `,`, and spaces before converting to float
- **D-05:** Holdings are never written to Neo4j or disk — loaded into an in-memory dict keyed by ticker symbol for the duration of the report run only

### Ticker-Entity Bridge
- **D-06:** Use a static `TICKER_ENTITY_MAP` constant — a dict mapping ticker symbols to one or more canonical entity name substrings that appear in simulation entity data (e.g., `"AAPL": ["Apple", "Apple Inc"]`)
- **D-07:** Match is performed against `read_entity_impact()` results — if any entity name for a ticker appears in the entity list (case-insensitive substring), the ticker is "covered"
- **D-08:** Tickers not found in the entity map (or found but without a match in entity_impact results) are listed as coverage gaps — ETFs will always be gaps since the swarm analyzes companies, not fund wrappers
- **D-09:** The `TICKER_ENTITY_MAP` starts populated for all equities currently in the Schwab portfolio (AAPL, AMZN, ARM, ASML, AVGO, BYDDY, COHR, DBX, HIMS, HON, ISRG, LPL, MRVL, NIO, NKE, NVDA, PLTR, PYPL, SCHW, SOFI, TLN, TSLA, TSM, VRT, VST) and can be extended as new positions are added

### LLM Narrative via ReACT Tool
- **D-10:** New `portfolio_impact` tool added to the ReACT engine's `tools` dict in `_handle_report()` — only when `--portfolio` is provided
- **D-11:** The tool function returns structured data: `matched_tickers` (list of `{ticker, shares, market_value, signal, confidence, entity_name}`), `gap_tickers` (list of `{ticker, shares, market_value}`), and `coverage_summary` stats
- **D-12:** The orchestrator's ReACT reasoning loop naturally synthesizes the narrative when it calls and observes `portfolio_impact` results alongside the other simulation tools — the narrative is part of the orchestrator's FINAL ANSWER synthesis, not a separate call
- **D-13:** A new Jinja2 template (`10_portfolio_impact.j2`) renders the structured data as a formatted table in the markdown report; `TOOL_TO_TEMPLATE` and `SECTION_ORDER` updated to include `"portfolio_impact"` — but only when the tool was actually called (guard on presence in observations)

### CLI Integration
- **D-14:** `--portfolio` flag added to the existing `report` argparse subparser — accepts a path string
- **D-15:** Portfolio parsing happens inside `_handle_report()` before the engine run — parsed holdings dict is passed into the tool closure as a captured variable
- **D-16:** If `--portfolio` is not provided (or path not found), `_handle_report()` behaves identically to current behavior — no regression

### Claude's Discretion
- Exact TICKER_ENTITY_MAP canonical name strings (as long as they match Neo4j entity naming)
- Template layout for the portfolio section (table structure, column order)
- Coverage gap display (table vs bullet list)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Report pipeline integration points
- `src/alphaswarm/cli.py` lines 633-740 — `_handle_report()` handler (model lifecycle, tool registry, format branching)
- `src/alphaswarm/cli.py` lines 763-776 — `report` argparse subparser definition (add `--portfolio` arg here)
- `src/alphaswarm/report.py` — `ReportEngine`, `ReportAssembler`, `TOOL_TO_TEMPLATE`, `SECTION_ORDER` (add portfolio_impact entries)

### Consensus data source
- `src/alphaswarm/graph.py` `read_entity_impact()` (line ~1359) — returns `[{entity_name, entity_type, avg_sentiment, mention_count, buy_mentions, sell_mentions, hold_mentions}]` — this is the consensus signal source for ticker matching

### Existing chart infrastructure (reuse for HTML)
- `src/alphaswarm/charts.py` `render_ticker_consensus()` (line 116) — already renders mini SVG per ticker from `{ticker, majority_signal, majority_pct}` dict
- `src/alphaswarm/templates/report/report.html.j2` lines ~272-290 — existing `market_context_data` slot in HTML template (portfolio tickers can render here)

### Reference CSV format
- `Schwab/Individual-Positions-2026-04-09-154713.csv` — canonical raw Schwab export to build parser against (has metadata header, currency formatting, mixed asset types)

### Requirements
- `.planning/REQUIREMENTS.md` — PORTFOLIO-01, PORTFOLIO-02, PORTFOLIO-03, PORTFOLIO-04

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ReportEngine` tool registry: already accepts a `dict[str, Callable]` — adding `"portfolio_impact"` is a one-liner in `_handle_report()` when `--portfolio` is provided
- `write_report()` / `write_sentinel()`: format-agnostic, no changes needed
- `render_ticker_consensus()` in charts.py: accepts `{ticker, majority_signal, majority_pct}` — can generate SVG bars for matched portfolio tickers
- `assemble_html()` `market_context_data` parameter: already threaded through to the HTML template; portfolio matched tickers can populate this list

### Established Patterns
- Tool closures in `_handle_report()`: all 8 current tools are lambdas capturing `gm` (graph_manager) and `cycle_id` — `portfolio_impact` follows the same pattern but also captures the parsed `holdings` dict
- `TOOL_TO_TEMPLATE` + `SECTION_ORDER`: canonical section ordering pattern — new portfolio section inserts as last numbered template (`10_portfolio_impact.j2`)
- Schwab CSV format: 2-row metadata header, row 3 = actual headers, "Positions Total" and "Cash & Cash Investments" as summary rows to detect and skip

### Integration Points
- `_handle_report()`: parse CSV before engine run, add tool to registry, pass market_context_data populated from matched holdings to `assemble_html()`
- `ReportAssembler.assemble()` and `assemble_html()`: no signature changes needed — portfolio section renders from `ToolObservation` if present in observations list
- argparse `report` subparser: add `--portfolio` string argument with `default=None`

</code_context>

<specifics>
## Specific Ideas

- The TICKER_ENTITY_MAP should cover all 25 equities currently in the Schwab portfolio (ETFs like QQQ/SPY/CHAT/CQQQ/WTAI will always be gaps — that's expected and useful output)
- Coverage gap output should clearly distinguish: (a) ETFs/non-equities (expected gaps, simulation doesn't model funds) vs (b) equities not mentioned in this specific simulation run

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 25-portfolio-impact-analysis*
*Context gathered: 2026-04-09*
