# Feature Research: v4.0 Interactive Simulation & Analysis

**Domain:** Multi-agent financial simulation -- interactive extensions
**Researched:** 2026-04-09
**Confidence:** MEDIUM-HIGH (patterns verified against existing codebase + domain research)

## Feature Landscape

This analysis covers the four v4.0 target features: mid-simulation shock injection, simulation replay from Neo4j, HTML report export with interactive charts, and portfolio impact analysis. Each feature is categorized by table stakes / differentiator / anti-feature within the context of what makes AlphaSwarm's simulation engine genuinely useful for its operator.

---

### Table Stakes (Users Expect These)

Features that must exist for the v4.0 feature set to feel complete once advertised.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **SHOCK: Single shock injection between rounds** | If you advertise "shock injection," users expect to inject at least one event between R1-R2 or R2-R3 and see agents respond | MEDIUM | Existing `run_simulation()` has clear R1->R2->R3 boundaries with `on_round_complete` callbacks; injection point is architecturally natural between rounds. Requires new `ShockEvent` type + prompt augmentation. |
| **SHOCK: Shock text visible to all agents in next round** | Injected shocks must propagate to every agent's context in the subsequent round; partial visibility defeats the purpose | LOW | `_dispatch_enriched_sub_waves()` already takes a `rumor` string; shock text can be appended to the rumor parameter for the subsequent round's dispatch. |
| **SHOCK: Shock persisted to Neo4j** | Shock events must be queryable post-simulation for replay and report generation | LOW | Create `ShockEvent` node linked to `Cycle` with `injected_before_round` property. One Cypher MERGE statement. Follows existing `create_cycle_with_seed_event` pattern. |
| **REPLAY: List past simulations from Neo4j** | Users must be able to discover what simulations exist before replaying one | LOW | `Cycle` nodes already have `cycle_id`, `seed_rumor`, `created_at`. One `MATCH (c:Cycle) RETURN c ORDER BY c.created_at DESC` query. |
| **REPLAY: Reconstruct per-round agent decisions for past simulation** | Core replay capability: read all `Decision` nodes for a cycle, grouped by round | MEDIUM | `Decision` nodes already store `cycle_id`, `round`, `signal`, `confidence`, `rationale`. Need a new `read_full_simulation()` query method that returns all 3 rounds of decisions + bracket summaries. |
| **REPLAY: Display reconstructed simulation in TUI** | If you advertise "replay in TUI," the grid must populate round-by-round from stored data | MEDIUM | StateStore already drives TUI via snapshots. Replay feeds stored data into StateStore at configurable pace rather than live inference. The TUI itself needs zero changes -- only the data source changes. |
| **EXPORT: Markdown report rendered to styled HTML** | Existing Jinja2 markdown report must convert to shareable HTML with basic styling | LOW | `markdown` or `markdown-it-py` library converts existing `.md` output to HTML. Wrap in a single-file HTML template with embedded CSS. |
| **EXPORT: Self-contained single HTML file** | Reports must open in any browser without a server or external dependencies | LOW | Plotly `to_html(full_html=False, include_plotlyjs='cdn')` for charts; inline CSS for styling. Single `<html>` document. CDN reference for Plotly.js keeps file size small; inline option available for true offline. |
| **PORTFOLIO: Parse Schwab CSV holdings** | If you advertise portfolio analysis, the system must read the user's actual holdings | LOW | Schwab CSV format is already in `schwab/holdings.csv` (sanitized). Simple `csv.DictReader` with `account`, `symbol`, `shares`, `cost_basis_per_share` columns. Already gitignored for privacy. |
| **PORTFOLIO: Map consensus signals to held tickers** | Core portfolio feature: "you hold NVDA, swarm says BUY with 0.74 confidence" | LOW | Join `TickerConsensus` results with parsed holdings on `ticker`/`symbol`. Pure data join, no inference needed. |

### Differentiators (Competitive Advantage)

