# Architecture Research — v6.0 Data Enrichment & Personalized Advisory

**Domain:** Local multi-agent financial simulation — ingestion + holdings-isolated advisory overlay
**Researched:** 2026-04-18
**Confidence:** HIGH (grounded in current code); MEDIUM on library specifics (yfinance/aiocache version behavior)

---

## 1. Architectural Verdict

Keep the existing v5.0 pipeline untouched at its core. v6.0 adds **three new subsystems** and one new orchestrator step, connected via pure dataclasses at well-defined seams:

1. `alphaswarm.ingestion/` — standalone async module (market, news, assembly)
2. `alphaswarm.holdings/` — isolated module, never imported by `simulation.py`, `worker.py`, `batch_dispatcher.py`, or `seed.py`
3. `alphaswarm.advisory/` — orchestrator synthesis step that runs after Round 3 consensus, before `generate_narratives`
4. `advisory` frontend route — mirrors the Phase 36 report pattern

The swarm path stays pure: `seed → inject_seed → run_simulation` operates only on `rumor: str`, `context_packet: ContextPacket` (new), and returns `AgentDecision`. Holdings never cross that boundary.

---

## 2. System Overview

```
┌────────────────────────────────────────────────────────────────────────┐
│                         Web Client (Vue 3)                             │
│   ControlBar   GraphView   ReportViewer   AdvisoryPanel (NEW)          │
└──────────────────────────────┬─────────────────────────────────────────┘
                               │ REST + WebSocket (~5Hz)
┌──────────────────────────────▼─────────────────────────────────────────┐
│                       FastAPI app (lifespan)                           │
│   SimulationManager   ReplayManager   ConnectionManager   Broadcaster  │
│   routes/: simulation, report, advisory(NEW), holdings(NEW)            │
└──────────────────────────────┬─────────────────────────────────────────┘
                               │
           ┌───────────────────┼───────────────────┐
           │                   │                   │
┌──────────▼─────────┐ ┌───────▼────────┐ ┌────────▼──────────┐
│  Ingestion (NEW)   │ │  SwarmCore     │ │ AdvisoryPipeline  │
│  market_data.py    │ │  simulation.py │ │  (NEW)            │
│  news.py           │ │  seed.py       │ │  holdings + swarm │
│  packet_builder.py │ │  worker.py     │ │  → advisory.md    │
│  cache.py          │ │  graph.py      │ │  orchestrator LLM │
└──────────┬─────────┘ └───────┬────────┘ └────────┬──────────┘
           │                   │                   │
           │           ┌───────▼────────┐          │
           │           │  Neo4j         │          │
           │           │  (cycle state, │          │
           │           │   rationales,  │          │
           │           │   edges)       │          │
           │           └────────────────┘          │
           │                                       │
           └──────► ContextPacket (frozen) ────────┤
                                                   │
                         ┌─────────────────────────▼───────┐
                         │ HoldingsStore (NEW, in-memory)  │
                         │  - never touches Neo4j          │
                         │  - never touches swarm prompts  │
                         │  - read only by AdvisoryPipeline│
                         └─────────────────────────────────┘
```

**Key invariant:** The arrow from HoldingsStore has exactly one consumer (AdvisoryPipeline). No other module imports `alphaswarm.holdings`.

---

## 3. Component Responsibilities

