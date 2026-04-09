# Architecture Research: v4.0 Interactive Simulation & Analysis

**Domain:** Local-first multi-agent LLM financial simulation engine (feature expansion)
**Researched:** 2026-04-09
**Confidence:** HIGH

This document maps how four new v4.0 features -- shock injection, simulation replay, HTML export, and portfolio impact analysis -- integrate with the existing AlphaSwarm codebase. It identifies new modules, modification points, data flows, and a dependency-aware build order.

---

## Existing Architecture Baseline (v3.0)

```
CLI Entry (cli.py)           TUI Entry (tui.py)
    |                             |
    v                             v
AppState (app.py) --- DI container: settings, governor, state_store,
                      ollama_client, model_manager, graph_manager
    |
    v
SeedInjector (seed.py) --> Orchestrator LLM --> Neo4j (Cycle + Entity + Ticker nodes)
    |
    v
MarketDataFetch (market_data.py) --> yfinance/AV --> Neo4j (Ticker + MarketDataSnapshot)
    |
    v
Enrichment (enrichment.py) --> bracket-tailored market context
    |
    v
SimulationEngine (simulation.py)
    |-- run_round1(): SEEDING --> dispatch_wave() --> write_decisions() --> write_posts()
    |-- Between R1-R2: compute_influence_edges(), callback
    |-- run_round2(): read_ranked_posts() --> _dispatch_enriched_sub_waves() --> write_decisions()
    |-- Between R2-R3: compute_influence_edges(), callback
    |-- run_round3(): same pattern --> consensus lock
    |
    v                                v
StateStore (state.py)           ResourceGovernor (governor.py)
  |  mutable, per-agent writes       TokenPool, 5-state machine
  |
  v (200ms poll)
TUI (tui.py)
  |-- AgentCell grid (10x10)
  |-- RationaleSidebar, BracketPanel, TickerConsensusPanel
  |-- TelemetryFooter
  |-- InterviewScreen overlay
    |
    v
ReportEngine (report.py) --> ReACT loop --> Jinja2 markdown assembly
    |
    v
results/*.md (filesystem)
```

### Neo4j Graph Schema (current)

Nodes: `Cycle`, `SeedEvent`, `Entity`, `Agent`, `Decision`, `Post`, `RationaleEpisode`, `Ticker`, `MarketDataSnapshot`, `TickerConsensusSummary`

Edges: `MENTIONS`, `MADE`, `FOR`, `CITED`, `INFLUENCED_BY`, `HAS_EPISODE`, `REFERENCES`, `PUBLISHED`, `READ_POST`, `HAS_TICKER`, `HAS_MARKET_DATA`, `HAS_CONSENSUS`

Key property: All `Decision`, `Post`, `INFLUENCED_BY` edges carry `cycle_id` + `round` for cycle-scoped queries.

### Data Available for Replay

Neo4j already stores everything needed to reconstruct a simulation visually:
- Per-agent decisions (signal, confidence, sentiment, rationale) per round
- Bracket membership on Agent nodes
- Influence edges with weights per round
- TickerConsensusSummary per round
- Posts, RationaleEpisodes
- Market data snapshots
- Seed rumor + entities

What Neo4j does NOT store (relevant gaps):
- GovernorMetrics (runtime telemetry, not persisted)
- TPS/throughput metrics (ephemeral in StateStore)
- Round timestamps / ordering metadata within a round (agents are concurrent, no per-agent timestamp)

---

## Feature 1: Mid-Simulation Shock Injection (SHOCK)

### Concept

Inject a "breaking event" text between rounds (after R1 or R2), which modifies the agent prompt context for subsequent rounds. Agents should visibly pivot their decisions in response.

### Architecture Integration

**Hook point:** `simulation.py:run_simulation()` between round callbacks. The function already has clear seams between rounds (lines 1133-1156) where influence edges are computed, callbacks fire, and the next round begins. The shock must be injected here.

**Design: Shock as a pre-round context modifier, not a new round.**

A shock does NOT add a Round 4. It modifies the peer context / system prompt for the next round. This preserves the 3-round invariant that the entire architecture (Neo4j schema, TUI, report tools) depends on.

