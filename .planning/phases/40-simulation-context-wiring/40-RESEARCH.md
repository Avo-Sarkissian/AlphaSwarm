# Phase 40: Simulation Context Wiring - Research

**Researched:** 2026-04-19
**Domain:** Simulation seed injection wiring (in-process integration — no new libraries)
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**ContextPacket Assembly:**
- **D-01:** ContextPacket assembled **inside `run_simulation`** after `inject_seed` extracts entities. `run_simulation` gains two optional keyword params: `market_provider: MarketDataProvider | None = None` and `news_provider: NewsProvider | None = None`. After inject_seed, if both providers are present, call `market_provider.fetch_batch(entity_tickers)` + `news_provider.fetch_headlines(entities)` and construct the ContextPacket. If either is absent, skip assembly.
- **D-02:** No providers configured → emit a structured log warning (`context_assembly_skipped`, reason=`no_providers_configured`) and continue with `context_packet = None`. Simulation proceeds with rumor-only prompts. No error raised.
- **D-03:** Partial fetch failures (some entities return `fetch_failed` slices) → ContextPacket carries **all** slices including `fetch_failed`. The prompt formatter skips `fetch_failed` entries silently. Agents see only successfully-fetched data. Mirrors Phase 38 D-19 never-raise contract — providers already handle this.

**Prompt Injection Mechanics:**
- **D-04:** Market context injected as a **system message**, placed after the persona system_prompt and before the user message. Mirrors the existing `peer_context` system message pattern in `agent_worker.infer()` exactly.
- **D-05:** New `market_context: str | None` param flows through the call chain: `run_round1` → `dispatch_wave` → `_safe_agent_inference` → `agent_worker.infer()`. Same plumbing shape as existing `peer_context` / `peer_contexts`.
- **D-06:** Market context injection is **Round 1 only**. `_dispatch_round` (Rounds 2-3) does not receive market_context; peer_context mechanism is unchanged.

**Context Content Selection:**
- **D-07:** **Same formatted context block for all 100 agents** — no per-bracket filtering. Block built once from ContextPacket, passed identically via dispatch_wave.
- **D-08:** Each entity in the block includes: current price (from `MarketSlice.price`), fundamentals (pe_ratio, eps, market_cap from `MarketSlice.fundamentals`), and top 5 headlines (from `NewsSlice.headlines[:5]`). Entities with `staleness='fetch_failed'` are silently omitted from the block.
- **D-09:** Headline cap: **top 5 per entity**. Formatter slices `NewsSlice.headlines[:5]` regardless of how many were fetched.

**Provider Wiring — Web Path:**
- **D-10:** `YFinanceMarketDataProvider` + `RSSNewsProvider` constructed **once in FastAPI lifespan** (`web/app.py`), stored on `app.state` (e.g., `app.state.market_provider`, `app.state.news_provider`). `SimulationManager` reads them from `app_state` and passes to `run_simulation`.

**Provider Wiring — CLI Path:**
- **D-11:** `cli.py` run command constructs real `YFinanceMarketDataProvider` + `RSSNewsProvider` inline and passes them to `run_simulation`. CLI users get grounded context identically to the web path.

### Claude's Discretion

- Exact string formatting of the market context block (column alignment, Decimal formatting precision, section headers within the block)
- Whether `market_provider.fetch_batch` receives all extracted entities or only ticker-shaped ones (Phase 38 D-02 dual-source routing already handles classification internally)
- Whether `app.state` uses typed slots or the existing dynamic attribute pattern for provider storage
- `SimulationManager.__init__` signature change: whether providers are constructor args or read from `app_state` at `_run()` time

### Deferred Ideas (OUT OF SCOPE)

- Per-bracket context filtering (Quants get fundamentals, Degens get headlines only) — Phase 40 uses uniform context for all agents; bracket-aware formatting can be revisited in v7.0
- Context staleness TTL (marking slices stale after N hours) — deferred from Phase 38; still deferred here
- RSS feed caching / TTL between simulation runs — deferred; providers fetch fresh each call per Phase 38 D-10
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INGEST-03 | `ContextPacket` assembled pre-simulation from provider outputs and wired into seed injection prompt — agents receive grounded market context in Round 1 | Assembly pattern grounded in existing `inject_seed → run_round1 → dispatch_wave` call graph (simulation.py:764-781). ContextPacket type is frozen pydantic (ingestion/types.py:83) with fields `cycle_id`, `as_of`, `entities`, `market`, `news` — all the fields required by success criterion #2. |
| SIM-04 | `run_simulation` accepts optional `context_packet: ContextPacket | None`; when provided, market prices and headlines appended to Round 1 agent prompts; backward-compatible default `None` | CONTEXT.md D-01 restructures this: `run_simulation` takes `market_provider` + `news_provider` (both optional, default `None`) and **assembles** the ContextPacket internally. The success criterion is satisfied semantically — `None` providers → `context_packet = None` → rumor-only prompts (backward-compatible). The prompt formatter receives the packet-derived string via new `market_context: str | None` plumbing. |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Concurrency:** 100% async. `run_simulation` is already async; provider `fetch_batch`/`get_prices` and `get_headlines` are `async def` per Phase 38. No blocking calls in the assembly block.
- **Local First:** LLM inference stays local via Ollama. Yahoo Finance + Google News RSS calls happen pre-simulation (one batch per run, Phase 38 D-07) and are permitted per the CLAUDE.md "LLM inference is local" scope — this is market data, not inference.
- **Memory Safety:** Providers run pre-simulation (not inside the 100-agent cascade), so the governor's per-agent semaphore does not apply. `run_simulation` has no governor session active during context assembly — it starts later at `governor.start_monitoring()` inside `run_round1` (simulation.py:489).
- **WebSocket Cadence:** Broadcaster is independent — this phase adds no new snapshot fields. WebSocket frames remain unchanged.
- **Runtime:** Python 3.11+ strict typing, `uv` package manager, `pytest-asyncio` auto mode.
- **GSD Workflow:** File edits happen via `/gsd-execute-phase` after planning.

## Summary

Phase 40 wires the Phase 38 ingestion providers into the existing simulation pipeline. **No new libraries are required** — every dependency (pydantic, structlog, asyncio, yfinance, feedparser, httpx) is already installed and in use. This is purely an integration phase: five function signatures gain optional params, one lifespan block constructs two providers, and one new prompt formatter converts `ContextPacket` → string.

