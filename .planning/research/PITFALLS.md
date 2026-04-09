# Pitfalls Research: v4.0 Interactive Simulation & Analysis

**Domain:** Adding mid-simulation shock injection, simulation replay from Neo4j, HTML report export with charts, and portfolio impact analysis to an existing multi-agent LLM financial simulation engine (M1 Max 64GB, Ollama, Neo4j Community, Textual TUI)
**Researched:** 2026-04-09
**Confidence:** HIGH (verified against existing codebase architecture -- simulation.py, governor.py, state.py, graph.py, tui.py, report.py, types.py -- plus Neo4j async driver docs, Textual patterns, and LLM privacy research)

---

## Critical Pitfalls

Mistakes that cause deadlocks, data corruption, privacy violations, or require architectural rewrites.

---

### Pitfall 1: Shock Injection Corrupts Governor State Machine -- Mid-Round Injection Races With TokenPool

**What goes wrong:** Mid-simulation shock injection between rounds requires re-running the agent dispatch with modified context (the shock event). The `ResourceGovernor` has a 5-state machine (RUNNING, THROTTLED, PAUSED, CRISIS, RECOVERING) with a `TokenPool` that tracks debt when tokens are checked out during shrink operations. The current architecture calls `governor.stop_monitoring()` at the end of Round 1 (which resets pool to baseline) and starts a fresh session for Rounds 2-3.

Injecting a shock between rounds means the governor must either: (a) stay alive across the inter-round gap while awaiting user input, or (b) be stopped and restarted around the shock processing. Option (a) is dangerous because the monitor loop continues checking memory while no agents are running, potentially entering THROTTLED/PAUSED state from unrelated system memory pressure (other apps, Neo4j heap, etc.). When agents resume after the shock, they encounter a governor in an unexpected state with a degraded TokenPool. Option (b) triggers the `pool.reset()` in `stop_monitoring()`, which resets to `baseline_parallel` -- but if the governor had scaled up during the round due to low memory pressure, that scale-up history is lost.

The truly critical race: if the shock injection involves an LLM call (e.g., orchestrator parses the shock event to extract entities, similar to `inject_seed()`), this LLM call happens in the gap between rounds while the worker model may still be loaded. With `OLLAMA_MAX_LOADED_MODELS=2`, loading the orchestrator to parse the shock would evict the worker, requiring a cold reload (30+ seconds) for the next round. Bug 7 from the governor deadlock analysis showed exactly this pattern: model loaded too early burns keep_alive time.

**Why it happens:** The current `run_simulation()` has a clean sequential flow: Round 1 -> compute influence -> Round 2 -> compute influence -> Round 3 -> COMPLETE. There is no "pause point" between rounds where external input can be injected. Developers try to add an `await shock_event.wait()` between rounds without understanding that the governor's monitoring session, model lifecycle, and StateStore phase all need coordinated pausing and resuming.

**How to avoid:**
1. Define an explicit `SimulationPhase.SHOCK_PENDING` state in the lifecycle enum. Between rounds, transition to this state, which signals the governor to enter a "suspended" mode -- monitor loop pauses (no state transitions) but does NOT reset the pool
2. Add `governor.suspend()` / `governor.resume()` methods that pause the monitor loop without resetting state (unlike `stop_monitoring()` which resets everything). The suspend simply cancels the `_monitor_task` and preserves `_state`, `_pool`, and `_crisis_start` as-is
3. Process shock events using the worker model (qwen3.5:9b), NOT the orchestrator. The shock is a text injection into agent prompts, not a structured extraction task. If orchestrator-quality parsing is needed, do it BEFORE loading the worker model for the round -- same pattern as `inject_seed()` which runs before `run_round1()`
4. Design the shock as prompt context, not a re-run. Agents in the next round receive the shock text prepended to their peer context, not a separate dispatch. This avoids doubling the inference cost

**Warning signs:**
- Governor enters PAUSED during inter-round gap despite low memory usage (monitor running with no agents = memory pressure from other sources triggers false transitions)
- Cold model reload after shock injection (30+ second gap in TPS telemetry)
- `pool.current_limit` drops to `baseline_parallel` after shock gap when it was previously scaled up
- `TokenPool.debt` is non-zero when agents resume after shock (leftover debt from pre-shock round)

**Phase to address:** SHOCK-01 (first shock injection phase) -- governor suspend/resume must be implemented before any inter-round pause logic

**Recovery if it occurs:** If governor state is corrupted mid-simulation, call `governor.stop_monitoring()` (full reset) and restart from the current round with fresh governor session. Agent decisions from the completed round are already persisted in Neo4j and can be re-read. The simulation will lose governor scale-up history but will not lose data.

