# Feature Research — v6.0 Data Enrichment & Personalized Advisory

**Domain:** Data-enriched multi-agent financial simulation + personalized advisory (localized, single-operator)
**Researched:** 2026-04-18
**Confidence:** MEDIUM-HIGH (broker CSV schemas HIGH, context packet patterns MEDIUM from emerging literature, disclosure patterns HIGH from SEC guidance)

---

## Information-Isolation Boundary (restated)

Every feature below is annotated with its relationship to the **Option A invariant**:

> Ingestion layer fetches data → Swarm consumes **context packets** only (ticker-level market/news facts, no holdings) → Orchestrator synthesizes advisory from (holdings + swarm output).

Tags used:
- **[INGEST]** — fetches/parses external or user data; never touches prompts
- **[SWARM-SAFE]** — feeds into context packets; MUST NOT contain holdings, cost basis, account IDs, or position sizes
- **[ORCH-ONLY]** — consumed exclusively by the orchestrator synthesis step; never crosses into worker prompts
- **[UI]** — surface layer; renders orchestrator output

---

## Feature Landscape

### Table Stakes (Expected, Must-Have for v6.0)

These are features a user who asks "run my portfolio against a rumor and give me advice" will expect to exist. Missing any of these makes the milestone feel incomplete.

| # | Feature | Category | Why Expected | Complexity | Swarm/Orch Boundary | Depends On |
|---|---------|----------|--------------|------------|----------------------|------------|
| TS-01 | Holdings CSV loader with Schwab/Fidelity/Robinhood auto-detect | Ingestion | Users won't hand-reformat; brokers export inconsistent columns. Fidelity emits `Account Number, Symbol, Quantity, Last Price, Cost Basis...`; Schwab emits positions exports with Symbol/Quantity/Cost Basis/Market Value; Robinhood mixes stock/crypto/options in a single file. A pluggable adapter per broker is table stakes. | MEDIUM | **[INGEST + ORCH-ONLY]** — result lives in an in-memory `Portfolio` object passed ONLY to orchestrator. | None (standalone) |
| TS-02 | Holdings schema validation (pydantic) with actionable errors | Ingestion | Silent coercion of bad rows → wrong advice. Users need "Row 12: Symbol missing" not a stack trace. | LOW | **[INGEST]** | TS-01 |
| TS-03 | In-memory-only holdings (never persisted to Neo4j or disk) | Ingestion / Security | PROJECT.md hard invariant. Users are handing over portfolio data; persistence raises privacy surface area. | LOW (discipline, not code) | **[ORCH-ONLY]** — holdings object dies with the process. | TS-01 |
| TS-04 | Market data fetch via yfinance per extracted entity | Ingestion | Swarm reasoning on a rumor without current price/volume is guesswork. yfinance is the de-facto free local-first feed. | MEDIUM | **[INGEST → SWARM-SAFE]** — ticker facts are public, safe to prompt. | Entity extraction (existing) |
| TS-05 | yfinance caching + rate limiting (`requests_cache` + `pyrate_limiter`) | Ingestion | Yahoo 429s IPs aggressively. Community consensus: cache + 2 req / 5 sec limiter (`CachedLimiterSession` pattern). Without this, a 100-agent run re-fetching entities will get blocked. | MEDIUM | **[INGEST]** | TS-04 |
| TS-06 | News headline fetch per entity (NewsAPI free tier OR RSS fallback) | Ingestion | A rumor simulation ignoring actual news is theatre. NewsAPI free = 100 req/day, 24h-delayed articles; RSS (Yahoo Finance, Reuters) has no limit but requires parsing. | MEDIUM | **[INGEST → SWARM-SAFE]** | Entity extraction |
| TS-07 | Context packet assembly (typed pydantic model per entity) | Context Packets | Prompt stability requires a single canonical shape the swarm sees. Ad-hoc string concat will drift. Literature (TradingAgents, GuruAgents) converges on structured per-ticker briefs. | MEDIUM | **[SWARM-SAFE]** — explicit model enforces no holdings leak. | TS-04, TS-06 |
| TS-08 | Context packet injected into swarm round-1 prompt | Swarm Integration | Without this, all the ingestion is dead weight. Round 1 is where entity-level context should land; rounds 2-3 are peer influence. | MEDIUM | **[SWARM-SAFE]** | TS-07, existing Round 1 dispatcher |
| TS-09 | Orchestrator recommendation synthesis (holdings + consensus → advisory markdown) | Advisory | The whole point of v6.0. User-facing deliverable. | HIGH | **[ORCH-ONLY]** — only place holdings and swarm output meet. | TS-01, existing consensus output |
| TS-10 | Advisory report has plain-English regulatory disclaimer | Advisory | SEC robo-adviser guidance (IM 2017-02) requires plain-English disclosure of methodology + "not personalized professional advice" framing. Even for a local sim, presenting a portfolio recommendation without this is reckless. | LOW | **[ORCH-ONLY]** | TS-09 |
| TS-11 | Advisory report surfaces in web UI (new panel or route) | UI | Report viewer pattern already exists (Phase 36). Reusing `GET /api/report/...` pattern with a new endpoint is the low-friction path. | MEDIUM | **[UI]** | TS-09, existing ReportViewer.vue |
| TS-12 | Information-isolation unit test (log-grep + prompt assertion) | Security / Test | PROJECT.md line 74 states the invariant is "enforced by log-grep and unit tests." Must exist day one, not bolted on. | LOW | **[TEST]** | TS-08, TS-09 |