Features that make v4.0 genuinely powerful beyond basic expectations.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **SHOCK: Before/after consensus comparison** | Show how the swarm's opinion shifted due to the shock; quantify the delta. Follows the "Inject, Fork, Compare" research pattern from recent multi-agent simulation literature. | MEDIUM | Already have `_compute_shifts()` that computes `ShiftMetrics` between rounds. Shock-aware version labels pre-shock round N and post-shock round N+1, highlighting shock-attributed opinion changes vs organic drift. |
| **SHOCK: TUI shock input during simulation** | Inject shocks interactively via TUI `Input` widget between rounds, not pre-configured | MEDIUM | Textual already has `Input` widget in the codebase. Simulation needs an `asyncio.Event` or `asyncio.Queue` gate between rounds where TUI can push shock text. Requires simulation loop to await user input at round boundaries. |
| **SHOCK: Shock-specific section in report** | Post-simulation report includes a "Shock Impact Analysis" section showing how agents pivoted | LOW | New Jinja2 template `10_shock_impact.j2` rendering `ShiftMetrics` pre/post shock. Plugs into existing `ReportAssembler.assemble()` pipeline via `TOOL_TO_TEMPLATE` dict and `SECTION_ORDER` list. |
| **REPLAY: Adjustable playback speed** | Step through rounds manually or at 0.5x/1x/2x speed in TUI | LOW | Timer-controlled StateStore feeding. A `speed_multiplier` on the replay tick interval. Already using `set_interval` for 200ms TUI ticks. |
| **REPLAY: Side-by-side simulation comparison** | Compare two cycle_ids: same seed, different shocks or different market conditions | HIGH | Requires parallel StateStore instances or a comparison data model. Extremely powerful for "what if" analysis but complex TUI layout (split-screen or tabbed). Defer to v4.1 unless time permits. |
| **EXPORT: Interactive Plotly charts in HTML** | Consensus heatmaps, bracket distribution bar charts, signal timeline charts -- all hoverable/zoomable in a single file | MEDIUM | Plotly `to_html(full_html=False)` generates self-contained `<div>` strings. Embed in Jinja2 HTML template. Target charts: (1) bracket consensus stacked bars, (2) round-over-round signal timeline, (3) ticker consensus gauge/heatmap, (4) influence leader scatter plot. |
| **EXPORT: Dark theme matching TUI aesthetic** | Consistent visual identity between TUI and exported reports | LOW | Plotly has `plotly_dark` built-in template. CSS dark theme is straightforward (`background: #1e1e2e`, light text). Matches the user's preference for "clean and minimalist aesthetic." |
| **PORTFOLIO: Unrealized P&L impact projection** | Calculate hypothetical portfolio impact: "if NVDA moves +5% as swarm suggests, your unrealized gain changes by $X" | MEDIUM | Requires `shares * current_price * expected_return_pct` math. `expected_return_pct` comes from `TickerDecision` aggregation. `current_price` from `MarketDataSnapshot.last_close`. Pure arithmetic, no inference needed. |
| **PORTFOLIO: Holdings not in simulation flagged** | Show which portfolio holdings were NOT mentioned in the simulation (coverage gap analysis) | LOW | Set difference: `{held_tickers} - {simulated_tickers}`. One line of Python. High value -- tells the user what the simulation did NOT cover. |
| **PORTFOLIO: Multi-account support** | Parse both Individual and Roth IRA accounts from Schwab exports | LOW | The `holdings.csv` already has an `account` column distinguishing `individual` vs `roth_ira`. Group by account in the analysis. |
| **PORTFOLIO: LLM-generated portfolio narrative** | Orchestrator LLM produces a natural-language summary of "what the swarm thinks about your portfolio" | MEDIUM | Single orchestrator inference call with consensus + holdings data as context. Follows existing ReACT report pattern but simpler (one-shot, not iterative). Produces a paragraph like "The swarm is strongly bullish on 3 of your top 5 holdings by value..." |

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem good but create problems in this specific context.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **SHOCK: Real-time mid-round injection** | "What if I could shock agents DURING a round?" | Agents are dispatched as a batch via `dispatch_wave()`. Injecting mid-batch means some agents see the shock and others do not, creating an inconsistent information state. The 100-agent batch is the atomic unit. | Inject between rounds only. All agents in the next round see the same shock context. This is the natural boundary in the 3-round cascade. |
| **SHOCK: Unlimited additional rounds after shock** | "Let me add Round 4, 5, 6 after a shock" | Current architecture is hardcoded to 3 rounds with specific peer influence patterns (R1: standalone, R2: R1 peers, R3: R2 peers). Adding arbitrary rounds requires refactoring the entire simulation loop, and `SimulationPhase` enum only has ROUND_1/2/3. Memory pressure on M1 Max 64GB already near limits at 3 rounds x 100 agents. | Keep 3-round cascade. If users want more rounds, they can run a new simulation with the shock as the initial seed rumor. |
| **REPLAY: Full state time-travel with Neo4j temporal versioning** | "Use Neo4j's temporal features for point-in-time graph reconstruction" | Neo4j Community Edition (Docker) has limited temporal support. Implementing proper bi-temporal versioning (valid_time + transaction_time) on every node and relationship is massive scope creep. The existing `created_at` timestamps on nodes are sufficient. | Query by `cycle_id` + `round` (already indexed via `decision_cycle_round`). These two keys reconstruct any simulation state. No temporal versioning needed. |
| **REPLAY: Re-run simulation with same random seed** | "Reproduce the exact same agent outputs" | LLM inference is non-deterministic even with temperature=0 (floating point accumulation varies). Ollama does not guarantee reproducible outputs across runs. | Replay from stored Neo4j decisions (deterministic). Do not promise inference reproducibility. Present replay as "view past results," not "reproduce past results." |
| **EXPORT: PDF export** | "I want a PDF to share" | WeasyPrint/wkhtmltopdf add heavy system dependencies. Interactive charts become static images. PDF rendering is a rabbit hole of CSS compatibility issues. Plotly charts lose all interactivity. | HTML is the universal format. Opens in any browser, retains interactivity. Users can print-to-PDF from browser if needed (Cmd+P). |
| **EXPORT: Live Dash/Flask server for reports** | "Serve reports as a web dashboard" | Adds a persistent server process, port management, security concerns. Violates local-first design. Way beyond scope for a single-operator tool. | Single-file HTML with inline/CDN Plotly.js. Zero infrastructure. Open in browser, done. |
| **PORTFOLIO: Automated trade recommendations** | "Tell me what to buy/sell based on the simulation" | Crosses the line from analysis into financial advice. Regulatory minefield. The simulation is explicitly NOT a trading system per PROJECT.md out-of-scope: "Trade execution -- no real money, no broker integration." | Present consensus signals alongside holdings as informational context. Never use imperative language ("you should buy"). Frame as "swarm consensus vs. your position." |
| **PORTFOLIO: Real-time portfolio sync via Schwab API** | "Auto-import my portfolio" | Schwab Developer API requires OAuth2 app registration, compliance review, and ongoing token management. Massive scope for a local-first tool. CSV export is manual but takes 30 seconds. | Manual CSV export from schwab.com placed in `schwab/` directory. Parse on demand. Already works with existing `holdings.csv` format. |
| **PORTFOLIO: Historical portfolio tracking over time** | "Show me how simulation accuracy changed over time" | Requires storing portfolio snapshots over time, tracking actual price movements post-simulation, and building a backtesting comparison engine. Explicitly out of scope per PROJECT.md: "Historical backtesting -- forward simulation only." | Single-point-in-time analysis: "here is the swarm consensus, here are your current holdings, here is the overlap." No time series. |

