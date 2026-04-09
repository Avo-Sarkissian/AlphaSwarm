# Stack Research: v4.0 Interactive Simulation & Analysis

**Domain:** Mid-simulation shock injection, simulation replay, HTML report export with charts, portfolio impact analysis
**Researched:** 2026-04-09
**Confidence:** HIGH
**Builds on:** v1-v3 stack research (validated, not re-evaluated here)

## Scope

This document covers ONLY the stack additions needed for v4.0 features. The validated stack (Python 3.11+, asyncio, uv, ollama >=0.6.1, neo4j >=5.28, textual >=8.1.1, pydantic, structlog, psutil, httpx, backoff, yfinance, Jinja2, aiofiles) is NOT re-evaluated.

## Critical Finding: One New Dependency

v4.0 requires exactly **one** new package: `pygal` for SVG chart generation in HTML reports. The other three features (shock injection, simulation replay, portfolio CSV parsing) are built entirely on existing dependencies and stdlib.

## Recommended Stack Additions

### New Dependencies

| Library | Version | Purpose | Why Recommended | Feature |
|---------|---------|---------|-----------------|---------|
| pygal | >=3.1.0 | SVG chart generation for HTML consensus visualizations | Zero runtime dependencies. Generates inline SVG strings that embed directly in Jinja2 HTML templates via `render()` or `render_data_uri()`. Lightweight (~100KB installed) vs Plotly's 9.9MB wheel. SVG output is vector-based (crisp at any DPI, any zoom). Supports bar, stacked bar, horizontal bar, pie, gauge, SolidGauge, and radar charts -- all chart types needed for consensus/bracket/ticker/influence visualization. Self-contained output with no external JavaScript or CSS required. Released 2025-12-09, supports Python >=3.8. LGPLv3+ license. | EXPORT-* |

### Stdlib Modules Used (No Install Needed)

| Module | Purpose | Feature |
|--------|---------|---------|
| `csv` | Parse Schwab CSV position exports | PORTFOLIO-* |
| `io.StringIO` | Handle CSV header preamble stripping | PORTFOLIO-* |
| `asyncio.Event` | Signal shock readiness between simulation rounds | SHOCK-* |

### Existing Dependencies -- No Version Changes

| Library | Current Pin | Status | Notes |
|---------|-------------|--------|-------|
| Jinja2 | >=3.1.6 | **Keep as-is.** | HTML report templates use the same `Environment`/`FileSystemLoader` pattern as existing markdown templates. Add `autoescape=True` for HTML template set. |
| aiofiles | >=25.1.0 | **Keep as-is.** | Async HTML file write, same as existing markdown report export. |
| neo4j | >=5.28,<6.0 | **Keep as-is.** | Replay queries use existing async driver. All cycle/round data already persisted. New queries are read-only Cypher filtered by cycle_id. |
| textual | >=8.1.1 | **Keep as-is.** | Shock injection uses existing `Input` widget pattern. Replay uses existing grid/panel rendering with different data source. |
| pydantic | >=2.12.5 | **Keep as-is.** | New models (`ShockEvent`, `PortfolioHolding`, `PortfolioSnapshot`) follow existing frozen BaseModel pattern. |
| ollama | >=0.6.1 | **Keep as-is.** | Shock re-processing and portfolio analysis use existing `OllamaClient.chat()` with orchestrator model. |

## Feature-by-Feature Stack Mapping

### SHOCK-*: Mid-Simulation Shock Injection

**New code, zero new dependencies.** Shock injection is an orchestration pattern.

| Component | Technology | Integration Point |
|-----------|-----------|-------------------|
| Shock event model | pydantic (existing) | New `ShockEvent(BaseModel, frozen=True)` mirroring `SeedEvent`: raw text, entities, sentiment. Reuses `SeedEntity` and `EntityType` from `types.py`. |
| Between-round signal | asyncio (existing) | `asyncio.Event` set by TUI when user submits shock text, awaited by simulation loop between rounds. Or: callback pattern matching existing `on_round_complete`. |
| TUI shock input | textual (existing) | Same `Input` widget pattern used for agent interviews. Show input field between rounds when simulation pauses. |
| Entity extraction | ollama (existing) | Orchestrator LLM processes shock text identically to seed rumor -- same `inject_seed()` extraction pipeline, producing entities and tickers. |
| Modifier regeneration | ollama (existing) | If shock changes market context, regenerate bracket modifiers via existing `generate_modifiers()` flow. |
| Graph persistence | neo4j (existing) | New `ShockEvent` node type linked to cycle via `[:SHOCKED_BY]` edge with round_injected property. Read by replay feature for faithful reconstruction. |
| Agent re-prompting | ollama (existing) | Next round's agent prompts include shock context prepended to peer decisions, same as market data enrichment pattern. |