| Component | New/Modified | Responsibility | Implementation |
|---|---|---|---|
| `alphaswarm.ingestion.market_data` | NEW | Fetch OHLCV + fundamentals per ticker | async wrapper over `yfinance` (sync lib → `asyncio.to_thread`) with TTL cache |
| `alphaswarm.ingestion.news` | NEW | Fetch news headlines per entity | `httpx.AsyncClient` against NewsAPI/RSS; entity-keyed cache |
| `alphaswarm.ingestion.packet_builder` | NEW | Assemble `ContextPacket` from entities → slice per archetype | Pure function; no I/O |
| `alphaswarm.ingestion.cache` | NEW | Async TTL cache primitive | `aiocache` SimpleMemoryCache OR hand-rolled `dict + asyncio.Lock` |
| `alphaswarm.holdings.loader` | NEW | Parse Schwab CSV → `PortfolioSnapshot` | `pandas.read_csv` inside `asyncio.to_thread` |
| `alphaswarm.holdings.types` | NEW | `Holding`, `PortfolioSnapshot` frozen dataclasses | Immutable, never serialized to Neo4j |
| `alphaswarm.holdings.store` | NEW | In-memory holder on AppState | Single instance on `app.state.holdings_store` |
| `alphaswarm.advisory.pipeline` | NEW | Post-consensus: holdings + swarm → advisory markdown | Calls orchestrator LLM through existing `OllamaModelManager` |
| `alphaswarm.advisory.prompts` | NEW | System prompt, JSON schema for structured advisory | Jinja templates (mirrors `alphaswarm/templates/`) |
| `alphaswarm.simulation.run_simulation` | MODIFIED | Accept optional `context_packet` param; fire new `on_advisory_ready` hook at end | 5 lines changed, 0 removed |
| `SimulationManager._run` | MODIFIED | After `run_simulation` returns, invoke `AdvisoryPipeline.generate()` if holdings present | Additive try/finally block |
| `web/routes/advisory.py` | NEW | `POST /api/advisory/generate`, `GET /api/advisory/{cycle_id}` | Clones Phase 36 report route pattern |
| `web/routes/holdings.py` | NEW | `POST /api/holdings/upload`, `GET /api/holdings/status` | Uploads stay in memory only |
| `frontend/src/components/AdvisoryPanel.vue` | NEW | Markdown viewer + recommendation list | Mirrors `ReportViewer.vue` (marked + DOMPurify) |

---

## 4. Answers to the Six Integration Questions

### Q1. Where does the ingestion layer live?

**Recommendation:** Standalone module (`alphaswarm/ingestion/`), invoked from `SimulationManager` **before** `run_simulation` inside the same task.

**Rationale:**
- Not a dedicated process — adds IPC complexity, violates "local-first, single-operator" design; the ResourceGovernor cannot see into a subprocess.
- Not a FastAPI background task decoupled from the sim — creates race window where the sim starts with stale/empty packets.
- Sequential inside `SimulationManager._run` is correct: latency budget for ingestion is ~3–8s (yfinance cached hit <100ms, cold ~2s per ticker; NewsAPI ~300–800ms per entity), small relative to the 3-round cascade (~2–5 min).
- Phase order: `ingestion → inject_seed → run_simulation → advisory`. Ingestion surfaces its status via a new `SimulationPhase.INGESTING` state for WebSocket visibility.

**Modification to `SimulationManager._run`:**

```python
async def _run(self, seed: str) -> None:
    from alphaswarm.ingestion import ContextAssembler
    from alphaswarm.simulation import run_simulation
    from alphaswarm.advisory import AdvisoryPipeline

    try:
        # 1. NEW: build context packet from seed entities
        assembler = ContextAssembler(self._app_state)
        packet = await assembler.build(seed)  # fires ingestion phase

        # 2. Existing pipeline, now passed the packet
        sim_result = await run_simulation(
            rumor=seed,
            context_packet=packet,  # NEW param (optional, defaults None for back-compat)
            ...
        )

        # 3. NEW: advisory synthesis if holdings present
        if self._app_state.holdings_store.has_portfolio:
            advisory = AdvisoryPipeline(self._app_state)
            await advisory.generate(sim_result, self._app_state.holdings_store.snapshot())
    except asyncio.CancelledError:
        ...
```

**Confidence:** HIGH on placement. MEDIUM on exact latency budget — needs a ping test in Phase 6.1.

---

### Q2. Context packets: persisted vs ephemeral?

**Recommendation:** Ephemeral per-cycle dataclass passed in-memory; **optional, lossy audit trail** persisted to Neo4j as a `ContextSnapshot` node tied to the `Cycle`.

**Reasoning:**
- Packets are derived data (yfinance + NewsAPI are the source of truth). Re-fetching on replay is pointless for historical cycles because prices have moved — replays should be reasoning replays, not market replays.
- In-memory lifetime: from `ContextAssembler.build()` until the last Round 3 worker call completes. GC'd naturally.
- For reproducibility/debugging, persist a **slim audit node** on the `Cycle`:
  ```cypher
  CREATE (c:Cycle {cycle_id: $id})-[:HAS_CONTEXT]->
         (cs:ContextSnapshot {tickers: $tickers, as_of: $iso_ts, source_hash: $hash})
  ```
  Store just enough to reconstruct what data the swarm saw, not the data itself. This keeps Neo4j small and avoids re-hydrating price series on replay.