### New Module: `shock.py`

```python
# New file: src/alphaswarm/shock.py (~120 LOC)

@dataclass(frozen=True)
class ShockEvent:
    """Mid-simulation breaking event injected between rounds."""
    text: str                    # The shock rumor text
    inject_after_round: int      # 1 or 2
    timestamp: str               # ISO timestamp
    severity: float              # 0.0-1.0, affects prompt emphasis

def format_shock_context(shock: ShockEvent, budget: int = 500) -> str:
    """Format shock event into a prompt context block for agent injection."""
    ...

async def persist_shock_event(
    graph_manager: GraphStateManager,
    cycle_id: str,
    shock: ShockEvent,
) -> str:
    """Write ShockEvent node linked to Cycle in Neo4j."""
    ...
```

### Module Modifications

| Module | Change | Scope |
|--------|--------|-------|
| `simulation.py` | Add `shocks: list[ShockEvent] | None` parameter to `run_simulation()`. Between rounds, check for applicable shock and prepend to peer context. | ~40 LOC added to run_simulation between-round seams |
| `state.py` | Add `active_shock: str | None` field to `StateSnapshot` for TUI display | ~10 LOC |
| `tui.py` | Add `ShockBanner` widget that appears when `snapshot.active_shock` is set. In TUI mode, add an `Input` widget or keybinding (e.g., `s` key) to prompt for shock text | ~60 LOC new widget + keybinding |
| `cli.py` | Add `--shock-after-round1 "text"` and `--shock-after-round2 "text"` flags to `run` and `tui` subcommands | ~15 LOC |
| `graph.py` | Add `write_shock_event()` method + `ShockEvent` node schema. Add `read_shock_events()` for replay. | ~60 LOC |
| `types.py` | No change -- ShockEvent lives in shock.py (single-use, not cross-module) | 0 LOC |
| `config.py` | Add `shock_context_budget: int = 500` to AppSettings | ~3 LOC |

### Data Flow

```
User provides shock text (CLI flag or TUI input during sim)
    |
    v
simulation.py: after on_round_complete(R1), before Round 2 dispatch
    |
    v
shock.format_shock_context() --> prepend to each agent's peer_context
    |
    v
state_store.set_active_shock(shock.text)  --> TUI ShockBanner renders
    |
    v
graph_manager.write_shock_event() --> Neo4j (for replay)
    |
    v
Agents in Round 2/3 see: [BREAKING EVENT] ... before peer posts
```

### Neo4j Schema Addition

```
(:Cycle)-[:HAS_SHOCK]->(:ShockEvent {
    shock_id: uuid4,
    text: str,
    inject_after_round: int,
    severity: float,
    created_at: datetime
})
```

### TUI Interaction Model (Interactive Shock)

For TUI-mode interactive shock injection (typing a shock mid-simulation):

The simulation Worker runs in a Textual `@work` coroutine. The TUI event loop is separate. Communication happens via `StateStore` (sim writes, TUI reads) but there is no reverse channel (TUI writes, sim reads).

**Solution: Add an `asyncio.Queue[ShockEvent]` to StateStore.**

- TUI writes shock events to the queue via a keybinding + input dialog.
- `run_simulation()` polls the queue between rounds (non-blocking `get_nowait()`).
- This follows the existing pattern (StateStore is already the sim<->TUI bridge).

```
# In StateStore:
self._shock_queue: asyncio.Queue[ShockEvent] = asyncio.Queue(maxsize=5)

# In simulation.py between rounds:
try:
    shock = state_store._shock_queue.get_nowait()
    # apply shock to next round's context
except asyncio.QueueEmpty:
    pass  # no shock injected
```

---

## Feature 2: Simulation Replay from Neo4j (REPLAY)

### Concept

Reconstruct a past simulation in the TUI, animating agent decisions round-by-round from stored Neo4j data. No LLM inference needed -- pure data playback.

### Architecture Integration

**The TUI already supports snapshot-based rendering.** Replay just needs to populate StateStore from Neo4j reads instead of from live simulation writes. The TUI does not care where the data comes from.

### New Module: `replay.py`