## Feature Dependencies

```
[SHOCK: ShockEvent type + Neo4j persistence]
    |
    +--requires--> [Existing run_simulation() round boundary hooks]
    |
    +--enables---> [SHOCK: Before/after consensus comparison]
    |                  |
    |                  +--enables---> [SHOCK: Shock section in report]
    |
    +--enables---> [SHOCK: TUI shock input]
                       |
                       +--requires--> [Existing Textual Input widget + asyncio gate]

[REPLAY: List past simulations]
    |
    +--requires--> [Existing Neo4j Cycle nodes with created_at]
    |
    +--enables---> [REPLAY: Reconstruct per-round decisions]
                       |
                       +--enables---> [REPLAY: Display in TUI via StateStore]
                       |                  |
                       |                  +--enables---> [REPLAY: Adjustable playback speed]
                       |
                       +--enables---> [REPLAY: Side-by-side comparison] (v4.1)

[EXPORT: Markdown to HTML conversion]
    |
    +--requires--> [Existing Jinja2 report templates + ReportAssembler]
    |
    +--enables---> [EXPORT: Interactive Plotly charts]
    |                  |
    |                  +--requires--> [plotly pip dependency]
    |
    +--enables---> [EXPORT: Dark theme styling]

[PORTFOLIO: Parse Schwab CSV]
    |
    +--requires--> [schwab/holdings.csv exists, gitignored]
    |
    +--enables---> [PORTFOLIO: Map consensus to holdings]
    |                  |
    |                  +--requires--> [Existing TickerConsensus from simulation]
    |                  |
    |                  +--enables---> [PORTFOLIO: P&L impact projection]
    |                  |                  |
    |                  |                  +--requires--> [MarketDataSnapshot.last_close]
    |                  |
    |                  +--enables---> [PORTFOLIO: Coverage gap analysis]
    |                  |
    |                  +--enables---> [PORTFOLIO: LLM narrative]
    |                                      |
    |                                      +--requires--> [Orchestrator model available]
    |
    +--enables---> [PORTFOLIO: Multi-account support]

[SHOCK: Shock section in report] --enhances--> [EXPORT: HTML report]
[PORTFOLIO: Map consensus to holdings] --enhances--> [EXPORT: HTML report]
```

