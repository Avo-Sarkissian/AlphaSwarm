# Phase 20: Report Enhancement and Integration Hardening - Research

**Researched:** 2026-04-07
**Domain:** Neo4j graph writes/reads, Jinja2 template rendering, report assembly, simulation integration
**Confidence:** HIGH

## Summary

Phase 20 extends the existing post-simulation report with a market data context section that compares agent consensus against real market indicators on a per-ticker basis. The implementation touches four files (graph.py, simulation.py, report.py, cli.py), adds one new Jinja2 template, and requires a new Neo4j node type (TickerConsensusSummary). All patterns are well-established in the codebase -- the UNWIND batch write, session-per-method reads, Jinja2 template rendering, and assembler extension all have direct precedents in existing code.

The `TickerConsensus` dataclass (state.py) is already computed per-round by `compute_ticker_consensus()` in simulation.py and pushed to StateStore for TUI display. Phase 20 adds a parallel Neo4j write at the same three call sites so the data becomes queryable by the report CLI command. The report assembler (`ReportAssembler.assemble()`) gains an optional `market_context_data` parameter; when provided, a `09_market_context.j2` template is rendered and prepended before the existing 8 sections.

**Primary recommendation:** Follow the existing UNWIND/session-per-method patterns exactly -- no new abstractions needed. The three simulation write sites, two graph methods, one template, and two wiring changes (cli.py + report.py) form a clean, minimal scope.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Market data context section is **assembler-injected** (non-ReACT path) -- not a 9th ReACT tool. `_handle_report()` fetches market data from Neo4j directly via `read_market_context()`, passes result to `ReportAssembler.assemble()`.
- **D-02:** `REACT_SYSTEM_PROMPT`, `TOOL_TO_TEMPLATE`, `SECTION_ORDER`, and `MAX_ITERATIONS` in `report.py` are **not changed**.
- **D-03:** `assemble()` extended with optional `market_context_data` parameter. When provided, renders `09_market_context.j2` prepended to section list. When absent, silently skipped.
- **D-04:** Phase 20 adds Neo4j write for per-ticker consensus -- `TickerConsensusSummary` nodes persisted after each round in simulation.py.
- **D-05:** New `write_ticker_consensus_summary(cycle_id, round_num, consensus_list)` -- UNWIND batch write.
- **D-06:** New `read_market_context(cycle_id)` -- Cypher query fetching `(Cycle)-[:HAS_TICKER]->(Ticker)-[:HAS_MARKET_DATA]->(MarketDataSnapshot)` + latest `TickerConsensusSummary`.
- **D-07:** Comparison narrative in `09_market_context.j2` uses Jinja2 logic for per-ticker lines with `| default('N/A')` filter.
- **D-08:** Headlines **excluded** from report market context section -- graph-sourced only.
- **D-09:** Degraded data flag renders `[degraded data]` marker.
- **D-10:** Unit tests for `read_market_context()`, `write_ticker_consensus_summary()`, `assemble()` with/without market_context_data, and template rendering.
- **D-11:** SC3 verified by extending `test_report.py` with mocked `market_context_data` in `assemble()` -- no live Ollama or Neo4j required.

### Claude's Discretion
- Exact Cypher query structure for `read_market_context()` (OPTIONAL MATCH for TickerConsensusSummary)
- Whether `TickerConsensusSummary` nodes linked via `(Ticker)-[:HAS_CONSENSUS]->(tcs)` or `(Cycle)-[:HAS_CONSENSUS]->(tcs)`
- Exact section heading and Jinja2 template formatting
- Whether `market_context_data` is `list[dict]` or a typed `MarketContextRow` dataclass

