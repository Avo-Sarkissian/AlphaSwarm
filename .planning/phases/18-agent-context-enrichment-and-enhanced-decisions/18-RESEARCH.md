# Phase 18: Agent Context Enrichment and Enhanced Decisions - Research

**Researched:** 2026-04-06
**Domain:** Prompt engineering, Pydantic model extension, Alpha Vantage NEWS_SENTIMENT, async HTTP, 3-tier parse fallback
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Prompt Injection Architecture**
- D-01: Market data is appended to `user_message` as a formatted block prepended to the rumor text. Format: `f"{format_market_block(snapshots, bracket)}\n\nRumor: {rumor}"`. No changes to `AgentWorker.infer()`, `dispatch_wave()`, or the messages list structure.
- D-02: New module `src/alphaswarm/enrichment.py` owns all formatting logic: `format_market_block(snapshots: dict[str, MarketDataSnapshot], bracket: BracketType) -> str` and `build_enriched_user_message(rumor: str, snapshots, bracket) -> str`. Called from `simulation.py` before each `dispatch_wave()` call (Rounds 1, 2, 3).
- D-03: Token budget enforced via per-bracket-group character caps (`MAX_MARKET_BLOCK_CHARS: dict[BracketType, int]`). `format_market_block()` truncates to fit. Values are conservative (below actual token limit) to leave headroom. No tokenizer API call on the hot path.

**Bracket Data Slices**
- D-04: All 10 brackets grouped into 3 slice categories:
  - Technicals (Quants, Degens, Whales): `last_close`, `price_change_30d_pct`, `price_change_90d_pct`, `avg_volume_30d`, `fifty_two_week_high`, `fifty_two_week_low`
  - Fundamentals (Suits, Sovereigns, Policy Wonks): `pe_ratio`, `market_cap`, `revenue_ttm`, `gross_margin_pct`, `debt_to_equity`
  - Earnings/Insider (Insiders, Macro, Agents, Doom-Posters): `earnings_surprise_pct`, `next_earnings_date`, `eps_trailing`, `market_cap`, plus top 10 news headlines from AV NEWS_SENTIMENT
- D-05: Every agent sees all tickers (Phase 16 caps at 3), formatted with their bracket slice. Token budget applies across all tickers combined.

**AgentDecision Extension**
- D-06: New frozen Pydantic model `TickerDecision` in `types.py`:
  ```python
  class TickerDecision(BaseModel, frozen=True):
      ticker: str
      direction: SignalType
      expected_return_pct: float | None = None
      time_horizon: str | None = None
  ```
- D-07: `AgentDecision` gains one new field: `ticker_decisions: list[TickerDecision] = Field(default_factory=list)`. All other existing fields unchanged. Empty list = backward-compatible None equivalent.
- D-08: `time_horizon` is a free string (not enum). Agent prompt instructs one of `'1d'`, `'1w'`, `'1m'`, `'3m'`, `'6m'`, `'1y'`. No Pydantic enum validator.

**News Headlines (DATA-03)**
- D-09: Fetch 10 headlines per ticker from AV NEWS_SENTIMENT endpoint. Runs in `enrichment.py` after `fetch_market_data()` returns snapshots, before Round 1. Headlines stored into `MarketDataSnapshot.headlines`.
- D-10: If `ALPHA_VANTAGE_API_KEY` is absent or AV call fails, emit a `structlog` WARNING and keep `headlines=[]`. Simulation never aborts. Uses `httpx.AsyncClient` pattern as Phase 17.
- D-11: Headlines injected only into Earnings/Insider bracket slice. Technicals and Fundamentals brackets do not receive headlines.

### Claude's Discretion
- Exact char cap values per bracket group (tune to stay within ~87% of context window)
- Exact formatting style of the market data block (markdown table vs key-value lines vs prose)
- Whether `direction` in `TickerDecision` reuses `SignalType` (BUY/SELL/HOLD) or defines a separate Direction enum
- Whether headlines are truncated to 120 chars per headline in the formatted block
- Test fixture approach for enrichment.py (mock `fetch_market_data` return or use real `MarketDataSnapshot` instances)