```python
# New file: src/alphaswarm/replay.py (~250 LOC)

@dataclass(frozen=True)
class ReplayCycleMetadata:
    """Summary of a past simulation cycle for selection UI."""
    cycle_id: str
    seed_rumor: str
    created_at: str
    agent_count: int
    round_count: int
    has_shocks: bool

async def list_replay_cycles(
    graph_manager: GraphStateManager,
    limit: int = 20,
) -> list[ReplayCycleMetadata]:
    """List available cycles for replay from Neo4j."""
    ...

async def replay_simulation(
    cycle_id: str,
    graph_manager: GraphStateManager,
    state_store: StateStore,
    *,
    round_delay_seconds: float = 2.0,
    agent_delay_seconds: float = 0.05,
) -> None:
    """Replay a stored simulation by feeding StateStore from Neo4j reads.

    Animates round-by-round with configurable delays:
    1. Set phase to ROUND_N
    2. Read all decisions for round N
    3. Feed decisions to state_store one-by-one with agent_delay
    4. Compute bracket summaries and ticker consensus from stored data
    5. Pause round_delay_seconds before next round
    """
    ...
```

### Module Modifications

| Module | Change | Scope |
|--------|--------|-------|
| `graph.py` | Add `read_all_decisions(cycle_id, round_num)` method returning `list[tuple[str, AgentDecision]]`. Add `read_cycle_metadata(cycle_id)` for header display. Add `list_cycles()` for cycle selection. | ~100 LOC (3 new Cypher queries) |
| `state.py` | Add `seed_rumor: str = ""` and `cycle_id: str = ""` fields to `StateSnapshot` for replay header context | ~5 LOC |
| `tui.py` | Add `ReplayDashboard(AlphaSwarmDashboard)` subclass (or mode flag) that: (a) skips `_run_simulation()`, (b) runs `replay_simulation()` as the Worker, (c) disables shock injection keybinding, (d) shows "REPLAY" badge in header | ~80 LOC |
| `cli.py` | Add `replay` subcommand: `alphaswarm replay [--cycle CYCLE_ID] [--speed MULTIPLIER]`. Lists available cycles if no ID given. | ~50 LOC |
| `config.py` | No change needed | 0 LOC |

### Data Flow

```
CLI: `alphaswarm replay --cycle abc123`
    |
    v
graph_manager.read_cycle_metadata(cycle_id)  --> display header
    |
    v
For round in [1, 2, 3]:
    graph_manager.read_all_decisions(cycle_id, round)
        |
        v
    state_store.set_phase(ROUND_N)
    for (agent_id, decision) in decisions:
        state_store.update_agent_state(agent_id, signal, confidence)
        await asyncio.sleep(agent_delay)  # animate agent grid
        |
        v
    Compute bracket_summaries from read decisions (pure function)
    state_store.set_bracket_summaries(summaries)
    state_store.set_ticker_consensus(consensus)
        |
        v
    graph_manager.read_shock_events(cycle_id, round)  --> display if present
    await asyncio.sleep(round_delay)
        |
        v
state_store.set_phase(COMPLETE)
```

### Key Design Decision: Reuse Existing TUI

The TUI already renders from `StateSnapshot`. Replay feeds the same StateStore. The TUI does not need to know it is replaying -- it just sees snapshot updates on the 200ms timer. This means:

- AgentCell grid works unchanged
- BracketPanel works unchanged
- TickerConsensusPanel works unchanged
- RationaleSidebar needs replay-specific rationale reads from Neo4j (push stored RationaleEntry to queue)
- TelemetryFooter shows "REPLAY" instead of live governor metrics

### Replay vs. Live Comparison

A natural extension: replay two cycles side-by-side. This is OUT OF SCOPE for v4.0 but the architecture supports it -- just instantiate two StateStores and two sets of TUI panels. Defer to v5.

---

## Feature 3: HTML Report Export (EXPORT)

### Concept

Convert the existing markdown report (already generated by `report.py` + Jinja2) into a styled, shareable HTML document with embedded CSS and optional visualizations.

### Architecture Integration