### Dependency Notes

- **SHOCK requires existing round boundaries:** The `run_simulation()` function already has clear R1->R2->R3 transitions with `on_round_complete` callbacks and `SimulationPhase` state machine. Shock injection inserts a pause + prompt augmentation between these transitions. The `_dispatch_enriched_sub_waves()` function's `rumor` parameter is the natural injection point.
- **REPLAY requires existing Neo4j data model:** All Decision, Post, Agent, Cycle, Entity, and TickerConsensusSummary nodes are already persisted with `cycle_id` + `round` composite indexes. Replay is primarily a read path, not a new write path. The `InterviewContext` pattern in `graph.py` already demonstrates reconstructing agent state from stored data.
- **EXPORT builds on existing report pipeline:** The `ReportAssembler` + Jinja2 templates already produce markdown from `ToolObservation` records. HTML export adds either (a) a markdown-to-HTML conversion pass, or (b) new HTML-native Jinja2 templates that render directly. Option (b) is recommended because it allows embedding Plotly chart `<div>` elements inline.
- **PORTFOLIO requires TickerConsensus:** The consensus mapping depends on simulation results being available. Portfolio analysis is strictly a post-simulation feature. The `TickerConsensus` dataclass already provides `weighted_signal`, `weighted_score`, `majority_signal`, and `majority_pct` per ticker.
- **PORTFOLIO: CSV format is already known.** The `schwab/holdings.csv` has 4 columns: `account`, `symbol`, `shares`, `cost_basis_per_share`. The raw Schwab export (`Individual-Positions-*.csv`) has a more complex 16-column format with header rows to skip. The sanitized `holdings.csv` is the target parse format.

## MVP Definition

### Launch With (v4.0 Core)

Minimum viable set that delivers on all four advertised capabilities.

