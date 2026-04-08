# Phase 20: Report Enhancement and Integration Hardening - Context

**Gathered:** 2026-04-07 (assumptions mode)
**Status:** Ready for planning

<domain>
## Phase Boundary

The post-simulation report (built in Phase 15) is extended with a market data context section that shows the live market conditions available to agents during simulation, and a per-ticker comparison that contrasts agent consensus direction against actual market indicators. No changes to the simulation engine, agent prompts, or TUI. The existing 8-section ReACT report structure is preserved; market context is a new 9th section assembled via a non-LLM path. A full v3 end-to-end smoke test verifies the pipeline completes without errors.

</domain>

<decisions>
## Implementation Decisions

### Market Context Section Architecture
- **D-01:** Market data context section is **assembler-injected** (non-ReACT path) — not a 9th ReACT tool. The `_handle_report()` CLI handler fetches market data snapshots from Neo4j directly (new `read_market_context()` graph method), then passes the result alongside ReACT observations into `ReportAssembler.assemble()`. The assembler renders it as a dedicated section in canonical position (before or after the 8 existing sections).
- **D-02:** `REACT_SYSTEM_PROMPT`, `TOOL_TO_TEMPLATE`, `SECTION_ORDER`, and `MAX_ITERATIONS` in `report.py` are **not changed**. The existing 8-tool ReACT loop runs as-is; market context is injected separately by the assembler after the ReACT loop completes.
- **D-03:** The `assemble()` method signature is extended to accept an optional `market_context_data` parameter. When provided, the market context section is rendered using a new `09_market_context.j2` template and prepended to the section list (before consensus summary, so users see market conditions first). When absent (e.g., no tickers in cycle), the section is silently skipped.

### Per-Ticker Consensus Data Source
- **D-04:** Phase 20 adds a new **Neo4j write** for per-ticker consensus: after each round in `simulation.py`, the `TickerConsensus` objects (already computed by `compute_ticker_consensus()`) are persisted to Neo4j as `TickerConsensusSummary` nodes linked to the Cycle and Ticker nodes. This makes per-ticker vote counts queryable from the `report` CLI command.
- **D-05:** New `GraphStateManager` method: `write_ticker_consensus_summary(cycle_id, round_num, consensus_list)` — UNWIND batch write, same pattern as `create_ticker_with_market_data()`. Stores: `ticker`, `round_num`, `weighted_signal`, `weighted_score`, `majority_signal`, `majority_pct`.
- **D-06:** New `GraphStateManager` method: `read_market_context(cycle_id)` — Cypher query that fetches `(Cycle)-[:HAS_TICKER]->(t:Ticker)-[:HAS_MARKET_DATA]->(md)` + latest `TickerConsensusSummary` for each ticker in the cycle. Returns a list of dicts combining market snapshot fields with final-round consensus signals — the raw data for the comparison narrative.
- **D-07:** The comparison narrative in `09_market_context.j2` uses Jinja2 logic to produce lines like: `TSLA: Agents 72% SELL | Last close $185.40 | 30d change -12.3% | P/E 62.1`. The template handles None financial fields with a `| default('N/A')` filter — no Python-side null-coalescing needed.

### Headlines in Market Context
- **D-08:** Headlines are **excluded** from the report market context section. The `read_market_context()` Cypher query returns only the fields stored in Neo4j (financial metrics, price data). Reading from disk cache in a CLI command that doesn't have access to the cache path creates a new external dependency; excluding headlines keeps the report fully graph-sourced and consistent.
- **D-09:** If a ticker's `MarketDataSnapshot` was degraded (the `is_degraded` flag is stored in Neo4j via `graph.py:297`), the template adds a `[degraded data]` marker next to that ticker's row.

### E2E Integration Test Shape (SC3)
- **D-10:** Phase 20 adds unit tests for:
  - `read_market_context()` Cypher query (mocked Neo4j session, same pattern as `test_graph.py`)
  - `write_ticker_consensus_summary()` UNWIND write (mocked session)
  - `ReportAssembler.assemble()` with `market_context_data` present and absent (assert section heading appears / is skipped)
  - `09_market_context.j2` template rendering with full and partial data (None fields render as N/A; degraded flag renders marker)
- **D-11:** SC3 ("full v3 simulation end-to-end completes without errors") is verified by extending the existing `test_report.py` integration fixture to include a mocked `market_context_data` block passed to `assemble()` — asserts the output markdown contains the `## Market Context` heading and at least one ticker row. No live Ollama or Neo4j required.

### Claude's Discretion
- Exact Cypher query structure for `read_market_context()` (OPTIONAL MATCH for TickerConsensusSummary to handle cycles where write_ticker_consensus_summary was never called)
- Whether `TickerConsensusSummary` nodes are linked via `(Ticker)-[:HAS_CONSENSUS]->(tcs)` or `(Cycle)-[:HAS_CONSENSUS]->(tcs)` — either works; use whichever is more efficient for the query
- Exact section heading and Jinja2 template formatting (column widths, separator lines, field order)
- Whether `market_context_data` is a `list[dict]` or a typed `MarketContextRow` dataclass passed to the assembler

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Report Layer (Primary)
- `src/alphaswarm/report.py` — `ReportAssembler.assemble()` (signature to extend with `market_context_data`), `SECTION_ORDER`, `TOOL_TO_TEMPLATE` (do NOT modify), `ReportEngine` (do NOT modify), `write_report()` / `write_sentinel()`
- `src/alphaswarm/templates/report/` — existing 8 `.j2` files as style reference; new `09_market_context.j2` goes here
- `src/alphaswarm/cli.py:_handle_report()` (line 682) — where market context fetch and assembler injection are wired