**The report pipeline already produces structured data.** The ReACT engine gathers `ToolObservation` objects. `ReportAssembler` renders them through Jinja2 templates into markdown sections. HTML export adds a parallel rendering path: same data, different templates.

### New Module: `html_export.py`

```python
# New file: src/alphaswarm/html_export.py (~200 LOC)

class HtmlReportAssembler:
    """Jinja2-based assembler for HTML report output.

    Uses HTML templates (not markdown templates) with embedded CSS.
    Renders the same ToolObservation data as ReportAssembler but produces
    a self-contained HTML file with styling.
    """

    def __init__(self) -> None:
        self._env = Environment(
            loader=FileSystemLoader(str(HTML_TEMPLATE_DIR)),
            autoescape=True,  # HTML output -- autoescape ON
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def assemble(
        self,
        observations: list[ToolObservation],
        cycle_id: str,
        *,
        market_context_data: list[dict] | None = None,
        portfolio_impact_data: dict | None = None,
    ) -> str:
        """Assemble all observations into a complete HTML report."""
        ...

async def write_html_report(path: Path, content: str) -> None:
    """Write HTML content to disk using aiofiles."""
    ...
```

### New Templates Directory

```
src/alphaswarm/templates/
    report/              # existing markdown templates (9 files)
    html_report/         # NEW: HTML templates
        base.html.j2     # full HTML document skeleton with embedded CSS
        01_consensus_summary.html.j2
        02_round_timeline.html.j2
        03_bracket_narratives.html.j2
        04_key_dissenters.html.j2
        05_influence_leaders.html.j2
        06_signal_flip_analysis.html.j2
        07_entity_impact.html.j2
        08_social_post_reach.html.j2
        09_market_context.html.j2
        10_portfolio_impact.html.j2   # NEW: portfolio section
        style.css                      # inline-ready CSS
```

### Module Modifications

| Module | Change | Scope |
|--------|--------|-------|
| `report.py` | No structural change. `ReportAssembler` stays as-is for markdown. `HtmlReportAssembler` in new module reuses same `ToolObservation` data. | 0 LOC changed |
| `cli.py` | Add `--format html` flag to `report` subcommand. When set, use `HtmlReportAssembler` instead of `ReportAssembler`. Default remains markdown. | ~20 LOC |
| `tui.py` | Optional: Add `H` keybinding to export HTML report post-simulation (same pattern as existing `action_save_results`) | ~15 LOC |

### Data Flow

```
Existing path (unchanged):
    ReportEngine.run() --> list[ToolObservation]
        |
        v
    ReportAssembler.assemble() --> markdown string --> results/report.md

New parallel path:
    ReportEngine.run() --> list[ToolObservation]  (same data!)
        |
        v
    HtmlReportAssembler.assemble() --> HTML string --> results/report.html
```

### Styling Strategy

**Self-contained HTML with embedded CSS.** No external dependencies (CDN, JS frameworks). The report must be shareable as a single file that opens in any browser.

- Use `<style>` block in `base.html.j2` with a clean, dark theme matching TUI aesthetic
- Tables styled with alternating row colors, BUY/SELL/HOLD color coding
- Use CSS-only bar charts for consensus visualization (no JS needed for v4.0)
- Optionally use `<svg>` inline for simple donut/bar charts (pure template logic)
- `markdown` library (already implied by Jinja2 dependency) for any markdown-in-HTML rendering

### Technology Choice: Jinja2 HTML Templates (no new dependencies)

Jinja2 is already a dependency. HTML templates are just Jinja2 templates with `autoescape=True`. No need for `markdown` library, Plotly, or other heavy dependencies. The report data is already structured (dicts from Neo4j) -- templates render it directly into HTML tables and styled elements.

---

## Feature 4: Portfolio Impact Analysis (PORTFOLIO)

### Concept

After simulation completes, load the user's Schwab portfolio holdings (CSV), cross-reference with the swarm's ticker consensus, and produce a "portfolio impact" section showing which holdings the swarm is bullish/bearish on, unrealized P&L context, and suggested attention areas.

### Architecture Integration

**This is a post-simulation analysis step, similar to the existing ReACT report.** It does NOT modify the simulation pipeline. It reads consensus data from Neo4j + holdings from CSV, then produces analysis via orchestrator LLM.