**Key design decision:** The simulation loop in `simulation.py` already has hook points via the `on_round_complete` callback. Shock injection inserts between the callback return and the next `dispatch_wave()` call. The TUI sets an `asyncio.Event` and the simulation loop awaits it with a timeout (allowing auto-continue if no shock is injected within N seconds).

### REPLAY-*: Simulation Replay from Neo4j

**New code, zero new dependencies.** All data already lives in Neo4j.

| Component | Technology | Integration Point |
|-----------|-----------|-------------------|
| Cycle listing | neo4j (existing) | New Cypher query in `GraphStateManager`: `MATCH (c:Cycle) RETURN c.cycle_id, c.seed_rumor, c.created_at ORDER BY c.created_at DESC`. Returns available cycles for replay selection. |
| Decision retrieval | neo4j (existing) | Existing `read_peer_decisions()` pattern extended: `MATCH (d:Decision) WHERE d.cycle_id = $cid RETURN d ORDER BY d.round, d.agent_id`. All 300 decisions (100 agents x 3 rounds) fetched in one query. |
| Shock event retrieval | neo4j (existing) | `MATCH (s:ShockEvent)-[:SHOCKED_BY]->(c:Cycle {cycle_id: $cid}) RETURN s ORDER BY s.round_injected`. Needed for faithful replay of shocked simulations. |
| State reconstruction | StateStore (existing) | `StateStore.update_agent()` accepts agent_id + AgentDecision. Feed historical decisions sequentially, grouped by round. StateStore produces snapshots the TUI renders. |
| TUI rendering | textual (existing) | Same 10x10 grid, same panels, same color computation. The TUI does not know or care whether data comes from live simulation or replay. Swap the simulation Worker for a replay Worker. |
| Playback pacing | asyncio (existing) | `asyncio.sleep(0.3)` between agent updates for visual effect, `asyncio.sleep(2.0)` between rounds. Configurable via replay speed setting. |
| Run comparison | Neo4j queries + pydantic | Query two cycle_ids, compute delta metrics (signal distribution diff, confidence drift, bracket shifts). Render as a comparison view or additional report section. |

**Key design decision:** Replay is read-only. It never writes to Neo4j or triggers LLM calls. The StateStore/TUI pipeline is already decoupled from the simulation engine -- it just consumes `AgentDecision` objects. The replay module produces the same objects from stored data instead of live inference.

### EXPORT-*: HTML Report Export

**New dependency: pygal. Uses existing Jinja2 and aiofiles.**

| Component | Technology | Integration Point |
|-----------|-----------|-------------------|
| Chart generation | pygal (NEW) | Generate SVG chart strings in Python. Each chart type maps to a report section. Charts created during report assembly, before template rendering. |
| HTML templates | Jinja2 (existing) | New template directory `templates/report_html/` parallel to existing `templates/report/` (markdown). HTML templates use `autoescape=True` with `{{ chart_svg\|safe }}` for trusted pygal output. |
| Template rendering | Jinja2 `Environment` (existing) | Existing `ReportAssembler` pattern: `Environment(loader=FileSystemLoader(template_dir))`. Add an `html=True` flag to switch template directory and autoescape setting. |
| File export | aiofiles (existing) | `async with aiofiles.open(path, "w") as f: await f.write(html)`. Same as existing `write_report()` function. |
| Inline CSS | Jinja2 template (existing) | All CSS embedded in `<style>` block within the HTML template head. No external stylesheet files needed. Single self-contained .html file output. |
| Section assembly | Existing `ReportAssembler.assemble()` | Extend to accept `output_format: Literal["markdown", "html"]`. When "html", load from `report_html/` templates, inject chart SVGs into template context alongside data. |

**Chart type mapping:**

| Report Section | Chart Type | Pygal Class |
|----------------|-----------|-------------|
| Consensus Summary | Pie chart (BUY/SELL/HOLD split) | `pygal.Pie` |
| Round Timeline | Grouped bar (signals per round) | `pygal.Bar` |
| Bracket Narratives | Stacked bar (bracket signal distribution) | `pygal.StackedBar` |
| Influence Leaders | Horizontal bar (top agents by citation count) | `pygal.HorizontalBar` |
| Signal Flip Analysis | Sankey-style or stacked bar (flip transitions) | `pygal.StackedBar` |
| Ticker Consensus | Gauge (weighted confidence score 0-1) | `pygal.SolidGauge` |
| Market Context | Bar (consensus vs market indicator comparison) | `pygal.Bar` |
| Portfolio Impact | Horizontal bar (holding exposure by signal) | `pygal.HorizontalBar` |