- On-disk cache (yfinance TTL) lives in `.alphaswarm/cache/` — same dir already used; gitignored.

**Anti-pattern to avoid:** Persisting full context packets (price histories, news bodies) to Neo4j. Bloats the graph, entangles market data with agent reasoning, and causes replay confusion. (See PITFALLS.md, pitfall: "Context packet as graph node".)

---

### Q3. Where does the holdings boundary live? (the hard question)

**Defense in depth — three independent enforcement layers:**

**Layer 1: Module boundary (architectural).**
- `alphaswarm/holdings/` has NO imports from `alphaswarm/{simulation,worker,batch_dispatcher,seed,parsing}.py`.
- Enforced by a `ruff`/`importlinter` contract in `pyproject.toml`:
  ```toml
  [tool.importlinter]
  root_packages = ["alphaswarm"]

  [[tool.importlinter.contracts]]
  name = "holdings-isolation"
  type = "forbidden"
  source_modules = [
      "alphaswarm.simulation",
      "alphaswarm.worker",
      "alphaswarm.batch_dispatcher",
      "alphaswarm.seed",
      "alphaswarm.parsing",
      "alphaswarm.ingestion",
  ]
  forbidden_modules = ["alphaswarm.holdings"]
  ```
  Runs in CI; fails the build on violation. Stronger than convention because it catches "accidental" imports introduced by refactors.

**Layer 2: Type system (structural).**
- Swarm functions take `ContextPacket` (never `PortfolioSnapshot`). The two types share NO fields.
- `ContextPacket` has no `portfolio`, `holdings`, `positions`, `cost_basis`, or `account_*` attributes. Adding one is a typed API change reviewers will notice.
- `AdvisoryPipeline.generate(sim_result: SimulationResult, portfolio: PortfolioSnapshot)` is the ONLY function signature accepting both.

**Layer 3: Runtime tripwire (behavioral).**
- Unit test `tests/invariants/test_holdings_isolation.py`:
  - Loads test `PortfolioSnapshot` with unique sentinel tickers (e.g., `HOLDINGS_CANARY_TICKER_ZZZ`, `SECRET_COST_BASIS_999999`).
  - Runs a full `run_simulation` with mocked Ollama that captures every prompt string sent to workers.
  - `assert "HOLDINGS_CANARY_TICKER_ZZZ" not in captured_prompt` for every worker call.
  - `assert "SECRET_COST_BASIS_999999" not in captured_prompt`.
  - `assert "990099"` (canary cost basis) `not in captured_prompt`.
- Log-grep CI gate: `grep -r "holdings\|portfolio" src/alphaswarm/templates/ src/alphaswarm/worker.py src/alphaswarm/simulation.py` must return empty. Fails CI if any match. Crude but cheap.

**All three must be in place.** Layer 1 catches refactor accidents. Layer 2 catches API drift. Layer 3 catches prompt-template leakage (e.g., someone copies a portfolio string into a Jinja template).

**Confidence:** HIGH — this is a standard defense-in-depth information-isolation pattern.

---

### Q4. Caching + async event loop

**Recommendation:** Two-tier cache, both async-safe.

**Tier 1 — In-process TTL cache (aiocache SimpleMemoryCache or hand-rolled).**
- **Choice:** Hand-rolled `dict + asyncio.Lock + TTL tuples` is ~30 lines and zero deps. aiocache is fine but pulls extras. Given the project's "minimal deps" style and that you already pull `aiofiles`, I lean hand-rolled.
- **Shape:**
  ```python
  class AsyncTTLCache:
      def __init__(self, ttl_seconds: int): ...
      async def get(self, key: str) -> Any | None: ...
      async def set(self, key: str, value: Any) -> None: ...
      # Lock protects dict mutation; reads are lock-free on CPython dict (GIL)
  ```
- **TTLs:** market data 5 min (during trading hours), 1h (off-hours, detected via `datetime`); news 15 min.

