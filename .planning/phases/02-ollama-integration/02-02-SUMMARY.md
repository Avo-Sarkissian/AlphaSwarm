---
phase: 02-ollama-integration
plan: 02
subsystem: infra
tags: [ollama, asyncio, backoff, pydantic, structured-output, model-management]

# Dependency graph
requires:
  - phase: 02-ollama-integration-01
    provides: "Error types (OllamaInferenceError, ModelLoadError, ParseError), AgentDecision type, OllamaSettings config, ResourceGovernor semaphore"
provides:
  - "OllamaClient wrapper with backoff, num_ctx stripping, and error boundary"
  - "OllamaModelManager with sequential load/unload, Lock serialization, and scoped cleanup"
  - "parse_agent_decision 3-tier fallback (JSON, regex, PARSE_ERROR) with code-fence stripping"
affects: [02-ollama-integration-03, 03-resource-governor, 05-orchestrator, 06-agent-worker]

# Tech tracking
tech-stack:
  added: [backoff, httpx]
  patterns: [exponential-backoff-decorator, asyncio-lock-serialization, 3-tier-parse-fallback, code-fence-stripping]

key-files:
  created:
    - src/alphaswarm/ollama_client.py
    - src/alphaswarm/ollama_models.py
    - src/alphaswarm/parsing.py
    - tests/test_ollama_client.py
    - tests/test_models.py
    - tests/test_parsing.py
  modified: []

key-decisions:
  - "backoff decorator on internal _chat_with_backoff, not public chat(), so public method catches final exception and wraps in OllamaInferenceError"
  - "RequestError caught separately from backoff tuple -- not retried but wrapped in OllamaInferenceError at public boundary"
  - "is_model_loaded() not Lock-guarded since it is read-only; called from within locked methods"
  - "Greedy regex (.*) for JSON extraction to handle nested structures; lazy would stop at first closing brace"

patterns-established:
  - "Error boundary pattern: all public OllamaClient methods wrap exceptions in OllamaInferenceError"
  - "Lock serialization pattern: asyncio.Lock in OllamaModelManager for model transitions"
  - "3-tier parse pattern: JSON direct -> code-fence strip + regex -> PARSE_ERROR fallback"
  - "Scoped cleanup pattern: ensure_clean_state only touches configured_aliases"

requirements-completed: [INFRA-03, INFRA-04, INFRA-08]

# Metrics
duration: 5min
completed: 2026-03-24
---

# Phase 02 Plan 02: Ollama Client, Model Manager, and Structured Output Parsing Summary

**OllamaClient wrapper with exponential backoff and error boundary, OllamaModelManager with Lock-serialized sequential loading, and parse_agent_decision 3-tier fallback with code-fence stripping**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-24T23:34:05Z
- **Completed:** 2026-03-24T23:39:00Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- OllamaClient enforces no-num_ctx contract, applies exponential backoff on transient errors, wraps ALL errors (including RequestError) in OllamaInferenceError at the public boundary
- OllamaModelManager loads/unloads models via keep_alive=0 with ps() verification, serializes all transitions with asyncio.Lock, and scopes cleanup to configured aliases only
- parse_agent_decision implements 3-tier fallback: JSON mode, code-fence stripping + regex extraction, PARSE_ERROR sentinel -- never raises, always returns AgentDecision
- All 25 plan tests pass, 46 total tests pass with no regressions

## Task Commits

Each task was committed atomically (TDD: RED -> GREEN):

1. **Task 1: OllamaClient wrapper, OllamaModelManager, and their unit tests**
   - `01f6d04` (test: failing tests for OllamaClient and OllamaModelManager)
   - `eaa3572` (feat: implement OllamaClient wrapper and OllamaModelManager)
2. **Task 2: Structured output parsing with 3-tier fallback, code-fence stripping, and tests**
   - `acfad4d` (test: failing tests for parse_agent_decision 3-tier fallback)
   - `d0b9a5e` (feat: implement parse_agent_decision 3-tier fallback)

## Files Created/Modified
- `src/alphaswarm/ollama_client.py` - OllamaClient wrapper with backoff, num_ctx stripping, error boundary
- `src/alphaswarm/ollama_models.py` - OllamaModelManager for sequential load/unload with Lock serialization
- `src/alphaswarm/parsing.py` - parse_agent_decision 3-tier fallback with code-fence stripping
- `tests/test_ollama_client.py` - 6 tests: chat, num_ctx, backoff, max retries, request error, format
- `tests/test_models.py` - 7 tests: unload, verify, sequential, load failure, scoped cleanup, serialization
- `tests/test_parsing.py` - 12 tests: model validation, tier1/2/3 parsing, code fences, log tracking

## Decisions Made
- backoff decorator placed on internal `_chat_with_backoff` method (not public `chat`), so the public method can catch the final exception after retries are exhausted and wrap it in OllamaInferenceError
- RequestError caught separately from the backoff exception tuple -- not retried, but IS wrapped in OllamaInferenceError at the public boundary to maintain the locked error boundary contract
- `is_model_loaded()` is not guarded by the Lock since it is a read-only ps() call; it is called from within already-locked methods (load_model, unload_model)
- Greedy regex pattern `\{.*\}` used for JSON extraction to correctly handle nested structures like arrays and sub-objects; lazy match would stop at the first closing brace

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test_sequential_load ps() side_effect ordering**
- **Found during:** Task 1 (GREEN phase)
- **Issue:** Test had 3 ps() side_effects but unload_model does not call ps(), so the second side_effect (empty list) was consumed by the wrong load_model call, causing ModelLoadError
- **Fix:** Removed the middle side_effect; only 2 ps() responses needed (one per load_model call)
- **Files modified:** tests/test_models.py
- **Verification:** test_sequential_load passes
- **Committed in:** eaa3572

**2. [Rule 1 - Bug] Fixed mypy no-any-return in _chat_with_backoff**
- **Found during:** Task 2 (verification step)
- **Issue:** `return await self._client.chat(**kwargs)` returned Any due to kwargs spreading, violating strict mypy
- **Fix:** Added explicit type annotation `result: ChatResponse = await self._client.chat(**kwargs)`
- **Files modified:** src/alphaswarm/ollama_client.py
- **Verification:** `uv run mypy src/alphaswarm/ollama_client.py` passes with no errors
- **Committed in:** d0b9a5e

---

**Total deviations:** 2 auto-fixed (2 bugs)
**Impact on plan:** Both fixes necessary for correctness. No scope creep.

## Issues Encountered
None beyond the auto-fixed deviations above.

## Known Stubs
None -- all modules are fully implemented with no placeholder data or TODO markers.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- OllamaClient, OllamaModelManager, and parse_agent_decision are ready for Plan 03 (AgentWorker context manager integration)
- The inference path is: OllamaClient.chat() -> parse_agent_decision() -> AgentDecision
- Model lifecycle is: OllamaModelManager.load_model() -> inference -> unload_model()
- All error types flow through OllamaInferenceError boundary

## Self-Check: PASSED

All 7 created files verified on disk. All 4 commit hashes verified in git log.

---
*Phase: 02-ollama-integration*
*Completed: 2026-03-24*