**Pygal SVG embedding pattern:**

```python
import pygal

# Generate chart
chart = pygal.Pie(inner_radius=0.4, style=custom_style)
chart.title = "Consensus Distribution"
chart.add("BUY", buy_count)
chart.add("SELL", sell_count)
chart.add("HOLD", hold_count)

# Get inline SVG string for Jinja2
svg_string = chart.render(is_unicode=True)

# In Jinja2 HTML template: {{ consensus_chart|safe }}
```

**Pygal style customization:**

```python
from pygal.style import Style

alphaswarm_style = Style(
    background="transparent",
    plot_background="transparent",
    foreground="#e0e0e0",
    foreground_strong="#ffffff",
    foreground_subtle="#808080",
    colors=("#4CAF50", "#f44336", "#FFC107"),  # BUY=green, SELL=red, HOLD=amber
    font_family="system-ui, -apple-system, sans-serif",
)
```

### PORTFOLIO-*: Portfolio Impact Analysis

**New code, zero new dependencies.** Stdlib `csv` handles Schwab CSV format.

| Component | Technology | Integration Point |
|-----------|-----------|-------------------|
| CSV parsing | csv (stdlib) | `csv.DictReader` with header preamble skip. Schwab exports have 2-line preamble (account info line, blank line) before the actual CSV header row. Strip `$`, `,`, `%`, whitespace from numeric fields. |
| Data model | pydantic (existing) | New `PortfolioHolding(BaseModel, frozen=True)` with fields: symbol, description, quantity, price, market_value, cost_basis, gain_loss_pct, asset_type. New `PortfolioSnapshot` as container. |
| Holdings cache | aiofiles + json (existing) | Cache parsed holdings to `data/portfolio_cache/` (already in .gitignore). Avoid re-parsing on every simulation run. Same atomic temp-file-rename pattern as market data cache. |
| Overlap detection | Python set ops (stdlib) | Intersect portfolio symbols with simulation ticker_decisions. Flag holdings that have consensus signals. Compute exposure-weighted impact. |
| Impact analysis | ollama (existing) | Orchestrator LLM receives a combined prompt: portfolio holdings summary + consensus signals per overlapping ticker + market data context. Produces natural-language portfolio impact assessment. |
| Report section | Jinja2 (existing) | New template `10_portfolio_impact.j2` (markdown) and corresponding HTML template. Renders holdings table, overlap analysis, and LLM-generated impact narrative. |
| Config | pydantic-settings (existing) | `portfolio_csv_path: Path \| None = None` in `AppSettings`. When None, portfolio analysis is silently skipped. When set, parsed at simulation startup alongside market data. |

**Schwab CSV parsing specifics (verified against actual exports):**

```python
import csv
from io import StringIO

def parse_schwab_positions(raw_text: str) -> list[dict]:
    """Parse Schwab position export CSV, handling 2-line preamble."""
    lines = raw_text.strip().split("\n")

    # Skip preamble: line 1 = "Positions for account...", line 2 = blank
    # Line 3 = actual CSV header (Symbol, Description, Qty, ...)
    csv_start = 2
    for i, line in enumerate(lines):
        if line.startswith("Symbol,") or line.startswith('"Symbol"'):
            csv_start = i
            break

    reader = csv.DictReader(lines[csv_start:])
    holdings = []
    for row in reader:
        symbol = row.get("Symbol", "").strip()
        if not symbol or symbol == "Account Total":
            continue
        holdings.append({
            "symbol": symbol,
            "quantity": _parse_numeric(row.get("Qty (Quantity)", row.get("Qty", "0"))),
            "market_value": _parse_currency(row.get("Mkt Val (Market Value)", "0")),
            "cost_basis": _parse_currency(row.get("Cost Basis", "0")),
            "gain_loss_pct": _parse_pct(row.get("Gain % (Gain/Loss %)", "0")),
        })
    return holdings

def _parse_currency(val: str) -> float:
    """Strip $, commas, quotes, whitespace from Schwab currency fields."""
    return float(val.replace("$", "").replace(",", "").replace('"', "").strip() or "0")

def _parse_pct(val: str) -> float:
    """Strip % from Schwab percentage fields."""
    return float(val.replace("%", "").replace(",", "").strip() or "0")

def _parse_numeric(val: str) -> float:
    """Parse numeric field, stripping commas and quotes."""
    return float(val.replace(",", "").replace('"', "").strip() or "0")
```