**Tier 2 — yfinance's own on-disk cache.**
- yfinance supports `yf.set_tz_cache_location(...)` and pickles request data. Point it at `.alphaswarm/cache/yfinance/`.
- This handles network failures gracefully (stale-is-better-than-nothing).

**httpx AsyncClient lifecycle:**
- Single shared `httpx.AsyncClient` instance created in FastAPI `lifespan`, attached as `app.state.http_client`.
- Passed to `NewsIngestor` via constructor, not imported globally.
- Closed in the lifespan teardown BEFORE `graph_manager.close()` (same teardown order pattern already used).
- Timeouts: `httpx.Timeout(connect=2.0, read=5.0, total=10.0)` — fail fast, let ingestor return empty slice rather than stalling the sim.
- Retries: 2 attempts with exponential backoff; mirror `OllamaClient` retry style.

**yfinance is synchronous:**
- Wrap calls in `asyncio.to_thread(yf.Ticker(symbol).history, ...)`.
- This respects Hard Constraint 1 (no blocking I/O on main loop).
- Parallelism bounded by a new semaphore `ingestion_concurrency` (default 4) to avoid rate-limiting yfinance's unofficial endpoints.

**Confidence:** HIGH for httpx + asyncio.to_thread pattern. MEDIUM on yfinance rate limits — may need adjustment after integration testing.

---

### Q5. Where does the advisory step fit in the simulation lifecycle?

**Recommendation:** New **phase extension** inside the existing simulation task, NOT a separate command.

**Flow:**

```
SEEDING → INGESTING (NEW) → ROUND_1 → ROUND_2 → ROUND_3 → ADVISING (NEW) → COMPLETE
```

**Why inline, not separate command:**
- The orchestrator LLM is already hot at the end of the pipeline (or easy to re-load; `OllamaModelManager` handles this). Cost of a second CLI round-trip is wasted model load time (~30s for 70B cold).
- UX: user wants "start sim with portfolio → get advisory" as one action, not two.
- State coherence: swarm results exist in-memory (`SimulationResult`); persisting and re-reading them just to feed the orchestrator is busywork.
- Broadcaster already emits phase transitions; `ADVISING` is a free WebSocket signal to the UI to show a spinner.

**Implementation shape:**

```python
# alphaswarm/advisory/pipeline.py
class AdvisoryPipeline:
    async def generate(
        self,
        sim_result: SimulationResult,          # from run_simulation
        portfolio: PortfolioSnapshot,          # from HoldingsStore
        context_packet: ContextPacket,         # pass-through for full context
    ) -> AdvisoryReport:
        await self._state_store.set_phase(SimulationPhase.ADVISING)
        await self._model_manager.load_model(self._settings.ollama.orchestrator_model_alias)
        try:
            advisory_md = await self._synthesize(sim_result, portfolio, context_packet)
            await write_advisory(sim_result.cycle_id, advisory_md)
            return AdvisoryReport(cycle_id=sim_result.cycle_id, markdown=advisory_md)
        finally:
            await self._model_manager.unload_model(self._settings.ollama.orchestrator_model_alias)
```

**Integration point:** `SimulationManager._run` (one new call), `simulation.py` unchanged at its core. The advisory step is in `SimulationManager`, not `simulation.py`, because `simulation.py` is the swarm-pure module and must not import holdings.

**Alternative considered and rejected:** Separate `alphaswarm advise <cycle_id>` CLI command that reads `SimulationResult` from Neo4j. Rejected because (a) `SimulationResult` isn't fully persisted today, (b) doubles orchestrator load time, (c) creates stale-advisory risk when portfolio changes mid-flight.

---

### Q6. Build order + data flow

**Dependencies drive order.** Each step ships independently; tests at each layer.

