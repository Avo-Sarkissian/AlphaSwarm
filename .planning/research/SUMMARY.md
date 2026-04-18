# Research Summary — v6.0 Data Enrichment & Personalized Advisory

**Project:** AlphaSwarm
**Domain:** Local-first multi-agent financial simulation with real-data ingestion and holdings-aware advisory synthesis
**Researched:** 2026-04-18
**Confidence:** HIGH (architecture, stack integration); MEDIUM (archetype tailoring specifics, news dedup tuning)

---

## Executive Summary

AlphaSwarm v6.0 transforms the existing 3-round swarm engine into an informed advisory system by adding three new subsystems — ingestion, holdings, and advisory — without touching the proven simulation core. The fundamental design principle (Option A, locked) is strict information isolation: the ingestion layer fetches public market data and news, packages it into typed `ContextPacket` dataclasses, and feeds those packets into swarm prompts; the orchestrator receives the swarm's consensus output plus the user's in-memory holdings and synthesizes a qualitative advisory report. Holdings never cross into any worker prompt at any round.

The recommended implementation strategy keeps additions purely additive: new top-level packages (`alphaswarm/ingestion/`, `alphaswarm/holdings/`, `alphaswarm/advisory/`) that bolt onto the existing `SimulationManager._run` flow with two new `SimulationPhase` enum values (`INGESTING`, `ADVISING`) and minimal surface-area modifications to `simulation.py` and `worker.py`. The critical gate is that holdings isolation enforcement — module-level import contracts, a frozen typed boundary, and a runtime canary test — must land before any advisory code is written. Every subsequent phase inherits that invariant.

The highest risks are: (1) yfinance rate-limiting causing mid-simulation 429 failures if caching and a serialized fetch worker are not shipped alongside the first fetch integration; (2) the orchestrator LLM fabricating portfolio positions not in the user's CSV if grounding constraints and a post-synthesis ticker validator are not enforced; and (3) context packet bloat re-triggering the ResourceGovernor deadlock documented in `bug_governor_deadlock.md` if token budgets are not enforced at the packet assembly stage. All three are solvable with established patterns and are non-negotiable acceptance criteria for their respective phases.

---

## Key Findings

### Stack Additions

The existing stack (Python 3.11+, uv, ollama-python, async Neo4j, FastAPI + httpx, Vue 3 + D3, pydantic, structlog, pytest-asyncio) is unchanged. v6.0 adds exactly four core dependencies.

**Core new dependencies:**

| Package | Version | Purpose | Notes |
|---------|---------|---------|-------|
| `yfinance` | 1.3.0 | Market data (price/volume/fundamentals) | REST methods are synchronous — wrap with `asyncio.to_thread`; use `yf.download()` for bulk to avoid per-ticker 429s |
| `pandas` | 3.0.2 | CSV parsing + technical indicator computation (RSI, SMA) | Requires Python >=3.11 (matches our runtime); DataFrames never leave the ingestion layer |
| `aiocache` | 0.12.3 | Async TTL cache for ingested data | Architecture prefers a 30-line hand-rolled `AsyncTTLCache` (dict + asyncio.Lock) to keep deps minimal; aiocache is an acceptable alternative |
| `feedparser` | 6.0.12 | RSS/Atom parsing for news fallback | Sync/fast (<50ms); fetch bytes via existing `httpx.AsyncClient`, pass to `feedparser.parse()` |

**Conditional additions:**
- `tenacity` (9.x) — retry/backoff for yfinance + news fetches; mirrors existing Ollama retry style
- `aiofiles` (24.x) — already present from Phase 36; reuse for holdings CSV async read
- `mistune` (3.2.0) — only if server-side markdown export is required; client-side already has marked + DOMPurify
- `jinja2` (3.1.x) — transitive FastAPI dep; promote to explicit if advisory templates gain conditional sections

**Hard avoids:**
- `newsapi-python` — sync `requests`-based; roll a ~50-line async client over existing `httpx.AsyncClient` instead
- Calling `yf.Ticker(...).history()` directly from an async function — blocks the event loop
- `requests` for any new code — httpx is already in the stack