---

### Pitfall 2: Replay Loads Full Graph Into Memory -- N+1 Query Explosion Kills Neo4j Connection Pool

**What goes wrong:** Simulation replay requires reconstructing the full state of a past simulation from Neo4j: 100 agents x 3 rounds of decisions, bracket summaries, influence edges, rationale episodes, posts, and ticker consensus. The naive approach issues one query per agent per round (300 queries for decisions alone), plus additional queries for influence edges, posts, and bracket summaries. The current `GraphStateManager` uses a session-per-method pattern with `max_connection_pool_size=50`. At 300+ queries, the connection pool saturates, queries queue, and latency spikes cause Bolt timeout errors.

The deeper problem: the current graph schema stores decisions indexed by `(cycle_id, round)` with composite indexes, which is efficient for current-round reads during simulation. But replay needs ALL rounds for a cycle at once. There is no "load full cycle" query -- every read method (`read_peer_decisions`, `read_ranked_posts`, `read_cycle_entities`, `read_market_context`) takes `cycle_id` + `round_num` as parameters, forcing per-round queries.

Additionally, the existing `StateStore` is a mutable container designed for live simulation writes. Replaying into it means overwriting whatever is currently in the store. If the TUI is still connected to the store (e.g., displaying a "simulation complete" screen), switching to replay mode without creating a fresh `StateStore` instance will produce ghost state where live and replay data intermingle.

**Why it happens:** Developers use the existing read methods designed for single-round lookups during live simulation and iterate over rounds. "It works for one round, so I'll call it three times" seems reasonable but multiplies by the number of data types being read (decisions, posts, episodes, influence, consensus = 5 types x 3 rounds = 15 query batches, each containing sub-queries).

**How to avoid:**
1. Write a dedicated `read_full_cycle(cycle_id)` method on `GraphStateManager` that returns all data for a cycle in 2-3 large Cypher queries using COLLECT + UNWIND aggregation, not per-round iteration. Example: one query returns all Decision nodes for the cycle, grouped by round, with COLLECT for bracket summaries
2. Create a `ReplayStateStore` (or factory method `StateStore.from_replay(cycle_data)`) that is pre-populated and read-only. Do NOT mutate the live `StateStore`. The TUI's 200ms snapshot timer should be pointed at the replay store, not the live store
3. Pre-compute the replay data in a background Worker (Textual Worker pattern), not in the TUI's event loop. The graph queries block for 500ms-2s even with efficient Cypher. Use `self.run_worker(load_replay_data(...))` and handle the `Worker.StateChanged` event
4. Add a cycle list query (`read_available_cycles()`) that returns cycle metadata (seed_rumor, timestamp, ticker count, round count) for the replay selector UI without loading full cycle data

**Warning signs:**
- Replay load takes 5+ seconds (N+1 query problem)
- Neo4j Bolt timeout errors in structlog during replay
- TUI shows stale data during replay load (ghost state from live store)
- Connection pool exhaustion logs: "Failed to acquire connection from the pool"

**Phase to address:** REPLAY-01 (first replay phase) -- the `read_full_cycle()` query must be designed before building replay UI

**Recovery if it occurs:** If replay queries exhaust the connection pool, add `acquire_timeout=30` to the driver config and implement query batching. If ghost state occurs, create a new `StateStore()` instance for each replay session.

---

### Pitfall 3: Schwab CSV Portfolio Data Leaks Into Neo4j, Disk Cache, or LLM Context Window History

**What goes wrong:** The portfolio impact analysis reads the user's Schwab brokerage CSV (holdings, positions, cost basis -- highly sensitive financial data). The constraint is explicit: "Schwab portfolio CSV must NEVER be persisted to Neo4j or disk cache -- in-memory only during report step." But the current architecture has multiple persistence paths that could accidentally capture this data:

1. **Neo4j leakage:** The `ReportEngine` ReACT loop accumulates `ToolObservation` records. If a `portfolio_impact` tool is added to the ReACT tool registry, the tool's return value (containing portfolio data) gets stored in `observations` and passed to `ReportAssembler.assemble()`. The assembler renders this into the markdown report, which is written to disk via `write_report()`. The report itself on disk is fine (user expects to see their portfolio analysis), but if the raw `ToolObservation.result` dict also gets persisted to Neo4j as part of a "report metadata" write, the portfolio data ends up in the graph.

2. **LLM context leakage:** The ReACT loop passes ALL previous observations as chat history to the orchestrator LLM. If portfolio data is provided as a tool observation early in the loop, every subsequent LLM call includes the portfolio in its context. With `num_ctx=4096`, this may push out other important context. Worse, if Ollama's conversation caching retains this context across sessions, the portfolio data persists in Ollama's KV cache on disk.