### Schwab CSV Format (from actual data)

Two formats exist in `schwab/`:

1. **Normalized `holdings.csv`** (simple, 4 columns):
   ```
   account,symbol,shares,cost_basis_per_share
   individual,AAPL,101.3071,165.5365
   ```

2. **Raw Schwab export** (16 columns, header rows, quoted numbers with `$` and `,`):
   ```
   "Positions for account Individual as of 03:47 PM ET, 2026/04/09"
   Symbol,Description,Qty (Quantity),Price,...
   AAPL,APPLE INC,101.3071,260.7572,...
   ```

### New Module: `portfolio.py`

```python
# New file: src/alphaswarm/portfolio.py (~300 LOC)

@dataclass(frozen=True)
class Holding:
    """Single portfolio position."""
    account: str
    symbol: str
    shares: float
    cost_basis_per_share: float
    current_price: float | None = None  # From market data if available
    market_value: float | None = None
    gain_loss_pct: float | None = None

@dataclass(frozen=True)
class PortfolioImpact:
    """Cross-reference result: one holding vs swarm consensus."""
    holding: Holding
    consensus_signal: str | None      # BUY/SELL/HOLD from swarm
    consensus_score: float | None     # weighted score
    majority_signal: str | None
    majority_pct: float | None
    alignment: str                    # "aligned" / "contrary" / "no_data"
    attention_level: str              # "high" / "medium" / "low"

def parse_holdings_csv(path: Path) -> list[Holding]:
    """Parse Schwab CSV (auto-detect normalized vs raw format)."""
    ...

def parse_schwab_raw_csv(path: Path) -> list[Holding]:
    """Parse raw Schwab export with header rows, quoted numbers."""
    ...

async def compute_portfolio_impact(
    holdings: list[Holding],
    graph_manager: GraphStateManager,
    cycle_id: str,
) -> list[PortfolioImpact]:
    """Cross-reference holdings with swarm consensus from Neo4j."""
    ...

async def generate_portfolio_analysis(
    impacts: list[PortfolioImpact],
    ollama_client: OllamaClient,
    model: str,
) -> str:
    """Use orchestrator LLM to generate narrative portfolio analysis."""
    ...
```

### Module Modifications

| Module | Change | Scope |
|--------|--------|-------|
| `graph.py` | Add `read_ticker_consensus_for_portfolio(cycle_id)` -- returns latest-round consensus per ticker. (Could reuse `read_market_context()` but better to have a focused query.) | ~40 LOC |
| `cli.py` | Add `--portfolio PATH` flag to `report` subcommand. When set, parse holdings, compute impact, include in report assembly. | ~30 LOC |
| `report.py` | Add `portfolio_impact_data` parameter to `ReportAssembler.assemble()` (already has `market_context_data` pattern to follow). Add `10_portfolio_impact.j2` template. | ~15 LOC in report.py |
| `html_export.py` | Accept `portfolio_impact_data` in `HtmlReportAssembler.assemble()` | ~5 LOC |
| `config.py` | Add `schwab_portfolio_path: Path | None = None` to AppSettings (env var `ALPHASWARM_PORTFOLIO_PATH`) | ~5 LOC |

### Data Flow

```
CLI: `alphaswarm report --cycle abc123 --portfolio schwab/holdings.csv --format html`
    |
    v
portfolio.parse_holdings_csv("schwab/holdings.csv")
    |
    v
list[Holding] (e.g., AAPL 101 shares @ $165.54 cost)
    |
    v
portfolio.compute_portfolio_impact(holdings, graph_manager, cycle_id)
    |   reads: graph_manager.read_market_context(cycle_id) for consensus + prices
    |
    v
list[PortfolioImpact]:
    AAPL: consensus=BUY (0.74), you hold 101 shares, +57% gain --> alignment="aligned", attention="low"
    NKE:  consensus=SELL (0.82), you hold 100 shares, -52% loss --> alignment="aligned", attention="high"
    PLTR: consensus=BUY (0.91), you hold 400 shares, +644% gain --> alignment="aligned", attention="medium"
    |
    v
portfolio.generate_portfolio_analysis(impacts, ollama_client, model)
    |   orchestrator LLM generates 2-3 paragraph narrative
    |
    v
ReportAssembler.assemble(..., portfolio_impact_data=impacts_dict)
    or
HtmlReportAssembler.assemble(..., portfolio_impact_data=impacts_dict)
    |
    v
Report includes "Portfolio Impact" section:
    - Table: holdings vs consensus alignment
    - Narrative: "The swarm is bearish on NKE where you hold 100 shares at a 52% loss..."
```

