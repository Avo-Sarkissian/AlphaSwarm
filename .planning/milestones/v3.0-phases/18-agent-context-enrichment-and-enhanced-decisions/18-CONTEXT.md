# Phase 18: Agent Context Enrichment and Enhanced Decisions - Context

**Gathered:** 2026-04-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Every agent receives bracket-appropriate market data injected into its prompt before inference, budget-capped by bracket group. Agents produce a new `ticker_decisions` list in their structured output — one `TickerDecision` per ticker — with direction, expected_return_pct, and time_horizon. Phase 18 also fulfills DATA-03 by fetching news headlines via Alpha Vantage NEWS_SENTIMENT. No TUI or report changes in this phase.

</domain>

<decisions>
## Implementation Decisions

### Prompt Injection Architecture
- **D-01:** Market data is **appended to `user_message`** as a formatted block prepended to the rumor text. Format: `f"{format_market_block(snapshots, bracket)}\n\nRumor: {rumor}"`. No changes to `AgentWorker.infer()`, `dispatch_wave()`, or the messages list structure.
- **D-02:** New module `src/alphaswarm/enrichment.py` owns all formatting logic: `format_market_block(snapshots: dict[str, MarketDataSnapshot], bracket: BracketType) -> str` and `build_enriched_user_message(rumor: str, snapshots, bracket) -> str`. Called from `simulation.py` before each `dispatch_wave()` call (Rounds 1, 2, 3).
- **D-03:** Token budget enforced via **per-bracket-group character caps** (`MAX_MARKET_BLOCK_CHARS: dict[BracketType, int]`). `format_market_block()` truncates to fit. Values are conservative (below actual token limit) to leave headroom. No tokenizer API call on the hot path.

### Bracket Data Slices
- **D-04:** All 10 brackets grouped into **3 slice categories**:
  - **Technicals** (Quants, Degens, Whales): `last_close`, `price_change_30d_pct`, `price_change_90d_pct`, `avg_volume_30d`, `fifty_two_week_high`, `fifty_two_week_low`
  - **Fundamentals** (Suits, Sovereigns, Policy Wonks): `pe_ratio`, `market_cap`, `revenue_ttm`, `gross_margin_pct`, `debt_to_equity`
  - **Earnings/Insider** (Insiders, Macro, Agents, Doom-Posters): `earnings_surprise_pct`, `next_earnings_date`, `eps_trailing`, `market_cap`, plus **news headlines** (top 10 from AV NEWS_SENTIMENT)
- **D-05:** When multiple tickers are present (Phase 16 caps at 3), **every agent sees all tickers** formatted with their bracket slice. Token budget applies across all tickers combined — e.g., a Quant with 3 tickers has its full block stay within the Technicals char cap.

### AgentDecision Extension
- **D-06:** New frozen Pydantic model `TickerDecision` in `types.py`:
  ```python
  class TickerDecision(BaseModel, frozen=True):
      ticker: str
      direction: SignalType
      expected_return_pct: float | None = None
      time_horizon: str | None = None
  ```
- **D-07:** `AgentDecision` gains one new field: `ticker_decisions: list[TickerDecision] = Field(default_factory=list)`. All other existing fields unchanged. Empty list = backward-compatible None equivalent — agents that fail to emit new fields get `[]` without triggering PARSE_ERROR (success criterion 4).
- **D-08:** `time_horizon` is a **free string** (not enum). Agent prompt instructs: one of `'1d'`, `'1w'`, `'1m'`, `'3m'`, `'6m'`, `'1y'`. Stored as-is; Phase 19 display consumes the raw string. No Pydantic enum validator — reduces PARSE_ERROR risk with qwen3.5:9b.

### News Headlines (DATA-03)
- **D-09:** Fetch **10 headlines per ticker** from AV NEWS_SENTIMENT endpoint. Runs in `enrichment.py` as part of the pre-simulation enrichment step (after `fetch_market_data()` returns snapshots, before Round 1). Fetched headlines are stored into `MarketDataSnapshot.headlines` (already reserved in Phase 17).
- **D-10:** If `ALPHA_VANTAGE_API_KEY` is absent or the AV call fails, emit a `structlog` WARNING (`component='enrichment'`, `event='headlines_fetch_failed'`) and keep `headlines=[]`. Simulation never aborts. Uses the same `httpx.AsyncClient` pattern as Phase 17's AV fallback.
- **D-11:** Headlines are **only injected into the Earnings/Insider bracket slice** (Insiders, Macro, Agents, Doom-Posters). Technicals and Fundamentals brackets do not receive news headlines in their formatted block.

