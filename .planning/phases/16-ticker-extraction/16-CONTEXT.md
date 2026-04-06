# Phase 16: Ticker Extraction - Context

**Gathered:** 2026-04-05 (assumptions mode)
**Status:** Ready for planning

<domain>
## Phase Boundary

The orchestrator resolves specific stock tickers from natural-language seed rumors, giving the entire v3 pipeline concrete symbols to fetch data for and track consensus against. Delivered as an extension to the existing `inject_seed()` flow — tickers are co-extracted with entities in a single LLM call, validated against the SEC symbol table, capped at 3, and stored on the `Cycle` node. No market data fetching. No prompt enrichment. No TUI changes beyond extending the injection summary display.

</domain>

<decisions>
## Implementation Decisions

### Extraction Integration Point
- **D-01:** Ticker extraction is co-located in `seed.py` — the existing `ORCHESTRATOR_SYSTEM_PROMPT` and `inject_seed()` are augmented to produce tickers alongside entities in a single LLM call. No second LLM call, no second model load.
- **D-02:** The orchestrator's JSON response schema expands from `{"entities": [...], "overall_sentiment": float}` to include a `"tickers": [...]` array. The parse path in `parsing.py::parse_seed_event()` is updated to read this new field.

### Type Model Changes
- **D-03:** A new `ExtractedTicker` Pydantic model is added to `types.py`, parallel to `SeedEntity` (lines 79-85). Fields: `symbol: str`, `company_name: str`, `relevance: float`. This preserves relevance scores for TICK-03 ranking and company-name association for Phase 17-18.
- **D-04:** `SeedEvent` gains a `tickers: list[ExtractedTicker]` field. All downstream consumers receive tickers automatically via the existing `SeedEvent` object — no new plumbing required.
- **D-05:** The 3-ticker cap (TICK-03) is enforced at parse time in `parse_seed_event()` — sort by relevance descending, keep top-3 before constructing the `SeedEvent`. Relevance scores come directly from the LLM response (same pattern as `SeedEntity.relevance`).

### SEC Validation Strategy
- **D-06:** `company_tickers.json` is loaded from disk as an in-memory dict. The file is fetched once from the SEC CDN (no API key required) and stored in a project data directory (e.g., `data/sec_tickers.json`) — not bundled in the repo (too large / needs to stay current). A lazy-load helper loads it on first use and caches it for the process lifetime.
- **D-07:** Validation is a synchronous in-memory dict lookup. Invalid symbols (not found in the SEC table) are rejected with a `structlog` warning before simulation proceeds. Simulation does not abort — it continues with only validated tickers. If all tickers fail validation, the simulation proceeds with `tickers=[]` and a clear warning.
- **D-08:** The SEC file download is a one-time setup step exposed as a CLI utility (e.g., `alphaswarm setup-data`) or auto-triggered on first `inject` run when the file is missing.

### Neo4j Ticker Persistence
- **D-09:** Extracted tickers are stored as a property on the `Cycle` node (e.g., `tickers: ["AAPL", "TSLA"]`) — no separate `Ticker` nodes in Phase 16. Schema stays minimal; `Ticker` nodes become justified in Phase 17 when market data needs to attach to them.
- **D-10:** `graph.py::create_cycle_with_seed_event()` is updated to include the `tickers` list in the Cypher write. No new graph methods needed for Phase 16.

### CLI Visibility (TICK-03)
- **D-11:** The ticker selection result (kept symbols, dropped symbols, relevance scores) is displayed by extending `_print_injection_summary()` in `cli.py` — a new tickers section following the existing entity table pattern (lines 82-88). No new display function added.
- **D-12:** Dropped tickers (exceeded the 3-ticker cap or failed validation) are shown in the summary with a reason label (`"cap"` or `"invalid"`), satisfying ROADMAP success criterion 3.