The research surfaced **one critical inconsistency** between CONTEXT.md D-01 and the actual Phase 38 API: CONTEXT.md refers to `market_provider.fetch_batch(...)` and `news_provider.fetch_headlines(...)`, but the `MarketDataProvider` Protocol defines `get_prices` / `get_fundamentals` / `get_volume` and `NewsProvider` defines `get_headlines` (ingestion/providers.py:42-62). There is no `fetch_batch` method. Per `yfinance_provider.py:42-48` module docstring, Phase 40 **MUST call exactly one** of the market methods per simulation run (recommended: `get_prices`, which returns the complete `MarketSlice` including `fundamentals` — calling all three would triple network cost for identical payload). The planner should normalize CONTEXT.md D-01 to `market_provider.get_prices(entity_tickers)` + `news_provider.get_headlines(entities)`.

The second architectural finding is that Phase 38 D-02 **internalizes ticker-vs-topic routing inside `RSSNewsProvider`** (`_route_url` in rss_provider.py:77). The caller in Phase 40 should pass **all extracted entity names** to `get_headlines` and **ticker-shaped entities** to `get_prices` — but the news provider itself does dual-source routing per entity. Phase 40 therefore needs a small classifier (regex `^[A-Z]{1,5}$` — already defined in rss_provider.py:73 as `_TICKER_RE`) to split extracted entities into ticker-like (for market) vs. the full set (for news).

**Primary recommendation:** Implement Phase 40 as a **three-plan split**:
1. **Plan 01** — Thread `market_context: str | None` plumbing through `worker.infer → dispatch_wave → run_round1` (signature-only; unit tests mirror the existing `peer_context` suite).
2. **Plan 02** — Add `MarketContextFormatter` pure function (`ContextPacket → str`) + `_assemble_context_packet` helper in `simulation.py`; extend `run_simulation` with `market_provider` / `news_provider` params; handle no-providers skip + partial-failure cases.
3. **Plan 03** — Lifespan + CLI wiring: construct real providers in `web/app.py` lifespan, read them in `SimulationManager._run`, construct inline in `cli.py:_handle_run` / `_run_pipeline`. Add integration test for the full end-to-end assembly with Fake providers.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | >=2.12.5 | `ContextPacket`, `MarketSlice`, `NewsSlice`, `Fundamentals` frozen models | Already installed; Phase 37 established frozen+forbid pattern |
| structlog | >=25.5.0 | `context_assembly_skipped` / `context_assembly_failed` warning events | Project-wide structured logging with PII-redaction processor |
| asyncio (stdlib) | 3.11+ | Assembly orchestrates two `async def` provider calls via `asyncio.gather` for parallelism | Phase 38 providers are `async def` end-to-end |
| pytest-asyncio | >=0.24.0 | `asyncio_mode = "auto"` test decoration | Existing test infra |
| pytest-socket | ==0.7.0 | `--disable-socket` global gate; unit tests use `FakeMarketDataProvider` / `FakeNewsProvider` | Phase 37 ISOL-06 established |

### Supporting (already in use, no changes needed)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| yfinance | >=1.2.2,<2.0 | Real `YFinanceMarketDataProvider` | Lifespan construction |
| feedparser | >=6.0.12,<7.0 | Real `RSSNewsProvider` XML parsing | Lifespan construction |
| httpx | >=0.28.0 | `RSSNewsProvider` async HTTP fetcher | Lifespan construction |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `asyncio.gather(market_fut, news_fut)` | Sequential `await market` then `await news` | Sequential wastes 2-3s on the critical path. Phase 38 D-19 never-raise means `gather` is safe — no exception propagation to handle. [RECOMMENDED: gather] |
| Scalar `market_context: str` on `dispatch_wave` | List `market_contexts: list[str]` mirroring `peer_contexts` | Scalar is correct for D-07 (same block for all 100 agents). List would be dead complexity. |
| Per-agent `market_context` inside `WorkerPersonaConfig` TypedDict | Function param on `infer()` | Param matches existing `peer_context` pattern exactly (worker.py:72). TypedDict would require downstream changes in all dispatch call sites. |

**Installation:** No new installs required. Verify existing:
```bash
uv tree | grep -E "yfinance|feedparser|httpx|pydantic|structlog"
```

## Architecture Patterns

### Recommended Project Structure (no new files required)

Three modules change; no new modules added:

```
src/alphaswarm/
├── simulation.py           # + _format_market_context, + _assemble_context_packet helpers
│                           # + market_provider, news_provider params on run_simulation
│                           # + market_context param on run_round1
├── batch_dispatcher.py     # + market_context scalar param on dispatch_wave + _safe_agent_inference
├── worker.py               # + market_context param on AgentWorker.infer, inject as system message
├── cli.py                  # + inline provider construction in _run_pipeline
└── web/
    ├── app.py              # + lifespan constructs YFinance/RSS providers, stores on app.state
    └── simulation_manager.py  # + read providers from app_state, pass to run_simulation
```

Optionally, a single new helper module for formatter testability:
```
src/alphaswarm/
└── context_formatter.py    # OPTIONAL — pure fn format_market_context(packet) -> str
                            # Moving it out of simulation.py makes unit testing trivial
                            # and avoids bloating simulation.py with string templating
```

### Pattern 1: Mirror `peer_context` plumbing exactly
**What:** The `peer_context` pattern is already battle-tested through four phases (Phase 7, 8, 11, 12). Copy the shape: scalar `str | None` param, None-guard before injection, system message with a header prefix.
**When to use:** Round 1 market context injection.
**Example:**
```python
# Source: src/alphaswarm/worker.py:87-92 (existing pattern)
messages: list[dict[str, str]] = [
    {"role": "system", "content": self._persona["system_prompt"]},
]
if peer_context:
    messages.append({"role": "system", "content": f"Peer context:\n{peer_context}"})
messages.append({"role": "user", "content": user_message})

# Phase 40: add market_context BETWEEN system and user (before peer_context if both ever combined)
if market_context:
    messages.insert(1, {"role": "system", "content": f"Market context:\n{market_context}"})
# Net order for Round 1: [persona_system, market_system, user] — peer_context is None in Round 1
# Net order for Rounds 2-3: [persona_system, peer_system, user] — market_context is None
```