3. **Structlog leakage:** If `structlog` logs the portfolio tool observation at DEBUG level (the ReACT engine already logs `react_step` with action name), and the log sink writes to a file or structured logging service, the portfolio data appears in logs.

**Why it happens:** The ReACT engine is designed to be generic -- tools return data, observations accumulate, the LLM reasons over all observations. There is no concept of "sensitive" vs "non-sensitive" tool data. Adding portfolio analysis as "just another tool" means it follows the same data flow as bracket_summary or round_timeline, which are fine to persist everywhere.

**How to avoid:**
1. Do NOT implement portfolio analysis as a ReACT tool. Instead, run it as a separate post-report step: after the ReACT loop completes and the base report is assembled, load the CSV, run a single orchestrator LLM call with the consensus data + portfolio holdings, and append the result as a markdown section. The portfolio data never enters the ReACT observation chain
2. Parse the Schwab CSV into an in-memory dataclass (`PortfolioSnapshot`) with an explicit `__del__` that zeros the holdings data. Use `del portfolio_snapshot` and `gc.collect()` immediately after the analysis section is rendered
3. Mark the portfolio analysis section in the markdown report with a `<!-- PORTFOLIO_DATA_START -->` / `<!-- PORTFOLIO_DATA_END -->` comment pair. The HTML exporter can optionally strip this section for "shareable" exports vs "personal" exports
4. Never log portfolio data. The portfolio analysis function should use a `structlog.get_logger().bind(redacted=True)` context that a custom processor strips before output
5. Add an explicit `assert not graph_manager.has_portfolio_data(cycle_id)` check as a test assertion in the portfolio phase test suite

**Warning signs:**
- Portfolio holdings appear in structlog JSON output
- Neo4j Browser query `MATCH (n) WHERE n.holdings IS NOT NULL RETURN n` returns results
- The markdown report file is larger than expected (portfolio data duplicated in raw observations section)
- Ollama's `~/.ollama/` directory grows after portfolio analysis (KV cache retained)

**Phase to address:** PORTFOLIO-01 (first portfolio phase) -- data flow architecture must be designed to exclude portfolio data from ALL persistence paths from day one

**Recovery if it occurs:** If portfolio data leaks to Neo4j: `MATCH (n) WHERE n.holdings IS NOT NULL DETACH DELETE n` and audit all write methods. If it leaks to logs: rotate/delete log files and add the redaction processor. If it leaks to Ollama cache: restart Ollama to clear KV cache.

---

### Pitfall 4: Shock Injection Invalidates In-Progress Influence Topology and Consensus Aggregation

**What goes wrong:** The simulation computes influence edges after Round 1 (`compute_influence_edges(cycle_id, up_to_round=1)`) and uses those weights for Round 2 peer selection. The weights are derived from citation patterns, agreement patterns, and bracket diversity in Round 1 decisions. A shock event injected between Round 1 and Round 2 changes the information landscape -- agents who were "correct" pre-shock may now be "wrong."

If the shock is injected AFTER Round 1 influence computation but BEFORE Round 2 dispatch, the influence weights used for Round 2 peer selection are based on pre-shock reality. The post-shock Round 2 agents receive peer context from the most influential pre-shock agents, who may now be giving outdated or contradictory advice. This creates a confusing divergence: agents are influenced by pre-shock leaders but must react to post-shock conditions.

The `TickerConsensus` aggregation faces the same problem: Round 1 ticker consensus is computed pre-shock. If the TUI displays this alongside the post-shock Round 2 consensus, the visual comparison is misleading -- the "shift" between rounds is not just agent evolution, it includes the shock effect, but there is no visual indicator distinguishing organic shifts from shock-induced shifts.

**Why it happens:** The influence edge computation is an expensive Neo4j operation that runs once per round. Developers treat it as immutable between rounds. The shock injection concept was not part of the original 3-round cascade design, so there is no "recompute after external event" trigger.

**How to avoid:**
1. Mark shock-injected rounds with a `shock_event` property on the Cycle node in Neo4j: `SET c.shock_round_2 = $shock_text`. This creates an audit trail for which rounds were influenced by shocks
2. Do NOT recompute Round 1 influence edges after a shock. The pre-shock weights are the correct inputs for peer selection -- agents should see what their peers thought BEFORE the shock. The shock itself IS the new information. Recomputing would create a paradox (weights based on reactions to a shock that agents have not yet seen)
3. Add a `shock_injected: bool` field to `StateSnapshot` and `RoundCompleteEvent`. The TUI can display a visual indicator (e.g., lightning bolt icon in HeaderBar) for rounds that follow a shock injection
4. In the shift metrics computation (`_compute_shifts()`), distinguish shock-induced flips from organic flips by comparing the shock-round's flip rate against the non-shock round. Surface this in the CLI callback and report

