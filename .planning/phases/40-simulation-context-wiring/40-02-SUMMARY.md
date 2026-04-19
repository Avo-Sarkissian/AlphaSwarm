---
phase: 40-simulation-context-wiring
plan: 02
subsystem: simulation
tags:
  - phase-40
  - context-wiring
  - context-formatter
  - market-context
  - news-context
  - ingestion-consumption
  - ISOL-04
  - SIM-04
  - INGEST-03
dependency_graph:
  requires:
    - 40-01 (market_context plumbing through dispatch_wave/run_round1)
    - 37 (ContextPacket, MarketSlice, NewsSlice types)
    - 38 (MarketDataProvider + NewsProvider protocols)
  provides:
    - context_formatter.format_market_context
    - run_simulation.market_provider
    - run_simulation.news_provider
  affects:
    - src/alphaswarm/simulation.py
    - src/alphaswarm/context_formatter.py (new)
    - tests/test_simulation.py
    - tests/test_context_formatter.py (new)
    - tests/test_logging.py
tech_stack:
  added: []
  patterns:
    - "asyncio.gather parallel provider fetch (market + news) — single trip, no sequential awaits"
    - "Pure formatter function separated from simulation.py for testability"
    - "Decimal.__str__ for financial-precision rendering (no float round trips)"
    - "Greedy-fill budget cap (mirrors _format_peer_context) — drops tail entities, never mid-block truncation"
    - "Provider-agnostic integration via typed Protocols (MarketDataProvider / NewsProvider)"
    - "_TICKER_RE defense-in-depth regex at orchestrator layer (duplicates Phase 38 rss_provider)"
    - "ISOL-04 redaction canary test (frozen set membership assertion)"
key_files:
  created:
    - src/alphaswarm/context_formatter.py
    - tests/test_context_formatter.py
  modified:
    - src/alphaswarm/simulation.py
    - tests/test_simulation.py
    - tests/test_logging.py
decisions:
  - "Two-provider gate semantics: `market_provider is None OR news_provider is None` → skip assembly entirely. No partial assembly. Keeps control flow linear and test surface small (Pitfall 8)."
  - "_TICKER_RE defense-in-depth: re-apply the Phase 38 rss_provider regex at the simulation layer BEFORE calling market_provider.get_prices. Avoids pointless yfinance round trips for company-name entities. Company-name limitation is scoped as KNOWN and tested at both layers."
  - "Company-name entity limitation (REVIEWS concern #2): orchestrator emits human-readable names (\"NVIDIA\", \"Federal Reserve\") not tickers. Formatter joins by exact entity==ticker equality, so price/fundamentals block is absent for those entities. News still attaches. Two pinning tests: formatter layer (test_format_market_context_company_name_entity_news_only) + simulation layer (test_run_simulation_company_name_entity_gets_news_only). Closing this limitation is deferred to a future phase (name→ticker resolver)."
  - "Formatter returns None (not \"\") when nothing to emit — callers MUST NOT append an empty system message (Pitfall 5)."
  - "context_packet_assembled log includes total_headlines for headline-cap debugging (Gemini review suggestion adopted)."
metrics:
  duration_minutes: 25
  completed_date: 2026-04-19
---

# Phase 40 Plan 02: Simulation-Level Context Assembly Summary

Plan 02 wires the Phase 37/38 ingestion seam directly into `run_simulation`:
agents now receive a grounded market-context system message in Round 1
whenever both providers are configured, with clean backward-compatible
degradation (structured warning + `market_context=None`) when either is
missing.

## What Shipped

**1. Pure formatter module — `src/alphaswarm/context_formatter.py`**

A zero-dependency (beyond `ContextPacket`) formatter function with a clear
contract:

```python
def format_market_context(packet: ContextPacket, *, budget: int = 4000) -> str | None
```

- Indexes `packet.market` by ticker and `packet.news` by entity, both
  filtering out `staleness == "fetch_failed"` slices (D-03).
