# Project Research Summary

**Project:** AlphaSwarm v4.0 — Interactive Simulation & Analysis
**Domain:** Multi-agent LLM financial simulation — interactive feature expansion
**Researched:** 2026-04-09
**Confidence:** HIGH

## Executive Summary

AlphaSwarm v4.0 extends a proven, production-quality 3-round consensus simulation engine with four distinct capabilities: mid-simulation shock injection, simulation replay from Neo4j, self-contained HTML report export with SVG charts, and portfolio impact analysis against real Schwab holdings. The core simulation stack (Python 3.11+, asyncio, Ollama, Neo4j, Textual, Jinja2) is validated and unchanged. Only one new dependency is required: `pygal>=3.1.0` for SVG chart generation in HTML reports. Every other feature — shock injection, replay, CSV parsing — is built entirely from existing dependencies and stdlib, keeping the installed footprint at approximately 150MB unchanged.

The recommended approach treats all four features as independent modules that integrate at well-defined seams in the existing architecture. HTML export and portfolio analysis are purely post-simulation paths that do not touch `simulation.py`. Shock injection is the highest-risk feature because it inserts a pause point into the simulation's main loop, requiring coordinated suspension of the ResourceGovernor without resetting its TokenPool state. Replay is architecturally isolated but requires a purpose-built `ReplayStore` class — reusing the live `StateStore` for replay is a fundamental design mismatch that causes queue drain bugs, phase state corruption, and elapsed timer overwrite.

The primary risks are architectural rather than technological. Shock injection must implement `governor.suspend()`/`governor.resume()` before any inter-round logic is written, or the governor will enter false THROTTLED/PAUSED states during the inter-round pause. HTML export must commit to SVG charts (pygal) from the start — switching from Plotly after integration requires rewriting all chart generation functions. Portfolio data must be explicitly excluded from the ReACT observation chain and all Neo4j write paths from the first line of code; retrofitting data isolation is significantly harder than designing for it upfront.

## Key Findings

### Recommended Stack

The v4.0 stack adds exactly one package to the existing validated dependency set. The existing stack (Python 3.11+, asyncio, uv, ollama >=0.6.1, neo4j >=5.28, textual >=8.1.1, pydantic, structlog, psutil, httpx, backoff, yfinance, Jinja2, aiofiles) is not re-evaluated — it is proven across three prior milestones. The deliberate choice to add only one dependency reflects the goal of minimizing installed footprint on a memory-constrained system running two concurrent LLMs.

**Core technologies added:**
- `pygal>=3.1.0`: SVG chart generation for HTML reports — pure Python, zero runtime deps, ~100KB installed, vector output crisp at any DPI. Chosen over Plotly (9.9MB wheel, 3MB JS per HTML file) and matplotlib (30MB with C extensions, raster PNG requiring base64 encoding).
- `csv` (stdlib): Schwab CSV parsing — handles <100 rows with no external dependency. pandas/polars ruled out as 80MB+ for a trivial use case.
- `asyncio.Event` / `asyncio.Queue` (stdlib): Shock injection signaling between TUI and simulation loop — no Redis, no external message broker for a single-process application.

### Expected Features

**Must have (table stakes — v4.0 core):**
- SHOCK: ShockEvent type, Neo4j persistence, propagation to all agents in the next round
- SHOCK: TUI Input widget for interactive shock injection between rounds
- SHOCK: Before/after consensus comparison via ShiftMetrics
- REPLAY: Cycle listing from Neo4j, per-round decision reconstruction, TUI display via StateStore feed
- EXPORT: Single self-contained HTML file with SVG charts under 500KB, dark theme matching TUI
- PORTFOLIO: Schwab CSV parsing (both normalized 4-column and raw 16-column formats), consensus signal mapping to held tickers, coverage gap analysis (held tickers not in simulation)

**Should have (v4.x polish — add after core validates):**
- Shock-specific report section, adjustable replay playback speed, unrealized P&L impact projection, multi-account portfolio support, LLM-generated portfolio narrative