### Differentiators (Competitive Advantage for AlphaSwarm's Niche)

These go beyond "robo-advisor with a rumor input." They align with AlphaSwarm's Core Value: **believable, diverse market reactions from 100 agents**.

| # | Feature | Category | Value Proposition | Complexity | Swarm/Orch Boundary | Depends On |
|---|---------|----------|-------------------|------------|----------------------|------------|
| DIFF-01 | Per-archetype data tailoring (Quants see fundamentals, Degens see social/volume spikes, Macro sees news sentiment, Whales see volume/flow) | Context Packets | 100 agents with identical context = 100 identical opinions. Tailoring by bracket is what makes the swarm "diverse by design." Literature: GuruAgents encodes investment philosophy via prompt; extending to context slicing is the AlphaSwarm twist. | HIGH | **[SWARM-SAFE]** — same packet, different projections. Each archetype gets a filtered view. | TS-07, existing 10 bracket archetypes |
| DIFF-02 | Cited-position advisory — every recommendation references specific agent rationales ("Quant #7 cited earnings, Macro #3 cited Fed tone") | Advisory | Turns opaque LLM advice into auditable narrative. Ties directly to existing `RationaleEpisode` graph memory — unique to AlphaSwarm's architecture. | MEDIUM | **[ORCH-ONLY]** — orchestrator queries Neo4j for rationales at synthesis time. | TS-09, existing RationaleEpisode nodes |
| DIFF-03 | Holdings-weighted consensus view ("Your portfolio is 40% exposed to entities where the swarm concluded BEAR") | Advisory | Direct translation of swarm signal to user impact. This is the step robo-advisors fake with static allocations; AlphaSwarm grounds it in live simulation output. | MEDIUM | **[ORCH-ONLY]** | TS-09 |
| DIFF-04 | Risk-disclosure block auto-generated per position (confidence score, dissent ratio, shock-sensitivity) | Advisory | Advisory reports without dissent stats overstate confidence. Surfacing "3 archetypes disagreed" is a trust-builder and differentiates from black-box LLM advice. | MEDIUM | **[ORCH-ONLY]** | DIFF-02 |
| DIFF-05 | Archetype-data match visualization in UI (which brackets consumed which data lanes) | UI | Makes the information-isolation architecture legible. Users can visually confirm holdings never hit the swarm. | LOW-MEDIUM | **[UI]** | DIFF-01, existing D3 graph |
| DIFF-06 | Replay-compatible advisory (re-run synthesis against stored Neo4j state) | Advisory | Orchestrator synthesis is deterministic-ish if the swarm output is fixed. Lets users swap portfolios and re-ask "what would this simulation say for a different holdings file?" without re-running 100 agents. | MEDIUM | **[ORCH-ONLY]** | TS-09, existing replay (Phase 32/34) |
| DIFF-07 | Fundamentals snapshot in context packet (P/E, market cap, sector via `Ticker.fast_info`) | Context Packets | Lets Quants reason on valuation without heavy API calls. `fast_info` is lightweight and cached. | LOW | **[SWARM-SAFE]** | TS-04 |

