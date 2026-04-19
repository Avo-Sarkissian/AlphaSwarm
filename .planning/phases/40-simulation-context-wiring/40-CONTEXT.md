# Phase 40: Simulation Context Wiring - Context

**Gathered:** 2026-04-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire `ContextPacket` (market slices + news slices) into the simulation's Round 1 agent prompts so each agent reacts to the seed rumor with grounded current price, fundamentals, and headline context. Assembly happens inside `run_simulation` after `inject_seed` extracts entities. Simulation runs correctly with no providers configured (backward-compatible default). Rounds 2-3 are unchanged.

</domain>

<decisions>
## Implementation Decisions

### ContextPacket Assembly
- **D-01:** ContextPacket assembled **inside `run_simulation`** after `inject_seed` extracts entities. `run_simulation` gains two optional keyword params: `market_provider: MarketDataProvider | None = None` and `news_provider: NewsProvider | None = None`. After inject_seed, if both providers are present, call `market_provider.fetch_batch(entity_tickers)` + `news_provider.fetch_headlines(entities)` and construct the ContextPacket. If either is absent, skip assembly.
- **D-02:** No providers configured → emit a structured log warning (`context_assembly_skipped`, reason=`no_providers_configured`) and continue with `context_packet = None`. Simulation proceeds with rumor-only prompts. No error raised.
- **D-03:** Partial fetch failures (some entities return `fetch_failed` slices) → ContextPacket carries **all** slices including `fetch_failed`. The prompt formatter skips `fetch_failed` entries silently. Agents see only successfully-fetched data. Mirrors Phase 38 D-19 never-raise contract — providers already handle this.

### Prompt Injection Mechanics
- **D-04:** Market context injected as a **system message**, placed after the persona system_prompt and before the user message. Mirrors the existing `peer_context` system message pattern in `agent_worker.infer()` exactly:
  ```
  [system: persona system_prompt]
  [system: "Market context:\n{block}"]   ← new (Round 1 only)
  [system: "Peer context:\n{peer}"]      ← existing (Rounds 2-3 only)
  [user:   rumor text]
  ```
- **D-05:** New `market_context: str | None` param flows through the call chain: `run_round1` → `dispatch_wave` → `_safe_agent_inference` → `agent_worker.infer()`. Same plumbing shape as existing `peer_context` / `peer_contexts`.
- **D-06:** Market context injection is **Round 1 only**. `_dispatch_round` (Rounds 2-3) does not receive market_context; peer_context mechanism is unchanged.

### Context Content Selection
- **D-07:** **Same formatted context block for all 100 agents** — no per-bracket filtering. Block built once from ContextPacket, passed identically via dispatch_wave. Avoids 100× formatting overhead.
- **D-08:** Each entity in the block includes: current price (from `MarketSlice.price`), fundamentals (pe_ratio, eps, market_cap from `MarketSlice.fundamentals`), and top 5 headlines (from `NewsSlice.headlines[:5]`). Entities with `staleness='fetch_failed'` are silently omitted from the block.
- **D-09:** Headline cap: **top 5 per entity**. Formatter slices `NewsSlice.headlines[:5]` regardless of how many were fetched.

### Provider Wiring — Web Path
- **D-10:** `YFinanceMarketDataProvider` + `RSSNewsProvider` constructed **once in FastAPI lifespan** (`web/app.py`), stored on `app.state` (e.g., `app.state.market_provider`, `app.state.news_provider`). `SimulationManager` reads them from `app_state` and passes to `run_simulation`. Follows the same lifespan pattern as `governor`, `graph_manager`, `sim_manager`.

### Provider Wiring — CLI Path
- **D-11:** `cli.py` run command constructs real `YFinanceMarketDataProvider` + `RSSNewsProvider` inline and passes them to `run_simulation`. CLI users get grounded context identically to the web path.

### Claude's Discretion
- Exact string formatting of the market context block (column alignment, Decimal formatting precision, section headers within the block)
- Whether `market_provider.fetch_batch` receives all extracted entities or only ticker-shaped ones (Phase 38 D-02 dual-source routing already handles classification internally)
- Whether `app.state` uses typed slots or the existing dynamic attribute pattern for provider storage
- `SimulationManager.__init__` signature change: whether providers are constructor args or read from `app_state` at `_run()` time

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Simulation pipeline (integration points)
- `src/alphaswarm/simulation.py` — `run_simulation` and `run_round1` entry points; `_dispatch_round` for Rounds 2-3; Phase 7 lifecycle docs inline
- `src/alphaswarm/batch_dispatcher.py` — `dispatch_wave` signature; `_safe_agent_inference` plumbing; existing `peer_context` / `peer_contexts` param shapes to mirror
- `src/alphaswarm/worker.py` — `AgentWorker.infer()` message list construction; `peer_context` system message injection (lines 88-92); mirror this for `market_context`