- Emits entities in `packet.entities` order. Per entity:
  `== {entity} ==` → `Price: ${decimal}` (if present) → `Fundamentals: P/E,
  EPS, Mkt Cap` (comma-joined, only non-None fields) → `Recent headlines:`
  (max 5 bullets, D-09).
- Budget-greedy fill (mirrors `_format_peer_context` simulation.py:314):
  stops at the first entity whose block would overflow the budget. Never
  truncates mid-block. Default budget 4000 matches SHOCK_TEXT_MAX_LEN.
- Returns `None` when nothing to emit (all entities filtered, or every
  data item is fetch_failed). Callers skip the system message entirely
  (Pitfall 5).
- Module docstring documents the company-name vs ticker KNOWN LIMITATION
  (REVIEWS concern #2) — entities are joined by exact equality, so
  orchestrator output "NVIDIA" does not match MarketSlice("NVDA").

**2. `run_simulation` signature extension + context assembly block**

Two new keyword-only params:

```python
market_provider: MarketDataProvider | None = None,
news_provider: NewsProvider | None = None,
```

After `inject_seed` and before `run_round1`, a single conditional block:

- If either provider is `None` → emit `context_assembly_skipped` warning
  with `reason="no_providers_configured"` and set `market_context_str = None`.
- Else → extract entity names; filter to ticker-shape only via
  `_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")`; call both providers in parallel
  via `asyncio.gather(get_prices(tickers), get_headlines(entity_names))`;
  build the `ContextPacket`; log `context_packet_assembled` with
  `total_headlines` (Gemini review suggestion); call `format_market_context`.
- Forward the result to `run_round1(..., market_context=market_context_str)`
  (Plan 01 already added the kwarg to the callee).

Rounds 2-3 are untouched — D-06 preserves "market context Round 1 only."

**3. `_TICKER_RE` defense-in-depth constant at module scope**

Mirrors `alphaswarm.ingestion.rss_provider._TICKER_RE` (Phase 38 T-38-01).
Re-applying at the orchestrator layer means company-name entities never
reach `market_provider.get_prices`. For T-40-04 (URL injection via seed
entity), the rss_provider-side regex already secures the network call;
this simulation-layer filter is pure performance hygiene (no wasted
yfinance requests).

**4. 19 new tests — all green**

Formatter (10 tests in `tests/test_context_formatter.py`):
- Full block emission with price + fundamentals + headlines in D-08 order
- Headline cap at 5 (D-09)
- Silent skip of `fetch_failed` market slice (news-only block)
- Silent skip of `fetch_failed` news slice (market-only block)
- Skip of entities with no data (no empty blocks)
- `None` return when all fetch_failed
- `None` return when entities is empty
- Budget cap respected (no mid-block truncation)
- Decimal precision preserved via `__str__` (no float rounding)
- Company-name entity news-only limitation pin (REVIEWS concern #2)

Simulation (8 tests in `tests/test_simulation.py`):
- `test_run_simulation_assembles_context_packet` — full positive path
- `test_run_simulation_skips_context_when_market_provider_missing`
- `test_run_simulation_skips_context_when_news_provider_missing`
- `test_run_simulation_skips_context_when_both_providers_missing`
- `test_run_simulation_backward_compatible` — SIM-04 omit-both-kwargs path
- `test_run_simulation_formatter_drops_all_fetch_failed`
- `test_run_simulation_filters_non_ticker_entities_from_market_call` —
  entities=["NVDA", "Federal Reserve", "AAPL"] → get_prices receives only
  ["NVDA", "AAPL"], get_headlines receives all three
- `test_run_simulation_company_name_entity_gets_news_only` — REVIEWS
  concern #2 pinned end-to-end through simulation layer

Logging canary (1 test in `tests/test_logging.py`):
- `test_context_packet_fields_not_in_pii_redaction_set` — asserts
  `"market"`, `"news"`, `"entities"` are NOT members of
  `_LITERAL_NORMALIZED`. Prevents future drift where a maintainer adds
  these keys to the redaction list, which would silently corrupt
  ContextPacket log events.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Two-provider AND gate | Simpler control flow, smaller test matrix, no "partial assembly" corner cases | Single `if market_provider is None or news_provider is None` branch |
| `_TICKER_RE` at simulation layer | Avoid wasted yfinance calls for company-name entities while Phase 38 rss_provider still handles the security-critical URL-injection case | Regex literal mirrored; duplication acknowledged and called out in comments |
| Pure formatter module | Unit testability without simulation fixture set; keeps string-templating logic separable | `context_formatter.py` with one public function, 10 targeted unit tests |
| Company-name limitation documented, not fixed | A name→ticker resolver is a scope-expanding new LLM surface or alias-map; both out of scope for Phase 40 | Module docstring + two pinning tests (formatter + simulation) |
| `None` return from formatter | Signals "do not emit a system message" without sentinel strings | Callers do nothing when `market_context_str is None`; run_round1 plumbing already handles None |
| `total_headlines` in `context_packet_assembled` log | Headline caps + silent drops are operationally opaque — structured count aids debugging | Gemini review suggestion adopted |

## Verification Results

```
uv run pytest tests/test_simulation.py tests/test_context_formatter.py \
    tests/test_worker.py tests/test_batch_dispatcher.py tests/test_logging.py -x
→ 126 passed, 3 warnings
```

```
uv run mypy src/alphaswarm/context_formatter.py
→ Success: no issues found in 1 source file
```

```
uv run lint-imports
→ Holdings isolation contract KEPT (no drift from new module)
```

**Note on `mypy src/alphaswarm/simulation.py`:** Six pre-existing errors remain
(lines 28, 107, 1185, 1204, 1207, 1244 pre-edit — `BracketConfig` re-export,
`str | None` variable, generic `dict` missing type params, `OllamaClient.generate`
keyword). These existed before Plan 02's changes and are out of scope per
deviation rule (scope boundary). Verified via `git stash + mypy` — the same
six errors appear with the commit reverted.

## Deviations from Plan

None — plan executed exactly as written.

- Rule 1 (bug) — none triggered
- Rule 2 (missing critical functionality) — none triggered (threat model T-40-04
  through T-40-08 fully mitigated per the plan's inline spec: `_TICKER_RE`
  applied, ISOL-04 canary in place, budget cap shipped, provider exceptions
  accepted per D-19)
- Rule 3 (blocking issue) — none triggered
- Rule 4 (architectural change) — none triggered

## Commits

| Task | Message | Hash |
|------|---------|------|
| 1 | feat(40-02): add format_market_context pure formatter + ISOL-04 canary | 7c2a7bb |
| 2 | feat(40-02): wire ContextPacket assembly into run_simulation | 6fbe23d |

## Files

**Created:**
- `src/alphaswarm/context_formatter.py` (105 lines including module docstring)
- `tests/test_context_formatter.py` (236 lines, 10 tests)

**Modified:**
- `src/alphaswarm/simulation.py` (+58 lines: imports, _TICKER_RE constant,
  run_simulation signature + context-assembly block + run_round1 forwarding;
  docstring lifecycle updated)
- `tests/test_simulation.py` (+456 lines: 1 helper + 8 new tests)
- `tests/test_logging.py` (+13 lines: 1 canary test)

## Self-Check

**Files created:**
- FOUND: src/alphaswarm/context_formatter.py
- FOUND: tests/test_context_formatter.py

**Files modified:**
- FOUND: src/alphaswarm/simulation.py
- FOUND: tests/test_simulation.py
- FOUND: tests/test_logging.py

**Commits present:**
- FOUND: 7c2a7bb
- FOUND: 6fbe23d

## Self-Check: PASSED