**Warning signs:**
- Round 2 agents unanimously flip from Round 1 consensus (100% flip rate = shock overwhelmed peer influence, normal is 10-30%)
- Users confused by "why did the consensus change so dramatically" without shock indication in TUI
- Report does not mention the shock event, making the Round 1 -> Round 2 shift analysis misleading

**Phase to address:** SHOCK-02 (shock + TUI integration) -- visual indicators and graph metadata must be added alongside shock processing, not as an afterthought

**Recovery if it occurs:** Add the `shock_round_N` property to existing Cycle nodes retroactively. The influence weights do not need recomputation -- the pre-shock weights are correct by design.

---

### Pitfall 5: HTML Export Produces 15MB+ Files -- Plotly.js Bundling and Base64 Charts Explode File Size

**What goes wrong:** The existing report system produces markdown via Jinja2 templates (`ReportAssembler`). Converting this to HTML with embedded chart visualizations requires either: (a) interactive charts via Plotly.js (3MB+ library bundle per file), or (b) static chart images embedded as base64 data URIs. A report with 8 sections, 3 tickers, and 10 brackets could need 10-15 charts. With Plotly.js in self-contained mode: 3MB library + chart data = 5-8MB per file. With base64 PNG charts at 50KB each: 15 charts x 50KB = 750KB of base64 data.

The self-contained requirement (no CDN dependency, no external files) means the full Plotly.js bundle must be inlined. Opening a 15MB HTML file in a browser causes a multi-second render delay. Emailing the report may hit attachment size limits (10-25MB depending on provider). The user expects a clean, shareable document -- not a bloated artifact.

**Why it happens:** Developers pick Plotly for interactivity ("users can hover over data points") without considering the offline cost. Plotly.js is 3MB minified. Each interactive chart adds JSON data to the HTML. The "self-contained" requirement is often added late, after the Plotly integration is already built.

**How to avoid:**
1. Use SVG charts, NOT Plotly. SVGs are vector, tiny (2-20KB per chart), and render instantly. For consensus bars, sentiment timelines, and bracket distribution, SVG is more than sufficient. Libraries: `matplotlib` with `savefig(format='svg')` or `pygal` for declarative SVG charts
2. Inline the SVGs directly into HTML (no base64 encoding needed for SVG -- it is valid HTML). This produces a self-contained HTML file under 500KB even with 15 charts
3. Use the existing Jinja2 infrastructure (`ReportAssembler._env`) to render HTML templates. Add an HTML template set alongside the existing markdown templates. The assembler already has the section-ordering logic -- add `output_format: Literal["markdown", "html"]` to `assemble()`
4. Inline CSS in a single `<style>` block in the HTML head. Use the existing AlphaSwarm color scheme (the `_SIGNAL_COLORS` dict in tui.py: `#66BB6A` for buy, `#EF5350` for sell, `#78909C` for hold). Do NOT use a CSS framework (Bootstrap, Tailwind) -- it adds 100KB+ for a report that needs 50 lines of CSS
5. If interactivity is genuinely needed later, use Plotly's CDN mode with a `--self-contained` flag that switches to inline for offline sharing. But start with SVG

**Warning signs:**
- HTML file exceeds 1MB (check before shipping the feature)
- Browser takes 2+ seconds to render the report
- Email clients strip or block the attachment
- Chart fonts render differently across systems (base64 PNG) vs consistently (SVG with embedded fonts)

**Phase to address:** EXPORT-01 (first HTML export phase) -- chart strategy must be decided before writing any chart generation code. SVG-first, Plotly-never for v4.0

**Recovery if it occurs:** If Plotly is already integrated, replace chart generation functions with matplotlib SVG equivalents. The Jinja2 template layer insulates the report assembly from the chart implementation -- only the chart rendering functions need to change.

---

### Pitfall 6: Replay TUI Fights Live TUI for StateStore Ownership -- Single-Store Architecture Cannot Serve Both

**What goes wrong:** The current `StateStore` is a singleton created once in `create_app_state()` and shared between the simulation engine (writer) and the TUI (reader via 200ms snapshots). The `StateStore.snapshot()` method has a documented side effect: it drains up to 5 rationale entries from the internal queue per call. This is a destructive read.

When replay mode is added, the TUI needs to display historical data from a past simulation. If replay writes historical data into the same `StateStore` instance, three problems emerge:

1. **Destructive rationale drain:** Each `snapshot()` call drains 5 rationale entries. During replay, if you push all 300 rationale entries (100 agents x 3 rounds) at once, they will be drained over 60 snapshot ticks (12 seconds at 200ms). But the user might want to scrub forward/backward through rounds, which requires re-pushing rationale entries. The queue-based design does not support random access.

2. **Phase state conflict:** `StateStore.set_phase()` clears `_agent_states` when transitioning to a new round phase. During replay, transitioning from Round 1 to Round 2 display wipes the Round 1 agent states. If the user scrubs back to Round 1, the data is gone -- it was cleared on the forward transition and not preserved.

3. **Elapsed timer corruption:** `StateStore._start_time` is set on the first non-IDLE phase and `_final_elapsed` freezes on COMPLETE. Replaying a second simulation overwrites these values, showing incorrect elapsed time.

**Why it happens:** `StateStore` was designed as a write-once-read-many store for a single simulation lifecycle. It has no concept of "multiple simulation states" or "read without consuming." The queue-based rationale sidebar is explicitly a destructive consumer -- documented as a design decision in Phase 10.

**How to avoid:**
1. Build replay on a completely different data path. Create a `ReplayStore` class that holds ALL rounds' data pre-loaded (not streamed) with random access by round number. The `ReplayStore.snapshot(round_num)` method returns a `StateSnapshot` for any round without side effects
2. The TUI should accept a `store: StateStore | ReplayStore` via a common protocol. Both expose `snapshot() -> StateSnapshot`, but `ReplayStore.snapshot()` takes an optional `round_num` parameter and does NOT drain queues
3. For replay, pre-compute all `StateSnapshot` objects during the graph load phase (one per round) and store them in a `list[StateSnapshot]`. The TUI scrubs through this list by index. No mutable state, no queue drain, no phase transitions
4. The TUI's 200ms timer in replay mode should NOT call `snapshot()` repeatedly. Instead, it renders from the cached snapshot and only updates when the user navigates to a different round (event-driven, not poll-driven)

**Warning signs:**
- Replayed simulation shows "00:00:00" elapsed time (timer overwritten)
- Rationale sidebar is empty during replay (all entries drained before display)
- Scrubbing backward shows empty agent grid (agent_states cleared by forward phase transition)
- Two simulations bleed into each other in the TUI display

**Phase to address:** REPLAY-01 -- the `ReplayStore` must be the first thing built, before any TUI replay integration

**Recovery if it occurs:** If you built replay on `StateStore` and it doesn't work, extract the snapshot pre-computation into a `ReplayStore` and update TUI bindings. The graph queries and data loading are reusable -- only the in-memory storage layer needs replacement.

---

### Pitfall 7: Portfolio CSV Parsing Assumes Schwab Export Format Is Stable -- Schema Drift Breaks Analysis

**What goes wrong:** Schwab's CSV export format for portfolio holdings is not documented with a stable schema. Column names, order, and data formatting change between Schwab platform updates (classic vs. modern platform). Common variations include:

- Column name changes: "Symbol" vs "Sym" vs "Ticker", "Quantity" vs "Shares" vs "Qty"
- Cost basis formats: "$1,234.56" (with dollar sign and commas) vs "1234.56" (bare number)
- Date formats: "MM/DD/YYYY" vs "YYYY-MM-DD"
- Header row position: some exports have 1-2 metadata rows before the header
- Account type prefixes: "AAPL" vs "AAPL (Margin)" vs "AAPL - Individual"
- Cash positions: "Cash & Cash Investments" row with special formatting
- Empty rows or summary rows at the bottom of the file

A rigid CSV parser that expects exact column names will fail silently (missing column = empty portfolio) or crash (KeyError) when the user upgrades their Schwab app or downloads from a different Schwab interface.

**Why it happens:** Developers test with one sample CSV and hard-code the column names. Schwab does not publish a CSV specification. Each developer's Schwab export may have slightly different formatting based on account type, platform version, or export date.

**How to avoid:**
1. Use fuzzy column matching: normalize all column headers to lowercase + strip whitespace, then match against a priority list of known variants. Example: `{"symbol": ["symbol", "sym", "ticker", "security"], "quantity": ["quantity", "shares", "qty", "amount"]}`
2. Validate the parsed result: after parsing, check that every row has a non-empty symbol and a numeric quantity. Log warnings for rows that fail validation and skip them (do not crash)
3. Strip currency formatting: `re.sub(r'[$,]', '', value)` before `float()` conversion
4. Skip metadata rows: detect the header row by scanning for the first row that contains at least 3 of the expected column name variants
5. Provide a clear error message when parsing fails completely: "Could not parse Schwab CSV -- expected columns [Symbol, Quantity, ...], found [...]"
6. Include 2-3 sample CSVs in the test suite (different Schwab formats) and test against all of them

