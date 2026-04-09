# Phase 24: HTML Report Export - Context

**Gathered:** 2026-04-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Export simulation results as self-contained, shareable HTML files with professional SVG visualizations. Users run `alphaswarm report --format html` and receive a single `.html` file that opens in any browser without network access. File must stay under 1MB.

</domain>

<decisions>
## Implementation Decisions

### Chart Types & SVG Approach
- **D-01:** Consensus signals visualized as pygal HorizontalBar charts — BUY/SELL/HOLD stacked bars per bracket
- **D-02:** Round-over-round signal changes shown as pygal Line chart — 3 lines (BUY/SELL/HOLD) across rounds 1-3
- **D-03:** Per-ticker consensus gets mini pygal HorizontalBar charts (up to 3 tickers), mirroring TUI TickerConsensusPanel
- **D-04:** All SVGs embedded as inline SVG tags via pygal `render_inline()` — CSS-styleable, smallest size, dark theme inherits

### HTML Template Architecture
- **D-05:** Single master HTML template (`report.html.j2`) with new `assemble_html()` method on ReportAssembler — existing markdown .j2 templates stay untouched
- **D-06:** All CSS inline in a `<style>` block inside the `.html.j2` template — truly self-contained, no external files

### CLI Integration
- **D-07:** `--format html` flag added to existing `report` subcommand (default remains `md`). Same `--cycle` and `--output` flags work.
- **D-08:** Default HTML output path: `reports/{cycle_id}_report.html` — same directory as markdown reports, just `.html` extension

### Report Content & Layout
- **D-09:** All 9 existing report sections included in HTML report, each with appropriate SVG chart or styled HTML table
- **D-10:** Dashboard-style 2-column grid layout: charts side-by-side at top (consensus bars + round timeline), text/table sections full-width below
- **D-11:** Dark color scheme matching TUI minimalist aesthetic (per EXPORT-03)

### Claude's Discretion
- Exact dark theme color palette (as long as it matches TUI aesthetic)
- pygal chart configuration details (tooltips, legends, sizing)
- Responsive breakpoints for the grid layout
- Print-friendliness CSS tweaks

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing report pipeline
- `src/alphaswarm/report.py` — ReportEngine (ReACT loop), ReportAssembler (Jinja2 markdown assembly), write_report(), write_sentinel()
- `src/alphaswarm/cli.py` lines 698-796 — `_handle_report()` handler with model lifecycle, tool registry, output path logic
- `src/alphaswarm/templates/report/` — 9 existing Jinja2 markdown templates (01-09)

### CLI integration point
- `src/alphaswarm/cli.py` lines 824-832 — argparse `report` subcommand definition (add --format flag here)

### Data sources (graph queries used by report tools)
- `src/alphaswarm/graph.py` — GraphStateManager methods: read_consensus_summary, read_round_timeline, read_bracket_narratives, read_key_dissenters, read_influence_leaders, read_signal_flips, read_entity_impact, read_social_post_reach, read_market_context

### Requirements
- `.planning/REQUIREMENTS.md` — EXPORT-01, EXPORT-02, EXPORT-03

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ReportAssembler` class: Already uses Jinja2 with `FileSystemLoader` — adding `assemble_html()` alongside existing `assemble()` is natural
- `write_report()` async helper: Works with any string content, no markdown-specific logic
- `write_sentinel()`: Updates `.alphaswarm/last_report.json` — works regardless of format
- `TOOL_TO_TEMPLATE` and `SECTION_ORDER` dicts: Define the canonical section ordering
- 9 existing `.j2` templates: Define the data shape per section — HTML template can reference same data structures

### Established Patterns
- Jinja2 Environment with `FileSystemLoader` pointing at `templates/report/`
- `autoescape=False` for markdown output — HTML template should set `autoescape=True`
- Report data flows: ReACT engine collects `ToolObservation` list → assembler renders sections → single string output
- Market context data passed separately via `market_context_data` kwarg

### Integration Points
- `_handle_report()` in cli.py: Add format branching after observations are collected — same data, different assembler method
- `ReportAssembler.assemble_html()`: New method consuming same `observations` + `market_context_data`
- argparse: Add `--format` argument with choices `["md", "html"]` to report subparser
- Output path logic: Branch `.md` vs `.html` extension based on format flag

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 24-html-report-export*
*Context gathered: 2026-04-09*