```
Phase 6.1  Holdings ingestion (CSV → PortfolioSnapshot)
           └── pure dataclass; no integration yet
Phase 6.2  Market data ingestion (yfinance + cache + async wrapper)
           └── standalone; unit tests with mock yfinance
Phase 6.3  News ingestion (httpx async + cache)
           └── standalone; unit tests with httpx MockTransport
Phase 6.4  Context packet assembly (per-archetype slicing)
           └── depends on 6.2, 6.3; pure function of ingested data
Phase 6.5  Swarm prompt integration (worker templates accept packet slices)
           └── depends on 6.4; regression: existing sim still passes with empty packet
Phase 6.6  Holdings isolation enforcement (importlinter + canary test + log-grep CI)
           └── depends on 6.1, 6.5; MUST land before advisory step
Phase 6.7  Advisory pipeline (orchestrator synthesis)
           └── depends on 6.1, 6.5, 6.6; new SimulationPhase.ADVISING
Phase 6.8  Advisory web UI (route + Vue panel)
           └── depends on 6.7; mirrors Phase 36 report pattern
Phase 6.9  E2E wire-up + UAT
           └── all phases; full CSV → advisory.md run against real holdings
```

**Critical gate:** **Phase 6.6 lands before 6.7.** You want the isolation enforcement in place the moment holdings and swarm touch the same process, not after.

**Data flow per cycle (with v6.0):**

```
User uploads holdings.csv
        ↓
POST /api/holdings/upload
        ↓
HoldingsLoader (asyncio.to_thread(pandas.read_csv))
        ↓
PortfolioSnapshot ───► HoldingsStore (app.state, in-memory only)
                              │
                              │  (read once, at advisory step)
                              ▼
User submits seed rumor
        ↓
POST /api/simulation/start
        ↓
SimulationManager.start(seed)
        ↓
SimulationManager._run:
    1. ContextAssembler.build(seed):
          ├── parse_entities(seed) [re-uses orchestrator prompt]
          ├── MarketDataIngestor.fetch(tickers)  ◄──► cache, yfinance
          ├── NewsIngestor.fetch(entities)       ◄──► cache, NewsAPI
          └── pack_by_archetype() → ContextPacket
    2. run_simulation(rumor, context_packet)
          └── workers see ONLY rumor + their archetype's slice
    3. if holdings_store.has_portfolio:
          AdvisoryPipeline.generate(sim_result, portfolio, context_packet)
          └── orchestrator sees: portfolio + final consensus + context
              (swarm outputs, NOT individual agent holdings awareness)
          → advisory.md written to reports/{cycle_id}/advisory.md
    4. COMPLETE phase set
        ↓
WebSocket snapshot sent (5 Hz) → frontend AdvisoryPanel polls GET /api/advisory/{cycle_id}
```

---

## 5. Recommended Project Structure

```
src/alphaswarm/
├── advisory/                      # NEW — holdings-aware synthesis
│   ├── __init__.py
│   ├── pipeline.py                # AdvisoryPipeline (orchestrator LLM call)
│   ├── prompts.py                 # system prompt + JSON schema
│   └── types.py                   # AdvisoryReport, Recommendation
├── holdings/                      # NEW — isolated; forbidden import target
│   ├── __init__.py
│   ├── loader.py                  # CSV → PortfolioSnapshot
│   ├── store.py                   # HoldingsStore (on AppState)
│   └── types.py                   # Holding, PortfolioSnapshot (frozen)
├── ingestion/                     # NEW — external data fetch
│   ├── __init__.py
│   ├── cache.py                   # AsyncTTLCache
│   ├── market_data.py             # yfinance wrapper
│   ├── news.py                    # httpx NewsAPI/RSS wrapper
│   ├── packet_builder.py          # ContextPacket assembly + archetype slicing
│   └── types.py                   # ContextPacket, MarketSlice, NewsSlice
├── app.py                         # MODIFIED: add holdings_store, http_client, ingestors
├── simulation.py                  # MODIFIED: accept optional context_packet
├── worker.py                      # MODIFIED: templates use packet slice if present
├── templates/
│   ├── worker_*.j2                # MODIFIED: reference {{ context_slice }}
│   └── advisory.j2                # NEW
└── web/
    ├── app.py                     # MODIFIED: wire new routers + http_client lifecycle
    ├── routes/
    │   ├── holdings.py            # NEW
    │   └── advisory.py            # NEW
    └── simulation_manager.py      # MODIFIED: ingestion → sim → advisory chain

frontend/src/components/
├── AdvisoryPanel.vue              # NEW — mirrors ReportViewer.vue
└── HoldingsUploader.vue           # NEW — drag-drop CSV

tests/
├── invariants/
│   └── test_holdings_isolation.py # NEW — canary ticker + cost-basis tripwires
├── ingestion/
│   ├── test_market_data.py
│   ├── test_news.py
│   └── test_packet_builder.py
├── holdings/
│   └── test_loader.py
└── advisory/
    └── test_pipeline.py
```