**Also supports consolidated `holdings.csv` format:** simpler 4-column CSV (account, symbol, shares, cost_basis_per_share) with no preamble. Auto-detect format by checking first line.

## Installation

```bash
# Single new dependency
uv add "pygal>=3.1.0"
```

Updated `pyproject.toml` dependencies section:

```toml
dependencies = [
    "pydantic>=2.12.5",
    "pydantic-settings>=2.13.1",
    "structlog>=25.5.0",
    "psutil>=7.2.2",
    "ollama>=0.6.1",
    "backoff>=2.2.1",
    "neo4j>=5.28,<6.0",
    "textual>=8.1.1",
    "jinja2>=3.1.6",
    "aiofiles>=25.1.0",
    "yfinance>=1.2.0",
    # v4 addition
    "pygal>=3.1.0",
]
```

## Alternatives Considered

| Recommended | Alternative | Why Not Alternative |
|-------------|-------------|---------------------|
| **pygal >=3.1.0** | Plotly 6.7.0 | Plotly's wheel is 9.9MB. Self-contained HTML exports bundle ~3MB of plotly.js per file. On a memory-constrained M1 Max running 2 LLMs, dependency weight matters. Plotly's interactive features (zoom, pan, hover) are unnecessary for a static shareable report. Pygal SVG is tiny, vector, self-contained, and includes built-in tooltips without JavaScript. |
| **pygal >=3.1.0** | matplotlib + base64 | matplotlib generates raster PNGs requiring base64 encoding into `<img>` tags. Blurry on high-DPI/Retina screens, larger encoded file sizes, zero interactivity. matplotlib itself is ~30MB installed with C extensions. Pygal SVG is vector, crisp at any zoom on any screen, and includes hover tooltips natively. |
| **pygal >=3.1.0** | Altair / Vega-Lite | Altair generates Vega-Lite JSON specs requiring the Vega runtime (~1MB JavaScript). More complex embedding than pygal's direct SVG render. Better suited for exploratory notebook analysis than self-contained static reports. |
| **csv (stdlib)** | pandas | pandas is 80MB+ installed with numpy. Schwab CSV has <100 rows with simple structure. `csv.DictReader` handles it in ~30 lines. pandas would add import latency (~500ms cold), memory overhead, and massive install bloat for zero functional benefit. |
| **csv (stdlib)** | polars | Same argument as pandas. Polars excels at large datasets. A 50-row portfolio CSV does not qualify. |
| **asyncio.Event** (shock signaling) | Redis pub/sub | AlphaSwarm is single-process. Inter-component communication happens within one asyncio event loop. Redis would add a network dependency, Docker service, and connection management for what is a single boolean signal. |

## What NOT to Add

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| pandas / polars | Massive deps for trivial CSV (<100 rows) | `csv.DictReader` (stdlib) |
| plotly | 9.9MB package, 3MB JS per HTML file | pygal (100KB, zero deps, SVG) |
| matplotlib | Raster output, 30MB installed, base64 encoding | pygal (vector SVG, inline) |
| weasyprint | PDF export not in v4.0 scope; requires Cairo/Pango C deps | Defer to v5.0 if PDF needed |
| dash / streamlit | Web framework overhead for file export | Jinja2 + pygal static HTML |
| schwab-api / schwab-py | Trade execution is out of scope | `csv.DictReader` for position CSV only |
| any embedding model / RAG lib | 2-model Ollama limit; RAG deferred | Neo4j Cypher queries |
| websockets | Single-process; all communication is in-loop | asyncio.Event, callbacks |
| SQLite / DuckDB | Replay state is already in Neo4j | Neo4j Cypher queries |
| Redis | No distributed components | asyncio primitives |

## Dependency Impact Summary