### Anti-Features (Tempting but Problematic)

| # | Feature | Why Tempted | Why Problematic | Better Alternative |
|---|---------|-------------|-----------------|--------------------|
| ANTI-01 | "Let the swarm see the holdings directly — it'll give better advice" | Seems obviously more informative. | **Violates Option A invariant.** Once any worker prompt contains AAPL=40%, every subsequent cached prompt, log, Neo4j episode, and future training data has leaked user portfolio data. Also biases the swarm toward the user's existing exposure (echo chamber). | Keep Option A; personalize only at orchestrator synthesis step (TS-09). |
| ANTI-02 | Persist holdings in Neo4j for "history" | Enables portfolio trajectory analysis. | Creates a privacy surface that needs encryption, retention policy, deletion tooling. Out of scope for a local-first simulation tool. | In-memory only (TS-03). If history is needed later, that's v7.0 with explicit user consent + encrypted-at-rest. |
| ANTI-03 | Real-time streaming market data (websockets) | Sounds impressive. | yfinance has no real-time feed; hitting paid streams contradicts Hard Constraint #2 (local-first, no cloud APIs beyond free public data). Also: a 3-round simulation runs in minutes — intra-simulation price changes are noise. | Snapshot at simulation start. Cache for the duration. Optional re-snapshot between rounds if truly needed. |
| ANTI-04 | "Generate a trade order" / brokerage integration | Users will ask. | Crosses from "simulation + advisory" into "regulated brokerage activity." SEC/FINRA exposure, legal risk. | Text advisory only, with explicit "not financial advice" (TS-10). Users execute manually. |
| ANTI-05 | Ingest full 10-K / 10-Q from SEC EDGAR into context packets | Depth feels valuable. | Token cost is enormous for 100 agents × 3 rounds × 10+ entities. qwen3.5:7b context window will shatter. | Summaries only. Or defer EDGAR to v7.0 with a distilled-by-orchestrator pattern (PROJECT.md already marks EDGAR as stretch). |
| ANTI-06 | One giant "universal" context packet shared across all archetypes | Simpler to implement than DIFF-01. | Kills swarm diversity — all 100 agents converge on the same reading. Defeats the Core Value of "believable, diverse market reactions." | Tailored packets (DIFF-01). Same raw data, archetype-specific projections. |
| ANTI-07 | LLM-generated "trade prices" or numerical forecasts | Users love a number. | LLMs hallucinate numbers confidently. A price target in the advisory report WILL be cited as fact later. | Qualitative advisory only: "Consensus BEARISH on X, dissent 30%, consider reviewing exposure." No price targets. |
| ANTI-08 | Social sentiment scraping (Twitter/X, Reddit) in v6.0 | Degens should "see social." | X/Reddit scraping is ToS-hostile, rate-limited, and noisy. Free APIs for finance-tagged social are flaky. | Proxy via news headlines + volume spikes for v6.0. Real social sentiment = v7.0 (PROJECT.md already defers). |
| ANTI-09 | Auto-refresh advisory as new headlines arrive | Feels dynamic. | Couples advisory generation to a news polling loop → violates "never block the simulation loop" and "one simulation = one advisory." | Advisory is a post-simulation artifact, one-shot per cycle. Re-run the simulation for a fresh advisory. |
| ANTI-10 | Store holdings encrypted and prompt-decrypt per request | "Secure" compromise. | Adds key management complexity for zero benefit over in-memory-only. | TS-03: in-memory, dies with process. |

---

## Data Shape Specifics (answers the research question directly)

### Holdings CSV — Schema Conventions

**Canonical internal schema (post-normalization):**

```python
class Position(BaseModel):
    symbol: str               # uppercase, stripped
    quantity: Decimal         # shares (fractional OK for Robinhood/Schwab Slices)
    cost_basis: Decimal | None    # per-share, optional (Schwab/Fidelity provide)
    market_value: Decimal | None  # current, optional
    account_id_hash: str      # SHA256 of original account number, never raw
    asset_class: Literal["stock", "etf", "mutual_fund", "crypto", "option", "bond", "cash"]
    source_broker: Literal["schwab", "fidelity", "robinhood", "generic"]
```

**Broker column mapping (verified MEDIUM-HIGH confidence):**