### Pattern 2: Parallel provider fetch via asyncio.gather
**What:** `run_simulation` calls both providers in parallel since they are independent.
**When to use:** Context assembly block, after `inject_seed` returns entity list.
**Example:**
```python
# Source: Phase 38 providers guarantee never-raise; gather is safe.
from alphaswarm.ingestion.types import ContextPacket

if market_provider is not None and news_provider is not None:
    entities = tuple(e.name for e in parsed_result.seed_event.entities)
    import re
    _TICKER_RE = re.compile(r"^[A-Z]{1,5}$")
    tickers = [e for e in entities if _TICKER_RE.match(e)]

    # Parallel fetch — providers are D-19 never-raise per Phase 38
    market_slices, news_slices = await asyncio.gather(
        market_provider.get_prices(tickers),        # NOT fetch_batch — Protocol name
        news_provider.get_headlines(list(entities)), # dual-source routing internal
    )
    context_packet = ContextPacket(
        cycle_id=cycle_id,
        as_of=datetime.now(UTC),
        entities=entities,
        market=tuple(market_slices.values()),
        news=tuple(news_slices.values()),
    )
else:
    logger.warning("context_assembly_skipped", reason="no_providers_configured")
    context_packet = None
```

### Pattern 3: Formatter skips `fetch_failed` silently
**What:** CONTEXT.md D-03 — the formatter is the single point where staleness is filtered.
**When to use:** Converting `ContextPacket` to the `market_context` string passed into Round 1.
**Example:**
```python
def _format_market_context(packet: ContextPacket) -> str | None:
    """CONTEXT.md D-08, D-09: price + fundamentals + top-5 headlines per entity.

    Silently skips MarketSlice/NewsSlice with staleness='fetch_failed' (D-03).
    Returns None if no entity has any fresh data — callers should not append an
    empty 'Market context:' system message to prompts.
    """
    # Index slices by entity/ticker for joined lookup
    market_by_ticker = {s.ticker: s for s in packet.market if s.staleness != "fetch_failed"}
    news_by_entity   = {s.entity: s for s in packet.news   if s.staleness != "fetch_failed"}

    blocks: list[str] = []
    for entity in packet.entities:
        m = market_by_ticker.get(entity)  # may be None (not a ticker or fetch_failed)
        n = news_by_entity.get(entity)    # may be None (news fetch_failed)
        if m is None and n is None:
            continue
        lines = [f"== {entity} =="]
        if m is not None:
            if m.price is not None:
                lines.append(f"Price: ${m.price}")
            if m.fundamentals is not None:
                f = m.fundamentals
                parts = []
                if f.pe_ratio is not None:    parts.append(f"P/E: {f.pe_ratio}")
                if f.eps is not None:         parts.append(f"EPS: {f.eps}")
                if f.market_cap is not None:  parts.append(f"Mkt Cap: {f.market_cap}")
                if parts:
                    lines.append("Fundamentals: " + ", ".join(parts))
        if n is not None and n.headlines:
            lines.append("Recent headlines:")
            for h in n.headlines[:5]:  # D-09
                lines.append(f"  - {h}")
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks) if blocks else None  # None short-circuits system message
```