| Metric | Before v4.0 | After v4.0 | Delta |
|--------|-------------|------------|-------|
| Runtime dependencies (pyproject.toml) | 11 packages | 12 packages | +1 (pygal) |
| Approximate installed size | ~150MB | ~150.1MB | +~100KB |
| New C extensions | 0 | 0 | 0 |
| New system-level deps | 0 | 0 | 0 |
| New Docker services | 0 | 0 | 0 |

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| pygal >=3.1.0 | Python >=3.8 | Pure Python, no C extensions. Latest release 2025-12-09. Tested with 3.11+. |
| pygal >=3.1.0 | Jinja2 >=3.1.6 | Independent: pygal renders SVG strings, Jinja2 embeds them. No API coupling. |
| pygal >=3.1.0 | textual >=8.1.1 | Independent: pygal runs during report export only, never during TUI rendering. |
| csv (stdlib) | Python >=3.11 | Always available. DictReader stable for 15+ years. |

## Model Strategy for v4 Features

| Feature | Model | Why | Memory Impact |
|---------|-------|-----|---------------|
| Shock entity extraction | Orchestrator (qwen3.5:35b) | Reuses seed injection pipeline. Orchestrator already loaded if shock happens between rounds. | None -- orchestrator loaded during simulation. But if unloaded between rounds, requires ~30s cold load. Design decision: keep orchestrator loaded for shock-enabled sims. |
| Shock modifier regeneration | Orchestrator (qwen3.5:35b) | Same as seed modifiers. | None. |
| Portfolio impact analysis | Orchestrator (qwen3.5:35b) | Needs reasoning to synthesize consensus + holdings + market data into actionable narrative. | Runs post-simulation when orchestrator is loaded for report generation. No additional model swap. |
| Simulation replay | N/A | No LLM calls. Pure data retrieval and state reconstruction. | Zero. Replay is read-only. |
| HTML report charts | N/A (pygal) | Pure computation. No LLM needed for chart generation. | Negligible CPU. |

**Shock-enabled simulation model lifecycle:**
1. Load orchestrator for seed injection
2. Unload orchestrator, load worker for agent rounds
3. **NEW: Between rounds, if shock submitted:** unload worker, load orchestrator for shock extraction, unload orchestrator, reload worker for next round (~60s total swap overhead)
4. **Alternative (recommended):** Keep orchestrator loaded alongside worker for shock-enabled sims. This uses both model slots but eliminates swap latency. Only viable if combined model VRAM fits in 64GB. qwen3.5:35b (~20GB) + qwen3.5:9b (~6GB) = ~26GB, leaving ~38GB for system + Neo4j. Feasible.
5. Post-simulation: worker stays loaded for interviews, orchestrator loaded for report + portfolio analysis.

## Sources

- [pygal PyPI](https://pypi.org/project/pygal/) -- v3.1.0, released 2025-12-09, Python >=3.8, zero runtime deps (HIGH confidence)
- [pygal output documentation](https://www.pygal.org/en/stable/documentation/output.html) -- render(), render_data_uri(), render_tree() methods (HIGH confidence)
- [pygal chart types](https://www.pygal.org/en/stable/documentation/types/index.html) -- bar, stacked bar, pie, gauge, SolidGauge, horizontal bar, radar (HIGH confidence)
- [pygal web embedding](https://pygal.org/en/stable/documentation/web.html) -- inline SVG + Jinja2 integration patterns (HIGH confidence)
- [Plotly PyPI](https://pypi.org/project/plotly/) -- v6.7.0, 9.9MB wheel, released 2026-04-09 (HIGH confidence)
- [Plotly HTML export docs](https://plotly.com/python/interactive-html-export/) -- write_html/to_html with include_plotlyjs options (HIGH confidence)
- [Plotly HTML file size discussion](https://github.com/plotly/plotly.py/issues/1226) -- ~3MB plotly.js per self-contained file (HIGH confidence)
- [Python csv vs pandas comparison](https://pytutorial.com/pandas-vs-csv-module-best-practices-for-csv-data-in-python/) -- csv module for lightweight use cases (MEDIUM confidence)
- [Schwab CSV format](https://help.wingmantracker.com/article/3178-charles-schwab-positions-csv-instructions) -- export structure verified against actual files in schwab/ directory (HIGH confidence)
- [Jinja2 HTML report generation patterns](https://www.justintodata.com/generate-reports-with-python/) -- Jinja2 + chart embedding workflows (MEDIUM confidence)
- [Neo4j async driver docs](https://neo4j.com/docs/api/python-driver/current/async_api.html) -- AsyncDriver for replay queries (HIGH confidence)

---
*Stack research for: AlphaSwarm v4.0 Interactive Simulation & Analysis*
*Researched: 2026-04-09*
*Builds on: v1/v2/v3 stack research (2026-03-24 through 2026-04-06)*