| Broker | Positions CSV columns (common) | Notes |
|--------|-------------------------------|-------|
| Fidelity | `Account Number, Account Name, Symbol, Description, Quantity, Last Price, Last Price Change, Current Value, Today's Gain/Loss Dollar, Today's Gain/Loss Percent, Total Gain/Loss Dollar, Total Gain/Loss Percent, Percent Of Account, Cost Basis, Cost Basis Per Share, Type` | 16 columns, `Type` distinguishes cash/margin/retirement |
| Schwab | `Symbol, Description, Quantity, Price, Price Change %, Market Value, Day Change $, Day Change %, Cost Basis, Gain/Loss $, Gain/Loss %, Ratings, Reinvest Dividends?, Capital Gains?, % of Account, Security Type, ...` | 1,500 record cap per export; may need quarterly chunks |
| Robinhood | Stock rows: `Date, Symbol, Description, Quantity, Price, Amount`; crypto uses `Units` + `Spot Price`; options use `Contracts` + `Strike Price` | Mixed-asset rows in one file — adapter MUST handle heterogeneity |
| Generic | User-provided `symbol,quantity` minimum | Fallback for unknown brokers |

**Validation rules:**
- Reject zero/negative quantities (except explicit short position flag — defer shorts to v7.0)
- Reject non-alphanumeric symbols longer than 10 chars (catches headers-as-rows)
- Strip BOM from first column (Windows Excel adds `\ufeff`)
- Account numbers → immediate SHA256 hash, never stored raw

### Market Data Context Packet — What Fields Matter

Based on multi-agent finance literature (TradingAgents: fundamental/sentiment/technical decomposition) and practical yfinance availability:

**Core packet (all archetypes see):**
```python
class MarketContext(BaseModel):
    symbol: str
    current_price: float
    day_change_pct: float
    volume: int
    avg_volume_30d: int
    volume_ratio: float      # volume / avg_volume_30d — spike detector
    price_52w_high: float
    price_52w_low: float
    as_of_timestamp: datetime
```

**Fundamentals (Quants + Suits):**
```python
    market_cap: float
    pe_trailing: float | None
    pe_forward: float | None
    sector: str
    industry: str
```

**Technicals (Quants + Degens):**
```python
    sma_20: float
    sma_50: float
    sma_200: float
    rsi_14: float            # computed, not yfinance-native
    price_vs_sma_200: float  # % above/below — regime indicator
```

**News block (Macro + Doom-Posters + Policy Wonks):**
```python
class NewsContext(BaseModel):
    headlines: list[Headline]  # 5-10 per entity, 72h window, dedup'd

class Headline(BaseModel):
    title: str
    source: str              # "Reuters", "Bloomberg RSS", etc.
    published_at: datetime
    url: str | None          # for UI linking, stripped before prompt
```

**Rationale for field selection:**
- **Volume ratio** > raw volume: a 100M-share day is nothing for AAPL, huge for a mid-cap. Ratio normalizes.
- **RSI + SMA trio**: cheapest computed technicals that give Quants something to chew on. Computed in-process (pandas), not fetched.
- **Forward P/E**: more useful to LLM reasoning than trailing for rumor-driven scenarios.
- **52w range**: compact regime signal — "near high" vs "near low" changes rumor interpretation.

### News Aggregation — Headline Count, Freshness, Dedup

**Recommended defaults (LOW-MEDIUM confidence, adjust after first runs):**

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Headlines per entity | 5–10 | qwen3.5:7b context budget. Each headline ~30 tokens. 10 headlines × 10 entities × 100 agents = manageable if cached per-entity. |
| Freshness window | 72 hours (tunable to 24h for fast-moving rumors) | Balances signal/noise. News older than 3 days rarely drives a rumor reaction. |
| Dedup strategy | Normalize title (lowercase, strip punctuation, first 80 chars), hash, drop collisions | Same story syndicates across Reuters/Yahoo/Bloomberg/AP. Naïve dedup misses headline-case-variants. |
| Cross-source ranking | Prefer Reuters > Bloomberg > AP > Yahoo Finance RSS > generic | Source trust tier affects downstream credibility. |
| Primary API | NewsAPI.org free tier (100 req/day, 24h delay) — acceptable for simulation | Delay is fine for rumor reasoning; user isn't front-running |
| Fallback | Yahoo Finance RSS per ticker (`https://feeds.finance.yahoo.com/rss/2.0/headline?s=SYM`) | Unlimited, no key, brittle format — parser must be defensive |