**Warning signs:**
- Portfolio analysis shows 0 holdings (column name mismatch, silent failure)
- `KeyError: 'Symbol'` crash during report generation
- Dollar amounts parsed as strings instead of floats (currency symbol not stripped)
- Cash position parsed as a stock holding

**Phase to address:** PORTFOLIO-01 -- CSV parser must handle format variation from the start

**Recovery if it occurs:** Add the fuzzy matching layer. The portfolio analysis function should accept a `PortfolioSnapshot` dataclass, so the parsing and analysis are decoupled -- fixing the parser does not require touching the analysis logic.

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Reuse `StateStore` for replay instead of building `ReplayStore` | Ship replay faster | Queue drain bugs, phase state corruption, no random access -- eventual rewrite | Never -- the architectural mismatch is fundamental |
| Use Plotly for HTML charts | Interactive charts look impressive | 3MB+ per file, breaks self-contained requirement, 2s render delay | Only if interactivity is explicitly required AND CDN mode is acceptable |
| Parse shock events with orchestrator model | Higher quality entity extraction | 30s cold-load delay, model lifecycle collision with worker | Only if shock parsing runs BEFORE worker model load, never between rounds |
| Inline Schwab CSV path handling instead of abstraction | Quick portfolio prototype | Locked to Schwab format, no path to other brokers | MVP only -- abstract to `BrokerCSVParser` protocol before v4.1 |
| Store portfolio data in `ToolObservation` chain | Reuse existing ReACT pattern | Portfolio data enters graph/log persistence paths | Never -- privacy constraint is absolute |
| Skip `governor.suspend()` and just stop/start monitoring | Simpler shock implementation | Lose governor scale-up history, potential pool corruption | Acceptable for v4.0 MVP if documented as tech debt with Phase ticket |

## Integration Gotchas

Common mistakes when connecting the four v4.0 features to existing subsystems.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Shock + Governor | Leaving monitor running during inter-round pause | Implement `governor.suspend()` / `governor.resume()` that pause without resetting pool state |
| Shock + TUI StateStore | Injecting shock without updating `SimulationPhase` | Add `SimulationPhase.SHOCK_PENDING` and `SHOCK_PROCESSING` phases so TUI displays shock status |
| Shock + Influence Weights | Recomputing influence weights post-shock (paradox) | Keep pre-shock weights for peer selection; the shock IS the new information agents react to |
| Replay + TUI snapshot timer | Using 200ms polling for static replay data | Switch to event-driven rendering in replay mode; poll only during live simulation |
| Replay + Neo4j | Per-round queries for full cycle reconstruction | Write `read_full_cycle()` with COLLECT aggregation in 2-3 queries max |
| Replay + Interview | Trying to interview agents from a replayed simulation | Interviews require loaded LLM model; replay is read-only. Disable interview in replay mode or require explicit model load |
| HTML Export + Report templates | Reusing markdown Jinja2 templates for HTML output | Create separate HTML template set; markdown tables do not translate to styled HTML tables automatically |
| HTML Export + Chart colors | Hardcoding chart colors separate from TUI colors | Import from shared color constants (extend `_SIGNAL_COLORS` into a `colors.py` module) |
| Portfolio + ReACT engine | Adding portfolio_impact as a ReACT tool | Run portfolio analysis as a post-ReACT step with isolated data flow; never enters observation chain |
| Portfolio + Report assembly | Persisting portfolio section alongside graph-derived sections | Use `<!-- PORTFOLIO -->` markers; provide "shareable" export that strips portfolio section |
| Portfolio + Ollama context | Sending full CSV contents in LLM prompt | Pre-aggregate: send summary (ticker, shares, weight%) not raw CSV rows. Reduces tokens and prevents data over-exposure |

## Performance Traps

Patterns that work in testing but fail at production scale.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| N+1 replay queries | 5+ second replay load, Neo4j connection pool saturation | `read_full_cycle()` with COLLECT + UNWIND aggregation | Any cycle with >50 agents (current system: 100 agents) |
| Plotly.js self-contained HTML | 15MB file, 2s browser render, email attachment rejected | SVG charts inline in HTML, no JavaScript dependencies | First report with >5 charts |
| Full CSV in LLM context | Context window overflow, portfolio data in 4096 tokens alongside consensus data | Pre-aggregate to summary table (ticker + shares + weight%), cap at 500 tokens | Portfolio with >20 holdings |
| Synchronous SVG chart generation | TUI freezes during report export | Run chart generation in `asyncio.to_thread()` (matplotlib is not async-safe) | Report with >10 charts on M1 |
| Replay loads all historical cycles for selector | Multi-second startup delay, unnecessary Neo4j reads | Paginated cycle list query with LIMIT/SKIP, lazy loading | After 50+ simulations stored in Neo4j |
| Shock event text unbounded | Shock text injected into prompt exceeds token budget | Cap shock text at 500 chars, same as seed rumor budget pattern | User pastes multi-paragraph shock text |