### Claude's Discretion
- SEC data directory name and path (e.g., `data/sec_tickers.json` vs `.alphaswarm/sec_tickers.json`)
- Whether SEC auto-download uses `httpx` (already a dependency) or `urllib.request` for a one-shot fetch
- Exact `ORCHESTRATOR_SYSTEM_PROMPT` wording for the `tickers` field instruction
- Whether `ExtractedTicker` is a frozen Pydantic model or a dataclass (follow `SeedEntity` pattern)
- Whether the `setup-data` CLI subcommand is added in Phase 16 or the download is purely auto-triggered

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/REQUIREMENTS.md` — TICK-01 (co-extraction in single LLM call), TICK-02 (SEC validation), TICK-03 (3-ticker cap, relevance ranking)
- `.planning/ROADMAP.md` — Phase 16 success criteria (3 criteria)

### Seed Injection (Primary)
- `src/alphaswarm/seed.py` — `ORCHESTRATOR_SYSTEM_PROMPT` (lines 24-36, expand schema here), `inject_seed()` (line 63, extraction call), `generate_personas()` (lines 98-103, pattern for co-located orchestrator use within same try block)

### Type Definitions (Primary)
- `src/alphaswarm/types.py` — `SeedEntity` (lines 79-85, direct template for `ExtractedTicker`), `SeedEvent` (lines 88-94, add `tickers` field here), `ParsedSeedResult` (wrapper — should not need changes)

### Parsing (Primary)
- `src/alphaswarm/parsing.py` — `parse_seed_event()` / `_try_parse_seed_json()` (lines 136-165, add tickers key read and top-3 cap logic here)

### CLI (Primary)
- `src/alphaswarm/cli.py` — `_print_injection_summary()` (lines 65-90, extend with tickers section), `main()` (argparse block — add `setup-data` subcommand if applicable)

### Graph Layer (Secondary)
- `src/alphaswarm/graph.py` — `create_cycle_with_seed_event()` (lines 175-221, add tickers property to Cycle node write)

### Prior Phase Context
- `.planning/phases/15-post-simulation-report/15-CONTEXT.md` — D-12 (orchestrator model lifecycle), patterns for direct `OllamaClient.chat()` usage
- `.planning/phases/13-dynamic-persona-generation/13-CONTEXT.md` — pattern for reusing already-loaded orchestrator within same `inject_seed()` try block

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `seed.py:ORCHESTRATOR_SYSTEM_PROMPT` (lines 24-36) — self-contained JSON instruction block; adding a `"tickers"` field to the required output schema is a minimal diff
- `types.py:SeedEntity` (lines 79-85) — frozen Pydantic model with `name`, `type`, `relevance`, `sentiment`; `ExtractedTicker` mirrors this shape (`symbol`, `company_name`, `relevance`)
- `parsing.py:_try_parse_seed_json()` (lines 136-165) — already reads `data.get("entities", [])` and `data.get("overall_sentiment", 0.0)`; adding `data.get("tickers", [])` follows the exact same pattern
- `cli.py:_print_injection_summary()` (lines 65-90) — tabular entity display using Rich table; trivially extended with a second table for tickers

### Established Patterns
- All orchestrator calls use `OllamaClient.chat()` directly (bypass governor) — confirmed in `seed.py` and `interview.py`
- Structured output: `format="json"` + `think=True` on orchestrator calls
- Multi-tier parse fallback: JSON mode → regex extraction → PARSE_ERROR (all in `parsing.py`)
- `structlog` component-scoped logger: `logger = structlog.get_logger(component="seed")`
- Pydantic frozen models for all data types in `types.py`
- Session-per-method on `GraphStateManager` for all Cypher writes

### Integration Points
- `seed.py:inject_seed()` — primary change point; prompt expansion + response parsing + ticker validation all happen here or in called helpers
- `types.py` — `ExtractedTicker` new model + `SeedEvent.tickers` field
- `parsing.py:parse_seed_event()` — add tickers parsing and top-3 cap
- `graph.py:create_cycle_with_seed_event()` — add `tickers` property to Cycle node
- `cli.py:_print_injection_summary()` — add ticker display section
- New file: `src/alphaswarm/ticker_validator.py` (or inline in `seed.py`) — SEC dict loader and validate function

</code_context>

<specifics>
## Specific Ideas

- `ExtractedTicker` should mirror `SeedEntity` closely — same frozen Pydantic model pattern, same `relevance: float` for ranking. This makes the LLM prompt symmetric: "for each entity return name/type/relevance/sentiment; for each ticker return symbol/company_name/relevance".
- The SEC `company_tickers.json` validation should be a simple `symbol.upper() in ticker_set` check — no fuzzy matching, no partial lookups. Fast, deterministic, auditable.
- Dropped tickers shown with reason in the injection summary creates a nice feedback loop: users learn which mentions were too vague or ambiguous to map to a valid symbol.
- The lazy-load pattern for SEC data (load once, cache in module-level dict) fits the existing `config.py` singleton style.

</specifics>

<deferred>
## Deferred Ideas

- `Ticker` nodes in Neo4j with `MENTIONS` edges to Cycle — deferred to Phase 17 when market data attaches
- Fuzzy company-name matching against SEC table (e.g., "Apple" → AAPL without explicit mention) — out of scope; Phase 16 relies on LLM to resolve symbols
- Ticker persistence to a local watchlist / user preferences — future milestone
- Multi-session SEC data refresh / staleness checking — Phase 16 does a one-time download, TTL/refresh deferred

</deferred>

---

*Phase: 16-ticker-extraction*
*Context gathered: 2026-04-05*