### Deferred Ideas (OUT OF SCOPE)
- Tokenizer validation (one-time calibration test, not hot-path enforcement)
- NEWS_SENTIMENT for Fundamentals brackets (Suits/Policy Wonks)
- Ticker MENTIONS edges to Neo4j Entity nodes
- Multi-day headline cache with market-hours awareness
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ENRICH-01 | All market data fetching completes before Round 1; each agent prompt includes a formatted market data block within a strict token budget | Pre-simulation enrichment step in `run_simulation()` already established by Phase 17 at line 776; `build_enriched_user_message()` called at each of 3 `dispatch_wave()` sites |
| ENRICH-02 | Different bracket archetypes receive different data slices — Quants see price/volume/technicals, Macro agents see sector-level data, Insiders see earnings surprises | 3-slice architecture (D-04) implemented by `format_market_block(bracket)` in `enrichment.py`; verifiable by inspecting `user_message` in agent calls |
| ENRICH-03 | News headlines (DATA-03) fetched via AV NEWS_SENTIMENT and injected into Earnings/Insider bracket slice | `fetch_headlines()` in `enrichment.py` mirrors Phase 17 AV pattern; graceful skip when key absent |
| DECIDE-01 | Agent decisions include ticker, direction, expected_return_pct, and time_horizon fields in structured output | `TickerDecision` Pydantic model added to `types.py`; `AgentDecision.ticker_decisions` list field; `JSON_OUTPUT_INSTRUCTIONS` updated with new schema example |
| DECIDE-02 | The 3-tier parse fallback handles new fields gracefully — missing fields get `[]` defaults without PARSE_ERROR | `ticker_decisions: list[TickerDecision] = Field(default_factory=list)` makes the field optional to Pydantic; existing 3-tier fallback in `parsing.py` requires no structural changes |
</phase_requirements>

---

## Summary

Phase 18 is a prompt engineering and data model extension phase. It builds directly on two complete Phase 17 outputs — `MarketDataSnapshot` (with a reserved `headlines: list[str]` field) and the `fetch_market_data()` async pipeline — and connects them to the agent inference layer via a new `enrichment.py` module. No new infrastructure, no new external dependencies beyond Alpha Vantage (already integrated), and no TUI or report surface changes.

The three technical sub-problems are well-bounded: (1) build `format_market_block()` with 3 bracket-slice configs and per-bracket char caps; (2) extend `AgentDecision` with a `ticker_decisions: list[TickerDecision]` field and update the JSON output prompt schema to instruct agents; (3) fetch AV NEWS_SENTIMENT headlines and populate `MarketDataSnapshot.headlines` before calling `build_enriched_user_message()`.

The primary risk is prompt reliability: qwen3.5:9b must understand the new JSON schema change well enough to emit `ticker_decisions` reliably. The existing 3-tier parse fallback already handles missing optional fields via Pydantic defaults — adding `ticker_decisions=[]` extends this gracefully with zero structural changes to `parsing.py`.

**Primary recommendation:** Implement Phase 18 in 3 plans: (1) types, enrichment module skeleton, and char cap constants; (2) format logic, AV headline fetch, simulation wiring; (3) prompt schema update and integration tests.

---

## Standard Stack

### Core (all already in project dependencies)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `pydantic` | >=2.0 | `TickerDecision` model, `AgentDecision` extension | Frozen Pydantic models are the established type contract in this codebase |
| `httpx` | current | AV NEWS_SENTIMENT async HTTP fetch | Already used by Phase 17 AV fallback; `httpx.AsyncClient` pattern established |
| `structlog` | current | `component='enrichment'` logger for warnings on missing AV key | All modules use `structlog.get_logger(component=...)` convention |
| `asyncio` | stdlib | `asyncio.TaskGroup` for parallel headline fetches per ticker | Established async pattern; no sync blocking on event loop |

### No New Dependencies
Phase 18 introduces no new packages. `enrichment.py` imports from `alphaswarm.types` (MarketDataSnapshot, BracketType), `alphaswarm.market_data` (AV_BASE_URL), and stdlib `httpx` + `structlog` already in pyproject.toml.

---

## Architecture Patterns

### Module Layout (new file only)

```
src/alphaswarm/
├── enrichment.py        # NEW — format_market_block(), build_enriched_user_message(), fetch_headlines()
├── types.py             # MODIFIED — TickerDecision model, AgentDecision.ticker_decisions field
├── config.py            # MODIFIED — JSON_OUTPUT_INSTRUCTIONS updated with new schema
├── simulation.py        # MODIFIED — 3 dispatch sites call build_enriched_user_message()
└── parsing.py           # NO CHANGES needed — Pydantic default handles new field
```

### Pattern 1: `enrichment.py` Module Structure