- [ ] **SHOCK: ShockEvent type + Neo4j persistence** -- foundation for all shock features
- [ ] **SHOCK: Single shock injection between rounds via TUI Input** -- the marquee interactive feature
- [ ] **SHOCK: Shock text visible to all agents in next round** -- makes injection meaningful
- [ ] **SHOCK: Before/after consensus comparison (ShiftMetrics)** -- quantifies shock impact
- [ ] **REPLAY: List past simulations** -- discovery mechanism
- [ ] **REPLAY: Reconstruct per-round decisions from Neo4j** -- core replay data path
- [ ] **REPLAY: Display reconstructed simulation in TUI** -- visual replay
- [ ] **EXPORT: Styled HTML single-file export with Plotly charts** -- shareable interactive reports
- [ ] **PORTFOLIO: Parse Schwab CSV holdings** -- data ingestion
- [ ] **PORTFOLIO: Map consensus signals to held tickers** -- core value proposition
- [ ] **PORTFOLIO: Holdings not in simulation flagged** -- coverage gap analysis

### Add After Validation (v4.x)

Features to add once core v4.0 is stable.

- [ ] **SHOCK: Shock-specific section in report** -- add when report pipeline is proven with HTML export
- [ ] **REPLAY: Adjustable playback speed** -- add once basic replay works correctly
- [ ] **EXPORT: Dark theme** -- add once HTML structure is finalized
- [ ] **PORTFOLIO: Unrealized P&L impact projection** -- add once basic holdings mapping is validated
- [ ] **PORTFOLIO: Multi-account support** -- add once single-account parsing is solid
- [ ] **PORTFOLIO: LLM-generated portfolio narrative** -- add once mapping data is correct

### Future Consideration (v4.1+)

Features to defer until v4.0 is complete and stable.

- [ ] **REPLAY: Side-by-side simulation comparison** -- complex TUI layout, high value but high cost
- [ ] **EXPORT: Chart type expansion** -- influence network graph, per-agent heatmap, etc.

## Feature Prioritization Matrix

| Feature | User Value | Impl Cost | Priority | Phase Recommendation |
|---------|------------|-----------|----------|---------------------|
| SHOCK: ShockEvent type + persistence | HIGH | LOW | P1 | Early -- foundation |
| SHOCK: TUI injection between rounds | HIGH | MEDIUM | P1 | After ShockEvent type |
| SHOCK: Agent context propagation | HIGH | LOW | P1 | Same phase as TUI injection |
| SHOCK: Before/after comparison | HIGH | LOW | P1 | Same phase as injection |
| REPLAY: List simulations | MEDIUM | LOW | P1 | Early -- simple query |
| REPLAY: Reconstruct decisions | HIGH | MEDIUM | P1 | Core replay |
| REPLAY: TUI display | HIGH | MEDIUM | P1 | After reconstruction |
| EXPORT: HTML with Plotly charts | HIGH | MEDIUM | P1 | Independent of other features |
| PORTFOLIO: CSV parse | MEDIUM | LOW | P1 | Independent |
| PORTFOLIO: Consensus mapping | HIGH | LOW | P1 | After CSV parse |
| PORTFOLIO: Coverage gaps | MEDIUM | LOW | P1 | After mapping |
| SHOCK: Report section | MEDIUM | LOW | P2 | After export pipeline |
| REPLAY: Playback speed | LOW | LOW | P2 | After basic replay |
| EXPORT: Dark theme | MEDIUM | LOW | P2 | After HTML structure |
| PORTFOLIO: P&L projection | MEDIUM | MEDIUM | P2 | After mapping validated |
| PORTFOLIO: Multi-account | LOW | LOW | P2 | After single-account |
| PORTFOLIO: LLM narrative | MEDIUM | MEDIUM | P2 | After mapping validated |
| REPLAY: Side-by-side comparison | HIGH | HIGH | P3 | v4.1 |

