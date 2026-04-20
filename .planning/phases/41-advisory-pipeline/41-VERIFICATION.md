---
phase: 41-advisory-pipeline
verified: 2026-04-20T02:15:00Z
status: human_needed
score: 4/4 roadmap success criteria verified (automated); 1 human checkpoint documented as approved in SUMMARY but unconfirmable programmatically
re_verification: false
human_verification:
  - test: "Confirm 16-step browser flow approval is authentic"
    expected: "User typed 'approved' after completing all 16 steps in Plan 41-03 Task 3"
    why_human: "41-03-SUMMARY.md records approval on 2026-04-20 but this verifier cannot programmatically confirm the browser session occurred; human must affirm the approval is genuine"
---

# Phase 41: Advisory Pipeline Verification Report

**Phase Goal:** After simulation completes, synthesize a personalized advisory by joining the agent consensus signals against the user's PortfolioSnapshot holdings — surfacing which positions are most affected by the simulated market reaction.
**Verified:** 2026-04-20T02:15:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `alphaswarm.advisory.synthesize()` joins bracket consensus signals against holdings tickers, returns ranked `AdvisoryItem` list | ✓ VERIFIED | `engine.py` implements asyncio.gather prefetch + LLM call + D-07 ranking; 8 unit tests pass (ranking order confirmed by `test_synthesize_returns_ranked_list`) |
| 2 | `POST /api/advisory/{cycle_id}` triggers synthesis and returns advisory JSON; Vue `AdvisoryPanel.vue` renders it post-simulation | ✓ VERIFIED | Route exists with 202/404/500 responses; AdvisoryPanel.vue (601 lines) exists with polling state machine; build passes; 12 route tests pass |
| 3 | ISOL-07 four-surface canary ACTIVE: `_minimal_simulation_body` replaced with real `synthesize()` call; no holdings values leak to logs/Neo4j/WS/prompts | ✓ VERIFIED | `_minimal_simulation_body` absent from canary file; `await synthesize(` present at line 93; 10 canary tests pass including all four negative-assertion surfaces |
| 4 | Advisory uses orchestrator model with lifecycle serialization — never concurrent with interviews or report generation | ✓ VERIFIED | `_run_advisory_synthesis` wraps in try/finally with `load_model`/`unload_model`; 409 guards for both `report_task` and `advisory_task` in flight; `test_post_advisory_409_report_in_progress` and `test_post_advisory_409_conflict` pass |