## Security Mistakes

Domain-specific security and privacy issues for v4.0 features.

| Mistake | Risk | Prevention |
|---------|------|------------|
| Portfolio CSV data persisted to Neo4j | User's brokerage holdings exposed in graph database accessible via Neo4j Browser | Never store portfolio data in graph; in-memory only with explicit cleanup |
| Portfolio data in structlog output | Holdings appear in log files on disk | Add `redacted=True` structlog binding; custom processor strips fields |
| Portfolio data in Ollama KV cache | Holdings persist in `~/.ollama/` model cache | Use `keep_alive=0` for the portfolio analysis LLM call; model unloads immediately after |
| Portfolio section in "shareable" HTML export | User shares report containing personal financial data | Default export strips `<!-- PORTFOLIO -->` section; require explicit `--include-portfolio` flag |
| Shock injection as attack vector | Adversarial shock text with prompt injection attempts | Sanitize shock text same as seed rumor; escape special characters, cap length |
| Replay exposes other users' simulations | In multi-operator scenario, all cycles visible | Add `operator_id` to Cycle nodes and filter replay list (future-proofing; single-operator for now) |

## UX Pitfalls

Common user experience mistakes for v4.0 features.

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Shock injection prompt blocks TUI rendering | User types shock text in modal, TUI appears frozen | Use Textual `Input` widget inline (already available in tui.py imports); non-blocking text entry |
| No visual indicator for shock-affected rounds | User sees dramatic consensus shift, confused about cause | Add lightning bolt or "SHOCK" badge in HeaderBar for post-shock rounds |
| Replay has no round navigation | User must watch entire replay sequentially | Add Round 1/2/3 buttons or keyboard shortcuts (1/2/3 keys) for instant round jump |
| HTML report opens in terminal browser (lynx/w3m) | Report looks broken in text browser | Use `webbrowser.open()` to launch system browser; log file path as fallback |
| Portfolio analysis runs silently for 30+ seconds | User thinks app is frozen during orchestrator inference | Show "Analyzing portfolio impact..." spinner in TUI or CLI progress indicator |
| Replay selector shows raw UUIDs | User cannot identify which simulation to replay | Show seed rumor text (truncated), timestamp, and ticker list instead of cycle_id |
| Chart colors don't match TUI colors | Green means BUY in TUI but different shade in HTML report | Use single color constant source for both TUI and HTML exports |

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **Shock injection:** Often missing governor suspend/resume -- verify that `pool.current_limit` and `_state` are preserved across the inter-round gap, not reset to baseline
- [ ] **Shock injection:** Often missing shock metadata in Neo4j -- verify `Cycle` node has `shock_round_N` property after shock simulation
- [ ] **Shock injection:** Often missing TUI phase indicator -- verify HeaderBar shows SHOCK_PENDING/SHOCK_PROCESSING during inter-round pause
- [ ] **Replay:** Often missing random-access round navigation -- verify user can jump to any round without sequential playback
- [ ] **Replay:** Often missing rationale sidebar population -- verify rationale entries appear for replayed rounds (not drained by snapshot polling)
- [ ] **Replay:** Often missing elapsed time display -- verify replay shows original simulation elapsed time, not current wall clock
- [ ] **HTML export:** Often missing self-contained check -- verify HTML file opens correctly with network disabled (no CDN dependencies)
- [ ] **HTML export:** Often missing chart color consistency -- verify chart colors match TUI signal colors exactly
- [ ] **HTML export:** Often missing file size check -- verify HTML file is under 1MB for typical 3-ticker simulation
- [ ] **Portfolio analysis:** Often missing privacy audit -- verify `MATCH (n) WHERE n.holdings IS NOT NULL` returns zero results in Neo4j after analysis
- [ ] **Portfolio analysis:** Often missing log redaction -- verify portfolio holdings do not appear in structlog JSON output
- [ ] **Portfolio analysis:** Often missing Ollama cache cleanup -- verify `keep_alive=0` on the portfolio LLM call
- [ ] **Portfolio analysis:** Often missing CSV format resilience -- verify parser handles at least 3 different Schwab export formats
- [ ] **Cross-feature:** Often missing model lifecycle coordination -- verify that shock parsing, replay, and portfolio analysis do not cause unexpected model evictions

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Governor state corrupted during shock | LOW | Call `governor.stop_monitoring()` (full reset), restart from current round. Agent decisions already in Neo4j. Lose scale-up history only. |
| N+1 replay query explosion | MEDIUM | Write `read_full_cycle()` query with COLLECT aggregation. Existing per-round methods remain for live simulation. Add query alongside, not replace. |
| Portfolio data leaked to Neo4j | MEDIUM | `MATCH (n) WHERE n.holdings IS NOT NULL DETACH DELETE n`. Audit all `GraphStateManager` write methods for portfolio field passthrough. Add assertion tests. |
| Portfolio data in logs | LOW | Rotate/delete log files. Add structlog processor to strip `portfolio_*` fields. |
| HTML export files too large (Plotly) | HIGH | Replace Plotly with matplotlib SVG generation. Requires rewriting all chart generation functions. Jinja2 template layer insulates assembly logic -- only chart renderers change. |
| StateStore corruption during replay | MEDIUM | Build `ReplayStore` class. Update TUI to accept `store: StateStore | ReplayStore` via protocol. ~200 LOC new class + TUI protocol change. |
| Schwab CSV parse failure | LOW | Add fuzzy column matching. Parser and analysis are decoupled via `PortfolioSnapshot` dataclass -- fix parser without touching analysis. |
| Shock text overwhelms token budget | LOW | Add `max_len=500` truncation to shock text input, same pattern as `sanitize_rationale(max_len=50)` in utils.py. |
| Model eviction during inter-feature transitions | MEDIUM | Audit model lifecycle across all v4.0 features. Create a model lifecycle state diagram showing which features need which model and when. Add `model_manager.assert_model(alias)` guard before each LLM call. |

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| P1: Governor state corruption during shock | SHOCK-01 (governor suspend/resume) | Unit test: `governor.suspend()` preserves `pool.current_limit` and `_state`; `governor.resume()` restarts monitor without reset |
| P2: N+1 replay queries | REPLAY-01 (graph query design) | Integration test: `read_full_cycle()` completes in <2s for 100-agent 3-round cycle; connection pool usage <50% |
| P3: Portfolio data leakage | PORTFOLIO-01 (data flow architecture) | Assertion test: no Neo4j nodes with portfolio properties after analysis; no portfolio fields in captured structlog output |
| P4: Shock invalidates influence topology | SHOCK-02 (TUI + graph integration) | Visual test: post-shock rounds show shock indicator; shift metrics distinguish shock-induced vs organic flips |
| P5: HTML file size explosion | EXPORT-01 (chart strategy decision) | File size assertion: HTML output <1MB for 3-ticker report; rendering test: opens in <1s in browser |
| P6: StateStore replay corruption | REPLAY-01 (ReplayStore design) | Unit test: `ReplayStore.snapshot(round_num=1)` returns consistent data on repeated calls; no side effects |
| P7: Schwab CSV schema drift | PORTFOLIO-01 (CSV parser design) | Parameterized test: parser handles 3+ CSV format variants; fuzzy column matching resolves known Schwab variations |