Install command: `uv add yfinance==1.3.0 pandas==3.0.2 aiocache==0.12.3 feedparser==6.0.12 tenacity`

---

### Feature Table Stakes (P1 Must-Ship)

| ID | Feature | Isolation Boundary |
|----|---------|-------------------|
| TS-01 | Holdings CSV loader — Fidelity + Schwab + generic adapters; broker fingerprint dispatch | INGEST + ORCH-ONLY |
| TS-02 | Pydantic holdings validation with row-level error messages | INGEST |
| TS-03 | In-memory-only invariant — holdings never reach Neo4j or disk | ORCH-ONLY |
| TS-04 | yfinance per-entity fetch (price, volume, 52w range, fundamentals via `fast_info`) | INGEST → SWARM-SAFE |
| TS-05 | Cache + rate limiting — non-negotiable; ship with first fetch, never as follow-up | INGEST |
| TS-06 | News headline fetch (RSS primary, NewsAPI optional enrichment behind feature flag) | INGEST → SWARM-SAFE |
| TS-07 | `ContextPacket` pydantic model (`extra="forbid"`, frozen, zero holdings fields) — **the critical seam** | SWARM-SAFE |
| TS-08 | Context packet injection into Round 1 prompt; Rounds 2-3 unmodified for v6.0 | SWARM-SAFE |
| TS-09 | Orchestrator synthesis: holdings + consensus output → advisory markdown | ORCH-ONLY |
| TS-10 | SEC-style plain-English disclaimer block (non-optional boilerplate) | ORCH-ONLY |
| TS-11 | Advisory report in web UI — new route + Vue panel; reuse Phase 36 ReportViewer pattern | UI |
| TS-12 | Information-isolation log-grep + canary test in CI | TEST |
| DIFF-02 | Cited-position advisory referencing specific agent rationales (RationaleEpisode nodes exist; nearly free) | ORCH-ONLY |

**Should-Have (P2 — same milestone if time permits):**
- DIFF-01 Per-archetype context tailoring (start with Quants-get-fundamentals / Degens-get-volume split; expand to all 10 brackets)
- DIFF-03 Holdings-weighted consensus view in advisory
- DIFF-04 Risk-disclosure block surfacing dissent ratios
- DIFF-07 Fundamentals snapshot in context packet (cheap after TS-04 works)

**Defer to v7.0+:** Archetype-data visualization, replay-compatible advisory, SEC EDGAR, social sentiment, short positions/options in holdings schema, encrypted holdings persistence.

**Never ship:** Holdings visible to any worker agent; holdings persisted to Neo4j; LLM-generated price targets or trade orders; real-time streaming market data in MVP.

---

### Architecture Decisions

v6.0 is a bolt-on, not a rewrite. Three new top-level packages hang off the existing `SimulationManager._run` in a sequential chain:

```
SEEDING → INGESTING (NEW) → ROUND_1 → ROUND_2 → ROUND_3 → ADVISING (NEW) → COMPLETE
```

`ContextAssembler.build(seed)` → `run_simulation(rumor, context_packet)` → `AdvisoryPipeline.generate(sim_result, portfolio, packet)`

The swarm core gains a single optional `context_packet` parameter; it is otherwise untouched. Holdings never enter that call tree.

**Major new components:**

| Component | Package | Responsibility |
|-----------|---------|---------------|
| `MarketDataIngestor` | `ingestion/market_data.py` | `asyncio.to_thread` yfinance wrapper; 4-worker bounded semaphore; AsyncTTLCache; `tenacity` backoff |
| `NewsIngestor` | `ingestion/news.py` | httpx async; RSS primary + NewsAPI optional; dedup + freshness filter; per-source cap |
| `ContextAssembler` | `ingestion/packet_builder.py` | Pure function; `slice_for(bracket)` projection (filter, not expand); token budget enforcement |
| `HoldingsStore` | `holdings/store.py` | In-memory singleton on `app.state`; cleared on shutdown; never serialized |
| `HoldingsLoader` | `holdings/loader.py` | Broker adapter pattern; pandas inside `asyncio.to_thread`; SHA256 account-number hashing |
| `AdvisoryPipeline` | `advisory/pipeline.py` | Orchestrator LLM at `temperature=0.1`; closed-universe grounding; post-synthesis ticker validator |
| `AdvisoryPanel.vue` | `frontend/src/components/` | Mirrors ReportViewer.vue; marked + DOMPurify; persistent disclaimer banner |
| `HoldingsUploader.vue` | `frontend/src/components/` | Drag-drop CSV; post-parse preview table; "Confirm" gate before HoldingsStore commits |