**Defer (v4.1+):**
- Side-by-side simulation comparison (complex TUI layout requiring two StateStore instances)
- Unlimited rounds after shock (breaks 3-round invariant, requires architectural rewrite)
- PDF export (WeasyPrint C deps, interactive charts become static)
- Real-time portfolio sync via Schwab API (OAuth2, compliance, ongoing token management)

### Architecture Approach

All four features integrate at specific seams in the existing v3.0 architecture without requiring changes to the core simulation logic. The design principle is additive: four new modules (`shock.py`, `replay.py`, `html_export.py`, `portfolio.py`) with narrow, typed integration points into existing modules. The TUI's 200ms snapshot-driven rendering is exploited by replay — which feeds the same StateStore interface from Neo4j reads instead of live inference. The report pipeline's Jinja2 + ToolObservation pattern is mirrored in HTML export with a parallel template set using `autoescape=True`.

**New modules:**
1. `shock.py` (~120 LOC): ShockEvent dataclass, prompt context formatter, Neo4j persistence. Integrates with `simulation.py` at the between-round seam via `asyncio.Queue[ShockEvent]` on StateStore.
2. `replay.py` (~250 LOC): Cycle listing, full-cycle Neo4j reads via `read_full_cycle()` with COLLECT aggregation, animated StateStore feeding with configurable per-agent and per-round delays.
3. `html_export.py` (~200 LOC): Parallel Jinja2 assembler using `templates/html_report/` with `autoescape=True`. Renders same `ToolObservation` data as markdown assembler. Chart SVGs injected via `{{ chart_svg|safe }}`.
4. `portfolio.py` (~300 LOC): Dual-format CSV parser, `Holding`/`PortfolioImpact` dataclasses, consensus cross-reference, single-call orchestrator LLM narrative. Runs post-ReACT, never enters observation chain.

**Modified files (all additive, ~510 LOC total across 7 files):**
- `simulation.py` (~60 LOC): shock queue poll between rounds, SHOCK_PENDING phase transitions
- `graph.py` (~200 LOC): replay and portfolio read methods, ShockEvent write
- `tui.py` (~100 LOC): ShockBanner widget, replay mode indicator, keybindings
- `cli.py` (~100 LOC): `replay` subcommand, `--format html`, `--portfolio` flag
- `state.py` (~20 LOC): `active_shock` and `cycle_id` fields on StateSnapshot
- `report.py` (~15 LOC): `portfolio_impact_data` parameter threading
- `config.py` (~10 LOC): `schwab_portfolio_path`, `shock_context_budget` settings

### Critical Pitfalls

Seven critical pitfalls were identified and verified directly against the existing codebase. The top five requiring proactive prevention:

1. **Governor state corruption during shock injection** — leaving the ResourceGovernor monitor running during the inter-round pause causes false THROTTLED/PAUSED transitions from unrelated system memory pressure. The fix is `governor.suspend()`/`governor.resume()` methods that pause the monitor loop without resetting the TokenPool. This must be implemented before any between-round pause logic is added.

2. **N+1 query explosion during replay load** — using existing per-round query methods in a loop produces 15+ query batches for a full cycle, saturating the Neo4j connection pool. The fix is a dedicated `read_full_cycle(cycle_id)` method using COLLECT + UNWIND aggregation to fetch all 300 decisions in 2-3 queries.

3. **Portfolio data leakage through ReACT observation chain** — if portfolio analysis is implemented as a ReACT tool, portfolio CSV data enters the `ToolObservation` accumulation chain and can reach Neo4j writes, structlog output, and Ollama KV cache. The fix is to run portfolio analysis as a post-ReACT step with isolated data flow, never entering the observation chain.

4. **StateStore/ReplayStore architecture conflict** — the live `StateStore` uses destructive reads (snapshot drains rationale queue), clears agent states on phase transitions, and has a single elapsed timer. Replay on the same store produces queue drain, ghost state, and timer corruption. A separate `ReplayStore` with random-access round snapshots is mandatory.

