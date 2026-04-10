# Phase 24: HTML Report Export - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-09
**Phase:** 24-HTML Report Export
**Areas discussed:** Chart types & SVG approach, HTML template architecture, CLI integration & format flag, Report content & layout

---

## Chart Types & SVG Approach

| Option | Description | Selected |
|--------|-------------|----------|
| Horizontal bar charts | pygal HorizontalBar — BUY/SELL/HOLD stacked bars per bracket. Clean, compact, reads well in dark theme. | ✓ |
| Pie/donut charts | pygal Pie — one donut per bracket showing signal distribution. More visual but takes more space. | |
| Grouped vertical bars | pygal Bar — vertical bars grouped by bracket. Traditional but wider. | |

**User's choice:** Horizontal bar charts
**Notes:** None

| Option | Description | Selected |
|--------|-------------|----------|
| Line chart per signal | pygal Line — 3 lines (BUY/SELL/HOLD) across rounds 1-3. Shows convergence at a glance. | ✓ |
| Stacked area chart | pygal StackedBar per round — shows total distribution shifting. | |
| You decide | Let Claude pick the best visualization. | |

**User's choice:** Line chart per signal
**Notes:** None

| Option | Description | Selected |
|--------|-------------|----------|
| Inline SVG tags | pygal render_inline() — SVG XML directly in DOM. Smallest size, CSS-styleable. | ✓ |
| Base64 data URIs | pygal render_data_uri() — SVG as base64 in <img>. ~33% larger, not CSS-styleable. | |
| You decide | Let Claude pick the embedding approach. | |

**User's choice:** Inline SVG tags
**Notes:** None

| Option | Description | Selected |
|--------|-------------|----------|
| Mini horizontal bars per ticker | Small pygal HorizontalBar for each ticker. Mirrors TUI TickerConsensusPanel. | ✓ |
| Styled HTML table only | Rich HTML table with color-coded signal cells. No SVG overhead. | |
| You decide | Let Claude pick based on typical ticker count (up to 3). | |

**User's choice:** Mini horizontal bars per ticker
**Notes:** None

---

## HTML Template Architecture

| Option | Description | Selected |
|--------|-------------|----------|
| Single master HTML template | One new report.html.j2 with inline CSS + all sections. Existing .j2 templates untouched. | ✓ |
| Reuse existing .j2 partials | Convert 9 markdown .j2 templates to dual-format. More DRY but riskier. | |
| Separate HTML template per section | Mirror markdown approach: 9 HTML .j2 templates + master layout. | |

**User's choice:** Single master HTML template
**Notes:** None

| Option | Description | Selected |
|--------|-------------|----------|
| Inline in HTML template | All CSS in a <style> block inside .html.j2. Truly self-contained. | ✓ |
| Separate .css file bundled at build | CSS in standalone file, injected at render. Easier to edit but adds complexity. | |
| You decide | Let Claude pick. | |

**User's choice:** Inline in HTML template
**Notes:** None

---

## CLI Integration & Format Flag

| Option | Description | Selected |
|--------|-------------|----------|
| --format html flag on existing report command | `alphaswarm report --format html`. Minimal CLI surface change. | ✓ |
| Separate `export` subcommand | `alphaswarm export --html`. Cleaner separation but more boilerplate. | |
| You decide | Let Claude pick. | |

**User's choice:** --format html flag on existing report command
**Notes:** None

| Option | Description | Selected |
|--------|-------------|----------|
| reports/{cycle_id}_report.html | Same directory as markdown reports, just .html extension. | ✓ |
| exports/{cycle_id}.html | Separate exports/ directory. | |
| You decide | Let Claude pick. | |

**User's choice:** reports/{cycle_id}_report.html
**Notes:** None

---

## Report Content & Layout

| Option | Description | Selected |
|--------|-------------|----------|
| All 9 existing sections + charts | Every section with appropriate SVG chart or styled table. | ✓ |
| Curated top 5 sections | Only the most visually impactful sections. | |
| You decide | Let Claude determine. | |

**User's choice:** All 9 existing sections + charts
**Notes:** None

| Option | Description | Selected |
|--------|-------------|----------|
| Single-column scrolling page | Clean vertical flow. Reads like a professional research note. | |
| Dashboard-style grid | 2-column layout with charts side-by-side, tables below. | ✓ |
| You decide | Let Claude pick. | |

**User's choice:** Dashboard-style grid
**Notes:** Charts side-by-side at top, text/table sections full-width below

## Claude's Discretion

- Exact dark theme color palette
- pygal chart configuration details (tooltips, legends, sizing)
- Responsive breakpoints for the grid layout
- Print-friendliness CSS tweaks

## Deferred Ideas

None — discussion stayed within phase scope