### Portfolio Data Security

- CSV files live in `schwab/` (already gitignored per commit c57585c)
- Holdings data never sent to any API -- processing is pure Python + local LLM
- Portfolio path is optional -- feature degrades gracefully if not provided

---

## Component Boundary Summary

### New Files (4)

| File | LOC Estimate | Dependencies |
|------|-------------|--------------|
| `src/alphaswarm/shock.py` | ~120 | types, graph |
| `src/alphaswarm/replay.py` | ~250 | graph, state, types, simulation (pure functions only) |
| `src/alphaswarm/html_export.py` | ~200 | report (ToolObservation), jinja2, aiofiles |
| `src/alphaswarm/portfolio.py` | ~300 | graph, types, ollama_client |

### New Template Files (12)

| Directory | Files |
|-----------|-------|
| `templates/html_report/` | `base.html.j2`, 9 section templates, `10_portfolio_impact.html.j2`, `style.css` |
| `templates/report/` | `10_portfolio_impact.j2` (markdown version) |

### Modified Files (7)

| File | Change Size | Risk |
|------|------------|------|
| `simulation.py` | ~60 LOC | MEDIUM -- touches hot path between rounds |
| `graph.py` | ~200 LOC | LOW -- additive (new methods only, no existing method changes) |
| `state.py` | ~20 LOC | LOW -- additive fields |
| `tui.py` | ~100 LOC | MEDIUM -- new widgets + keybindings |
| `cli.py` | ~100 LOC | LOW -- new subcommand + flags |
| `report.py` | ~15 LOC | LOW -- additive parameter |
| `config.py` | ~10 LOC | LOW -- additive settings |

---

## Suggested Build Order

### Phase 1: HTML Export (EXPORT)

**Rationale:** Zero dependencies on other v4.0 features. Does not touch simulation.py. Already has all data flowing through report.py. Establishes the HTML template infrastructure that portfolio impact will also use.

**Builds:**
- `html_export.py` module
- `templates/html_report/` directory with all section templates
- `--format html` CLI flag

**Modifies:** `cli.py`

**Tests easily** with existing simulation data in Neo4j.

### Phase 2: Portfolio Impact Analysis (PORTFOLIO)

**Rationale:** Depends on HTML export templates being established (for the portfolio section template). Does not touch simulation.py. Pure post-simulation analysis.

**Builds:**
- `portfolio.py` module
- `templates/report/10_portfolio_impact.j2`
- `templates/html_report/10_portfolio_impact.html.j2`

**Modifies:** `cli.py`, `report.py`, `html_export.py`, `config.py`, `graph.py`

**Tests easily** with CSV fixtures + existing Neo4j data.

### Phase 3: Shock Injection (SHOCK)

**Rationale:** Modifies `simulation.py` (highest risk). Should be built after non-invasive features are stable. Requires careful testing of the between-round injection seam.

**Builds:**
- `shock.py` module
- Neo4j ShockEvent schema

**Modifies:** `simulation.py`, `state.py`, `tui.py`, `cli.py`, `graph.py`, `config.py`

**Testing:** Requires running a live simulation to verify agent behavior changes. Integration-heavy.

### Phase 4: Simulation Replay (REPLAY)

**Rationale:** Depends on shock events being persisted in Neo4j (to replay shocks). Depends on all StateStore fields being finalized (shock adds `active_shock`). Most architecturally isolated -- new module + new CLI subcommand, but touches TUI for replay mode.

**Builds:**
- `replay.py` module
- `replay` CLI subcommand

**Modifies:** `graph.py`, `state.py`, `tui.py`, `cli.py`