### Claude's Discretion
- Exact char cap values per bracket group (tune to stay within ~87% of context window)
- Exact formatting style of the market data block (markdown table vs key-value lines vs prose)
- Whether `direction` in `TickerDecision` reuses `SignalType` (BUY/SELL/HOLD) or defines a separate Direction enum
- Whether headlines are truncated to 120 chars per headline in the formatted block
- Test fixture approach for enrichment.py (mock `fetch_market_data` return or use real `MarketDataSnapshot` instances)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/ROADMAP.md` — Phase 18 goal, success criteria (4 criteria), ENRICH-01/02/03, DECIDE-01/02 requirement IDs
- `.planning/STATE.md` — "Token budget char estimates vs actual tokenizer counts — must validate in Phase 18" (blocker concern to address)

### Phase 17 Output (Primary — this phase consumes it)
- `src/alphaswarm/market_data.py` — `fetch_market_data()`, `MarketDataSnapshot` fetch/cache logic; enrichment.py imports from this
- `src/alphaswarm/types.py` — `MarketDataSnapshot` (line 100), `AgentDecision` (line 169), `BracketType` (line 12), `ExtractedTicker` — all modified or consumed in Phase 18
- `.planning/phases/17-market-data-pipeline/17-CONTEXT.md` — D-04 (headlines deferred to Phase 18), D-18 (AV endpoints already used in Phase 17)

### Simulation Integration Points
- `src/alphaswarm/simulation.py` — `run_simulation()` (line 776: market_snapshots already threaded through); `run_round1()` (~line 502), `_dispatch_round()` (~line 682) — add `build_enriched_user_message()` call before `dispatch_wave()` in all 3 dispatch sites
- `src/alphaswarm/batch_dispatcher.py` — `dispatch_wave()` signature (line 81) — `user_message: str` param, no changes needed (enriched message passed in)

### Bracket Config
- `src/alphaswarm/config.py` — `DEFAULT_BRACKETS` (line 320), `BRACKET_MODIFIERS`, `BracketConfig.system_prompt_template` — slice groupings must align with existing bracket archetypes

### Parsing Layer (3-tier fallback)
- `src/alphaswarm/parsing.py` — `parse_agent_decision()` (line 52) — must handle `ticker_decisions` list gracefully; empty list default on parse failure

### Alpha Vantage Integration (Phase 17 pattern to mirror)
- `src/alphaswarm/market_data.py` — AV `httpx.AsyncClient` pattern, `_safe_float()` helper, `ALPHA_VANTAGE_API_KEY` guard — news fetch in enrichment.py follows same pattern

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `market_data.py:_fetch_av_fallback()` — AV `httpx.AsyncClient` call pattern with `ALPHA_VANTAGE_API_KEY` guard; news fetch in `enrichment.py` mirrors this for `NEWS_SENTIMENT` endpoint
- `types.py:MarketDataSnapshot` — `headlines: list[str]` field already reserved (empty list default); enrichment.py populates it
- `batch_dispatcher.py:dispatch_wave()` — `user_message: str` is already per-wave, not per-agent; enrichment.py produces one enriched message per bracket group per round
- `parsing.py:parse_agent_decision()` — 3-tier fallback already handles missing optional fields via Pydantic defaults; adding `ticker_decisions=[]` default extends this naturally

### Established Patterns
- New frozen Pydantic models go in `types.py` (all existing data types live there — `SeedEvent`, `ExtractedTicker`, `MarketDataSnapshot`, `AgentDecision`)
- New standalone data-layer modules follow `market_data.py` pattern: `structlog.get_logger(component="enrichment")`, `asyncio.to_thread()` for blocking work, `httpx.AsyncClient` for REST
- All simulation extension work goes in `simulation.py` — no new entry points; `run_simulation()` already threads `market_snapshots` through as a param
- `aiofiles` used for file I/O; `httpx` for REST APIs — both already in dependencies

### Integration Points
- `simulation.py`: 3 dispatch sites need enriched user_message — `run_round1()` (~line 502), `_dispatch_round()` round2 call (~line 913), `_dispatch_round()` round3 call (~line 1031). All currently pass `user_message=rumor` directly.
- `types.py`: Add `TickerDecision` before `AgentDecision`; add `ticker_decisions` field to `AgentDecision`
- New file: `src/alphaswarm/enrichment.py` — `format_market_block()`, `build_enriched_user_message()`, `fetch_headlines()` (AV NEWS_SENTIMENT)
- `parsing.py`: No structural changes needed — `ticker_decisions: list[TickerDecision] = Field(default_factory=list)` makes it optional by default

</code_context>

<specifics>
## Specific Ideas

- `TickerDecision.direction` should reuse `SignalType` (BUY/SELL/HOLD/PARSE_ERROR) to avoid a new enum — agents already know `SignalType` from the existing prompt schema
- Market block format should be compact key-value (not markdown table) to minimize char usage: `"AAPL: close=$182.50, 30d=+4.2%, 52w=[$142/$199]"` — readable and token-efficient
- Prompt schema update for agents: add `ticker_decisions` array to the JSON schema instruction in system prompts — show worked example with 2 tickers so qwen3.5:9b understands the array structure
- Agent prompts should instruct `time_horizon` choices explicitly: `'1d'|'1w'|'1m'|'3m'|'6m'|'1y'` to minimize parse variance

</specifics>

<deferred>
## Deferred Ideas

- **Tokenizer validation** — State.md flags char-vs-token estimation as a concern. Actual qwen3.5 tokenizer count validation should be done as a one-time calibration test (not hot-path enforcement). Deferred to post-Phase 18 tuning.
- **NEWS_SENTIMENT for Fundamentals brackets** — Suits/Policy Wonks could benefit from regulatory news. Deferred; keep slice definitions simple for Phase 18.
- **Ticker `MENTIONS` edges to Entity nodes in Neo4j** — Phase 16 and 17 deferred this. Still out of scope.
- **Multi-day cache for headlines** — Headlines are re-fetched each session. Smart caching with off-hours awareness is a future improvement.

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 18-agent-context-enrichment-and-enhanced-decisions*
*Context gathered: 2026-04-06*