**Defense-in-depth isolation (all three required, all in place before Phase 41):**
1. `importlinter` contract — `holdings` is a `forbidden_module` for simulation/worker/ingestion/seed; fails CI
2. Type system — `ContextPacket` has no holdings fields (`extra="forbid"`); `AdvisoryPipeline.generate` is the only function accepting both `SimulationResult` and `PortfolioSnapshot`
3. Runtime canary test — sentinel ticker `HOLDINGS_CANARY_TICKER_ZZZ` asserts it never appears in any captured worker prompt or log

**Existing systems unchanged:** ResourceGovernor (ingestion uses a separate `ingestion_semaphore` — I/O bound, not memory bound), GraphStateManager (+1 method: `create_context_snapshot`), WriteBuffer, Broadcaster, ReplayManager.

**Advisory report structure (6 sections):** Portfolio Impact Summary → Position-Level Recommendations (cited, qualitative only) → Positions Outside Scope → Risk Disclosures → Methodology Disclosure (SEC-style) → Appendix. Never: price targets, "Buy/Sell" language, brokerage integration.

---

### Critical Pitfalls

**1. Holdings leakage into swarm prompts — CRITICAL (Pitfall 1)**
`ContextPacket` must use `extra="forbid"` with zero holdings fields. importlinter contract must be in place. Canary test must exist before advisory code is written. Recovery if leaked: git history audit + log purge + fixture rotation.

**2. yfinance 429 / IP block mid-simulation — CRITICAL (Pitfall 4)**
Naive per-ticker fetch will trigger Yahoo's anti-bot system within one demo run. Use `yf.download(tickers_list, group_by="ticker")` for bulk OHLCV (10-20x fewer requests). Ship cache + serialized `MarketDataFetcher` + `tenacity` backoff with the first fetch integration. Graceful degradation: packet carries `{data: null, staleness: "fetch_failed"}` rather than crashing.

**3. Advisory report hallucinating positions — CRITICAL (Pitfall 3)**
Closed-universe constraint in synthesis prompt (`"You may ONLY reference tickers from: {ticker_allowlist}"`). Post-synthesis validator rejects any ticker not in `holdings_tickers ∪ swarm_entities`. Empty holdings → "No actionable signal" (never fabricated). `temperature=0.1` for advisory synthesis.

**4. Context packet bloat re-triggering governor deadlock — HIGH (Pitfall 6)**
`MAX_WORKER_CONTEXT_TOKENS = 2000` enforced at packet assembly. Archetype projections filter (reduce), never concatenate (expand). `count_tokens(prompt) <= budget` assertion in every `build_agent_prompt()` test. Scale smoke test at 100 agents × full packet before shipping swarm injection.

**5. CSV schema drift across brokers — MEDIUM (Pitfall 8)**
Ship broker adapter pattern from day one; never hardcode Schwab column positions. Golden-file fixtures per broker in CI. Robinhood: "generic column-mapping UI, map manually" or explicit deferral.

**6. Holdings in structlog output — HIGH (Pitfall 11)**
Redaction processor installed globally before any holdings code. `Portfolio.__repr__` returns `"<Portfolio: N holdings>"` only. NewsAPI key as `SecretStr` in pydantic-settings.

**7. Test suite requiring internet — MEDIUM (Pitfall 10)**
`pytest-socket` in CI from Phase 37 day one. `MarketDataProvider` / `NewsProvider` Protocol definitions allow `FakeProvider` test implementations.

---

## Implications for Roadmap

### Phase Numbering Reconciliation