5. **HTML file size explosion from Plotly** — self-contained HTML with Plotly.js bundles 3MB+ of JavaScript per file; 15 charts produces a 15MB+ file. SVG charts via pygal produce a self-contained file under 500KB with 15 charts. This chart strategy decision must precede any chart generation code — switching from Plotly to pygal after integration requires rewriting all chart rendering functions.

## Implications for Roadmap

Architecture research identified an explicit dependency-aware build order, independently confirmed across all research files. The four phases below reflect the cross-feature dependency graph, risk profile, and pitfall prevention sequencing.

### Phase 1: HTML Export Foundation (EXPORT)

**Rationale:** Zero dependencies on other v4.0 features. Does not touch `simulation.py`. Establishes the HTML template infrastructure and `HtmlReportAssembler` that portfolio analysis will extend. Testable immediately against any existing Neo4j simulation data. Lowest risk, high-visibility output that validates the Jinja2 + pygal SVG pipeline before it is relied on by other features.
**Delivers:** `html_export.py`, `templates/html_report/` (12 templates + CSS), `--format html` CLI flag, pygal SVG chart generation with AlphaSwarm dark theme, self-contained HTML reports under 500KB.
**Addresses:** All EXPORT table stakes and dark theme differentiator.
**Avoids:** Pitfall 5 (SVG-first commitment before any chart code is written; file size assertion <1MB verified before feature ships).

### Phase 2: Portfolio Impact Analysis (PORTFOLIO)

**Rationale:** Depends only on Phase 1's HTML template infrastructure for the portfolio section template. Does not touch `simulation.py` or the governor. Pure post-simulation analysis path. Testable with CSV fixtures and existing Neo4j data — no live simulation required. Establishes the privacy-first data isolation pattern (no Neo4j writes, no structlog exposure, `keep_alive=0` for LLM call) before the simulation-touching phases begin.
**Delivers:** `portfolio.py`, dual-format Schwab CSV parser with fuzzy column matching, `Holding`/`PortfolioImpact` dataclasses, consensus cross-reference, coverage gap analysis, portfolio section in both markdown and HTML reports, `--portfolio PATH` CLI flag.
**Uses:** Existing Neo4j TickerConsensusSummary nodes, existing orchestrator LLM for narrative (post-ReACT, isolated call), existing aiofiles for async write.
**Avoids:** Pitfall 3 (portfolio data leakage) — isolation architecture designed from day one. Pitfall 7 (CSV schema drift) — fuzzy column matching and parameterized tests with 3+ format variants from the start.

### Phase 3: Shock Injection (SHOCK)