**Priority key:**
- P1: Must have for v4.0 launch (delivers on all four advertised capabilities)
- P2: Should have, add when possible (polish and depth)
- P3: Nice to have, future milestone

## Existing Architecture Integration Points

Understanding where each feature connects to the current codebase is critical for roadmap phase ordering.

| Feature Area | Key Files to Modify | Key Files to Create | Existing Patterns to Follow |
|-------------|--------------------|--------------------|---------------------------|
| **SHOCK** | `simulation.py` (round boundary gate), `types.py` (ShockEvent type), `graph.py` (persist shock), `tui.py` (Input widget for shock text), `state.py` (new SimulationPhase.SHOCK_PENDING) | Possibly `shock.py` if logic is complex enough to warrant separation | `SeedEvent` in `types.py` for event type pattern; `on_round_complete` callback for boundary hooks; `SimulationPhase` enum extension; `create_cycle_with_seed_event()` in `graph.py` for Neo4j persistence pattern |
| **REPLAY** | `graph.py` (new bulk-read queries), `cli.py` (new `replay` subcommand), `tui.py` (replay mode vs live mode) | `replay.py` (orchestrate replay: query Neo4j, feed StateStore, manage playback) | `read_peer_decisions()` in `graph.py` for Neo4j read pattern; `StateStore.snapshot()` for TUI feeding; `InterviewContext` reconstruction in `graph.py` for agent state rebuild |
| **EXPORT** | `report.py` (add HTML assembly path alongside markdown), `cli.py` (new `export` subcommand or flag on `run`) | `export.py` (Plotly chart generation + HTML Jinja2 assembly), `templates/report/base.html.j2` (HTML wrapper template), `templates/report/charts/` (chart generation functions) | `ReportAssembler.assemble()` for section ordering; `Jinja2 FileSystemLoader` for template loading; `write_report()` for async file output; `TOOL_TO_TEMPLATE` dict for section mapping |
| **PORTFOLIO** | `cli.py` (new `portfolio` subcommand or post-sim hook) | `portfolio.py` (CSV parsing + consensus mapping + impact analysis), `templates/report/11_portfolio_impact.j2` (markdown section), `templates/report/portfolio.html.j2` (HTML section) | `market_data.py` pattern for data ingestion with graceful degradation; `TickerConsensus` for consensus data; Pydantic `BaseModel` for `HoldingPosition` type; `MarketDataSnapshot` for price data |

## Sources

- [Plotly Interactive HTML Export (official docs)](https://plotly.com/python/interactive-html-export/) -- `write_html()` and `to_html()` with `full_html=False` for embedding in Jinja2 templates
- [Plotly Theming and Templates (official docs)](https://plotly.com/python/templates/) -- `plotly_dark` template for dark theme charts
- [Inject, Fork, Compare: Interaction Vocabulary for Multi-Agent Simulation (2025)](https://arxiv.org/html/2509.13712) -- academic paper defining inject/fork/compare operations for multi-agent simulation platforms
- [Temporal Versioning in Neo4j (practical guide)](https://dev.to/satyam_shree_087caef77512/a-practical-guide-to-temporal-versioning-in-neo4j-nodes-relationships-and-historical-graph-1m5g) -- why full temporal versioning is overkill; `cycle_id + round` indexing is sufficient
- [Automated Interactive Reports with Plotly and Python](https://towardsdatascience.com/automated-interactive-reports-with-plotly-and-python-88dbe3aae5/) -- ETL pattern for Plotly + Jinja2 report generation
- [Schwab CSV Converter (GitHub)](https://github.com/rlan/convert-csv-schwab2pp) -- reference for Schwab CSV format parsing
- [Event-Driven Agent-Based Simulation Model](https://www.mdpi.com/2076-3417/10/12/4343) -- reactive agent patterns with publish-subscribe event injection

---
*Feature research for: AlphaSwarm v4.0 Interactive Simulation & Analysis*
*Researched: 2026-04-09*