**What:** Standalone data-layer module following `market_data.py` conventions.
**When to use:** Called from `simulation.py` at each `dispatch_wave()` site, not on the hot inference path.

```python
# src/alphaswarm/enrichment.py
import structlog
import httpx
from alphaswarm.types import BracketType, MarketDataSnapshot

logger = structlog.get_logger(component="enrichment")

# Bracket slice groupings (D-04)
_TECHNICALS_BRACKETS = {BracketType.QUANTS, BracketType.DEGENS, BracketType.WHALES}
_FUNDAMENTALS_BRACKETS = {BracketType.SUITS, BracketType.SOVEREIGNS, BracketType.POLICY_WONKS}
_EARNINGS_INSIDER_BRACKETS = {BracketType.INSIDERS, BracketType.MACRO, BracketType.AGENTS, BracketType.DOOM_POSTERS}

# Per-bracket-group char caps (Claude's discretion to tune; examples below)
MAX_MARKET_BLOCK_CHARS: dict[BracketType, int] = {
    # Technicals: ~6 fields * 3 tickers * ~40 chars/field = ~720 chars; cap at 900
    BracketType.QUANTS: 900,
    BracketType.DEGENS: 900,
    BracketType.WHALES: 900,
    # Fundamentals: ~5 fields * 3 tickers * ~50 chars/field = ~750; cap at 1000
    BracketType.SUITS: 1000,
    BracketType.SOVEREIGNS: 1000,
    BracketType.POLICY_WONKS: 1000,
    # Earnings/Insider: fields + 10 headlines * ~120 chars = larger; cap at 2000
    BracketType.INSIDERS: 2000,
    BracketType.MACRO: 2000,
    BracketType.AGENTS: 2000,
    BracketType.DOOM_POSTERS: 2000,
}

def format_market_block(
    snapshots: dict[str, MarketDataSnapshot],
    bracket: BracketType,
) -> str:
    """Return compact key-value market block capped to bracket's char limit."""
    ...

def build_enriched_user_message(
    rumor: str,
    snapshots: dict[str, MarketDataSnapshot],
    bracket: BracketType,
) -> str:
    """Return f'{format_market_block(snapshots, bracket)}\n\nRumor: {rumor}'."""
    ...

async def fetch_headlines(
    symbol: str,
    av_key: str,
    limit: int = 10,
) -> list[str]:
    """Fetch top N news headlines for symbol from AV NEWS_SENTIMENT."""
    ...

async def enrich_snapshots_with_headlines(
    snapshots: dict[str, MarketDataSnapshot],
    av_key: str | None,
) -> dict[str, MarketDataSnapshot]:
    """Populate headlines field on each snapshot. Returns new frozen snapshot instances."""
    ...
```

### Pattern 2: Compact Key-Value Block Format (Claude's Discretion Recommendation)

**What:** Token-efficient key-value per-ticker format, not markdown table.
**Why:** Tables add ~30% overhead in separator chars; key-value is readable and shorter.

```
--- Market Data ---
AAPL: close=$182.50, 30d=+4.2%, 90d=+8.1%, vol=48.2M, 52w=[$142/$199]
TSLA: close=$250.10, 30d=-1.8%, 90d=+12.4%, vol=102.1M, 52w=[$138/$299]
```

For Fundamentals bracket:
```
--- Market Data ---
AAPL: PE=28.5, mktcap=$3.0T, rev=$400B, margin=45.0%, D/E=1.5
TSLA: PE=72.1, mktcap=$795B, rev=$97B, margin=18.2%, D/E=0.1
```

For Earnings/Insider bracket:
```
--- Market Data ---
AAPL: surprise=+5.2%, next_earnings=2025-07-15, EPS=$6.50, mktcap=$3.0T
Headlines: "Apple beats Q2 estimates on iPhone sales" | "Services revenue hits record..."
TSLA: ...
```

### Pattern 3: Simulation Wiring — 3 Dispatch Sites

All 3 `dispatch_wave()` calls in `simulation.py` currently pass `user_message=rumor` (a bare string). Each needs `build_enriched_user_message(rumor, market_snapshots, persona.bracket)` — but `dispatch_wave` takes a single `user_message` shared across all personas in a wave.

**Critical insight:** `dispatch_wave()` takes a single shared `user_message` string, not per-persona messages. This means a bracket-specific enriched message cannot be per-agent — it must be per-bracket-group. The 3-slice design maps perfectly: group personas by slice category, dispatch separate `dispatch_wave()` calls per bracket group, or accept that all agents in a wave share one slice.