User spec: **7 phases, numbered 37–43**.
Architecture agent: 9-phase plan (6.1–6.9).
Pitfalls agent: 7-phase plan (phases 37/38/39/40/42/43 with a "38.5/39.5" note for news).

**Resolution — align to 37–43 (7 phases):**
- Architecture's phases 6.2 (market data) + 6.3 (news) → **Phase 38** (same cache infra, co-located)
- Architecture's phase 6.6 (isolation enforcement) → **Phase 37** (must precede all ingestion code; no benefit deferring)
- Architecture's phase 6.9 (E2E wire-up) → **Phase 43** (merged with UAT)
- Pitfalls' "Phase 38.5/39.5" for news → task within Phase 38 (not a separate phase)

---

### Phase 37 — Isolation Foundation & Provider Scaffolding

**Rationale:** Every subsequent phase inherits isolation contracts, provider protocols, PII redaction, and network-blocking CI. Security retrofit mid-milestone is expensive. This is the architecture agent's 6.1 + 6.6 collapsed — isolation is cheaper before ingestion code exists.

**Delivers:**
- `alphaswarm/holdings/types.py` — `Holding`, `PortfolioSnapshot` frozen dataclasses (no logic, no I/O)
- `alphaswarm/ingestion/types.py` — `ContextPacket`, `MarketSlice`, `NewsSlice` frozen dataclasses with `extra="forbid"`
- `importlinter` contract in `pyproject.toml` forbidding `holdings` imports from simulation/worker/ingestion/seed/parsing
- structlog PII redaction processor (global; installed before holdings code exists)
- `MarketDataProvider` + `NewsProvider` Protocol definitions (no implementations yet)
- `pytest-socket` in CI blocking outbound network calls
- Canary test scaffold (`test_holdings_isolation.py` with sentinel fixtures; trivially passes until Phase 41)

**Features:** TS-03, TS-12 (scaffolded), Pitfalls 1, 2, 10, 11
**Research flag:** Standard patterns — no phase-level research needed

---

### Phase 38 — Market Data + News Ingestion

**Rationale:** Market data and news share the same cache infrastructure, async wrapper patterns, and provider abstraction. Building them together avoids a second cache-layer setup and gives Phase 40 a complete data surface. The pitfalls agent's "Phase 38.5" for news is a task within this phase.

**Delivers:**
- `alphaswarm/ingestion/cache.py` — `AsyncTTLCache`; market-hours-aware TTL; integration hook with `ResourceGovernor`
- `alphaswarm/ingestion/market_data.py` — `YFinanceProvider`; `asyncio.to_thread` wrapper; 4-worker semaphore; `yf.download()` bulk; `tenacity` backoff on 429; graceful degradation; staleness metadata on every field
- `alphaswarm/ingestion/news.py` — `NewsAPIProvider` + `RSSProvider`; httpx async; freshness window (72h default); content-hash dedup; per-source cap (2 items/source/entity)
- Unit tests using `FakeMarketDataProvider` / `FakeNewsProvider`; VCR cassettes for provider contracts

**Acceptance criteria:** Cache hit-rate telemetry; rate limiter unit test; graceful-degradation test; staleness metadata present; 429 does not crash simulation; `pytest-socket` gates pass.

**Features:** TS-04, TS-05, TS-06, Pitfalls 4, 5, 7, 9, 10
**Research flag:** EMPIRICAL — measure actual 429 threshold under 100-ticker load during Phase 38 validation; tune concurrency semaphore from results (start 4, may drop to 2)

---

### Phase 39 — Holdings CSV Ingestion

**Rationale:** Independent of market data (no shared code path). Can develop in parallel with Phase 38; both must complete before Phase 40. Explicitly gates: holdings never touch Neo4j.

**Delivers:**
- `alphaswarm/holdings/loader.py` — broker adapter pattern (Schwab, Fidelity, generic); fingerprint dispatch; pandas in `asyncio.to_thread`; BOM stripping; SHA256 account-number hashing
- `alphaswarm/holdings/store.py` — `HoldingsStore` on `app.state`; in-memory; cleared on shutdown
- `web/routes/holdings.py` — `POST /api/holdings/upload`, `GET /api/holdings/status`
- `HoldingsUploader.vue` — drag-drop upload; post-parse preview table; "Confirm" gate
- Pydantic validation with row-level error messages
- Golden-file fixtures: Schwab + Fidelity + generic mapping; Robinhood documented as "manual column mapping"
- Neo4j schema assertion: no `:Holding` or `:Position` labels ever exist