**Score:** 4/4 roadmap success criteria verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/alphaswarm/advisory/__init__.py` | Public re-exports: synthesize, AdvisoryItem, AdvisoryReport | ✓ VERIFIED | Exports all three; re-exports Signal too |
| `src/alphaswarm/advisory/types.py` | AdvisoryItem, AdvisoryReport frozen pydantic models | ✓ VERIFIED | Both classes have `ConfigDict(frozen=True, extra="forbid")`; Signal defined; items is `tuple[AdvisoryItem, ...]` |
| `src/alphaswarm/advisory/prompt.py` | build_advisory_prompt pure function | ✓ VERIFIED | Returns list[dict[str,str]] with exactly 2 messages (system + user); embeds schema doc with `"BUY" | "SELL" | "HOLD"` |
| `src/alphaswarm/advisory/engine.py` | async synthesize() + _infer_with_retry() | ✓ VERIFIED | Both functions present; asyncio.gather over 4 reads; format="json" x2; model_validate_json x2; no load/unload model calls |
| `tests/unit/test_advisory.py` | 8 unit tests for ADVIS-01 | ✓ VERIFIED | All 8 named tests present and passing (0.09s) |
| `src/alphaswarm/web/routes/advisory.py` | APIRouter with POST+GET, _run_advisory_synthesis, _on_advisory_task_done | ✓ VERIFIED | All four functions present; 3x HTTP_409_CONFLICT; 2x HTTP_503_SERVICE_UNAVAILABLE; try/finally with unload_model |
| `src/alphaswarm/web/app.py` | advisory_router registration; advisory_task + advisory_generation_error state init | ✓ VERIFIED | Lines 24, 59-60, 138 contain all three required additions |
| `pyproject.toml` | importlinter source_modules entry for alphaswarm.web.routes.advisory | ✓ VERIFIED | Line 112 adds the entry; lines 129-130 add ignore_imports for advisory route's dependencies |
| `tests/unit/test_advisory_route.py` | 12 ADVIS-02 route unit tests | ✓ VERIFIED | All 12 tests present and passing (0.92s) |
| `tests/invariants/test_holdings_isolation.py` | Active ISOL-07 canary with real synthesize() | ✓ VERIFIED | `_advisory_harness_body` async function at line 68; `await synthesize` at line 93; `_minimal_simulation_body` absent |
| `tests/invariants/conftest.py` | CanaryFakeGraphManager, CanaryFakeOllamaClient, canary_valid_advisory_json | ✓ VERIFIED | All three present in Phase 41 D-20 block (lines 159-240) |
| `frontend/src/components/AdvisoryPanel.vue` | Full-screen modal, REVISION-1 dual-flag, polling, signal colors | ✓ VERIFIED | 601 lines; ViewState type, isAnalyzing ref, MAX_POLL_ITERATIONS=200, POLL_INTERVAL_MS=3000, advisory_generation_failed handler, all three signal CSS classes present; no v-html/marked/DOMPurify |
| `frontend/src/components/ControlBar.vue` | Advisory button in isComplete block, emits open-advisory-panel | ✓ VERIFIED | `control-bar__btn--advisory` class; `open-advisory-panel` emit; button appears only inside `v-else-if="isComplete"` block |
| `frontend/src/App.vue` | showAdvisoryPanel ref, onOpenAdvisoryPanel/onCloseAdvisoryPanel, AdvisoryPanel mount | ✓ VERIFIED | Lines 12, 77-84, 94, 142-145 confirm all required wiring |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `advisory/engine.py` | `alphaswarm.holdings.types` | `from alphaswarm.holdings.types import PortfolioSnapshot` | ✓ WIRED | Line 26 |
| `advisory/engine.py` | `GraphStateManager` (4 reads) | `asyncio.gather(read_consensus_summary, read_round_timeline, read_bracket_narratives, read_entity_impact)` | ✓ WIRED | Lines 56-61 |
| `advisory/engine.py` | `OllamaClient` | `ollama_client.chat(model=model, messages=messages, format="json")` | ✓ WIRED | Lines 141, 163 |
| `tests/unit/test_advisory.py` | `alphaswarm.advisory` | `from alphaswarm.advisory import synthesize, AdvisoryItem, AdvisoryReport` | ✓ WIRED | Line 18 |
| `advisory.py` (route) | `alphaswarm.advisory.synthesize` | `from alphaswarm.advisory import synthesize` | ✓ WIRED | Line 26 |
| `advisory.py` (route) | `_validate_cycle_id` | `from alphaswarm.web.routes.report import _validate_cycle_id` | ✓ WIRED | Line 28 |
| `web/app.py` | `advisory_router` | `app.include_router(advisory_router, prefix="/api")` | ✓ WIRED | Line 138 |
| `tests/invariants/test_holdings_isolation.py` | `alphaswarm.advisory.synthesize` | `await synthesize(...)` in `_advisory_harness_body` | ✓ WIRED | Line 93 |
| `ControlBar.vue` | `App.vue` | `emit('open-advisory-panel')` | ✓ WIRED | ControlBar line 197; App.vue line 94 |
| `App.vue` | `AdvisoryPanel.vue` | `v-if="showAdvisoryPanel"` mount | ✓ WIRED | App.vue lines 142-145 |
| `AdvisoryPanel.vue` | `/api/advisory/{cycle_id}` | `fetch('/api/advisory/${cycleId.value}')` POST + GET polling | ✓ WIRED | Lines 95, 149 |
| `AdvisoryPanel.vue` | `/api/replay/cycles` | `fetch('/api/replay/cycles')` to resolve latest cycle_id | ✓ WIRED | Line 77 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `AdvisoryPanel.vue` | `items`, `portfolioOutlook`, `holdingsTotal` | `GET /api/advisory/{cycle_id}` → disk JSON (written by `_run_advisory_synthesis` via `AdvisoryReport.model_dump_json`) | Yes — synthesis result from real Ollama LLM call (in production) | ✓ FLOWING |
| `advisory/engine.py` `synthesize()` | `bracket_summary, timeline, narratives, entities` | `asyncio.gather` over 4 Neo4j read methods on `GraphStateManager` | Yes — reads from live Neo4j graph state | ✓ FLOWING |
| `advisory/engine.py` `_infer_with_retry()` | `AdvisoryReport` | `ollama_client.chat(..., format="json")` → `AdvisoryReport.model_validate_json(content)` | Yes — real LLM response parsed into typed model | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command/Check | Result | Status |
|----------|---------------|--------|--------|
| Advisory library imports cleanly | `from alphaswarm.advisory import AdvisoryItem, AdvisoryReport, synthesize` (verified by test_advisory.py importing at line 18) | 8 tests pass | ✓ PASS |
| synthesize() prefetches 4 reads before LLM call | `test_prefetch_order` asserts all 4 read methods called, LLM called exactly once | PASS | ✓ PASS |
| Route 202 on valid POST | `test_post_advisory_202` | PASS | ✓ PASS |
| Route returns 409/503/400 on all guard paths | 7 guard tests | All PASS | ✓ PASS |
| ISOL-07 canary: no sentinel leaks across 4 surfaces | 4 negative-assertion async tests | All PASS | ✓ PASS |
| Frontend build compiles with no TypeScript errors | `npm run build` (vue-tsc -b && vite build) | Exit 0, 324 modules transformed | ✓ PASS |
| Advisory button only in isComplete ControlBar block | Grep confirms `open-advisory-panel` in `v-else-if="isComplete"` only | Single occurrence at line 193 | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| ADVIS-01 | 41-01-PLAN.md | `alphaswarm.advisory.synthesize()` with ranked AdvisoryItem list, frozen pydantic schema, 4-method Neo4j prefetch, single LLM call + bounded retry | ✓ SATISFIED | engine.py, types.py, prompt.py all substantive; 8 unit tests passing |
| ADVIS-02 | 41-02-PLAN.md | `POST /api/advisory/{cycle_id}` with lifecycle serialization; GET endpoint; background task + done_callback | ✓ SATISFIED | advisory.py route, app.py wiring, pyproject.toml importlinter entry all present; 12 route tests passing |
| ADVIS-03 | 41-02-PLAN.md (canary) + 41-03-PLAN.md (Vue UI) | Vue AdvisoryPanel.vue + ISOL-07 canary activated with real synthesize() | ✓ SATISFIED (automated portion) / ? NEEDS HUMAN (browser UI verification) | Canary tests pass; AdvisoryPanel.vue exists and builds; 16-step browser approval recorded in 41-03-SUMMARY.md but unconfirmable programmatically |

**Note on ISOL-07 (REQUIREMENTS.md):** ISOL-07 was scaffolded in Phase 37 and required activation in Phase 41. The canary is now ACTIVE — `_minimal_simulation_body` has been replaced with the real `synthesize()` harness and all 10 canary tests pass. The REQUIREMENTS.md traceability table shows "Partial" for ISOL-07 but the code reflects full activation.

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| None found | — | — | — |

Negative grep results confirming clean state:
- `grep "TODO\|FIXME\|NotImplementedError" src/alphaswarm/advisory/` → no matches
- `grep "log.*portfolio=\|log.*snapshot=\|log.*holdings=" src/alphaswarm/advisory/engine.py` → no matches
- `grep "load_model\|unload_model" src/alphaswarm/advisory/engine.py` → no matches (D-08 compliant)
- `grep "v-html\|marked\|DOMPurify" frontend/src/components/AdvisoryPanel.vue` → no matches (XSS surface absent)

### Notable Observations

**41-02-SUMMARY.md is absent:** The file `.planning/phases/41-advisory-pipeline/41-02-SUMMARY.md` does not exist on disk (only `41-01-SUMMARY.md` and `41-03-SUMMARY.md` are present). All code artifacts from Plan 41-02 are committed and functional — this is a documentation gap only, not a code gap.

**pyproject.toml ignore_imports:** Lines 129-130 added `ignore_imports` entries for `alphaswarm.web.routes.advisory -> alphaswarm.advisory` and `alphaswarm.web.routes.advisory -> alphaswarm.holdings.types`. Plan 41-02 Task 1 stated "No `ignore_imports` entry is added" (Assumption A6 — advisory route imports from `alphaswarm.advisory`, not `alphaswarm.holdings`). The actual implementation adds two `ignore_imports` entries. This diverges from the plan's stated assumption but does not represent a behavioral defect — it means the advisory route does import `alphaswarm.holdings.types` (indirectly or directly) and importlinter correctly required the whitelist. The lint-imports tool must exit 0 for this to be valid.

**Pre-existing test failures:** `tests/test_report.py` has 19 failing tests and `tests/test_graph_integration.py` has 1 error — both confirmed pre-existing before Phase 41 commits (verified by stash test). These are not Phase 41 regressions.

### Human Verification Required

#### 1. Confirm 16-Step Browser Flow Approval

**Test:** Confirm that the human operator who approved `41-03-SUMMARY.md` Task 3 actually ran the full 16-step browser flow described in 41-03-PLAN.md Task 3.

**Expected:** All 16 steps passed: Advisory button absent during idle/active/replay phases; complete-phase ControlBar shows `[Complete] [Advisory] [Report] [Stop]`; modal opens and displays portfolio_outlook + ranked table; signal colors BUY=accent, SELL=destructive, HOLD=text-secondary; Escape key and backdrop click close modal; re-open shows persisted rendered state without re-POST; no Vue warnings in DevTools.

**Why human:** The 41-03-SUMMARY.md records "approved 2026-04-20" but the verifier cannot programmatically confirm a browser session occurred. The Vue component exists, the TypeScript builds cleanly, and automated checks pass — but the rendering behavior, color correctness, and state machine UX require visual inspection in a real browser against a running backend.

---

### Gaps Summary

No gaps found in the automated verification. All code artifacts exist, are substantive (not stubs), are wired correctly, and data flows through them.

The single `human_needed` item is the browser-flow confirmation for Plan 41-03 Task 3. The SUMMARY records approval, but the GSD verification process requires the human to affirm this approval was genuine.

**Pre-existing issues (not Phase 41 gaps):**
- `tests/test_report.py` — 19 failures, pre-existing before Phase 41
- `tests/test_graph_integration.py` — 1 error (Neo4j event loop conflict), pre-existing

---

_Verified: 2026-04-20T02:15:00Z_
_Verifier: Claude (gsd-verifier)_