**Resolution from CONTEXT.md:** Dispatch sites currently call `dispatch_wave()` for ALL 100 personas at once with a single `user_message`. To inject bracket-specific messages, either:
- Option A: Split each round's wave into 3 sub-waves (one per slice group), each with its bracket's enriched message — then merge results. Clean but adds 2 extra dispatch calls per round.
- Option B: Use `dispatch_wave()`'s `peer_contexts` list to pass per-agent enriched messages as the user_message substitute — but `peer_contexts` is for peer context, not user_message; this would require modifying `dispatch_wave()` or `AgentWorker.infer()`, which D-01 explicitly forbids.
- Option C (CONTEXT.md D-01 implies): Pre-compute per-bracket enriched messages, then call `build_enriched_user_message()` once per bracket group and pass each result as `user_message` to separate sub-waves.

**Recommended approach (Option A):** For each round, loop over 3 bracket groups, build the enriched message for that group, dispatch a sub-wave for those personas only, collect results, then merge into the full list. This is cleanest and avoids any changes to `dispatch_wave()` or `AgentWorker.infer()`.

```python
# In simulation.py — per-round enrichment loop (conceptual):
bracket_groups = _group_personas_by_slice(personas)  # 3 groups
all_decisions = []
for group_personas, bracket_slice in bracket_groups:
    enriched_msg = build_enriched_user_message(rumor, market_snapshots, bracket_slice)
    group_decisions = await dispatch_wave(
        personas=group_configs,
        user_message=enriched_msg,
        ...
    )
    all_decisions.extend(group_decisions)
```

When `market_snapshots` is empty (no tickers extracted), `build_enriched_user_message()` returns the bare rumor string — zero behavior change.

### Pattern 4: `MarketDataSnapshot` Update Pattern (Frozen Model)

`MarketDataSnapshot` is frozen. To populate `headlines`, construct a new instance:

```python
# enrichment.py — enrich_snapshots_with_headlines()
updated = snapshot.model_copy(update={"headlines": headlines})
```

`model_copy(update=...)` is the Pydantic v2 pattern for updating frozen models. Returns a new frozen instance.

### Anti-Patterns to Avoid

- **Per-agent enrichment in AgentWorker.infer():** D-01 locks prompt injection to `user_message` at the dispatch site, not inside the worker. Do not touch `worker.py`.
- **Global `dispatch_wave()` with one shared user_message for all 100 agents:** This discards bracket differentiation. Must sub-wave per slice group.
- **Live tokenizer count on hot path:** D-03 locks this to conservative char caps. Never call `tiktoken` or Ollama tokenize API during inference.
- **Storing full headline body:** AV NEWS_SENTIMENT `summary` field can be 500+ chars. Extract only `title` (or title + 120-char truncated summary). Do not store raw `summary`.
- **Re-fetching headlines per round:** Headlines are fetched once pre-simulation and stored in the snapshot. `build_enriched_user_message()` reads from `snapshot.headlines`, not from AV.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Frozen model update | Manual `__init__` call or `dict()` | `snapshot.model_copy(update={...})` | Pydantic v2 standard for frozen BaseModel mutation |
| JSON parsing of new fields | Custom regex for `ticker_decisions` | Pydantic `model_validate_json()` with `default_factory=list` | Existing 3-tier parse fallback handles unknown fields via Pydantic defaults |
| Char truncation at word boundary | Custom truncate function | `text[:limit].rsplit(' ', 1)[0]` or adopt `_truncate_modifier()` pattern from `config.py` | `_truncate_modifier()` already handles this; apply same word-boundary truncation |
| Per-ticker AV rate limiting | Custom semaphore + retry | Single `httpx.AsyncClient` shared per `enrich_snapshots_with_headlines()` call; AV free tier 25 calls/day means 3 tickers × 1 endpoint = 3 calls — within limit | AV free tier is 25 calls/day; headline fetch uses only 1 endpoint (NEWS_SENTIMENT); rate limiting is not needed for this volume |

**Key insight:** The 3-tier parse fallback in `parsing.py` is already designed for graceful degradation. Adding `ticker_decisions: list[TickerDecision] = Field(default_factory=list)` to `AgentDecision` means Pydantic will silently fill `[]` when the field is absent in the LLM response — no code changes to `parsing.py` required.