### Graph Layer (Primary)
- `src/alphaswarm/graph.py:create_ticker_with_market_data()` (line 260) — pattern for `write_ticker_consensus_summary()` UNWIND batch write
- `src/alphaswarm/graph.py:_create_tickers_tx()` (line 321) — exact Cypher UNWIND pattern to replicate
- `src/alphaswarm/graph.py:read_consensus_summary()` (line 1189) — pattern for `read_market_context()` session + tx method pair
- `src/alphaswarm/graph.py:_read_consensus_summary_tx()` (line 1210) — tx function pattern

### Simulation Integration
- `src/alphaswarm/simulation.py:compute_ticker_consensus()` — output already computed per-round; Phase 20 calls `write_ticker_consensus_summary()` at same points as `set_ticker_consensus()` in StateStore
- `src/alphaswarm/state.py:TickerConsensus` — fields to mirror in Neo4j node (`ticker`, `round_num`, `weighted_signal`, `weighted_score`, `majority_signal`, `majority_pct`)

### Types
- `src/alphaswarm/types.py:MarketDataSnapshot` (line 100) — fields available in Neo4j: `pe_ratio`, `market_cap`, `fifty_two_week_high`, `fifty_two_week_low`, `eps_trailing`, `last_close`, `price_change_30d_pct`, `price_change_90d_pct`, `avg_volume_30d`, `is_degraded`

### Tests
- `tests/test_report.py` — existing mock patterns (`_mock_ollama_response`, `AsyncMock` tools) to extend for Phase 20 tests
- `tests/test_graph.py` — mock session / tx pattern for new `read_market_context()` and `write_ticker_consensus_summary()` tests

### Prior Phase Context
- `.planning/phases/15-post-simulation-report/15-CONTEXT.md` — D-07/D-08 (8 section definitions, Jinja2 template structure), D-09 (Jinja2 Environment config in `ReportAssembler.__init__()`)
- `.planning/phases/17-market-data-pipeline/17-CONTEXT.md` — Neo4j storage decisions for Ticker/MarketDataSnapshot nodes
- `.planning/phases/19-per-stock-tui-consensus-display/19-CONTEXT.md` — D-05 (`TickerConsensus` dataclass fields), D-08 (`compute_ticker_consensus()` logic)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `graph.py:create_ticker_with_market_data()` + `_create_tickers_tx()` — direct template for `write_ticker_consensus_summary()`: same UNWIND + MERGE/CREATE Cypher pattern, same `try/except Neo4jError` wrapper, same `_log.info()` call
- `graph.py:read_consensus_summary()` + `_read_consensus_summary_tx()` — direct template for `read_market_context()`: session-per-method pattern, tx function extracts records as dicts
- `ReportAssembler.assemble()` (`report.py:274`) — already handles an `obs_by_tool` dict with optional keys; extend to accept and render `market_context_data` block outside the observations loop
- Existing `.j2` templates (especially `03_bracket_narratives.j2`) — `{% for item in data %}` row-rendering pattern for the per-ticker comparison table
- `simulation.py:compute_ticker_consensus()` — result is `tuple[TickerConsensus, ...]`; call `await graph_manager.write_ticker_consensus_summary(cycle_id, round_num, list(ticker_consensus))` immediately after `await state_store.set_ticker_consensus(ticker_consensus)`

### Established Patterns
- All new graph write methods: UNWIND batch, `try/except Neo4jError` → `Neo4jWriteError`, `structlog` component logger
- All new graph read methods: session-per-method, `execute_read()`, return `list[dict]` or `dict`
- Jinja2 templates: `autoescape=False` (markdown output), `trim_blocks=True`, `lstrip_blocks=True`, `| default('N/A')` filter for nullable fields
- `_handle_report()` extension: fetch market data immediately after resolving `cycle_id`, before building tool registry

### Integration Points
- `simulation.py` — add `await graph_manager.write_ticker_consensus_summary(...)` call after `set_ticker_consensus()` at each round-completion point (all 3 rounds)
- `graph.py:GraphStateManager` — add `write_ticker_consensus_summary()` and `read_market_context()` methods
- `report.py:ReportAssembler.assemble()` — add optional `market_context_data` parameter; render `09_market_context.j2` when present
- `cli.py:_handle_report()` — call `await gm.read_market_context(cycle_id)` after resolving cycle_id; pass result to `assembler.assemble()`
- `src/alphaswarm/templates/report/09_market_context.j2` — new template file

</code_context>

<specifics>
## Specific Ideas

- Comparison line format per ticker: `TSLA: Agents 72% SELL | Last close $185.40 | 30d change -12.3% | P/E 62.1` — weighted signal is primary, majority_pct inline, key market indicators on same row
- `is_degraded` flag → `[degraded data]` marker in the template — keeps users aware that the market data for a ticker was incomplete during simulation
- Market context section placed first (before Consensus Summary) so users see real market conditions before reading agent reactions

</specifics>

<deferred>
## Deferred Ideas

- News headlines in report — headlines are not stored in Neo4j; including them would require a new disk-cache read path in the CLI handler. Deferred to a future enhancement.
- Interactive HTML report output — would require a full template refactor. Deferred.
- `TickerDecision.expected_return_pct` and `time_horizon` display in report — these Phase 18 fields are also not stored in Neo4j currently. Could be a future Phase 20.x enhancement.

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 20-report-enhancement-and-integration-hardening*
*Context gathered: 2026-04-07*