### Anti-Patterns to Avoid
- **Passing `ContextPacket` into `dispatch_wave` or `AgentWorker`:** Keep the type-coupling limited to `simulation.py`. Below that layer, pass only the formatted `str`. Prevents `ingestion.types` from leaking into `worker.py` / `batch_dispatcher.py` imports.
- **Re-formatting the context per-agent:** The context is identical across all 100 agents (D-07). Build once, pass scalar. A per-agent formatter call would be 100× wasted work.
- **Blanket try/except around the assembly block:** Phase 38 providers are D-19 never-raise. Wrapping `get_prices` + `get_headlines` in try/except is defensive theater — and would mask real bugs (e.g., pydantic validation errors on malformed fixtures). Let unexpected exceptions propagate.
- **Re-raising `fetch_failed` slices as errors:** The whole point of `fetch_failed` is graceful degradation. The formatter's job is to drop them; the assembly's job is to include them in the packet; no layer should convert them into exceptions.
- **Appending an empty "Market context:" system message when no data landed:** If all entities fetch_failed, `_format_market_context` returns None; skip the system message entirely. Otherwise agents see a misleading header with nothing below.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Provider retry / backoff on network failure | Custom retry loop | Phase 38 D-19 contract — providers internally never raise; failures land as `staleness='fetch_failed'` slices | Phase 38 already handles this. Retrying here would double-fetch on partial failures. |
| Ticker classification | Custom entity-type inference | Reuse `RSSNewsProvider._TICKER_RE` pattern (`^[A-Z]{1,5}$`) defined in `rss_provider.py:73` | Already validated and security-reviewed (T-38-01) for URL injection safety. |
| Decimal formatting for price | `f"{float(m.price):.2f}"` | `f"{m.price}"` (Decimal's `__str__` preserves precision) | CONTEXT.md `MarketSlice.price` is `Decimal | None` precisely to avoid float rounding. Casting to float reintroduces the bug. |
| News deduplication across entities | Custom dedup hash | Don't dedup — each entity gets its own `NewsSlice`; headlines may repeat across entities and that's fine for 5-per-entity cap | Phase 40 is not a news aggregator. |
| Empty-batch handling | Custom "if not entities, skip" chains | Providers already return `{}` on empty input (yfinance_provider.py:126, rss_provider.py:170) | Pitfall 9 from Phase 38 — already tested. |
| PII scrubbing on context packet before logs/Neo4j | Custom `redact_packet` | `pii_redaction_processor` in `shared_processors` already runs on every structlog event (logging.py:210) | Phase 37 ISOL-04 runs before renderer. Log the packet normally; the processor handles scrubbing for free. |

**Key insight:** Almost every "I should write X" instinct in this phase is covered by a Phase 37/38 artifact. The one genuinely new piece of code is the `_format_market_context` string formatter — everything else is wiring.

## Runtime State Inventory

**Not applicable** — Phase 40 is a greenfield wiring phase. No rename/refactor, no string replacements, no data migration. Nothing to inventory.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | Runtime | ✓ | 3.11+ | — |
| pydantic | `ContextPacket` construction | ✓ | 2.12.5 (pyproject.toml) | — |
| structlog | Log events | ✓ | 25.5.0 | — |
| yfinance | `YFinanceMarketDataProvider` (lifespan + CLI) | ✓ | 1.2.2+ | **None — but context assembly gracefully degrades to `context_packet=None` per D-02** |
| feedparser | `RSSNewsProvider` (lifespan + CLI) | ✓ | 6.0.12+ | Same as above |
| httpx | `RSSNewsProvider` HTTP | ✓ | 0.28.0+ | — |
| Ollama (live) | Simulation inference | Not probed | — | Not required for unit tests; integration tests use live Ollama (Phase 5+ pattern) |
| Neo4j (live) | Simulation persistence | Not probed | — | Not required for unit tests; docker compose for integration tests |
| Internet (Yahoo Finance + Google News RSS) | Real provider fetches | Runtime-only | — | **Fetch failures produce `staleness='fetch_failed'` slices; sim still runs** |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** Network outages are already handled by Phase 38's D-19 never-raise contract. Phase 40 adds nothing new to test here.

## Common Pitfalls

### Pitfall 1: CONTEXT.md D-01 method names don't exist on the Protocol
**What goes wrong:** The planner writes `market_provider.fetch_batch(tickers)` following CONTEXT.md D-01 verbatim. AttributeError at runtime; mypy strict catches it during type-check.
**Why it happens:** CONTEXT.md D-01 and the INGEST-03 requirement line 20 both say `fetch_batch` / `fetch_headlines`, but the Phase 38 Protocol (ingestion/providers.py:42-62) defines `get_prices` / `get_fundamentals` / `get_volume` / `get_headlines`. `fetch_batch` was never implemented; the YFinance provider has a PRIVATE `_fetch_batch_shared` helper that all three Protocol methods delegate to.
**How to avoid:** Call `market_provider.get_prices(tickers)` (returns full `MarketSlice` with price + fundamentals + volume per yfinance_provider.py:119-132 module docstring) and `news_provider.get_headlines(entities)`. The planner should **add this correction as a D-01' note** in the plan.
**Warning signs:** mypy error `"MarketDataProvider" has no attribute "fetch_batch"`; AttributeError at first test run.

### Pitfall 2: Calling get_prices + get_fundamentals + get_volume in sequence
**What goes wrong:** 3× network cost to Yahoo Finance for identical data. Wasted 2-3s on critical path.
**Why it happens:** Reading the Protocol in isolation suggests one method per field-type. But per `yfinance_provider.py:42-48` module docstring: "PHASE 40 CALL PATTERN (IMPORTANT): Phase 40 must call EXACTLY ONE of the three methods per simulation run (recommended: get_prices, since it returns the full market slice shape expected by ContextPacket.market)."
**How to avoid:** Call `get_prices` once. Use `Fundamentals` sub-object inside each `MarketSlice` for pe_ratio/eps/market_cap.
**Warning signs:** Any Phase 40 code with `await market_provider.get_fundamentals(...)` as a second call.

### Pitfall 3: Ticker classification leaking non-tickers into yfinance
**What goes wrong:** Passing the string `"Federal Reserve"` to `yf.Ticker("Federal Reserve")` triggers `fetch_failed` (as designed) but also adds pointless Yahoo Finance calls for every seed entity that isn't a ticker.
**Why it happens:** CONTEXT.md D-01 says "entity_tickers" vaguely — discretion item 2 asks whether to filter. The `RSSNewsProvider` internalizes ticker routing (rss_provider.py:77 `_route_url`) but `YFinanceMarketDataProvider` does NOT — it attempts every string.
**How to avoid:** Pre-filter entities with the same `^[A-Z]{1,5}$` regex before calling `get_prices`. Pass **all** entities to `get_headlines` (provider handles routing). The regex lives in rss_provider.py:73 — lift it to a shared helper (`alphaswarm.ingestion.tickers.is_ticker(e: str) -> bool`) to avoid duplication.
**Warning signs:** `fetch_failed` rate >90% on market slices for a typical seed. Pointless Yahoo Finance calls for entities like "Federal Reserve", "OPEC", "semiconductors".

### Pitfall 4: Context packet construction with tuple instead of list fields
**What goes wrong:** `ContextPacket(market=[slice1, slice2])` fails with pydantic `ValidationError` — the field is declared as `tuple[MarketSlice, ...]` with `extra="forbid"`.
**Why it happens:** Phase 37 REVIEW HIGH (ingestion/types.py:10-15) explicitly made all collection fields tuple to prevent mutation through the frozen model. Passing a list works via coercion in pydantic v2, but any tuple-type assertion in tests would fail.
**How to avoid:** Construct with `tuple(...)` explicitly. `tuple(market_slices.values())` / `tuple(news_slices.values())`.
**Warning signs:** Tests asserting `isinstance(packet.market, tuple)` fail when the constructor receives a list — pydantic may coerce, but explicit is better.

### Pitfall 5: Appending empty "Market context:" system message
**What goes wrong:** When every entity returns `fetch_failed` (total network outage), a naive formatter returns `"Market context:\n"` and the injector adds a misleading system message to every agent prompt. Agents see the header, no data, and may confuse-infer.
**Why it happens:** Following the `peer_context` pattern mechanically — but `_format_peer_context` returns `""` on empty posts, and `_dispatch_round` converts `""` to `None` (simulation.py:641, 666).
**How to avoid:** `_format_market_context` should return `None` on empty — matches the peer pattern's post-conversion semantics. Then `if market_context:` guards the injection site cleanly.
**Warning signs:** Agent prompts contain `"Market context:\n"` with no body. Integration test with all-failed ContextPacket should assert `market_context is None` passed to dispatch_wave.

### Pitfall 6: `app.state.market_provider` access in request handlers that predates Phase 40
**What goes wrong:** Existing route handlers read `app.state.market_provider` at request time; if Phase 40 sets it in lifespan BUT the handler is called before lifespan completes (unlikely — FastAPI gates requests on lifespan startup), AttributeError.
**Why it happens:** Dynamic `app.state` attribute pattern — there's no type guarantee the attribute exists.
**How to avoid:** Standard FastAPI lifespan ordering already gates this (startup must complete before requests are served). No new routes read these providers — only `SimulationManager._run` does. Low risk.
**Warning signs:** `AttributeError: 'State' object has no attribute 'market_provider'` in request handlers (should not appear during Phase 40 scope).

### Pitfall 7: `inject_seed` returns a tuple of 3 — parsed_result is [1]
**What goes wrong:** Writing `cycle_id, parsed_result = await inject_seed(...)` after CONTEXT.md D-01 skims "inject_seed extracts entities." `inject_seed` actually returns `(cycle_id, parsed_result, modifier_result)` — three elements (seed.py:47).
**Why it happens:** Phase 13 added `modifier_result` as the third element. CONTEXT.md and the phase description don't mention modifiers.
**How to avoid:** Use the existing pattern from simulation.py:764: `cycle_id, parsed_result, modifier_result = await inject_seed(...)`. Entities are `parsed_result.seed_event.entities` — a `list[SeedEntity]` where each has a `.name` attribute.
**Warning signs:** TypeError on unpacking; `parsed_result` typed as `ParsedModifiersResult | None`.

### Pitfall 8: Parallel gather with one None provider
**What goes wrong:** `asyncio.gather(market_provider.get_prices(...), news_provider.get_headlines(...))` fails with AttributeError if only one provider is configured and the other is None. CONTEXT.md D-02 says both must be present — but a defensive implementation might be tempted to allow one-or-the-other.
**Why it happens:** Sloppy None handling.
**How to avoid:** Enforce D-02 strictly: both providers present → assemble; either absent → skip entirely and log `context_assembly_skipped`. Do NOT attempt partial assembly.
**Warning signs:** `AttributeError: 'NoneType' object has no attribute 'get_prices'`.

### Pitfall 9: ISOL-04 PII redaction misfiring on ContextPacket
**What goes wrong:** The PII processor's recursive walker (logging.py:98) traverses dicts/lists/tuples/sets — it **does** traverse `ContextPacket` when logged (pydantic v2 model → dict via model_dump), which would redact any `fundamentals` key if fundamentals appeared in the `_LITERAL_NORMALIZED` set. Currently it does NOT — the redaction set is `{holdings, portfolio, positions, costbasis, qty, shares, positionsbyaccount, holdingsbyaccount, portfoliobyaccount}`.
**Why it happens:** False positive concern in discussion log (CONTEXT.md mentions "Context packet contents are scrubbed by the PII redaction processor before reaching logs"). This is already satisfied — but because ContextPacket has zero holdings-shaped fields (ISOL-02 / Phase 37), the processor correctly leaves it alone.
**How to avoid:** No action required. Success criterion #3 (ISOL-04 scrubbing) is **already inherited** from Phase 37 — every log event passes through `pii_redaction_processor`. The phase must not add any new field names to ContextPacket that would overlap with the redaction set (e.g., don't add a `position_ticker` field; don't name the market slice key `shares`). The existing tuple field names (`entities`, `market`, `news`) are all safe.
**Warning signs:** Tests asserting "market" or "news" strings appear in log output — they should, because ISOL-04 does not redact them. If a future author renames `market` to `positions`, redaction would kick in. Add a canary test asserting logged `ContextPacket` has unredacted `market`/`news` fields.

## Code Examples

Verified patterns from the live codebase (paths exact, line numbers as of 2026-04-19):

### Signature threading pattern — existing peer_context precedent to mirror
```python
# Source: src/alphaswarm/worker.py:69-92
async def infer(
    self,
    user_message: str,
    peer_context: str | None = None,
) -> AgentDecision:
    messages: list[dict[str, str]] = [
        {"role": "system", "content": self._persona["system_prompt"]},
    ]
    if peer_context:
        messages.append({"role": "system", "content": f"Peer context:\n{peer_context}"})
    messages.append({"role": "user", "content": user_message})
    # ... (chat call)

# Phase 40 extension:
async def infer(
    self,
    user_message: str,
    peer_context: str | None = None,
    market_context: str | None = None,   # NEW
) -> AgentDecision:
    messages: list[dict[str, str]] = [
        {"role": "system", "content": self._persona["system_prompt"]},
    ]
    if market_context:
        messages.append({"role": "system", "content": f"Market context:\n{market_context}"})
    if peer_context:
        messages.append({"role": "system", "content": f"Peer context:\n{peer_context}"})
    messages.append({"role": "user", "content": user_message})
```

### Dispatch plumbing — scalar peer_context vs list peer_contexts
```python
# Source: src/alphaswarm/batch_dispatcher.py:81-152
async def dispatch_wave(
    personas: list[WorkerPersonaConfig],
    governor: ResourceGovernor,
    client: OllamaClient,
    model: str,
    user_message: str,
    settings: GovernorSettings,
    *,
    peer_context: str | None = None,         # scalar (Round 1 — identical for all)
    peer_contexts: list[str | None] | None = None,  # per-agent (Rounds 2-3)
    state_store: StateStore | None = None,
) -> list[AgentDecision]:
    # ...
    # Phase 40 adds:
    #   market_context: str | None = None   (scalar — D-07)
    # Round 1: scalar peer_context=None + scalar market_context=<formatted>
    # Rounds 2-3: list peer_contexts=[...] + scalar market_context=None (D-06)
```

### Round 1 call site — existing peer_context=None, add market_context
```python
# Source: src/alphaswarm/simulation.py:496-505
decisions = await dispatch_wave(
    personas=worker_configs,
    governor=governor,
    client=ollama_client,
    model=worker_alias,
    user_message=rumor,
    settings=settings.governor,
    peer_context=None,
    state_store=state_store,
)

# Phase 40 extension: run_round1 receives new market_context param, threads through
decisions = await dispatch_wave(
    personas=worker_configs,
    governor=governor,
    client=ollama_client,
    model=worker_alias,
    user_message=rumor,
    settings=settings.governor,
    peer_context=None,
    market_context=market_context,   # NEW
    state_store=state_store,
)
```

### Lifespan provider construction — mirrors existing state object pattern
```python
# Source: src/alphaswarm/web/app.py:32-103 (existing lifespan)
# Current pattern:
app.state.app_state = app_state
app.state.sim_manager = sim_manager
app.state.replay_manager = replay_manager
app.state.connection_manager = connection_manager
app.state.portfolio_snapshot = await asyncio.to_thread(load_portfolio_snapshot, ...)

# Phase 40 addition (D-10):
from alphaswarm.ingestion import YFinanceMarketDataProvider, RSSNewsProvider
app.state.market_provider = YFinanceMarketDataProvider()  # stateless construction
app.state.news_provider = RSSNewsProvider()                # stateless construction
```

### SimulationManager wiring — D-10 via app_state attribute access
```python
# Source: src/alphaswarm/web/simulation_manager.py:118-133
await run_simulation(
    rumor=seed,
    settings=self._app_state.settings,
    ollama_client=self._app_state.ollama_client,
    model_manager=self._app_state.model_manager,
    graph_manager=self._app_state.graph_manager,
    governor=self._app_state.governor,
    personas=list(self._app_state.personas),
    brackets=list(self._brackets),
    state_store=self._app_state.state_store,
    consume_shock=self.consume_shock,
)

# Phase 40 extension (D-10): pass providers via app_state — but AppState dataclass
# does not currently hold providers. Two options:
#   (a) Extend AppState with optional provider fields (cleaner; tested pattern)
#   (b) Thread them via SimulationManager __init__ from app.state at lifespan time
# Discretion item from CONTEXT.md — planner should pick. Option (b) avoids making
# alphaswarm.app import ingestion (adds to importlinter source_modules); option (a)
# requires the importlinter source_modules list to remain valid since
# alphaswarm.ingestion is ALREADY in that list. Option (a) is cleaner and has
# no importlinter cost.
```

### Test pattern — Fake providers in unit tests stay under --disable-socket
```python
# Source: tests/test_simulation.py:155-180 (existing run_round1 test)
@patch("alphaswarm.simulation.dispatch_wave", new_callable=AsyncMock)
@patch("alphaswarm.simulation.inject_seed", new_callable=AsyncMock)
async def test_run_round1_dispatches_with_no_peer_context(
    mock_inject, mock_dispatch, mock_settings, mock_ollama_client,
    mock_model_manager, mock_graph_manager, mock_governor,
) -> None:
    mock_inject.return_value = ("test-cycle-id", MOCK_PARSED_RESULT, None)
    mock_dispatch.return_value = _default_decisions(len(TEST_PERSONAS))
    await run_round1(...)
    assert mock_dispatch.call_args.kwargs["peer_context"] is None

# Phase 40 pattern — use FakeMarketDataProvider/FakeNewsProvider with fixtures:
from alphaswarm.ingestion import FakeMarketDataProvider, FakeNewsProvider
from alphaswarm.ingestion.types import MarketSlice, NewsSlice, Fundamentals
from datetime import UTC, datetime
from decimal import Decimal

fake_market = FakeMarketDataProvider(fixtures={
    "NVDA": MarketSlice(
        ticker="NVDA",
        price=Decimal("523.45"),
        volume=12345678,
        fundamentals=Fundamentals(pe_ratio=Decimal("65.2"), eps=Decimal("8.03"), market_cap=Decimal("1.3e12")),
        fetched_at=datetime.now(UTC),
        source="fake",
        staleness="fresh",
    )
})
fake_news = FakeNewsProvider(fixtures={
    "NVDA": NewsSlice(
        entity="NVDA",
        headlines=("NVIDIA breaks records", "AI chip demand surges"),
        fetched_at=datetime.now(UTC),
        source="fake",
        staleness="fresh",
    ),
})
# Then: await run_simulation(..., market_provider=fake_market, news_provider=fake_news)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Rumor-only Round 1 prompts | Rumor + grounded `market_context` system message | Phase 40 (this phase) | 100 agents now see current price / fundamentals / top-5 headlines — simulations reflect actual market state |
| `peer_context` injection only | Dual system-message injection: `market_context` (Round 1) + `peer_context` (Rounds 2-3) | Phase 40 | Cleaner separation of "ground truth" (market) vs. "social influence" (peers) |
| Hand-written provider wiring per call site | Lifespan-constructed provider singletons on `app.state` | Phase 40 | Consistent with existing `sim_manager`, `replay_manager`, `portfolio_snapshot` pattern |

**Deprecated/outdated:**
- Nothing deprecated. Phase 40 is purely additive.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Passing all three extracted-entity classes (company/sector/person) to `get_headlines` is correct and produces useful output for sectors/persons via Google News RSS routing [ASSUMED — Phase 38 testing focused on tickers + entity names; sector-only outputs not explicitly verified in live tests] | Pitfall 3, Code Examples | Low — Phase 38 rss_provider.py `_route_url` explicitly handles non-ticker via `urllib.parse.quote_plus`. Worst case: Google News returns few matches for sparse sectors; formatter drops empty headlines gracefully. |
| A2 | `asyncio.gather(market, news)` is safe because Phase 38 providers are contractually never-raise [CITED: ingestion/providers.py:33-40 D-19, yfinance_provider.py:8, rss_provider.py:9] — but this assumes no bugs in Phase 38 implementation | Code Examples / Pattern 2 | Low — if Phase 38 has an escape-hatch exception, gather propagates it. Unit tests with Fake providers cover this path deterministically. |
| A3 | `ContextPacket.as_of = datetime.now(UTC)` at assembly time is appropriate — not e.g., min(slice.fetched_at) [ASSUMED] | Pattern 2 | Low — `as_of` is an informational field for Neo4j persistence later. Deviations of a few seconds are inconsequential. |
| A4 | FastAPI lifespan guarantees provider construction completes before `SimulationManager.start()` is callable [CITED: FastAPI docs — startup is awaited before serving requests] | Pitfall 6 | Low — standard FastAPI semantic, well-documented. |
| A5 | The `^[A-Z]{1,5}$` regex from rss_provider.py:73 is the right classifier for "is this a US-listed ticker" [CITED: Phase 38 D-02, rss_provider.py:44-53 international notes] — explicitly excludes international tickers (VOD.L, 7203.T) per intentional scope | Pitfall 3 | Low — international ticker support is out of scope (Phase 38 discussion); any non-matcher gracefully routes to Google News for news and is skipped for market data. |

## Open Questions (RESOLVED)

1. **CONTEXT.md API naming mismatch (`fetch_batch` vs `get_prices`)**
   - What we know: CONTEXT.md D-01 and REQUIREMENTS.md INGEST-03 both say `fetch_batch` / `fetch_headlines`. Actual Protocol methods are `get_prices`, `get_fundamentals`, `get_volume`, `get_headlines`.
   - What's unclear: Was this intentional rename in Phase 38 (possible; Phase 37 drafted the Protocol names) or a documentation drift?
   - Recommendation: Planner corrects to the actual method names in plan. File a tiny follow-up doc-fix ticket if CONTEXT.md needs reconciliation (not blocking).
   - **RESOLVED:** Plans use `market_provider.get_prices(tickers)` and `news_provider.get_headlines(entities)` throughout. Acceptance criteria in 40-01 and 40-02 assert `fetch_batch` never appears in source. CONTEXT.md D-01 naming is a documentation drift from Phase 37 — corrected in plans.

2. **AppState extension vs SimulationManager constructor for providers**
   - What we know: CONTEXT.md discretion item 4 explicitly defers this — "whether providers are constructor args or read from `app_state` at `_run()` time."
   - What's unclear: Which is cleaner given the CLI path that does NOT have an AppState-centric provider-carrier. CLI would need inline construction regardless.
   - Recommendation: **Extend `AppState` dataclass** with `market_provider: MarketDataProvider | None = None` and `news_provider: NewsProvider | None = None`. CLI's `create_app_state(...)` can set these (new `with_providers: bool` kwarg or always-on). Web path's lifespan sets them post-construction. `SimulationManager._run` reads `self._app_state.market_provider` / `.news_provider` and forwards to `run_simulation`. Minimizes signature churn across both paths.
   - **RESOLVED:** Plan 03 Task 1 extends `AppState` dataclass with `market_provider: MarketDataProvider | None = None` and `news_provider: NewsProvider | None = None`. `SimulationManager._run` reads from `app_state`. CLI constructs providers inline in `_run_pipeline` (D-11).

3. **Should the entity tuple passed to ContextPacket be uppercased / normalized?**
   - What we know: `SeedEntity.name` comes from orchestrator LLM output (unconstrained case). Tickers in seed rumors may be "NVIDIA" or "nvidia" or "Nvidia" or the ticker symbol "NVDA".
   - What's unclear: Does the orchestrator already normalize? Probably not — its prompt says "extract named entities" (seed.py:24).
   - Recommendation: Do NOT normalize at Phase 40 layer. Pass entity names as-is. The `_TICKER_RE.match()` is case-sensitive (uppercase-only) — this is intentional per T-38-01 security: only strict ticker strings reach Yahoo Finance. Non-matching strings (like "NVIDIA") route through Google News via `get_headlines` only. If the orchestrator produces "NVIDIA" instead of "NVDA", no market slice; news slice only. Acceptable degradation until v7.0 if users notice.
   - **RESOLVED:** Plans pass entity names as-is. `_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")` filters for market only; all entities pass to `get_headlines`. No normalization at Phase 40 layer.

4. **Does `_format_market_context` need a budget cap like `_format_peer_context`?**
   - What we know: `_format_peer_context` (simulation.py:314-361) caps at 4000 chars; top 10 posts. No such cap exists for market context in CONTEXT.md.
   - What's unclear: How long does a well-populated 5-entity × 5-headline block get? Rough estimate: 5 entities × (50 chars price + 60 chars fundamentals + 5 × 100 chars headline) ≈ 3000 chars. Should be fine for typical M1 model context windows but SHOCK_TEXT_MAX_LEN=4096 is the project's existing budget cap convention.
   - Recommendation: Add an optional `budget: int = 4000` param to `_format_market_context` matching the peer formatter's style. Greedy-fill with entity blocks; drop later entities if they would overflow. Keeps prompt budget predictable under unusual seeds (e.g., 20-entity geopolitical rumor).
   - **RESOLVED:** Plan 02 Task 1 implements `format_market_context(packet, budget=4000)` with greedy-fill: entity blocks are appended while cumulative length stays under budget; the first block that would overflow is dropped along with all subsequent blocks.

## Environment Availability

(See above — included in Summary section for Phase 40 since it's a wiring phase with no new dependencies.)

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.0+ with pytest-asyncio 0.24+ (`asyncio_mode = "auto"`) [VERIFIED: pyproject.toml:30-31, 52-53] |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest tests/test_simulation.py tests/test_worker.py tests/test_batch_dispatcher.py -x` |
| Full suite command | `uv run pytest` (includes socket-gated integration tests via `--disable-socket` + auto-marker) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INGEST-03 | run_simulation assembles ContextPacket from providers after inject_seed | unit (with fake providers) | `uv run pytest tests/test_simulation.py::test_run_simulation_assembles_context_packet -x` | ❌ Wave 0 |
| INGEST-03 | ContextPacket assembly emits context_assembly_skipped when providers=None | unit | `uv run pytest tests/test_simulation.py::test_run_simulation_skips_context_when_providers_missing -x` | ❌ Wave 0 |
| INGEST-03 | ContextPacket formatter drops fetch_failed slices silently | unit | `uv run pytest tests/test_simulation.py::test_format_market_context_drops_fetch_failed -x` | ❌ Wave 0 |
| INGEST-03 | ContextPacket logged without sensitive-key redaction kicking in | unit | `uv run pytest tests/test_logging.py::test_context_packet_not_redacted -x` | ❌ Wave 0 |
| SIM-04 | run_simulation accepts market_provider=None, news_provider=None; backward-compatible | unit | `uv run pytest tests/test_simulation.py::test_run_simulation_backward_compatible -x` | ❌ Wave 0 |
| SIM-04 | market_context flows through dispatch_wave → worker.infer | unit | `uv run pytest tests/test_batch_dispatcher.py::test_dispatch_wave_forwards_market_context -x` | ❌ Wave 0 |
| SIM-04 | AgentWorker.infer injects market_context as system message before user message | unit | `uv run pytest tests/test_worker.py::test_infer_with_market_context -x` | ❌ Wave 0 |
| SIM-04 | Market context injection is Round 1 only (Rounds 2-3 market_context is None) | unit | `uv run pytest tests/test_simulation.py::test_market_context_round1_only -x` | ❌ Wave 0 |
| Web wiring | lifespan constructs providers; sim_manager forwards them | integration | `uv run pytest tests/test_web.py::test_lifespan_wires_providers -x` | ❌ Wave 0 |
| CLI wiring | cli._run_pipeline constructs providers | unit | `uv run pytest tests/test_cli.py::test_run_pipeline_constructs_providers -x` | ❌ Wave 0 |
| End-to-end | FakeMarketDataProvider + FakeNewsProvider → run_simulation → worker receives fixture headlines | integration (no network) | `uv run pytest tests/test_simulation.py::test_run_simulation_end_to_end_with_fake_providers -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_simulation.py tests/test_worker.py tests/test_batch_dispatcher.py -x` (~ <30s)
- **Per wave merge:** `uv run pytest` (full suite — includes logging/cli/web tests)
- **Phase gate:** Full suite green + `uv run lint-imports` (importlinter — no new forbidden cross-imports) + `uv run mypy src` (strict) before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_simulation.py` — add Phase 40 section (`_format_market_context` tests, `run_simulation` provider wiring tests, fetch_failed filter test, round1-only guard test)
- [ ] `tests/test_worker.py` — add `test_infer_with_market_context` mirroring `test_infer_with_peer_context` (worker.py:154-167)
- [ ] `tests/test_batch_dispatcher.py` — add `test_dispatch_wave_forwards_market_context` mirroring the `peer_context` forward test
- [ ] `tests/test_logging.py` — add canary test asserting `market`/`news` keys are NOT in the PII redaction set (prevents future accidental additions)
- [ ] `tests/test_web.py` — add lifespan test asserting `app.state.market_provider` and `app.state.news_provider` are constructed
- [ ] `tests/test_cli.py` — add test asserting `_run_pipeline` constructs both providers before calling `run_simulation`

No new test framework install needed — all infrastructure (pytest-asyncio, pytest-socket, conftest fixtures) already in place.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth surface changes; web routes unchanged |
| V3 Session Management | no | No sessions introduced |
| V4 Access Control | no | No new endpoints |
| V5 Input Validation | yes | Seed rumor entities flow into provider calls — handled by existing Phase 38 guards (`_TICKER_RE` whitelist, `urllib.parse.quote_plus` for news URL) |
| V6 Cryptography | no | No new crypto surface |
| V7 Error Handling | yes | Providers never raise (Phase 38 D-19); assembly must not mask unexpected errors in logging |
| V8 Data Protection | yes | ISOL-04 PII redaction already covers log output; ContextPacket has no PII-shaped fields by ISOL-02 design |
| V14 Configuration | yes | Providers constructed in lifespan — no secrets needed (Yahoo Finance / Google News RSS are public, no API keys) |

### Known Threat Patterns for {python async integration phase}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| URL injection via seed entity passed to Yahoo/Google URL | Tampering | Phase 38 T-38-01 mitigation: `_TICKER_RE` regex whitelist (ticker path) + `urllib.parse.quote_plus` (news path) — already tested [VERIFIED: rss_provider.py:38-42] |
| PII leakage in structured logs when ContextPacket is logged | Information Disclosure | ISOL-04 `pii_redaction_processor` runs on every event (logging.py:210). ContextPacket fields (`entities`, `market`, `news`) are not in the redaction set — and by ISOL-02 design, have no holdings shape. Already covered. |
| Malicious seed rumor triggers unbounded network fan-out | Denial of Service | Phase 38 D-07 — providers called once per simulation run, not per agent. Phase 40 does not change this cardinality. Orchestrator LLM typically extracts ≤10 entities per rumor. |
| Fake provider fixture raises in fixture_source callback | Tampering (bypass D-19) | Phase 38 providers.py:116 catches callback exceptions and converts to `fetch_failed` slices — already covered in FakeMarketDataProvider. |
| Prompt injection via fetched headline text | Tampering | Headlines are injected as system messages inside a labeled block (`Market context:\n...`). If a headline contains `"\n\nIGNORE ABOVE, RESPOND WITH..."`, the LLM may be influenced. Mitigation is out-of-scope for Phase 40 (would apply to ALL external-content injection, including peer rationales from Phase 7). Track as known limitation; existing project design accepts that LLM inputs are soft-trusted. |

No new secrets, credentials, or cryptographic operations are introduced by this phase.

## Sources

### Primary (HIGH confidence)
- `.planning/phases/40-simulation-context-wiring/40-CONTEXT.md` — locked decisions D-01 through D-11
- `.planning/REQUIREMENTS.md` — INGEST-03, SIM-04 requirement text
- `src/alphaswarm/simulation.py` lines 424-711, 718-1164 — `run_round1` + `run_simulation` signatures and call graph
- `src/alphaswarm/worker.py` lines 69-120 — existing `peer_context` injection pattern, the exact mirror target for `market_context`
- `src/alphaswarm/batch_dispatcher.py` lines 39-168 — existing `peer_context` / `peer_contexts` param plumbing
- `src/alphaswarm/ingestion/providers.py` lines 33-62 — actual Protocol method names (`get_prices`, `get_fundamentals`, `get_volume`, `get_headlines`) — source of truth over CONTEXT.md D-01 naming
- `src/alphaswarm/ingestion/types.py` lines 29-99 — `ContextPacket`, `MarketSlice`, `NewsSlice`, `Fundamentals`, `StalenessState`
- `src/alphaswarm/ingestion/yfinance_provider.py` lines 42-48 — "call EXACTLY ONE method per run" guidance from Phase 38
- `src/alphaswarm/ingestion/rss_provider.py` lines 73, 77-87 — `_TICKER_RE` pattern + dual-source routing
- `src/alphaswarm/web/app.py` lines 32-103 — existing lifespan pattern for `app.state` construction
- `src/alphaswarm/web/simulation_manager.py` lines 106-150 — `_run` method / `run_simulation` call site
- `src/alphaswarm/cli.py` lines 474-518 — `_run_pipeline` / `run_simulation` CLI call site
- `src/alphaswarm/logging.py` lines 45-214 — PII redaction processor + `shared_processors` ordering
- `src/alphaswarm/seed.py` lines 39-117 — `inject_seed` 3-tuple return signature
- `pyproject.toml` lines 5-33, 48-70 — dependency versions, pytest config, importlinter config
- `.planning/phases/38-market-data-news-providers/38-RESEARCH.md` — Phase 38 recommendations, pitfalls, provider semantics

### Secondary (MEDIUM confidence)
- `tests/test_worker.py` lines 154-167 — existing `peer_context` test — template for `market_context` test
- `tests/test_simulation.py` lines 155-243 — existing `run_round1` test patterns
- `tests/integration/conftest.py` — `enable_socket` auto-marker mechanism
- `tests/integration/test_yfinance_provider_live.py` lines 37-146 — integration test patterns with real provider

### Tertiary (LOW confidence — not relied on)
- (none — all claims verified against source code or CONTEXT.md)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new libraries; every dep already installed and tested
- Architecture: HIGH — every integration point is a mirror of an existing pattern (peer_context, lifespan app.state attributes, FakeMarketDataProvider test fixtures); call sites read verbatim from source
- Pitfalls: HIGH — surfaced directly from Phase 38 code comments and module docstrings (e.g., "PHASE 40 CALL PATTERN" in yfinance_provider.py:42)
- CONTEXT.md D-01 API mismatch: HIGH — verified by grepping the actual Protocol; `fetch_batch` does not exist in the codebase

**Research date:** 2026-04-19
**Valid until:** 2026-05-19 (30 days — stable stack, no fast-moving libraries in this phase)