---

## Common Pitfalls

### Pitfall 1: Single `dispatch_wave()` call loses bracket differentiation
**What goes wrong:** Passing one enriched `user_message` to `dispatch_wave()` for all 100 agents gives every agent the same bracket slice.
**Why it happens:** `dispatch_wave()` takes a scalar `user_message` shared across all personas. The per-agent differentiation is only possible via `peer_contexts` list (which is per-agent) — but that field is for peer context, not the primary message.
**How to avoid:** Sub-wave per bracket group. 3 bracket groups → 3 `dispatch_wave()` calls per round. Results merged in persona order before any downstream processing (influence weights, Neo4j writes, bracket summaries).
**Warning signs:** ENRICH-02 test shows all agents receiving identical market block content regardless of bracket.

### Pitfall 2: Pydantic v2 frozen model update with `__init__`
**What goes wrong:** Calling `MarketDataSnapshot(symbol=s, headlines=h, **other_fields)` manually requires re-specifying all fields or missing some from the original.
**Why it happens:** `frozen=True` means no attribute assignment; developers attempt to create a new instance manually.
**How to avoid:** Use `snapshot.model_copy(update={"headlines": h})`. All other fields preserved automatically.
**Warning signs:** `TypeError: 'MarketDataSnapshot' object does not support item assignment` or silently dropping fields like `is_degraded`.

### Pitfall 3: JSON schema instruction not updated in `JSON_OUTPUT_INSTRUCTIONS`
**What goes wrong:** Agents never emit `ticker_decisions` because their system prompt doesn't show the new schema field.
**Why it happens:** `JSON_OUTPUT_INSTRUCTIONS` in `config.py` is the single source of truth for the JSON schema agents must follow. If not updated, qwen3.5:9b defaults to the old schema.
**How to avoid:** Update `JSON_OUTPUT_INSTRUCTIONS` to include `ticker_decisions` array with a 2-ticker worked example. Show the exact field names and types. Test by inspecting actual LLM output in logs.
**Warning signs:** All agents return `ticker_decisions=[]` (the default fallback) in every test run because they never emit the field.

### Pitfall 4: AV NEWS_SENTIMENT `feed` key missing on rate limit
**What goes wrong:** AV returns a `{"Note": "Thank you for using Alpha Vantage..."}` response (rate limit hit) instead of `{"feed": [...]}`. Accessing `data["feed"]` raises `KeyError`.
**Why it happens:** Phase 17 already handles this for GLOBAL_QUOTE and OVERVIEW. The same guard must apply to NEWS_SENTIMENT.
**How to avoid:** Mirror Phase 17's rate limit guard: `if "Note" in data: raise ValueError("Alpha Vantage rate limit exceeded")`. Catch in the outer try/except in `enrich_snapshots_with_headlines()`.
**Warning signs:** `KeyError: 'feed'` in structlog output during simulation.

### Pitfall 5: Sub-wave merging loses persona order
**What goes wrong:** Results from 3 sub-waves merged in insertion order into `all_decisions` but the order doesn't match the original `personas` list — downstream Neo4j writes (`write_decisions`) and influence weight maps use positional assumptions.
**Why it happens:** Sub-waving splits personas by bracket group; the merge must restore the original ordering.
**How to avoid:** Build a lookup by `agent_id` from all sub-wave results, then reconstruct in original `personas` list order: `all_decisions = [lookup[p.id] for p in personas]`.
**Warning signs:** `assert len(decisions) == len(worker_configs)` passes but agent IDs and decisions are misaligned in Neo4j.

### Pitfall 6: Empty `market_snapshots` must produce bare rumor (no block injected)
**What goes wrong:** `build_enriched_user_message()` called when `market_snapshots={}` (no tickers extracted); function returns `"\n\nRumor: ..."` with a leading blank section header.
**Why it happens:** `format_market_block({}, bracket)` might return `"--- Market Data ---\n"` even when empty.
**How to avoid:** `format_market_block()` returns `""` (empty string) when `snapshots` is empty. `build_enriched_user_message()` returns bare rumor when `format_market_block()` returns `""`.
**Warning signs:** Agent rationale shows "--- Market Data ---" section with no data.

---

## Code Examples

### AV NEWS_SENTIMENT Fetch Pattern (verified from Phase 17 `_fetch_alpha_vantage` pattern)