### Structure Rationale

- **Separate top-level packages** (`ingestion/`, `holdings/`, `advisory/`) rather than nesting under `simulation/` — mirrors the existing flat layout, makes import boundaries obvious, and makes the importlinter contract dead simple to write.
- **`ingestion/` NOT inside `web/`** — it's consumed by `SimulationManager` (in `web/`) but conceptually the ingestion layer is a core service, not web-specific. Keeps it CLI-usable too.
- **`advisory/` separate from `report/`** — `report.py` (Phase 15) is swarm-only post-mortem; advisory is portfolio-aware synthesis. Different inputs, different prompts, different audiences. Do not overload `report.py`.
- **`holdings/` flat at top level** — intentional visibility: anyone opening the src tree sees "oh, there's a holdings module," and the importlinter contract keeps its reach scoped.

---

## 6. Architectural Patterns

### Pattern 1: Ingestion → Packet → Swarm seam

**What:** Single immutable `ContextPacket` dataclass crosses from ingestion into the swarm. Workers receive a slice, not the whole packet.

**When:** Whenever external data feeds an agent population with differentiated needs.

**Trade-offs:**
- (+) Swarm has zero network I/O; deterministic given a packet.
- (+) Easy to snapshot packets for regression tests.
- (−) Adds a serialization boundary; packet schema must evolve carefully.

**Example:**
```python
@dataclass(frozen=True)
class MarketSlice:
    ticker: str
    price: float
    pct_change_1d: float
    pct_change_30d: float
    volume_vs_avg: float  # 0.5 = half avg, 2.0 = double
    pe_ratio: float | None

@dataclass(frozen=True)
class NewsSlice:
    entity: str
    headlines: tuple[str, ...]  # top N, already ranked

@dataclass(frozen=True)
class ContextPacket:
    cycle_id: str
    as_of: datetime
    entities: tuple[str, ...]
    market: tuple[MarketSlice, ...]
    news: tuple[NewsSlice, ...]

    def slice_for(self, bracket: BracketType) -> ArchetypeSlice:
        """Quants → fundamentals-heavy; Degens → price + social; Macro → news-heavy."""
        ...
```

### Pattern 2: Orchestrator re-use after consensus

**What:** Hot-reload orchestrator model at the end of the pipeline, once, for synthesis.

**When:** You need a strong LLM for a single follow-up inference after worker swarm completes.

**Trade-offs:**
- (+) Matches existing `inject_seed` model-load discipline.
- (−) ~30s cold load added to advisory step if worker was loaded in between; acceptable.

### Pattern 3: Defense-in-depth information isolation

**What:** Architectural (import contract) + structural (type signatures) + behavioral (canary tests) barriers, all three.

**When:** A dataset must not leak into an LLM prompt.

**Trade-offs:**
- (+) No single point of failure; a refactor can't silently break isolation.
- (−) Slight test overhead; importlinter adds ~1s to CI.

### Pattern 4: Phase extension, not pipeline rewrite

**What:** New `SimulationPhase` enum values (`INGESTING`, `ADVISING`) gate UI state; existing state machine unchanged internally.

**When:** Adding a step to an established state machine.

**Trade-offs:**
- (+) Frontend ControlBar.vue, broadcaster, replay all keep working.
- (−) Phase enum grows; watch for off-by-one in any phase-comparison code (search for `if phase ==`).

---

## 7. Data Flow

### Start-simulation flow (with v6.0)