### Deferred Ideas (OUT OF SCOPE)
- News headlines in report (not stored in Neo4j)
- Interactive HTML report output
- `TickerDecision.expected_return_pct` and `time_horizon` display in report
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DRPT-01 | Post-simulation report includes market data context with agent consensus comparison | SC1: Market context section in report with price/financials. SC2: Per-ticker consensus vs market indicators comparison. SC3: Full v3 E2E simulation completes without errors. All three addressed by graph write/read methods, template, assembler extension, and CLI wiring. |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| neo4j (async driver) | >=5.28,<6.0 | Graph DB for TickerConsensusSummary writes/reads | Already in use; session-per-method pattern established |
| Jinja2 | 3.1.5 (installed) | Template rendering for `09_market_context.j2` | Already configured in `ReportAssembler.__init__()` with `FileSystemLoader` |
| structlog | >=25.5.0 | Component-scoped logging for new graph methods | Already used in all graph/report methods |
| pytest-asyncio | >=0.24.0 | Async test support (`asyncio_mode = "auto"`) | Already configured project-wide |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pydantic | >=2.12.5 | Optional: `MarketContextRow` dataclass alternative | Only if discretion choice favors typed data over plain dicts |

No new dependencies needed. Everything is already in `pyproject.toml`.

## Architecture Patterns

### Recommended File Structure (changes only)
```
src/alphaswarm/
  graph.py                          # +2 methods: write_ticker_consensus_summary(), read_market_context()
  simulation.py                     # +3 call sites: graph_manager.write_ticker_consensus_summary()
  report.py                         # assemble() signature extended with market_context_data
  cli.py                            # _handle_report() wiring: fetch + pass market_context_data
  templates/report/
    09_market_context.j2            # NEW: market context + consensus comparison template
tests/
  test_graph.py                     # +2 test classes for new graph methods
  test_report.py                    # +2 test classes for assembler extension + template rendering
```

### Pattern 1: UNWIND Batch Write (for `write_ticker_consensus_summary`)
**What:** Neo4j UNWIND pattern for batch-creating TickerConsensusSummary nodes from a list of consensus dicts.
**When to use:** When writing multiple per-ticker consensus records in a single transaction.
**Existing precedent:** `graph.py:create_ticker_with_market_data()` (line 260) + `_create_tickers_tx()` (line 321).

**Structure:**
```python
# Public method: session wrapper with error handling
async def write_ticker_consensus_summary(
    self,
    cycle_id: str,
    round_num: int,
    consensus_list: list[TickerConsensus],
) -> None:
    # Convert TickerConsensus dataclass fields to plain dicts for Cypher params
    params = [
        {
            "ticker": tc.ticker,
            "round_num": tc.round_num,
            "weighted_signal": tc.weighted_signal,
            "weighted_score": tc.weighted_score,
            "majority_signal": tc.majority_signal,
            "majority_pct": tc.majority_pct,
        }
        for tc in consensus_list
    ]
    try:
        async with self._driver.session(database=self._database) as session:
            await session.execute_write(
                self._write_ticker_consensus_tx, cycle_id, round_num, params,
            )
    except Neo4jError as exc:
        raise Neo4jWriteError(...) from exc
    self._log.info("ticker_consensus_written", cycle_id=cycle_id, round_num=round_num, count=len(params))

# Static tx function: Cypher UNWIND
@staticmethod
async def _write_ticker_consensus_tx(
    tx: AsyncManagedTransaction,
    cycle_id: str,
    round_num: int,
    consensus_params: list[dict],
) -> None:
    await tx.run(
        """
        UNWIND $params AS c
        MATCH (t:Ticker {symbol: c.ticker})
        MATCH (cy:Cycle {cycle_id: $cycle_id})
        CREATE (tcs:TickerConsensusSummary {
            round_num: c.round_num,
            weighted_signal: c.weighted_signal,
            weighted_score: c.weighted_score,
            majority_signal: c.majority_signal,
            majority_pct: c.majority_pct,
            created_at: datetime()
        })
        CREATE (t)-[:HAS_CONSENSUS]->(tcs)
        CREATE (cy)-[:HAS_CONSENSUS]->(tcs)
        """,
        cycle_id=cycle_id,
        round_num=round_num,
        params=consensus_params,
    )
```