**Acceptance criteria:** Unknown broker → column-mapping UI (not crash); account numbers never stored raw; canary test still passes; Neo4j schema test passes.

**Features:** TS-01, TS-02, TS-03, Pitfall 8
**Research flag:** DECISION NEEDED before planning — Robinhood adapter scope: ship as "manual column-mapping UI" or explicitly defer with documentation?

---

### Phase 40 — Context Packet Assembly & Swarm Injection

**Rationale:** Bridges ingestion output to the swarm. Depends on Phases 38 and 39. The context packet is the trust boundary — token budget enforcement and archetype projection logic live here.

**Delivers:**
- `alphaswarm/ingestion/packet_builder.py` — `ContextAssembler.build(seed)`; `slice_for(bracket) -> ArchetypeSlice` (filter not expand); initial two-way split (Quants: fundamentals+technicals; Degens: volume ratio+52w+headline count)
- `MAX_WORKER_CONTEXT_TOKENS = 2000`; `count_tokens(prompt) <= budget` assertion in every `build_agent_prompt()` unit test
- `simulation.py` modification: optional `context_packet` param (5 lines, backward-compatible)
- `worker.py` + `templates/worker_*.j2` modifications: reference `{{ context_slice }}` if present; existing behavior unchanged if packet is None
- `SimulationPhase.INGESTING` emitted via `state_store.set_phase()` — UI picks up for free via broadcaster
- Regression test: simulation with None packet still produces correct output
- Scale smoke test: 100 agents × full packet; confirm no ResourceGovernor pause

**Acceptance criteria:** Token budget assertion passes at 100 agents; no swarm regression; `INGESTING` phase visible in UI; canary test still passes with packet injection active.

**Features:** TS-07, TS-08, DIFF-01 (simple version), DIFF-07, Pitfall 6
**Research flag:** EMPIRICAL — measure `qwen3.5:7b` quality vs. context size before locking `MAX_WORKER_CONTEXT_TOKENS`; calibrate during Phase 40 validation

---

### Phase 41 — Advisory Pipeline (Orchestrator Synthesis)

**Rationale:** The milestone's core deliverable. Depends on all prior phases. Introduces the only function in the codebase that receives both holdings and swarm output simultaneously — Phase 37's isolation enforcement makes this the controlled join point.

**Delivers:**
- `alphaswarm/advisory/pipeline.py` — `AdvisoryPipeline.generate(sim_result, portfolio, context_packet)`; orchestrator LLM via existing `OllamaModelManager`; `temperature=0.1`, `top_p=0.8`
- `alphaswarm/advisory/prompts.py` — Jinja templates with closed-universe constraint; system/instruction/user section separation (guards against prompt injection)
- Post-synthesis validator: extract uppercase tickers via regex; reject any not in `holdings_tickers ∪ swarm_entities`; regenerate up to 2 times; on persistent failure: "Advisory validation failed: fabricated ticker X"
- Explicit abstention: empty holdings or weak-signal consensus → "No actionable signal" (not fabricated)
- Advisory written to `reports/{cycle_id}/advisory.md` via aiofiles
- `SimulationPhase.ADVISING` emitted
- `SimulationManager._run` modification: invoke `AdvisoryPipeline.generate()` after `run_simulation` returns, if `holdings_store.has_portfolio`
- Advisory fully disableable via `settings.advisory.enabled = False`
- DIFF-02 cited-position advisory (query existing `RationaleEpisode` nodes for rationale snippets)

**Acceptance criteria:** Empty holdings → "No actionable signal"; unknown ticker rejected by validator; `temperature=0.1` assertion in config test; canary test still passes; 193+ existing tests pass; advisory disableable.