### Archetype Tailoring — "What does a Quant want vs a Degen?"

This is the DIFF-01 feature. The **same raw MarketContext + NewsContext** is projected differently into each archetype's prompt.

| Archetype | Data Lanes Surfaced | Data Lanes Hidden | Framing |
|-----------|---------------------|-------------------|---------|
| Quants (10) | Full fundamentals, full technicals, P/E deltas, sector-relative performance | Social tone, headline sentiment (too qualitative) | "Quantitative brief. Model-ready facts." |
| Degens (20) | Volume ratio, price_vs_sma_200, 52w-high distance, headline count-only (meme proxy) | Detailed fundamentals (TLDR) | "Ticker vibes. What's moving?" |
| Sovereigns (10) | Market cap, sector, 52w range, macro-tier headlines | Intraday noise, technicals | "Strategic positioning brief." |
| Macro (10) | Full news headlines, sector performance, rate/currency cross-references | Individual technicals | "Flow and narrative." |
| Suits (10) | Fundamentals, analyst-adjacent headlines, industry context | Retail-targeted social proxies | "Institutional-style research summary." |
| Insiders (10) | Volume anomalies, options flow hints (if available), filings-related headlines | General market commentary | "Signal, not noise." |
| Agents (15) | Balanced slice — full packet, de-weighted | — | "Default generalist view." |
| Doom-Posters (5) | Negative-tilt headlines emphasized, VIX-proxy, drawdown highlights | Positive fundamentals | "Risk-off framing." |
| Policy Wonks (5) | Regulatory/Fed/Treasury headlines, sector policy context | Technicals | "Policy-lens brief." |
| Whales (5) | Volume + 52w-high proximity, large-cap peer moves | Small-cap noise | "Size-matters brief." |

**Implementation pattern:** A `ContextPacketProjector` class with per-archetype methods that take the full packet and return a serialized prompt-fragment. Keeps projection logic testable and centralized.

### Personalized Advisory Report — Shape

**Section-by-section (proposed markdown structure):**

```markdown
# Advisory Report — Cycle <cycle_id>
**Generated:** <ISO timestamp>
**Seed rumor:** <1-line restated>
**Simulation duration:** <N seconds>
**Consensus outcome:** <overall BEAR/NEUTRAL/BULL with confidence %>

## 1. Portfolio Impact Summary
- Total positions analyzed: N
- Positions in rumor scope: M (the ones matching extracted entities)
- Exposure-weighted consensus: "Your portfolio skews <BEAR/NEUTRAL/BULL> on this rumor"
- Highest-impact position: <symbol> (<%-of-portfolio>, <swarm verdict>)

## 2. Position-Level Recommendations
For each position in rumor scope:
  ### <Symbol> — <quantity> shares (<% of portfolio>)
  **Swarm verdict:** <verdict> (<confidence>, <dissent %>)
  **Key rationales:**
  - <Archetype #X> cited: "<rationale snippet>"
  - <Archetype #Y> cited: "<rationale snippet>"
  **Dissent:**
  - <Archetype #Z> disagreed: "<counter-rationale>"
  **Suggested action:** Review / Monitor / No action indicated
  [Never: "Buy more" / "Sell" / specific price targets]

## 3. Positions Outside Rumor Scope
Listed, no action suggested — flags that they weren't analyzed.

## 4. Risk Disclosures
- Confidence caveats (dissent ratios)
- Shock-sensitivity notes (if shock was injected)
- Data freshness (news window, market data timestamp)

## 5. Methodology Disclosure (SEC-style plain English)
- "This report is generated by a local simulation of 100 AI personas..."
- "Recommendations are qualitative and derived from consensus patterns..."
- "This is NOT personalized professional financial advice. Consult a licensed advisor before making investment decisions."
- "Holdings data was processed in-memory only and not persisted."

## 6. Appendix
- Entities extracted from rumor
- Context packet snapshot (market data + headline counts per entity)
- Simulation parameters (rounds, archetype distribution)
```