**Key decision rationale (Discretion):** Link TickerConsensusSummary to BOTH Ticker and Cycle via dual relationships. This enables `read_market_context()` to traverse from `Cycle -> HAS_CONSENSUS -> TickerConsensusSummary` AND `Ticker -> HAS_CONSENSUS -> TickerConsensusSummary` efficiently. The dual-link is standard for many-to-many joins in Neo4j and avoids a second MATCH hop in the read query.

### Pattern 2: Session-per-Method Read (for `read_market_context`)
**What:** Cypher query that joins Ticker + MarketDataSnapshot + latest-round TickerConsensusSummary for a cycle.
**When to use:** Report generation CLI command needs combined market + consensus data.
**Existing precedent:** `graph.py:read_consensus_summary()` (line 1189) + `_read_consensus_summary_tx()` (line 1210).

**Structure:**
```python
async def read_market_context(self, cycle_id: str) -> list[dict]:
    try:
        async with self._driver.session(database=self._database) as session:
            records = await session.execute_read(
                self._read_market_context_tx, cycle_id,
            )
    except Neo4jError as exc:
        raise Neo4jConnectionError(...) from exc
    self._log.debug("report_market_context", cycle_id=cycle_id, ticker_count=len(records))
    return records

@staticmethod
async def _read_market_context_tx(
    tx: AsyncManagedTransaction,
    cycle_id: str,
) -> list[dict]:
    result = await tx.run(
        """
        MATCH (cy:Cycle {cycle_id: $cycle_id})-[:HAS_TICKER]->(t:Ticker)-[:HAS_MARKET_DATA]->(md:MarketDataSnapshot)
        OPTIONAL MATCH (t)-[:HAS_CONSENSUS]->(tcs:TickerConsensusSummary)
        WHERE (cy)-[:HAS_CONSENSUS]->(tcs)
        WITH t, md, tcs
        ORDER BY tcs.round_num DESC
        WITH t, md, collect(tcs)[0] AS latest_consensus
        RETURN
            t.symbol AS ticker,
            t.company_name AS company_name,
            md.last_close AS last_close,
            md.price_change_30d_pct AS price_change_30d_pct,
            md.price_change_90d_pct AS price_change_90d_pct,
            md.pe_ratio AS pe_ratio,
            md.market_cap AS market_cap,
            md.fifty_two_week_high AS fifty_two_week_high,
            md.fifty_two_week_low AS fifty_two_week_low,
            md.eps_trailing AS eps_trailing,
            md.avg_volume_30d AS avg_volume_30d,
            md.is_degraded AS is_degraded,
            latest_consensus.weighted_signal AS consensus_signal,
            latest_consensus.weighted_score AS consensus_score,
            latest_consensus.majority_signal AS majority_signal,
            latest_consensus.majority_pct AS majority_pct
        ORDER BY t.symbol
        """,
        cycle_id=cycle_id,
    )
    return [dict(record) async for record in result]
```

**Key design choice (Discretion):** OPTIONAL MATCH for TickerConsensusSummary handles cycles where `write_ticker_consensus_summary()` was never called (e.g., old cycles from before Phase 20). The `collect(tcs)[0]` with `ORDER BY round_num DESC` fetches only the latest round's consensus (Round 3 for complete simulations).

### Pattern 3: Assembler Extension (for `assemble()` with market_context_data)
**What:** Optional `market_context_data` parameter in `ReportAssembler.assemble()` that renders the `09_market_context.j2` template before the existing 8 sections.
**Existing precedent:** The assembler already loops over `SECTION_ORDER` and skips missing sections.

**Structure:**
```python
def assemble(
    self,
    observations: list[ToolObservation],
    cycle_id: str,
    *,
    market_context_data: list[dict] | None = None,
) -> str:
    # ... existing header ...

    sections: list[str] = []

    # Prepend market context section when data is available (D-03)
    if market_context_data:
        market_section = self.render_section(
            "09_market_context.j2",
            data=market_context_data,
            cycle_id=cycle_id,
        )
        sections.append(market_section)

    # Existing SECTION_ORDER loop (unchanged)
    for tool_name in SECTION_ORDER:
        ...

    return header + "\n\n".join(sections)
```