```python
# Source: Phase 17 market_data.py pattern + AV docs
async def fetch_headlines(symbol: str, av_key: str, limit: int = 10) -> list[str]:
    """Fetch news headlines from AV NEWS_SENTIMENT endpoint."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            AV_BASE_URL,
            params={
                "function": "NEWS_SENTIMENT",
                "tickers": symbol,
                "limit": limit,
                "apikey": av_key,
            },
        )
        data = resp.json()

    # Rate limit guard (mirrors Phase 17 pattern)
    if "Note" in data and "Thank you for using Alpha Vantage" in data["Note"]:
        raise ValueError("Alpha Vantage rate limit exceeded")

    feed = data.get("feed", [])
    headlines = []
    for item in feed[:limit]:
        title = item.get("title", "")
        if title:
            headlines.append(title[:120])  # truncate per-headline
    return headlines
```

### Updating Frozen `MarketDataSnapshot` with Headlines

```python
# Source: Pydantic v2 model_copy pattern
updated_snapshot = snapshot.model_copy(update={"headlines": headlines})
# Returns new frozen MarketDataSnapshot with all original fields + populated headlines
```

### `format_market_block()` — Technicals Slice Example

```python
def _format_technicals(symbol: str, snap: MarketDataSnapshot) -> str:
    """Compact key-value line for Technicals slice."""
    close = f"${snap.last_close:.2f}" if snap.last_close else "N/A"
    chg30 = f"{snap.price_change_30d_pct:+.1f}%" if snap.price_change_30d_pct is not None else "N/A"
    chg90 = f"{snap.price_change_90d_pct:+.1f}%" if snap.price_change_90d_pct is not None else "N/A"
    vol = f"{snap.avg_volume_30d/1e6:.1f}M" if snap.avg_volume_30d else "N/A"
    hi = f"${snap.fifty_two_week_high:.2f}" if snap.fifty_two_week_high else "N/A"
    lo = f"${snap.fifty_two_week_low:.2f}" if snap.fifty_two_week_low else "N/A"
    return f"{symbol}: close={close}, 30d={chg30}, 90d={chg90}, vol={vol}, 52w=[{lo}/{hi}]"
```

### Updated `JSON_OUTPUT_INSTRUCTIONS` (DECIDE-01)

The existing constant in `config.py`:
```python
JSON_OUTPUT_INSTRUCTIONS = (
    '\n\nRespond ONLY with a JSON object:\n'
    '{"signal": "buy"|"sell"|"hold", "confidence": 0.0-1.0, '
    '"sentiment": -1.0 to 1.0, "rationale": "brief reasoning", '
    '"cited_agents": []}'
)
```

Must be updated to include `ticker_decisions` with a worked 2-ticker example:
```python
JSON_OUTPUT_INSTRUCTIONS = (
    '\n\nRespond ONLY with a JSON object:\n'
    '{"signal": "buy"|"sell"|"hold", "confidence": 0.0-1.0, '
    '"sentiment": -1.0 to 1.0, "rationale": "brief reasoning", '
    '"cited_agents": [], '
    '"ticker_decisions": ['
    '{"ticker": "AAPL", "direction": "buy"|"sell"|"hold", '
    '"expected_return_pct": 5.2, "time_horizon": "1w"|"1m"|"3m"|"6m"|"1y"|"1d"}, '
    '{"ticker": "TSLA", "direction": "sell", "expected_return_pct": -3.1, "time_horizon": "1m"}'
    ']}'
)
```

Include empty array for no-ticker case: `"ticker_decisions": []`. This ensures backward compatibility when no tickers are present in the simulation.

### Sub-Wave Merge (Maintaining Persona Order)