### Ingestion types (Phase 37/38 outputs)
- `src/alphaswarm/ingestion/types.py` — `ContextPacket`, `MarketSlice`, `NewsSlice`, `Fundamentals`, `StalenessState` frozen pydantic types
- `src/alphaswarm/ingestion/providers.py` — `MarketDataProvider` and `NewsProvider` Protocol definitions; `FakeMarketDataProvider`, `FakeNewsProvider` for unit tests
- `src/alphaswarm/ingestion/yfinance_provider.py` — real `YFinanceMarketDataProvider` (Phase 38)
- `src/alphaswarm/ingestion/rss_provider.py` — real `RSSNewsProvider` (Phase 38)

### Web app wiring (Phase 38/39 patterns)
- `src/alphaswarm/web/app.py` — lifespan pattern for `app.state` construction; provider instances must be added here alongside existing state objects
- `src/alphaswarm/web/simulation_manager.py` — `SimulationManager._run()` → `run_simulation()` call site; `app_state` access pattern

### CLI wiring
- `src/alphaswarm/cli.py` — `run` command entry point (line ~483); existing `run_simulation` call site to extend with provider construction

### Importlinter contract
- `pyproject.toml` §[tool.importlinter] — `alphaswarm.simulation` can import from `alphaswarm.ingestion` freely (no whitelist restriction); `alphaswarm.holdings` boundary is the restricted one

### Requirements
- `.planning/REQUIREMENTS.md` §INGEST-03, §SIM-04 — two acceptance-tracked requirements this phase closes
- `.planning/ROADMAP.md` §"Phase 40: Simulation Context Wiring" — goal, success criteria, plan split

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `peer_context` system message pattern (`src/alphaswarm/worker.py:88-92`): `market_context` system message is a direct mirror — same position in messages list, same None-guard pattern
- `peer_contexts: list[str | None]` in `dispatch_wave` (`src/alphaswarm/batch_dispatcher.py`): `market_context: str | None` is a scalar (same block for all agents) — simpler than the per-agent `peer_contexts` list
- `FakeMarketDataProvider` / `FakeNewsProvider` (`src/alphaswarm/ingestion/providers.py`): ready-made fakes for unit testing the assembly path inside `run_simulation`
- `_fetch_failed_market_slice` / `_fetch_failed_news_slice` helpers: already handle the never-raise contract; formatter skipping `fetch_failed` entries is the complementary consumer-side pattern

### Established Patterns
- `asyncio_mode = "auto"` project-wide — async test functions need no decorator
- `pytest-socket --disable-socket` global gate — unit tests using Fake providers stay in `tests/` (no network); integration tests under `tests/integration/` for real providers
- `app.state` dynamic attribute pattern: `sim_manager`, `replay_manager`, `portfolio_snapshot` all set in lifespan — `market_provider`, `news_provider` follow the same pattern
- mypy strict mode — all new params must be fully typed including `MarketDataProvider | None` Protocol union

### Integration Points
- `src/alphaswarm/simulation.py:run_simulation` — add `market_provider: MarketDataProvider | None = None` and `news_provider: NewsProvider | None = None` params; after `inject_seed` call, add context assembly block
- `src/alphaswarm/simulation.py:run_round1` — add `market_context: str | None = None` param; pass to `dispatch_wave`
- `src/alphaswarm/batch_dispatcher.py:dispatch_wave` — add `market_context: str | None = None` param; pass to `_safe_agent_inference`
- `src/alphaswarm/worker.py:AgentWorker.infer` — add `market_context: str | None = None` param; insert system message before user message
- `src/alphaswarm/web/app.py:lifespan` — construct + store `YFinanceMarketDataProvider` and `RSSNewsProvider` on `app.state`
- `src/alphaswarm/web/simulation_manager.py:SimulationManager._run` — pass `app_state.market_provider` and `app_state.news_provider` to `run_simulation`
- `src/alphaswarm/cli.py` run command — construct providers inline and pass to `run_simulation`

</code_context>

<specifics>
## Specific Ideas

- The `market_context` system message is Round 1 exclusive — `_dispatch_round` (Rounds 2-3) already has its own per-agent `peer_contexts` mechanism. The two context channels (market vs peer) are entirely orthogonal: market context grounds agents in current reality, peer context shapes social influence. They don't interfere.
- `fetch_failed` silent omission in the formatter: if ALL entities fail (total network failure), the context block is empty and the system message is simply not appended (same as no providers case). No degenerate "Market context: (no data)" messages should appear in prompts.
- INGEST-03 says "assembled by the orchestrator before simulation" — interpreted as: the orchestrator layer of `run_simulation` (between inject_seed and dispatch_wave), not a separate external caller. This preserves the clean `run_simulation` single-function entry point pattern.

</specifics>

<deferred>
## Deferred Ideas

- Per-bracket context filtering (Quants get fundamentals, Degens get headlines only) — Phase 40 uses uniform context for all agents; bracket-aware formatting can be revisited in v7.0 if simulation quality warrants it
- Context staleness TTL (marking slices stale after N hours) — deferred from Phase 38; still deferred here. Each `run_simulation` call fetches fresh data.
- RSS feed caching / TTL between simulation runs in the same session — deferred; providers fetch fresh each call per Phase 38 D-10

</deferred>

---

*Phase: 40-simulation-context-wiring*
*Context gathered: 2026-04-19*