### Pattern 4: Jinja2 Template for Market Context
**What:** `09_market_context.j2` renders a per-ticker comparison table.
**Style reference:** `03_bracket_narratives.j2` uses `{% for b in data %}` row pattern.

**Structure:**
```jinja2
## Market Context

| Ticker | Consensus | Confidence | Last Close | 30d Change | P/E | 52w Range | Status |
|--------|-----------|------------|------------|------------|-----|-----------|--------|
{% for row in data %}
| {{ row.ticker }} | {{ row.majority_signal | default('N/A') }} ({{ "%.0f"|format(row.majority_pct * 100) if row.majority_pct is not none else 'N/A' }}%) | {{ "%.2f"|format(row.consensus_score) if row.consensus_score is not none else 'N/A' }} | ${{ "%.2f"|format(row.last_close) if row.last_close is not none else 'N/A' }} | {{ "%.1f"|format(row.price_change_30d_pct) if row.price_change_30d_pct is not none else 'N/A' }}% | {{ "%.1f"|format(row.pe_ratio) if row.pe_ratio is not none else 'N/A' }} | ${{ "%.2f"|format(row.fifty_two_week_low) if row.fifty_two_week_low is not none else '?' }}-${{ "%.2f"|format(row.fifty_two_week_high) if row.fifty_two_week_high is not none else '?' }} | {{ '[degraded data]' if row.is_degraded else '' }} |
{% endfor %}
```

**Key decision (Discretion):** Use `list[dict]` for `market_context_data` rather than a typed dataclass. Rationale: The graph query returns `list[dict]` natively, the template accesses fields by string key, and every other report tool observation uses untyped `dict` results. Adding a dataclass would be inconsistent with the existing pattern and would require an extra conversion step.

### Anti-Patterns to Avoid
- **Modifying SECTION_ORDER or TOOL_TO_TEMPLATE:** Locked per D-02. Market context is NOT a ReACT tool.
- **Using a 9th ReACT tool for market context:** The LLM does not need to "decide" to fetch market data -- it is always included when available. Assembler injection is the correct path.
- **Single-node Neo4j writes:** Always UNWIND batch, even for small ticker counts. Follows established project pattern.
- **Blocking I/O in cli.py:** The `_handle_report()` handler is async. The new `read_market_context()` call is async and follows the same pattern as existing tool registry lambdas.
- **Storing `bracket_breakdown` in Neo4j:** The TickerConsensus dataclass contains `bracket_breakdown: tuple[BracketSummary, ...]` which is too complex for a Neo4j property. Only the 6 scalar fields are persisted.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Null handling in Jinja2 | Python-side null coalescing before template | `\| default('N/A')` Jinja2 filter | D-07 locks this; template handles it natively |
| Batch Neo4j writes | Per-record CREATE loops | UNWIND + single tx | Connection pool exhaustion with 100 records; established project pattern |
| Latest-round filtering | Python filtering of all rounds | Cypher `ORDER BY round_num DESC` + `collect()[0]` | Let the DB do the work; avoids fetching unnecessary data |
| Percentage formatting | Python pre-formatting | Jinja2 `"%.1f"\|format()` | Consistent with existing templates (01, 03) |

## Common Pitfalls

### Pitfall 1: OPTIONAL MATCH vs MATCH for TickerConsensusSummary
**What goes wrong:** Using `MATCH` instead of `OPTIONAL MATCH` for consensus nodes causes `read_market_context()` to return empty results for cycles created before Phase 20 (no TickerConsensusSummary nodes exist).
**Why it happens:** MATCH eliminates rows where no match exists. Old cycles have Ticker+MarketDataSnapshot but no TickerConsensusSummary.
**How to avoid:** OPTIONAL MATCH on the consensus relationship. Null consensus fields render as "N/A" in the template.
**Warning signs:** `read_market_context()` returns empty list for a known cycle with tickers.