**Features:** TS-09, TS-10, DIFF-02, DIFF-03, DIFF-04, Pitfall 3
**Research flag:** ITERATIVE — synthesis prompt engineering requires 2–3 iteration cycles; plan explicit validation tasks for weak-signal and empty-holdings edge cases

---

### Phase 42 — Advisory Web UI

**Rationale:** Surfaces Phase 41 output. Well-established patterns from Phase 36 ReportViewer. Main new concern: WebSocket snapshots must never include holdings data.

**Delivers:**
- `web/routes/advisory.py` — `POST /api/advisory/generate`, `GET /api/advisory/{cycle_id}` (clone of Phase 36 report route)
- `AdvisoryPanel.vue` — markdown viewer + recommendation list; marked + DOMPurify; persistent "Simulation output — not investment advice" banner; staleness chip on every data point
- `AdvisoryReportPublic` Pydantic model for WebSocket payloads — no holdings fields, aggregate-only stats
- Explicit allowlist serializer `snapshot_to_ws_payload()` — new fields require touching this function (catches drift in code review)
- WebSocket contract test with sentinel ticker — assert sentinel never appears in any WS frame

**Acceptance criteria:** WS contract test passes with sentinel; advisory panel renders via `GET /api/advisory/{cycle_id}` (not via WS); "not financial advice" banner is non-removable; recommendation cards show source attributions.

**Features:** TS-11, Pitfall 2 (WebSocket payload)
**Research flag:** Standard patterns — Phase 36 ReportViewer is the direct blueprint. No phase-level research needed.

---

### Phase 43 — E2E Wire-Up, UAT & Carry-Forward Debt

**Rationale:** Full end-to-end validation with a real holdings CSV, real yfinance fetch, and real advisory synthesis. Also clears v5.0 carry-forward debt (Phase 29 backfill, VALIDATION.md backfills for 29/31/35.1, human UAT items for 32/34/36).

**Delivers:**
- Full E2E run: CSV upload → confirm → seed rumor → INGESTING → swarm rounds → ADVISING → advisory panel
- UAT checklist: advisory abstention on empty holdings; 429 graceful degradation (mock); staleness chip display; WS sentinel contract; isolation canary; CSV validation errors in UI; advisory disabled → pure rumor engine works
- 5-run RSS telemetry plateau confirmed (no cache memory leak)
- Final isolation audit: log-grep over full simulation log with sentinel holdings fixture
- v5.0 carry-forward items resolved or explicitly deferred with documented reason

**Features:** Full v6.0 milestone validation, Pitfall "Looks Done But Isn't" checklist
**Research flag:** No pre-phase research needed. UAT outcomes feed v7.0 backlog.

---

### Phase Ordering Rationale

1. **Phase 37 first** — isolation contracts, provider protocols, PII redaction, and network-blocking CI must exist before any ingestion code. A security retrofit mid-milestone is expensive.
2. **Phase 38 before Phase 40** — the context packet assembler requires real ingestion implementations (or fakes matching their interface) to be testable. Market data and news co-located because they share cache infrastructure.
3. **Phase 39 parallel-capable with Phase 38** — holdings has no dependency on market data. Only constraint: Phase 37 must precede both.
4. **Phase 40 after both 38 and 39** — packet assembly requires ingestion to exist and holdings types to be established (for the isolation check assertions).
5. **Phase 41 after Phase 40** — advisory pipeline ingests a `ContextPacket` produced by the assembler; swarm injection path must exist.
6. **Phase 42 after Phase 41** — UI surfaces data produced by the pipeline.
7. **Phase 43 last** — E2E validation requires the complete system.