**Key design choices:**
- Every recommendation is **cited** to specific agents (DIFF-02)
- Qualitative language only — `Review / Monitor / No action indicated` — never `Buy / Sell / $target` (ANTI-07)
- Dissent is surfaced, not hidden (DIFF-04)
- Disclosure section is not-optional boilerplate (TS-10)

---

## Feature Dependencies

```
TS-01 (CSV loader)
  └─> TS-02 (validation)
  └─> TS-03 (in-memory-only)
        └─> TS-09 (orchestrator synthesis) [ORCH-ONLY]
              └─> TS-10 (disclaimer)
              └─> TS-11 (UI surfacing)
              └─> DIFF-02 (cited positions) — requires Neo4j RationaleEpisode [existing]
              └─> DIFF-03 (holdings-weighted view)
              └─> DIFF-04 (risk disclosure)
              └─> DIFF-06 (replay-compatible)

TS-04 (yfinance fetch)
  └─> TS-05 (cache + rate limit)
        └─> TS-07 (context packet model) [SWARM-SAFE]
              └─> TS-08 (inject into Round 1 prompt)
                    └─> DIFF-01 (archetype tailoring) [SWARM-SAFE, PROJECTED]
              └─> DIFF-07 (fundamentals snapshot)

TS-06 (news fetch)
  └─> TS-07 (context packet — news block)

TS-12 (info-isolation test) ── enforces ──> TS-08, TS-09, DIFF-01
                                          (asserts no holdings fields in any worker prompt/log)

DIFF-05 (archetype-data viz) ── enhances ──> DIFF-01, existing D3 graph

ANTI-01 (swarm sees holdings) ── conflicts with ──> TS-03, TS-12, Option A invariant
```

### Dependency Notes

- **TS-07 is the critical seam.** It is the single chokepoint through which all swarm-bound data flows. If its pydantic model has no `holdings`/`position`/`cost_basis` fields, information isolation is enforced by the type system, not by discipline.
- **TS-09 is the only place holdings + swarm output coexist.** The orchestrator process reads Neo4j for swarm rationales and the in-memory `Portfolio` for holdings. Both sources feed one markdown generator.
- **TS-12 (log-grep test) must run in CI.** Scans all log output of a test simulation for position data patterns (known symbols, quantities, account hash prefix) and fails on hits. Cheap and catches accidental leaks fast.
- **DIFF-02 depends on existing `RationaleEpisode` nodes** (Phase 11, validated). No new graph schema required — queries existing structure.
- **DIFF-06 (replay advisory) depends on existing replay infrastructure** (Phase 32/34). Re-running synthesis against stored state is free compute — big user value for small effort.

---

## MVP Definition

### Launch With (v6.0 must-ship)

Minimum to validate "informed advisory from a simulation run."

- [ ] **TS-01** Holdings CSV loader (Fidelity + Schwab + generic adapters; Robinhood can be best-effort)
- [ ] **TS-02** Pydantic validation with row-level errors
- [ ] **TS-03** In-memory-only invariant (no DB writes of holdings)
- [ ] **TS-04** yfinance per-entity fetch (core packet: price, volume, 52w, fundamentals)
- [ ] **TS-05** yfinance caching + rate limit (CachedLimiterSession pattern — non-negotiable or Yahoo will 429 the run)
- [ ] **TS-06** News fetch (pick ONE: NewsAPI OR RSS — adapter pattern for later swap)
- [ ] **TS-07** Context packet pydantic model (typed, holdings-free)
- [ ] **TS-08** Packet injection into Round 1 prompt (Rounds 2-3 untouched for v6.0)
- [ ] **TS-09** Orchestrator synthesis → advisory markdown
- [ ] **TS-10** Disclaimer block
- [ ] **TS-11** UI surfacing (reuse Phase 36 ReportViewer pattern, new route)
- [ ] **TS-12** Information-isolation log-grep test
- [ ] **DIFF-02** Cited-position advisory (existing RationaleEpisode makes this nearly free)

### Add After Validation (v6.1, same milestone if time permits)

- [ ] **DIFF-01** Per-archetype context tailoring — ship with ONE simple split (Quants get fundamentals, Degens get volume/social proxies) then expand to 10 brackets
- [ ] **DIFF-03** Holdings-weighted consensus view in advisory
- [ ] **DIFF-04** Risk-disclosure block with dissent ratios
- [ ] **DIFF-07** Fundamentals in packet (cheap addition after TS-04 works)