```
POST /api/simulation/start
          ↓
    SimulationManager.start(seed)
          ↓ acquire lock, create_task
    SimulationManager._run(seed)
          ├─► state_store.set_phase(INGESTING)
          ├─► ContextAssembler.build(seed)
          │      ├─► parse entities via orchestrator (existing path)
          │      ├─► MarketDataIngestor.fetch()   [cache-first]
          │      ├─► NewsIngestor.fetch()         [cache-first]
          │      └─► pack_by_archetype() → ContextPacket
          ├─► state_store.set_phase(SEEDING)
          ├─► run_simulation(rumor, context_packet)
          │      └─► Round 1 → 2 → 3 (workers see slice only)
          ├─► IF holdings_store.has_portfolio:
          │      state_store.set_phase(ADVISING)
          │      AdvisoryPipeline.generate(result, portfolio, packet)
          │             └─► orchestrator LLM → advisory.md
          └─► state_store.set_phase(COMPLETE)
                 (source of truth in simulation.py line 1109 unchanged)
```

### State management

- **Holdings:** `app.state.holdings_store` (singleton). Clear on shutdown. Never serialized.
- **Ingestion caches:** `app.state.market_cache`, `app.state.news_cache` (AsyncTTLCache). Bounded by TTL, not size.
- **ContextPacket:** lives on `SimulationResult` only for the advisory step; discarded after.
- **AdvisoryReport:** written to `reports/{cycle_id}/advisory.md` (same dir as existing reports); `app.state.advisory_task` mirrors `app.state.report_task` for in-flight detection.

---

## 8. Scaling Considerations

Local single-operator, so "scale" means concurrent requests per sim cycle, not users.

| Concern | Small (single ticker) | Medium (10 tickers + news) | Large (50+ tickers) |
|---|---|---|---|
| yfinance fetch | <500ms cached, ~2s cold | 3-6s cold, <1s cached | 10-20s cold; chunk with gather |
| NewsAPI calls | 1 call | 5-10 calls, bounded semaphore | Rate-limited; use RSS fallback per entity |
| Context packet size | <2KB | <10KB | <30KB (still fits easily in 32K context) |
| Advisory prompt size | 4-8K tokens | 10-15K tokens | 20-25K tokens (approaching orchestrator context limit) |

### Scaling priorities

1. **First bottleneck — cold yfinance fetch.** Mitigation: warm cache on app startup for common tickers, aggressive TTL, parallel `asyncio.gather` bounded at 4.
2. **Second bottleneck — advisory prompt length.** Mitigation: trim context packet to top-N entities by relevance (already a field on `SeedEntity`); summarize per-ticker news into one-sentence headline digest before injection.
3. **Third bottleneck — NewsAPI rate limits.** Mitigation: RSS fallback, per-entity 15-min cache.

Don't pre-optimize. The typical seed rumor touches 2–5 entities; v6.0's ingestion latency will be bounded by the slowest cold yfinance call (~2–3s), negligible vs the 3-round cascade.

---

## 9. Anti-Patterns

### Anti-Pattern 1: Holdings in Neo4j

**What people do:** Persist `PortfolioSnapshot` as `User` or `Portfolio` nodes for "replay and audit."
**Why it's wrong:** (a) Violates the isolation invariant — now any Cypher query over the graph can surface holdings; the ReACT report tool and interview engine both run Cypher. (b) Tangles simulation reproducibility with personal finance data. (c) Neo4j is not a secure store — no encryption at rest by default.
**Do this instead:** In-memory only. If audit needed, log `advisory_generated` with a portfolio content hash (not values).

### Anti-Pattern 2: Orchestrator calls APIs

**What people do:** "Orchestrator is smart, let it call yfinance/NewsAPI directly via function-calling during advisory."
**Why it's wrong:** Breaks the locked Option A principle (orchestrator is synthesis-only). Introduces network variance into an LLM inference step, wrecking reproducibility and adding new failure modes inside a loaded-model window.
**Do this instead:** All fetches happen in the ingestion layer, before the LLM ever sees data.

### Anti-Pattern 3: Context packet as graph node

**What people do:** `CREATE (cp:ContextPacket {market_data: $json_blob, news: $json_blob})`.
**Why it's wrong:** Bloats Neo4j (price histories are huge), slows queries, muddles "what the swarm reasoned about" with "what the market actually was."
**Do this instead:** Persist `ContextSnapshot {tickers, as_of, source_hash}` only — the hash lets you detect drift without storing data.

### Anti-Pattern 4: Shared module between holdings and swarm