## Sources

- AlphaSwarm codebase analysis: `simulation.py` (run_simulation flow, governor lifecycle), `governor.py` (5-state machine, TokenPool debt tracking), `state.py` (StateStore snapshot drain, phase transitions), `graph.py` (session-per-method pattern, connection pool config), `tui.py` (200ms snapshot timer, widget patterns), `report.py` (ReACT engine, ToolObservation chain, Jinja2 assembly), `types.py` (SimulationPhase enum, AgentDecision model)
- Governor deadlock bug analysis: `/memory/bug_governor_deadlock.md` -- 7 bugs found across 2 debugging sessions, particularly Bug 7 (model loaded too early) directly relevant to shock injection timing
- [Neo4j Data Modeling Pitfalls](https://neo4j.com/blog/data-modeling-pitfalls/) -- graph schema design anti-patterns
- [Neo4j Async Python Driver API](https://neo4j.com/docs/api/python-driver/current/async_api.html) -- connection pool behavior, session lifecycle
- [Plotly HTML Export File Size](https://community.plotly.com/t/plotly-huge-html-file-size/64342) -- 3MB+ self-contained files due to plotly.js bundling
- [Textual Workers Documentation](https://textual.textualize.io/guide/workers/) -- async worker patterns, blocking handler pitfalls
- [LLM Privacy Risks 2025](https://www.sciencedirect.com/science/article/pii/S2667295225000042) -- data leakage through model context and logging
- [Python asyncio Synchronization Primitives](https://docs.python.org/3/library/asyncio-sync.html) -- semaphore thread safety constraints

---
*Pitfalls research for: v4.0 Interactive Simulation & Analysis*
*Researched: 2026-04-09*