**Testing:** Requires populated Neo4j from previous simulation runs (including shocks from Phase 3).

### Dependency Graph

```
Phase 1: HTML Export
    |
    v
Phase 2: Portfolio Impact  (uses HTML template infrastructure)
    |
    (independent)
    |
Phase 3: Shock Injection   (can start in parallel with Phase 2)
    |
    v
Phase 4: Replay            (needs shock schema from Phase 3)
```

Phase 1 must come first. Phases 2 and 3 can be parallelized (different modules, different concerns). Phase 4 must come last because it replays everything including shocks.

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Adding Round 4 for Shocks
**What:** Making shock injection add a "Round 4" to the simulation.
**Why bad:** The entire architecture assumes exactly 3 rounds. Neo4j queries filter `round: 3` for final consensus. Report tools query Round 3. TUI progress assumes 3 rounds. Changing this breaks everything.
**Instead:** Shock modifies the context for the NEXT existing round (Round 2 or 3), not a new round.

### Anti-Pattern 2: Rendering HTML from Markdown
**What:** Running `markdown` library over the existing markdown output to produce HTML.
**Why bad:** Loses structure. The report data is structured (dicts) -- rendering to markdown then parsing back to HTML throws away the structure. Also, markdown-to-HTML converters produce unstyled output that needs post-processing.
**Instead:** Render HTML directly from the same structured data using HTML Jinja2 templates. Two parallel template sets, one data source.

### Anti-Pattern 3: Live Portfolio Data Fetch During Simulation
**What:** Fetching real-time prices for portfolio holdings during simulation.
**Why bad:** Adds network dependency to post-simulation path. Market data is already cached for simulation tickers. Portfolio analysis is a comparison exercise, not a data fetch exercise.
**Instead:** Use market data already in Neo4j (MarketDataSnapshot nodes) for holdings that overlap with simulation tickers. For non-overlapping tickers, show cost basis only with "no simulation data" note.

### Anti-Pattern 4: Replay Re-Running LLM Inference
**What:** Re-running agent inference during replay.
**Why bad:** Defeats the purpose of replay (fast, deterministic). Wastes compute. Results would differ from original (LLM sampling is stochastic).
**Instead:** Replay reads stored decisions from Neo4j and feeds them to StateStore. Zero LLM calls.

### Anti-Pattern 5: Modifying StateStore for Bidirectional Communication
**What:** Making StateStore a general-purpose message bus between TUI and simulation.
**Why bad:** StateStore is designed as unidirectional (sim writes, TUI reads). Adding arbitrary bidirectional channels breaks the simplicity and introduces synchronization complexity.
**Instead:** Add a single `asyncio.Queue[ShockEvent]` specifically for shock injection. This is a narrow, typed channel -- not a general message bus. One producer (TUI), one consumer (simulation). Follows the existing `_rationale_queue` pattern.

---

## Scalability Considerations

| Concern | Current (v3.0) | After v4.0 |
|---------|----------------|------------|
| Neo4j node count per cycle | ~600 (100 agents x 3 decisions + posts + episodes) | ~610 (+ ShockEvent nodes, negligible) |
| Report generation time | ~30s (ReACT loop, 5-8 iterations) | ~35s (+ portfolio analysis LLM call) |
| HTML report file size | N/A | ~50-100KB (self-contained, no images) |
| Replay memory | N/A | Minimal -- reads Neo4j in chunks per round |
| Portfolio CSV parsing | N/A | Negligible -- <100 holdings, pure Python |

No scalability concerns for v4.0. All features are additive and lightweight relative to the existing 100-agent simulation.

---

## Sources

- Codebase analysis: `simulation.py` (1580 LOC), `graph.py` (1708 LOC), `report.py` (372 LOC), `tui.py` (1046 LOC), `state.py` (255 LOC), `cli.py` (890 LOC)
- Schwab CSV format: direct examination of `schwab/holdings.csv` and raw export files
- Jinja2 HTML templating: existing pattern in `report.py` with `autoescape=False` for markdown, inverted to `autoescape=True` for HTML
- Neo4j schema: `SCHEMA_STATEMENTS` in `graph.py` + Cypher queries throughout