```python
# Merge 3 bracket-group sub-wave results back to full 100-agent ordered list
decision_by_agent: dict[str, AgentDecision] = {}
for agent_id, decision in sub_wave_results:
    decision_by_agent[agent_id] = decision

all_decisions: list[tuple[str, AgentDecision]] = [
    (p.id, decision_by_agent[p.id]) for p in personas
]
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Pydantic v1 `copy(update=...)` | Pydantic v2 `model_copy(update=...)` | Pydantic v2 (2023) | Must use `model_copy`, not `copy` |
| `httpx` context manager per call | Shared `httpx.AsyncClient` within single function | Best practice | Reuse connection pool; Phase 17 uses per-function context manager |

---

## Open Questions

1. **Sub-wave dispatch order and influence weight interaction**
   - What we know: `compute_influence_edges()` and `write_decisions()` are called after all decisions are collected; they use `agent_id` lookups, not positional order.
   - What's unclear: Does any downstream code in `simulation.py` assume `decisions[i]` corresponds to `worker_configs[i]` by position rather than by `agent_id`?
   - Recommendation: Audit every downstream use of `agent_decisions` list in `simulation.py` before implementing sub-wave merge. The existing `zip(worker_configs, decisions)` pattern (lines 515, 918, 1036) is positional — the merge must restore exact original `personas` list order.

2. **Char cap tuning — what qwen3.5:9b actually tokenizes**
   - What we know: CONTEXT.md D-03 defers tokenizer validation; STATE.md flags this as a blocker concern. qwen3.5 uses its own tokenizer (not cl100k).
   - What's unclear: How many tokens per character for typical market data content.
   - Recommendation: Use conservative caps (plan estimates 900/1000/2000 chars for Technical/Fundamental/Earnings groups). For a 4096-token context with ~800 tokens already in system prompt + peer context, ~3000 tokens remain. At ~4 chars/token for English prose, 3000 tokens ≈ 12,000 chars — so even 2000-char cap is well within budget. Flag for post-Phase 18 calibration.

3. **Whether `direction` in `TickerDecision` should reuse `SignalType`**
   - What we know: CONTEXT.md Specifics section recommends reusing `SignalType` (BUY/SELL/HOLD/PARSE_ERROR). The Discretion section leaves this open.
   - Recommendation: Reuse `SignalType`. Agents already know `"buy"|"sell"|"hold"` from the existing schema. Adding a separate enum risks parse variance.

---

## Environment Availability

All external dependencies for Phase 18 are already verified present from Phase 17:

| Dependency | Required By | Available | Notes |
|------------|------------|-----------|-------|
| `httpx` | AV NEWS_SENTIMENT fetch | Already installed (Phase 17) | No version change needed |
| `yfinance` | Market data (Phase 17, unchanged) | Already installed | No change |
| `ALPHA_VANTAGE_API_KEY` | Headlines fetch | Optional — graceful skip if absent | D-10 locks silent skip with WARNING |
| Ollama worker model | Agent inference | Already running from Phase 17 | No change |
| Neo4j | Graph writes | Already running from Phase 17 | No change |

Step 2.6: No new external dependencies identified. All tools and services required by Phase 18 are already available and verified by Phases 16–17.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | `pyproject.toml` (pytest-asyncio mode configured) |
| Quick run command | `uv run pytest tests/test_enrichment.py -x -q` |
| Full suite command | `uv run pytest -x -q` |
| Baseline | 548 tests collected (Phase 17 complete) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ENRICH-01 | `build_enriched_user_message()` returns non-empty block when snapshots provided; returns bare rumor when snapshots empty | unit | `uv run pytest tests/test_enrichment.py::test_build_enriched_user_message -x` | Wave 0 |
| ENRICH-01 | Char budget: block length <= `MAX_MARKET_BLOCK_CHARS[bracket]` for all 3 slice groups | unit | `uv run pytest tests/test_enrichment.py::test_char_budget -x` | Wave 0 |
| ENRICH-02 | Different brackets produce different formatted blocks from same snapshots | unit | `uv run pytest tests/test_enrichment.py::test_bracket_slices -x` | Wave 0 |
| ENRICH-02 | Technicals block contains price/volume fields, not PE/earnings | unit | `uv run pytest tests/test_enrichment.py::test_technicals_fields -x` | Wave 0 |
| ENRICH-02 | Fundamentals block contains PE/revenue, not price_change_30d | unit | `uv run pytest tests/test_enrichment.py::test_fundamentals_fields -x` | Wave 0 |
| ENRICH-02 | Earnings/Insider block contains earnings_surprise, EPS, headlines | unit | `uv run pytest tests/test_enrichment.py::test_earnings_insider_fields -x` | Wave 0 |
| ENRICH-03 | `fetch_headlines()` returns list of str when AV responds with feed | unit (mocked httpx) | `uv run pytest tests/test_enrichment.py::test_fetch_headlines_success -x` | Wave 0 |
| ENRICH-03 | `enrich_snapshots_with_headlines()` skips and logs WARNING when av_key is None | unit | `uv run pytest tests/test_enrichment.py::test_enrich_no_av_key -x` | Wave 0 |
| ENRICH-03 | AV rate limit response raises ValueError, caught by outer try/except → empty headlines | unit (mocked httpx) | `uv run pytest tests/test_enrichment.py::test_fetch_headlines_rate_limit -x` | Wave 0 |
| DECIDE-01 | `TickerDecision` model validates with required fields | unit | `uv run pytest tests/test_parsing.py::test_ticker_decision_model -x` | Wave 0 |
| DECIDE-01 | `AgentDecision` with `ticker_decisions` list serializes/deserializes via `model_validate_json` | unit | `uv run pytest tests/test_parsing.py::test_agent_decision_with_ticker_decisions -x` | Wave 0 |
| DECIDE-02 | `parse_agent_decision()` on JSON without `ticker_decisions` field returns `ticker_decisions=[]` | unit | `uv run pytest tests/test_parsing.py::test_parse_agent_decision_backwards_compat -x` | Wave 0 |
| DECIDE-02 | `parse_agent_decision()` on JSON with malformed `ticker_decisions` does not return PARSE_ERROR | unit | `uv run pytest tests/test_parsing.py::test_parse_agent_decision_malformed_ticker_decisions -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_enrichment.py tests/test_parsing.py -x -q`
- **Per wave merge:** `uv run pytest -x -q` (full 548+ suite)
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_enrichment.py` — new file; covers ENRICH-01, ENRICH-02, ENRICH-03
- [ ] New test cases in `tests/test_parsing.py` — covers DECIDE-01, DECIDE-02 (file exists; new test class only)