### Pitfall 2: Forgetting to Write Consensus at All Three Round Sites
**What goes wrong:** If `write_ticker_consensus_summary()` is only added at Round 3, the `round_num` filtering in `read_market_context()` works, but intermediate round data is lost (less important for reports, but inconsistent with the TUI which shows all rounds).
**Why it happens:** There are 3 separate `set_ticker_consensus()` call sites in simulation.py (lines 1117, 1254, 1383) -- easy to miss one.
**How to avoid:** Add the graph write immediately after each `set_ticker_consensus()` call. The graph_manager is available at all three sites (it's a parameter of `run_simulation()`).
**Warning signs:** Neo4j only has consensus data for round 3, not rounds 1-2.

### Pitfall 3: Ticker Node Missing When Writing Consensus
**What goes wrong:** `write_ticker_consensus_summary()` uses `MATCH (t:Ticker {symbol: c.ticker})` which fails silently (no node created) if the Ticker node doesn't exist yet.
**Why it happens:** `create_ticker_with_market_data()` is called during seed injection (before rounds). If seed injection had no tickers (empty `SeedEvent.tickers`), Ticker nodes won't exist.
**How to avoid:** Guard the consensus write with `if ticker_consensus:` (same guard pattern as `create_ticker_with_market_data()` which checks `if not snapshots: return`). When tickers are empty, `compute_ticker_consensus()` returns an empty tuple, so the guard naturally skips the write.
**Warning signs:** `_log.info("ticker_consensus_written", count=0)` when tickers are expected.

### Pitfall 4: market_context_data Ordering in Report
**What goes wrong:** Market context section appears AFTER existing sections instead of before.
**Why it happens:** Appending market section after the SECTION_ORDER loop instead of prepending before it.
**How to avoid:** Per D-03, market context is prepended (inserted at index 0 or built first). The code example above shows the correct ordering.
**Warning signs:** Report markdown has market context at the bottom instead of the top.

### Pitfall 5: Neo4j Schema Cleanup in Tests
**What goes wrong:** Integration test teardown in `conftest.py` doesn't clean TickerConsensusSummary nodes, causing test pollution.
**Why it happens:** The cleanup fixture (line 161-170) explicitly lists node labels. A new label must be added.
**How to avoid:** Add `await session.run("MATCH (tcs:TickerConsensusSummary) DETACH DELETE tcs")` to the graph_manager fixture cleanup.
**Warning signs:** Test failures on second run that pass on first run.

## Code Examples

### Simulation.py: Adding Graph Write at Round Completion
```python
# Source: simulation.py lines 1117-1121 (Round 1 existing pattern)
# Immediately after set_ticker_consensus(), add graph write:
if state_store is not None:
    await state_store.set_ticker_consensus(
        compute_ticker_consensus(
            round1_result.agent_decisions, personas, brackets, round1_weights, round_num=1,
        )
    )
# Phase 20: Persist to Neo4j for report queries
ticker_consensus = compute_ticker_consensus(
    round1_result.agent_decisions, personas, brackets, round1_weights, round_num=1,
)
if state_store is not None:
    await state_store.set_ticker_consensus(ticker_consensus)
if ticker_consensus:
    await graph_manager.write_ticker_consensus_summary(cycle_id, 1, list(ticker_consensus))
```

**Optimization note:** Avoid calling `compute_ticker_consensus()` twice. Compute once, pass to both StateStore and graph_manager.

### CLI.py: Wiring Market Context into Report
```python
# Source: cli.py lines 732-755 (existing _handle_report flow)
# After resolving cycle_id, before building tool registry:
market_context_data = await gm.read_market_context(cycle_id)

# ... existing tool registry + ReACT engine ...

# Pass to assembler:
content = assembler.assemble(observations, cycle_id, market_context_data=market_context_data)
```

### Test Pattern: Mocked Graph Read
```python
# Source: test_graph.py fixture pattern (lines 23-39)
class TestReadMarketContext:
    async def test_returns_ticker_with_market_data(
        self, mock_driver: MagicMock, mock_personas: list,
    ) -> None:
        from alphaswarm.graph import GraphStateManager

        session = mock_driver.session.return_value
        session.execute_read = AsyncMock(return_value=[{
            "ticker": "TSLA",
            "company_name": "Tesla Inc",
            "last_close": 185.40,
            "price_change_30d_pct": -12.3,
            "pe_ratio": 62.1,
            "is_degraded": False,
            "consensus_signal": "SELL",
            "majority_pct": 0.72,
            # ... remaining fields ...
        }])

        gsm = GraphStateManager(mock_driver, mock_personas)
        result = await gsm.read_market_context("cycle1")

        assert len(result) == 1
        assert result[0]["ticker"] == "TSLA"
        assert result[0]["consensus_signal"] == "SELL"
```

### Test Pattern: Assembler with Market Context
```python
# Source: test_report.py TestReportAssembler pattern (lines 242-253)
class TestReportAssemblerMarketContext:
    def test_includes_market_context_when_data_present(self) -> None:
        from alphaswarm.report import ReportAssembler

        assembler = ReportAssembler()
        market_data = [{
            "ticker": "TSLA",
            "last_close": 185.40,
            "price_change_30d_pct": -12.3,
            "pe_ratio": 62.1,
            "majority_signal": "SELL",
            "majority_pct": 0.72,
            "consensus_score": 0.68,
            "is_degraded": False,
            # ... remaining fields with None defaults ...
        }]
        content = assembler.assemble([], "test-cycle", market_context_data=market_data)

        assert "## Market Context" in content
        assert "TSLA" in content
        assert "SELL" in content

    def test_skips_market_context_when_absent(self) -> None:
        from alphaswarm.report import ReportAssembler

        assembler = ReportAssembler()
        content = assembler.assemble([], "test-cycle")

        assert "## Market Context" not in content
```

## Project Constraints (from CLAUDE.md)

- **100% async:** All new graph methods must be async. `write_ticker_consensus_summary()` and `read_market_context()` follow async session pattern.
- **No blocking I/O:** The CLI handler `_handle_report()` is already async; new calls fit naturally.
- **Neo4j async driver:** Use `session.execute_write()` / `session.execute_read()` -- never synchronous sessions.
- **UNWIND batch writes:** Never single-node CREATE loops (CLAUDE.md Miro batching principle generalizes to all external writes).
- **structlog:** New graph methods must use component-scoped logger (`structlog.get_logger(component="graph")`).
- **Strict typing:** Python 3.11+ typing for all new method signatures.
- **pytest-asyncio:** `asyncio_mode = "auto"` is configured project-wide.
- **uv package manager:** No new dependencies needed.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 + pytest-asyncio 0.24.0+ |
| Config file | pyproject.toml (`asyncio_mode = "auto"`) |
| Quick run command | `uv run pytest tests/test_report.py tests/test_graph.py -x -q` |
| Full suite command | `uv run pytest tests/ -x -q` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DRPT-01 (SC1) | Report includes market context section with price/financials | unit | `uv run pytest tests/test_report.py::TestReportAssemblerMarketContext -x` | Wave 0 |
| DRPT-01 (SC1) | `09_market_context.j2` renders with full and partial data | unit | `uv run pytest tests/test_report.py::TestMarketContextTemplate -x` | Wave 0 |
| DRPT-01 (SC2) | `read_market_context()` returns combined market + consensus data | unit | `uv run pytest tests/test_graph.py::TestReadMarketContext -x` | Wave 0 |
| DRPT-01 (SC2) | `write_ticker_consensus_summary()` persists consensus nodes | unit | `uv run pytest tests/test_graph.py::TestWriteTickerConsensus -x` | Wave 0 |
| DRPT-01 (SC3) | Full assemble() with market_context_data produces valid markdown | unit | `uv run pytest tests/test_report.py::TestReportAssemblerMarketContext::test_includes_market_context_when_data_present -x` | Wave 0 |
| DRPT-01 (SC3) | Assembler handles absent market_context_data (backward compat) | unit | `uv run pytest tests/test_report.py::TestReportAssemblerMarketContext::test_skips_market_context_when_absent -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_report.py tests/test_graph.py -x -q`
- **Per wave merge:** `uv run pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_report.py::TestReportAssemblerMarketContext` -- covers assembler extension with/without market data
- [ ] `tests/test_report.py::TestMarketContextTemplate` -- covers `09_market_context.j2` rendering (full data, partial/None fields, degraded marker)
- [ ] `tests/test_graph.py::TestWriteTickerConsensus` -- covers `write_ticker_consensus_summary()` UNWIND write (mocked session)
- [ ] `tests/test_graph.py::TestReadMarketContext` -- covers `read_market_context()` query (mocked session, handles missing consensus)

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| ReACT tool for every section | Assembler-injected sections for non-LLM data | Phase 20 (D-01) | Market context doesn't need LLM reasoning to fetch -- it's a direct graph query |
| Per-ticker consensus only in StateStore (memory) | Dual persistence: StateStore (TUI) + Neo4j (report) | Phase 20 (D-04) | Report CLI command can access consensus data without a running simulation |

## Open Questions

1. **Schema index for TickerConsensusSummary**
   - What we know: Existing schema has indexes for Decision, Agent, Post, etc. (graph.py lines 60-69)
   - What's unclear: Whether a composite index on `(TickerConsensusSummary.round_num)` is needed for `ORDER BY round_num DESC` performance
   - Recommendation: Add `CREATE INDEX tcs_round IF NOT EXISTS FOR (tcs:TickerConsensusSummary) ON (tcs.round_num)` to `SCHEMA_STATEMENTS`. With only 3 rounds x N tickers per cycle, the data volume is tiny, but maintaining consistency with the existing index pattern costs nothing.

2. **conftest.py cleanup for TickerConsensusSummary**
   - What we know: The `graph_manager` fixture (conftest.py line 161) cleans Decision, Cycle, Entity, RationaleEpisode, Post, Ticker, MarketDataSnapshot nodes between tests
   - What's unclear: Whether the cleanup should also clean TickerConsensusSummary nodes
   - Recommendation: Yes, add cleanup line. Without it, integration tests may see stale consensus data from prior test runs.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11+ | Runtime | Yes | 3.11+ | -- |
| Jinja2 | Template rendering | Yes | 3.1.5 | -- |
| Neo4j (Docker) | Graph queries | Conditional | >=5.28 | Tests use mocked sessions; live Neo4j only for integration tests |
| pytest | Test execution | Yes | 9.0.2 | -- |

**Missing dependencies with no fallback:**
- None

**Missing dependencies with fallback:**
- Neo4j Docker container: Only needed for integration tests (skipped automatically via `conftest.py` when unavailable). Unit tests use `MagicMock`/`AsyncMock` drivers.

## Sources

### Primary (HIGH confidence)
- Direct codebase analysis: `graph.py`, `report.py`, `cli.py`, `simulation.py`, `state.py`, `types.py`
- Existing templates: `01_consensus_summary.j2`, `03_bracket_narratives.j2` (style reference)
- Existing tests: `test_report.py`, `test_graph.py` (mock patterns)
- Phase 15 CONTEXT: Report assembler architecture decisions
- Phase 17 CONTEXT: Neo4j Ticker/MarketDataSnapshot storage decisions
- Phase 19 CONTEXT: TickerConsensus dataclass and compute_ticker_consensus() logic
- `pyproject.toml`: Dependency versions and pytest-asyncio configuration

### Secondary (MEDIUM confidence)
- Jinja2 3.1.x documentation (default filter, format filter behavior) -- verified against installed 3.1.5

### Tertiary (LOW confidence)
- None -- all findings are from direct codebase inspection

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already in use, no new dependencies
- Architecture: HIGH -- all four patterns (UNWIND write, session read, assembler extension, template rendering) have direct precedents in existing code
- Pitfalls: HIGH -- identified from actual codebase structure (3 call sites, OPTIONAL MATCH need, conftest cleanup)

**Research date:** 2026-04-07
**Valid until:** 2026-05-07 (stable codebase, no external dependency churn expected)