### Future Consideration (v7.0+)

- [ ] **DIFF-05** Archetype-data viz (UI polish — ship v6.0 without)
- [ ] **DIFF-06** Replay-compatible advisory (requires replay phase work)
- [ ] SEC EDGAR ingestion (PROJECT.md stretch → v7.0)
- [ ] Social sentiment (PROJECT.md stretch → v7.0)
- [ ] Encrypted holdings persistence (ONLY if users explicitly request history)
- [ ] Short positions / margin / options advisory (requires much richer holdings schema)

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| TS-01 CSV loader | HIGH | MEDIUM | P1 |
| TS-02 Validation | HIGH | LOW | P1 |
| TS-03 In-memory invariant | HIGH (privacy) | LOW | P1 |
| TS-04 yfinance fetch | HIGH | MEDIUM | P1 |
| TS-05 Cache + rate limit | HIGH (blocker without) | MEDIUM | P1 |
| TS-06 News fetch | HIGH | MEDIUM | P1 |
| TS-07 Context packet model | HIGH (seam) | MEDIUM | P1 |
| TS-08 Swarm injection | HIGH | MEDIUM | P1 |
| TS-09 Orchestrator synthesis | HIGH (core deliverable) | HIGH | P1 |
| TS-10 Disclaimer | MEDIUM (regulatory hygiene) | LOW | P1 |
| TS-11 UI surfacing | HIGH | MEDIUM | P1 |
| TS-12 Isolation test | HIGH (invariant proof) | LOW | P1 |
| DIFF-01 Archetype tailoring | HIGH (core value) | HIGH | P1-P2 (ship simple first) |
| DIFF-02 Cited positions | HIGH | MEDIUM | P1 |
| DIFF-03 Weighted consensus | MEDIUM | MEDIUM | P2 |
| DIFF-04 Risk disclosure | MEDIUM | MEDIUM | P2 |
| DIFF-05 Archetype viz | MEDIUM | LOW-MED | P3 |
| DIFF-06 Replay advisory | MEDIUM | MEDIUM | P3 |
| DIFF-07 Fundamentals | MEDIUM | LOW | P2 |

---

## Competitor / Comparable Feature Analysis

| Feature | TradingAgents (OSS) | Origin AI | GuruAgents | AlphaSwarm Approach |
|---------|---------------------|-----------|------------|---------------------|
| Multi-agent decomposition | Fundamental / sentiment / technical / trader / risk roles | Specialist agents routed per query | Philosophy-encoded agents | 10-bracket archetype swarm (already built) |
| Holdings awareness | None explicit — market-facing only | Full user financial history | None | **Orchestrator-only (Option A)** |
| Data sources | Yahoo, SEC, Reddit, FinnHub | Real-time + user history | Per-guru curated | yfinance + NewsAPI/RSS (local-first) |
| Prompt personalization | Role-based | User-context-aware | Philosophy-based | Archetype-based (DIFF-01) |
| Output format | Trade signal + rationale | Conversational advisory | Buy/hold/sell + thesis | Qualitative advisory markdown with citations (TS-09, DIFF-02) |
| Privacy posture | N/A (public data only) | Cloud-hosted, regulated | N/A | **Local-first, in-memory-only holdings** |
| Regulatory disclosure | Minimal | SEC-regulated | Academic | SEC-style plain-English disclaimer (TS-10) |

**AlphaSwarm's position:** The only local-first, holdings-aware, multi-persona market-reaction simulator with hard information-isolation. Differentiation is not "another LLM advisor" but "a simulation that happens to advise."

---

## Open Questions / Research Gaps

Flag for phase-level research later:

1. **News API vs RSS final pick** — NewsAPI free tier's 24h delay is fine for rumor reasoning but may be perceived as stale. RSS has no delay but is format-fragile. Recommend prototyping both in one phase, picking based on signal quality.
2. **RSI computation library** — `pandas-ta` vs `TA-Lib` vs hand-rolled. TA-Lib requires C binary; pandas-ta is pure Python. Lean toward pandas-ta unless performance forces otherwise.
3. **Context window budgeting** — 10 entities × 10 headlines × 100 agents × qwen3.5:7b is workable, but specific token counts need empirical measurement. Budget test early in the ingestion phase.
4. **Robinhood adapter priority** — Robinhood's mixed-asset CSV is the messiest. Ship with "best-effort" parser, flag non-stock rows as "unsupported — excluded from analysis," expand later.
5. **Archetype projection logic location** — does it live inside the ContextPacketBuilder or inside the worker-agent prompt assembler? Architectural call for the roadmapper.

