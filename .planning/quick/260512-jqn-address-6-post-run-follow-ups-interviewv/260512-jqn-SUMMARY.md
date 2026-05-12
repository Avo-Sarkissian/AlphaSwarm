---
quick_task: 260512-jqn
title: "Address 6 post-run follow-ups: InterviewV2 CSS gap, /api/edges, governor slots, rationale window, SignalWire live audit, advisory items[]"
date: 2026-05-12
status: complete
commits:
  - 42a77c5 fix(41.6-04): port missing CSS for InterviewV2 + Onboarding + BracketDeepDive takeovers
  - 0474938 fix(api): compute INFLUENCED_BY edges after Round 3 so /api/edges?round=3 is non-empty
  - 8910b81 feat(state): emit governor current_slots + active_count in WS frame (closes KR-41.1-05)
  - 0e6e1c0 feat(state): rationale sliding window (closes mid-round-blackout + reconnect-data-loss)
  - 0ef828e feat(data): live SignalWire audit (replaces DEV mock seed; mocks stay as DEV fallback)
  - adc0fac feat(advisory): one-item-per-holding + sector enrichment + UI fallback (closes task #10)
requirements_closed:
  - POST-RUN-FU-01
  - POST-RUN-FU-02
  - POST-RUN-FU-03
  - POST-RUN-FU-04
  - POST-RUN-FU-05
  - POST-RUN-FU-06
krs_closed:
  - KR-41.1-05 (governor slot stub)
krs_unchanged:
  - KR-41.6-14 (DEV-only mock dynamic import — mocks/wire + mocks/sources stay on disk; only the SignalWire CONSUMER swaps to live)
---

# Quick Task 260512-jqn — Summary

Closed the six post-run follow-ups surfaced during the 2026-05-10/11 live UAT
against cycle 7ab3984d-36a5-4d6a-9178-bfaa842b15d2. Each item is an atomic
commit; the bundle was scoped as one quick task because every individual
change is narrow (1-5 files of focused work) and they share a common
deliverable: making the live UAT pass end-to-end with real data on every
surface.

## ITEM 1 — InterviewV2 + Onboarding + BracketDeepDive CSS gap

**Commit:** `42a77c5`
**Files:** `frontend/src/styles.css` (+429 lines, no deletions)
**Gates:** `npm run check` + `npm run build` green.

Added comprehensive CSS for the three W4 takeover components scheduled for
Plan 41.6-04. Without these rules the modals would render as glitched
strips because none of their `iv-*`, `ob-*`, `bdd-*`, `agent-*` class
names matched any existing rule. The CSS lands ahead of the W4 port so
the components work the moment they're ported.

Uses existing CSS variables only — no hex literals, no design-token leaks
(satisfies the project hard rule on tokenization). Follows the
`.adv-takeover` + `.ds-takeover` pattern established in earlier 41.6 plans.

## ITEM 2 — /api/edges Cypher fix + regression test

**Commit:** `0474938`
**Files:** `src/alphaswarm/simulation.py`, `tests/test_edges_route.py` (new)
**Gates:** `uv run pytest tests/test_edges_route.py -x -q` → 4 passed.

Root cause was producer-side, not route-side: simulation.py only called
`graph_manager.compute_influence_edges` for `up_to_round=1` (after R1)
and `up_to_round=2` (after R2). Round 3 never materialized INFLUENCED_BY
relationships in Neo4j, so the route's round-filtered Cypher returned
`{"edges": []}` even for cycles with 100 R3 decisions.

Fix: one `compute_influence_edges(cycle_id, up_to_round=3, total_agents=...)`
call after Round 3 decisions are written, mirroring the R1/R2 pattern.
Also threaded the new `round3_weights` into the (now-removed) rationale
selection.

Regression coverage asserts the route envelope shape, the empty-result
non-404 contract, that the `round` query param threads through to the
graph manager, and that round outside [1,3] returns 422.

## ITEM 3 — Governor slot metrics in WS frame (KR-41.1-05 closed)

**Commit:** `8910b81`
**Files:** `frontend/src/adapter/frame.ts`, `frontend/src/types.ts`, `tests/test_state.py`
**Gates:** 82 tests passed; check + build green.

Backend was already correct — `GovernorMetrics.current_slots` and
`active_count` (state.py:23-24) are populated by governor.py:391-400 on
every state transition, and broadcaster's `dataclasses.asdict` already
propagates new fields automatically.

Real work was in frame.ts: dropped the `{slotsUsed: gov.current_slots,
slotsMax: 8}` stub and read both fields directly. PARALLEL SLOTS KPI tile
now shows live numerator/denominator (e.g. 12/16) during dispatch instead
of freezing at 0/8.

Test fixture `test_governor_metrics_includes_slots_for_ws_frame` asserts
both fields survive `dataclasses.asdict` serialization to the wire format.

## ITEM 4 — Rationale sliding window refactor

**Commit:** `0e6e1c0`
**Files:** `src/alphaswarm/state.py`, `src/alphaswarm/web/broadcaster.py`,
`src/alphaswarm/batch_dispatcher.py`, `src/alphaswarm/simulation.py`,
`tests/test_state.py`, `tests/test_batch_dispatcher.py`
**Gates:** 106 tests passed (state + batch_dispatcher + governor + edges_route);
frontend check + build green.

Replaced the drain-based `asyncio.Queue` rationale path with a peek-only
`deque(maxlen=50)` sliding window. The prior design lost data in two ways:

1. **Mid-round blackout** — `_push_top_rationales` only fired at end-of-round,
   so the WS feed was empty for the entire 100-agent dispatch window.
2. **Reconnect data loss** — `drain_rationales(5)` destructively popped per
   consumer, so reconnecting WS clients always saw an empty feed.

Changes:
- `state.py`: `_rationale_queue: asyncio.Queue` → `_rationale_window: deque(maxlen=50)`;
  snapshot now embeds the full window directly; `peek_rationales()` added;
  `drain_rationales` retained as a peek wrapper for TUI back-compat.
- `web/broadcaster.py`: dropped the explicit `drain_rationales(5)` override —
  `dataclasses.asdict(snap)` picks up `rationale_entries` directly.
- `batch_dispatcher.py`: new `round_num` kwarg; after a successful inference,
  one `RationaleEntry` is pushed into state_store (PARSE_ERROR signals skip).
- `simulation.py`: round_num threaded through all 3 `dispatch_wave` call sites
  + the `_dispatch_round` helper; the 3 end-of-round `_push_top_rationales`
  calls removed (streaming covers per-agent now; duplication avoided).

`RationalesContext.tsx` was already a one-line `useMemo` over `frame.rationales`
from an earlier 41.6 plan — no change. The public hook contract
`useRationales(): { rationales: RationaleView[] }` and the
`RationalesProvider({ frame, children })` prop signature are unchanged.

## ITEM 5 — SignalWire live API audit

**Commit:** `0ef828e`
**Files:** `src/alphaswarm/data_audit.py` (new), `src/alphaswarm/state.py`,
`src/alphaswarm/ingestion/yfinance_provider.py`, `src/alphaswarm/ingestion/rss_provider.py`,
`src/alphaswarm/web/app.py`, `tests/test_data_audit.py` (new),
`frontend/src/hooks/useDataSourceAudit.ts` (new), `frontend/src/types.ts`,
`frontend/src/adapter/frame.ts`, `frontend/src/components/v2.tsx`
**Gates:** 66 backend tests passed; frontend check + build green;
production grep gates: SIGNAL_WIRE_SEED / mocks/wire / mocks/sources all 0 hits.

SignalWire ticker now scrolls real yfinance/RSS calls. KR-41.6-14 stays
valid — the mock files stay on disk; only the SignalWire CONSUMER swaps
from mock to live.

Backend wiring:
- `data_audit.py` — `DataSourceAuditEntry` (frozen) + `DataSourceAuditBuffer`
  (deque maxlen=100, lock-free O(1) record, defensive secret-pattern refusal
  for threat T-260512-jqn-03).
- `state.py` — StateStore holds the buffer; `record_data_source()` +
  `peek_data_source_audit()` exposed; new `StateSnapshot.data_source_audit`
  serialized through `dataclasses.asdict` to the WS wire format.
- `yfinance_provider.py` + `rss_provider.py` — opt-in `attach_audit_sink()`
  pattern. After each batch fetch, the provider records one entry per
  ticker / entity (sync, non-fatal — observability MUST NOT break fetch).
- `web/app.py` — lifespan attaches the state_store as audit sink right
  after providers are constructed.

Frontend wiring:
- `frame.ts` adapter maps wire snake_case `data_source_audit` →
  camelCase `dataSourceAudit: DataSourceAuditView[]`.
- New `useDataSourceAudit()` hook returns `lastFrame.dataSourceAudit ?? []`.
- `SignalWire` consumer in v2.tsx: live path is primary; DEV-only mock
  fallback retained for the IDLE / pre-first-call window so DEV builds
  still show motion. Production renders a "WAITING FOR FIRST PROVIDER
  CALL…" placeholder.

## ITEM 6 — Advisory items[] + sector enrichment + frontend fallback

**Commit:** `adc0fac`
**Files:** `src/alphaswarm/advisory/sector_map.py` (new), `src/alphaswarm/advisory/prompt.py`,
`src/alphaswarm/advisory/engine.py`, `frontend/src/components/v2.tsx`,
`tests/test_advisory_synthesize.py` (new)
**Gates:** 19 tests passed (`test_advisory_synthesize.py` + existing
`unit/test_advisory.py`); frontend check + build green.

AdvisoryV2 on cycle 7ab3984d-... returned `items=[]` because the prior
prompt explicitly instructed the orchestrator to OMIT holdings without
strong signals. Fix:

- **Prompt rewrite** in `_SYSTEM_INSTRUCTIONS`: "CRITICAL — ONE ITEM PER
  HOLDING. NEVER OMIT A HOLDING." HOLD@0.20-0.40 confidence placeholder
  documented for low-conviction holdings. `affected_holdings` redefined
  as count of items with directional or high-conviction view (distinct
  from `total_holdings`).
- **Sector map** (`sector_map.py`) — curated 32-entry SECTOR_MAP covering
  the user's Schwab + Roth holdings (Roth MRVL/QQQ duplicates collapse).
  Each entry: sector, region_exposure, supply_chain_sensitivity, macro_beta.
  UNKNOWN_SECTOR default for off-portfolio tickers.
- **Engine enrichment** — `_enrich_holdings` attaches sector fields and
  `relevance_score = |entity_impact| * |macro_beta| + 0.5 * seed_match`.
  `synthesize()` splits enriched output into top-15 (full enrichment) +
  rest (sector tag only) before calling `build_advisory_prompt`.
- **Frontend fallback** — Holdings tab now renders an explicit empty-state
  card explaining the items=[] case (pointing at ITEM 6 prompt rewrite
  as the resolution path).

Test coverage (11 cases): 32-ticker SECTOR_MAP completeness, UNKNOWN
fallback, case-insensitive lookup, relevance sort order, seed-match
bonus, unknown-ticker enrichment, prompt directive presence, top/rest
rendering, legacy `holdings` kwarg back-compat.

## Deviations from Plan

### Auto-fixed Issues

**[Rule 3 — Blocking issue] Frontend missing node_modules in worktree**
- Found during: ITEM 1
- Issue: `npm run check` failed with `tsc: command not found` because the
  worktree had no `node_modules/` directory.
- Fix: `npm install` inside the worktree's `frontend/` directory.
- Out of scope for any specific item — environment setup.

**[Rule 3 — Blocking issue] OllamaInferenceError signature in test**
- Found during: ITEM 4 (`test_safe_agent_inference_skips_rationale_on_parse_error`)
- Issue: `OllamaInferenceError("simulated failure")` raised `TypeError:
  missing 1 required positional argument: 'model'`.
- Fix: pass `model="test-model"` kwarg.
- Recorded in commit message.

**[Rule 3 — Blocking issue] Mock OllamaClient missing eval_count/eval_duration**
- Found during: ITEM 4 (`test_safe_agent_inference_streams_rationale_push_on_success`)
- Issue: `_make_mock_client` returns a MagicMock chat response; with the
  ITEM 4 change, `state_store` is now non-None in the streaming test path,
  which triggers `worker.infer`'s TPS read of `response.eval_count` +
  `response.eval_duration`. MagicMock comparisons with `int` raise TypeError.
- Fix: new helper `_make_mock_client_with_metadata` that supplies numeric
  eval_count=50 and eval_duration=1_000_000_000.
- Recorded in commit message.

**[Rule 4-ish — Optional design choice that was made automatically]
Plan said "delete `_push_top_rationales` calls"; kept the helper function
itself for tooling.**
- Found during: ITEM 4
- Plan says "Option A (delete): remove all 3 calls + the method body."
- Action: removed all 3 calls in simulation.py, KEPT the function body
  because two existing tests still reference it
  (test_push_top_rationales_sorts_by_influence /
  test_push_top_rationales_skips_parse_errors). Deleting would cascade
  into a non-trivial test rewrite that's not central to ITEM 4's goal.
- Updated those two tests to use the new peek semantics instead of drain.
- This is a defensible Option-A variant — the helper is now dead code in
  production paths but still exercisable from tests / TUI. Documented in
  the ITEM 4 commit message.

### Out-of-scope discoveries (logged to deferred-items.md)

**Pre-existing test failures in `tests/test_simulation.py`** — 4 cases
asserting `"[quants]" in result` but the actual format includes the agent
id prefix `"[agent_00|quants]"`. Discovered while validating ITEM 2 didn't
break anything. Confirmed pre-existing on `git stash`. Logged to
`.planning/phases/41.6-.../deferred-items.md` and NOT fixed (out of scope
per Rule 3 SCOPE BOUNDARY).

## Threat Flags

None. ITEM 5's `record_data_source` defensively refuses to log strings
containing `sk-`, `api_key=`, or `bearer ` prefixes (threat
T-260512-jqn-03 mitigated). ITEM 2's Cypher already used parameterized
queries (no string-format injection — threat T-260512-jqn-01 already
mitigated). No new surface introduced beyond what the plan's threat
model already enumerated.

## Self-Check: PASSED

Verified:
- All 6 commit hashes present on the worktree branch:
  - `42a77c5 fix(41.6-04): port missing CSS for InterviewV2 + Onboarding + BracketDeepDive takeovers`
  - `0474938 fix(api): compute INFLUENCED_BY edges after Round 3 so /api/edges?round=3 is non-empty`
  - `8910b81 feat(state): emit governor current_slots + active_count in WS frame (closes KR-41.1-05)`
  - `0e6e1c0 feat(state): rationale sliding window (closes mid-round-blackout + reconnect-data-loss)`
  - `0ef828e feat(data): live SignalWire audit (replaces DEV mock seed; mocks stay as DEV fallback)`
  - `adc0fac feat(advisory): one-item-per-holding + sector enrichment + UI fallback (closes task #10)`
- All created files exist:
  - `src/alphaswarm/data_audit.py`
  - `src/alphaswarm/advisory/sector_map.py`
  - `frontend/src/hooks/useDataSourceAudit.ts`
  - `tests/test_edges_route.py`
  - `tests/test_data_audit.py`
  - `tests/test_advisory_synthesize.py`
- Final consolidated gate: 133 backend tests passed for touched modules;
  frontend `npm run check` + `npm run build` green; production grep gates
  (SIGNAL_WIRE_SEED / mocks/wire / mocks/sources / window.AS_DATA / window.Icon)
  all 0 hits.

## Live UAT instructions (deferred — requires backend running)

The user can validate end-to-end by:
1. Hard-refresh dashboard (clear cached `dist/`).
2. Trigger a new sim from Idle.
3. Observe during R1: PARALLEL SLOTS shows live numerator (ITEM 3),
   Rationale Feed populates progressively (ITEM 4), SignalWire ticker
   scrolls real provider calls (ITEM 5).
4. Click any agent → InterviewV2 renders as full-screen modal (ITEM 1
   CSS — requires W4 components to land).
5. After R3 complete: `curl /api/edges/{cycle_id}?round=3 | jq '.edges|length'`
   returns > 0 (ITEM 2). Open AdvisoryV2 → Holdings tab shows all 32
   tickers (ITEM 6 — requires advisory re-trigger on the post-fix cycle).