**Where architecture's 9-phase plan exceeds 7 phases:** News ingestion (6.3) and isolation enforcement (6.6) are collapsed into Phase 37 and Phase 38 respectively. E2E wire-up (6.9) merges with Phase 43. No information is lost; sequencing rationale is identical.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack additions | HIGH | Versions verified via PyPI; async patterns from official sources; no compatibility conflicts with Python 3.11+ |
| Feature list | HIGH | Broker CSV schemas from multiple third-party guides; isolation from locked PROJECT.md; SEC disclosure from official SEC guidance |
| Architecture | HIGH | Grounded in existing codebase; bolt-on approach matches established patterns; importlinter well-documented |
| Pitfalls | HIGH | yfinance rate limits: GitHub issues + community; governor deadlock: documented in MEMORY.md; CSV drift: multiple independent broker guides |
| Archetype tailoring specifics | MEDIUM-LOW | Quant/Degen/Whale data-lane mapping is opinionated synthesis; validate with prompt experiments in Phase 40 |
| News dedup behavior | MEDIUM | NewsAPI dedup documented; specific simhash threshold for financial headlines requires empirical calibration |
| Advisory synthesis quality | MEDIUM | General LLM grounding patterns documented; specific prompt templates require iteration in Phase 41 |

**Overall confidence: HIGH** for architecture and stack decisions. MEDIUM for output-quality parameters (token budgets, synthesis temperatures, dedup thresholds) which require empirical calibration during execution.

---

### Open Questions

**Decision needed before planning (blocking):**

1. **Robinhood adapter scope** — Ship as "generic column-mapping UI, user maps manually" or explicitly defer with documentation? Determines Phase 39 UI scope. Recommendation: ship generic mapping UI, document Robinhood as unsupported without manual mapping.

2. **NewsAPI vs RSS as primary** — RSS has no delay or key; NewsAPI free tier has 24h embargo but is fine for simulation reasoning. Recommendation: RSS primary + NewsAPI as optional enrichment behind `settings.news.newsapi_enabled` feature flag. Matches "local-first, no mandatory cloud API" constraint better.

**Empirical tuning (resolve during phase execution):**

3. **`MAX_WORKER_CONTEXT_TOKENS` value** — Start at 2000; measure actual quality vs. context size with `qwen3.5:7b` during Phase 40 validation. May be 1200–3000.

4. **yfinance concurrency semaphore** — Start at 4 workers; tune downward if 429s appear in Phase 38 testing.

5. **Advisory synthesis temperature** — Start at 0.1; may need 0.05 for stricter grounding or 0.15 for more fluid prose. Calibrate in Phase 41.

**Phase-level research recommended:**

6. **Phase 40 scale smoke test** — Run 100 agents × full packet + ResourceGovernor monitoring before shipping swarm injection. Governor deadlock from `bug_governor_deadlock.md` can re-emerge from prompt bloat alone.

7. **Phase 41 abstention threshold** — Define what constitutes "weak signal" for the "No actionable signal" path before implementing the advisory generation decision branch (e.g., `confidence < 0.4` across all swarm entities that match holdings symbols).

---

## Sources

### Primary (HIGH confidence)
- Existing codebase — `simulation.py`, `web/simulation_manager.py`, `web/app.py`, `app.py`, `seed.py`, `report.py`
- PROJECT.md v6.0 milestone definition + Option A architecture lock
- CLAUDE.md hard constraints
- yfinance 1.3.0 PyPI; GitHub issues #2557 (sync REST confirmed), #2431 (rate limits)
- pandas 3.0.2 PyPI; feedparser 6.0.12 PyPI
- MEMORY.md `bug_governor_deadlock.md`
- SEC IM Guidance 2017-02 on robo-advisers
- Broker CSV guides: Wingman (Fidelity/Schwab), PdfStatementToExcel (Robinhood)
- NewsAPI.org Terms of Service

### Secondary (MEDIUM confidence)
- TradingAgents (GitHub), GuruAgents (arXiv 2510.01664), AlphaAgents (2508.11152) — multi-agent finance context packet patterns
- aiocache 0.12.3 PyPI + Snyk maintenance analysis
- Groundedness in RAG (arXiv 2404.07060); MDPI multi-layer hallucination mitigation framework

### Tertiary (LOW confidence — validate empirically)
- Per-archetype data-lane mapping (Quant vs Degen vs Whale) — opinionated synthesis, not documented in literature
- Specific `MAX_WORKER_CONTEXT_TOKENS` and synthesis temperature values

---
*Research completed: 2026-04-18*
*Ready for roadmap: yes*
*Phases: 37 → 38 → 39 → 40 → 41 → 42 → 43*