**What people do:** Create `alphaswarm/portfolio_context.py` that both holdings and worker prompts import for "shared types."
**Why it's wrong:** Single shared module is the leakage vector. A refactor adds a field; workers silently start seeing holdings.
**Do this instead:** Two separate type hierarchies (`holdings/types.py`, `ingestion/types.py`) with zero shared parent. Accept the duplication.

### Anti-Pattern 5: Ingestion inside worker call

**What people do:** Worker prompt includes `{{ fetch_price(ticker) }}` as a tool call.
**Why it's wrong:** 100 workers × 3 rounds × N entities = rate-limit apocalypse, and defeats the context-packet pattern's whole purpose.
**Do this instead:** Fetch once per cycle, fan out the packet slice to all workers.

---

## 10. Integration Points

### External Services (new in v6.0)

| Service | Integration Pattern | Notes |
|---|---|---|
| yfinance | `asyncio.to_thread(yf.Ticker.history)` + AsyncTTLCache + on-disk cache | Unofficial API, rate limits undocumented; degrade to stale cache on failure |
| NewsAPI (or RSS) | `httpx.AsyncClient` + AsyncTTLCache | NewsAPI has 100 req/day free tier; RSS per-entity is lower friction for local-first |
| SEC EDGAR (stretch) | `httpx.AsyncClient` against `data.sec.gov` with User-Agent header | Deferred to v7.0 per PROJECT.md |

### Internal Boundaries (v6.0 additions)

| Boundary | Communication | Enforcement |
|---|---|---|
| `ingestion` ↔ `simulation` | `ContextPacket` dataclass (one-way, swarm is read-only consumer) | Type signature; packet is `frozen=True` |
| `holdings` ↔ `advisory` | `PortfolioSnapshot` dataclass (one-way) | Only `advisory` imports `holdings` |
| `holdings` ↔ everything else | **FORBIDDEN** | importlinter contract + CI log-grep + runtime canary test |
| `simulation` ↔ `advisory` | `SimulationResult` dataclass (one-way, advisory consumes) | `advisory` imports `simulation`; `simulation` must NOT import `advisory` |
| `web.SimulationManager` ↔ `ingestion` + `advisory` | Direct call inside `_run` | Already the integration nexus; natural home |

### Existing systems unchanged

- **`ResourceGovernor`:** no change. Ingestion inherits the same event loop; if ingestion concurrency exceeds 4, add a separate `ingestion_semaphore` that does NOT share the governor's TokenPool (ingestion is I/O-bound, not memory-bound like LLM inference).
- **`GraphStateManager`:** +1 new method `create_context_snapshot(cycle_id, tickers, source_hash)`. Everything else unchanged.
- **`WriteBuffer`:** no change. Advisory is not an episode.
- **`Broadcaster`:** no change. New phases propagate for free via `state_store.set_phase()`.
- **`ReplayManager`:** no change. Replay surfaces historical cycle state only; does not re-run ingestion or advisory.

---

## 11. Critical Quality Gates (restating for clarity)

Before merging v6.0:

1. `importlinter` contract `holdings-isolation` passes in CI.
2. Canary test `test_holdings_isolation.py` with `HOLDINGS_CANARY_TICKER_ZZZ` passes.
3. CI step `scripts/check-holdings-leakage.sh` (grep over templates + prompt strings) returns zero matches.
4. Existing 193+ tests still pass (no swarm regressions).
5. Advisory step can be fully disabled via `settings.advisory.enabled=False` — the simulator must continue to function as a pure rumor engine.

---

## Sources

- Existing codebase inspection: `simulation.py`, `web/simulation_manager.py`, `web/app.py`, `app.py`, `seed.py`, `report.py`, `types.py`, `config.py` — HIGH confidence
- PROJECT.md (v6.0 requirements, Option A architecture lock) — HIGH confidence
- CLAUDE.md (hard constraints: 100% async, no blocking I/O, memory safety) — HIGH confidence
- yfinance is a synchronous library (pandas-based) — HIGH confidence (well-established)
- httpx AsyncClient lifecycle pattern — HIGH confidence (FastAPI standard practice)
- importlinter for architectural contracts — MEDIUM confidence on exact toml syntax; verify against current importlinter docs during Phase 6.6 implementation

---
*Architecture research for: AlphaSwarm v6.0 Data Enrichment & Personalized Advisory*
*Researched: 2026-04-18*