*(Framework install: not needed — pytest-asyncio already configured)*

---

## Project Constraints (from CLAUDE.md)

| Directive | Impact on Phase 18 |
|-----------|-------------------|
| 100% async (`asyncio`), no blocking I/O | `fetch_headlines()` uses `httpx.AsyncClient` async; no `requests` or `urllib` |
| Local first — no cloud APIs except Miro | AV is already an approved exception (Phase 17); NEWS_SENTIMENT is same provider |
| Memory safety — monitor RAM | No new long-lived objects; `MarketDataSnapshot.headlines` is a flat `list[str]` of capped strings; total overhead for 3 tickers × 10 headlines × 120 chars ≈ 3.6KB |
| Miro API — bulk only, 2s buffer | Not relevant; Phase 18 makes no Miro changes |
| Python 3.11+, strict typing | All new functions annotated; `from __future__ import annotations` in all new files |
| `uv` package manager | No new packages; no `pip install` |
| `pytest-asyncio` for tests | Async test class methods require `@pytest.mark.asyncio` or `asyncio_mode = "auto"` in config |
| `structlog` for logging | `logger = structlog.get_logger(component="enrichment")` in enrichment.py |
| `pydantic` for validation | `TickerDecision(BaseModel, frozen=True)` follows established frozen model convention |
| GSD Workflow Enforcement | All file changes go through `/gsd:execute-phase` |

---

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection — `src/alphaswarm/types.py`, `market_data.py`, `parsing.py`, `simulation.py`, `worker.py`, `config.py`, `batch_dispatcher.py`, `tests/test_market_data.py`, `tests/conftest.py`
- Phase 18 CONTEXT.md decisions D-01 through D-11 — locked implementation decisions
- Phase 17 codebase patterns — `_fetch_alpha_vantage()`, `_safe_float()`, `asyncio.to_thread()` patterns

### Secondary (MEDIUM confidence)
- Alpha Vantage NEWS_SENTIMENT endpoint: `https://www.alphavantage.co/documentation/` — response structure (`feed[].title`, rate limit `Note` key) verified via web search cross-referencing multiple sources
- Pydantic v2 `model_copy(update=...)` — established v2 API for updating frozen models

### Tertiary (LOW confidence)
- Token-per-character estimate for qwen3.5 tokenizer (~4 chars/token for English prose) — estimate only; STATE.md explicitly flags tokenizer validation as deferred

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; all libraries active in codebase
- Architecture patterns: HIGH — sub-wave approach derived directly from existing `dispatch_wave()` signature constraints and D-01 lock
- Pitfalls: HIGH — pitfalls 1, 3, 4, 5 derived from direct code inspection; pitfall 2 from Pydantic v2 docs
- AV NEWS_SENTIMENT response format: MEDIUM — verified response key names (`feed`, `title`) via multiple secondary sources; not directly inspected

**Research date:** 2026-04-06
**Valid until:** 2026-05-06 (stable stack; AV endpoint format is stable)