**Rationale:** Modifies `simulation.py` — the highest-risk file in the codebase. Deliberately deferred until non-invasive features (Phases 1-2) are stable and verified. The governor suspend/resume mechanism must be the first deliverable within this phase; the between-round pause logic depends on it. The shock is designed as a prompt context modifier, not a new simulation round — preserving the 3-round invariant that every downstream system depends on.
**Delivers:** `shock.py`, `ShockEvent` type + Neo4j persistence, `governor.suspend()`/`governor.resume()` (non-destructive pause), `asyncio.Queue[ShockEvent]` on StateStore, TUI ShockBanner widget, `SimulationPhase.SHOCK_PENDING`/`SHOCK_PROCESSING` states, CLI `--shock-after-round1`/`--shock-after-round2` flags, before/after ShiftMetrics with shock-attributed vs organic flip distinction.
**Uses:** Existing `on_round_complete` callback boundary in `simulation.py`, existing Textual Input widget pattern, existing pydantic BaseModel pattern.
**Avoids:** Pitfall 1 (governor corruption — suspend/resume is Phase 3's first deliverable, written before any pause logic). Pitfall 4 (influence topology invalidation — pre-shock weights kept for peer selection by design, shock is the new information agents react to).

### Phase 4: Simulation Replay (REPLAY)

**Rationale:** Must come last. Depends on ShockEvent Neo4j schema from Phase 3 to faithfully replay shock-affected simulations. Depends on all StateStore fields being finalized (Phase 3 adds `active_shock`). Most architecturally isolated feature: new module + new CLI subcommand, TUI receives a `ReplayStore` protocol instead of the live `StateStore`. `ReplayStore` must be the first deliverable within this phase before any TUI replay integration.
**Delivers:** `ReplayStore` class with random-access round snapshots (no destructive reads, no queue drain), `replay.py`, `read_full_cycle()` Neo4j query with COLLECT aggregation, `alphaswarm replay` CLI subcommand, round navigation keybindings (1/2/3 keys), "REPLAY" badge in TUI header, seed rumor + ticker display in cycle selector (not raw UUIDs).
**Uses:** All existing Neo4j data (decisions, posts, rationale, influence edges, ticker consensus, shocks). Zero LLM calls during replay.
**Avoids:** Pitfall 2 (N+1 queries — `read_full_cycle()` is designed first, verified <2s for 100-agent cycle). Pitfall 6 (StateStore corruption — `ReplayStore` is the first deliverable before TUI integration).

### Phase Ordering Rationale

- Phase 1 before Phase 2: The portfolio HTML section template requires the HTML template infrastructure established in Phase 1.
- Phases 1-2 before Phase 3: Non-invasive features verified stable before touching `simulation.py`. Reduces risk of regression during the most dangerous modification.
- Phase 3 before Phase 4: Replay must faithfully reconstruct shock-affected simulations. The ShockEvent Neo4j schema established in Phase 3 is consumed by Phase 4's replay queries.
- Governor suspend/resume first within Phase 3: Pitfall 1 is the most catastrophic failure mode — it can corrupt pool state mid-simulation. The suspend/resume mechanism must exist before the pause point is introduced.
- Phases 2 and 3 can be parallelized if two developers are available: they operate on completely different modules (portfolio.py + templates vs. simulation.py + shock.py). Phase 4 must wait for both.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 3 (SHOCK):** Governor suspend/resume implementation details. The 5-state machine and TokenPool debt tracking have documented bugs (bug_governor_deadlock.md, 7 bugs across prior sessions). Suspending without triggering state transitions or pool resets requires careful analysis of governor internals. Recommend `/gsd:research-phase` focused on governor.py before writing governor changes.
- **Phase 4 (REPLAY):** `read_full_cycle()` Cypher query design. COLLECT + UNWIND aggregation across 600+ nodes (100 agents x 3 rounds of decisions, posts, influence edges) needs performance profiling. Connection pool behavior under bulk reads needs verification against the per-round write pattern it was designed for.

Phases with standard patterns (skip research-phase):
- **Phase 1 (EXPORT):** Jinja2 HTML templates with autoescape, pygal SVG generation, and aiofiles async write are all well-documented with direct codebase analogs. No novel integration patterns.
- **Phase 2 (PORTFOLIO):** CSV parsing, pydantic dataclasses, and post-simulation LLM calls all follow existing codebase patterns. Data isolation is a design constraint, not a technical research problem.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Validated against the existing codebase. One new dependency (pygal) verified on PyPI with confirmed Python 3.11+ compatibility and zero runtime deps. All other stack elements have prior validation from v1-v3 milestones. |
| Features | MEDIUM-HIGH | Table stakes and anti-features are well-defined. P2/P3 feature scope is intentionally advisory — exact scope depends on how quickly P1 delivers. Side-by-side simulation comparison is deferred but may be pulled forward if the ReplayStore architecture enables it cleanly. |
| Architecture | HIGH | Based on direct codebase analysis of six key modules (simulation.py 1580 LOC, graph.py 1708 LOC, tui.py 1046 LOC, report.py 372 LOC, state.py 255 LOC, cli.py 890 LOC). Component boundaries, LOC estimates, and integration points are derived from the actual code, not external documentation. |
| Pitfalls | HIGH | Seven pitfalls verified against existing codebase logic, prior bug history (bug_governor_deadlock.md), and known Neo4j connection pool behavior. Recovery strategies tested against existing codebase patterns. |

**Overall confidence:** HIGH

### Gaps to Address

- **Governor suspend/resume API design:** The existing `governor.stop_monitoring()` is the only suspension mechanism and it resets pool state. During Phase 3 planning, audit `governor.py`'s internal state machine to confirm the exact fields that must be preserved (`_state`, `_pool`, `_crisis_start`) and verify there are no background tasks holding references to the monitor loop that would prevent clean suspension.
- **Schwab CSV format resilience:** Research identified 7+ known format variations but only 2 formats are present in the codebase's `schwab/` directory. During Phase 2 planning, create test fixtures with at least 3 CSV variants (classic platform, modern platform, raw Schwab export) to parameterize the parser tests before implementation.
- **ReplayStore protocol boundary:** The interface between TUI and `StateStore | ReplayStore` needs a formal protocol definition before TUI changes are written. During Phase 4 planning, define a `SimulationStore` protocol and verify `StateStore` satisfies it without modification — this determines whether TUI changes are additive or require refactoring.
- **Pygal style API compatibility:** The AlphaSwarm custom pygal style (dark theme, BUY/SELL/HOLD color constants) has not been tested against pygal 3.1.0's `Style` constructor. During Phase 1 planning, verify the `Style(background, plot_background, foreground, colors)` API before building the full chart set.

## Sources

### Primary (HIGH confidence)
- AlphaSwarm codebase: `simulation.py`, `graph.py`, `tui.py`, `state.py`, `report.py`, `cli.py`, `governor.py`, `types.py` — direct source analysis for architecture and pitfalls
- `/memory/bug_governor_deadlock.md` — 7 bugs found across prior debugging sessions; Bug 7 (model loaded too early) directly informs shock injection timing
- [pygal PyPI](https://pypi.org/project/pygal/) — v3.1.0, zero runtime deps, Python >=3.8, released 2025-12-09
- [pygal output documentation](https://www.pygal.org/en/stable/documentation/output.html) — `render()`, `render_data_uri()` methods verified
- [Neo4j Async Python Driver API](https://neo4j.com/docs/api/python-driver/current/async_api.html) — connection pool behavior, session lifecycle
- [Plotly PyPI](https://pypi.org/project/plotly/) — v6.7.0, 9.9MB wheel (basis for rejection in favor of pygal)

### Secondary (MEDIUM confidence)
- [Inject, Fork, Compare: Interaction Vocabulary for Multi-Agent Simulation (2025)](https://arxiv.org/html/2509.13712) — academic validation of shock injection as a first-class simulation operation
- [Automated Interactive Reports with Plotly and Python](https://towardsdatascience.com/automated-interactive-reports-with-plotly-and-python-88dbe3aae5/) — ETL pattern for Jinja2 + chart embedding
- [Schwab CSV Converter (GitHub)](https://github.com/rlan/convert-csv-schwab2pp) — reference for Schwab CSV format variations
- [Event-Driven Agent-Based Simulation Model (MDPI)](https://www.mdpi.com/2076-3417/10/12/4343) — reactive agent patterns with publish-subscribe event injection

### Tertiary (LOW confidence)
- [Temporal Versioning in Neo4j (practical guide)](https://dev.to/satyam_shree_087caef77512/a-practical-guide-to-temporal-versioning-in-neo4j-nodes-relationships-and-historical-graph-1m5g) — confirms that `cycle_id + round` indexing is sufficient; full bi-temporal versioning is overkill for this use case
- [LLM Privacy Risks 2025 (ScienceDirect)](https://www.sciencedirect.com/science/article/pii/S2667295225000042) — data leakage through model context and logging (supports portfolio isolation design)

---
*Research completed: 2026-04-09*
*Ready for roadmap: yes*