---

## Confidence Assessment

| Area | Confidence | Basis |
|------|------------|-------|
| Broker CSV schemas (Fidelity, Schwab, Robinhood) | HIGH | Multiple third-party broker-export guides + official support pages converge |
| yfinance caching pattern | HIGH | Official yfinance docs + community CachedLimiterSession idiom |
| NewsAPI free tier limits | HIGH | Official pricing page, 100 req/day + 24h delay |
| Multi-agent context packet patterns | MEDIUM | Emerging literature (TradingAgents, GuruAgents, AlphaAgents); patterns not yet standardized |
| Per-archetype tailoring specifics | MEDIUM-LOW | Literature supports philosophy-encoded agents; the specific "Quant vs Degen vs Whale" data-lane mapping is opinionated synthesis, not documented elsewhere — validate with prompt experiments |
| SEC-style disclosure language | HIGH | SEC IM Guidance 2017-02 on robo-advisers |
| Advisory report shape | MEDIUM | Synthesis of robo-advisor report conventions + AlphaSwarm's existing report viewer; specific section ordering is opinionated |

---

## Sources

**Broker CSV formats:**
- [Fidelity Positions CSV Instructions (Wingman)](https://help.wingmantracker.com/article/3175-fidelity-positions-csv-instructions)
- [Charles Schwab Positions CSV Instructions (Wingman)](https://help.wingmantracker.com/article/3178-charles-schwab-positions-csv-instructions)
- [Schwab Trade File Formats (PDF)](https://support.tamaracinc.com/help/content/resources/pdf/rebalancing/schwabwebtrading_all_fileformats_v5_9.pdf)
- [Exporting Robinhood investments to CSV](https://onlineaspect.com/2015/12/17/export-robinhood-investments-to-csv/)
- [Robinhood portfolio export guide](https://www.pdfstatementtoexcel.com/blog/export-robinhood-portfolio-to-excel)

**yfinance + caching:**
- [yfinance caching documentation](https://ranaroussi.github.io/yfinance/advanced/caching.html)
- [yfinance fast_info reference](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.fast_info.html)
- [Rate limiting and API best practices for yfinance (Sling Academy)](https://www.slingacademy.com/article/rate-limiting-and-api-best-practices-for-yfinance/)
- [yfinance rate-limit discussion #2431](https://github.com/ranaroussi/yfinance/discussions/2431)

**News APIs:**
- [NewsAPI.org pricing](https://newsapi.org/pricing)
- [Free News APIs 2026 comparison (NewsData.io)](https://newsdata.io/blog/best-free-news-api/)
- [World News API pricing](https://worldnewsapi.com/pricing/)

**Multi-agent financial LLM literature:**
- [TradingAgents framework (GitHub)](https://github.com/TauricResearch/TradingAgents)
- [GuruAgents: Prompt-guided LLM investor agents (arXiv)](https://arxiv.org/html/2510.01664v1)
- [Toward Expert Investment Teams: Multi-Agent LLM System (arXiv)](https://arxiv.org/html/2602.23330)
- [AlphaAgents: Multi-Agent LLM for Equity Portfolios](https://www.emergentmind.com/papers/2508.11152)
- [Origin AI financial advisor technical overview](https://useorigin.com/resources/blog/technical-overview)

**Regulatory / disclosure:**
- [SEC IM Guidance 2017-02 on robo-advisers (PDF)](https://www.sec.gov/investment/im-guidance-2017-02.pdf)
- [Investor Bulletin: Robo-Advisers (SEC)](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-45)
- [FINRA on Robo-Advisors](https://www.wagnerlawgroup.com/blog/2016/03/finra-weighs-in-on-robo-advisors/)

---
*Feature research for: v6.0 Data Enrichment & Personalized Advisory*
*Researched: 2026-04-18*
*Downstream: gsd-roadmapper — derive phase scope, carry Information-Isolation invariant (PROJECT.md line 74) into every phase's acceptance criteria*
