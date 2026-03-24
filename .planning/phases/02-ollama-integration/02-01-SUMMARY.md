---
phase: 02-ollama-integration
plan: 01
subsystem: infra
tags: [ollama, backoff, pydantic, asyncio, semaphore, typeddict, modelfile]

# Dependency graph
requires:
  - phase: 01-project-foundation
    provides: "AgentPersona, BracketConfig, SignalType, AppSettings, ResourceGovernor stub, AppState"
provides:
  - "OllamaInferenceError, ModelLoadError, ParseError domain exceptions"
  - "AgentDecision frozen Pydantic model with PARSE_ERROR signal"
  - "Updated OllamaSettings with qwen3.5:32b/qwen3.5:7b and model aliases"
  - "persona_to_worker_config conversion helper"
  - "Real BoundedSemaphore-backed ResourceGovernor"
  - "WorkerPersonaConfig TypedDict"
  - "Modelfiles for orchestrator and worker models"
  - "ollama and backoff packages installed"
affects: [02-02, 02-03, 03-resource-governor]

# Tech tracking
tech-stack:
  added: [ollama>=0.6.1, backoff>=2.2.1, httpx (transitive)]
  patterns: [domain-exception-hierarchy, typed-dict-hot-path, modelfile-based-config, semaphore-backpressure]

key-files:
  created:
    - src/alphaswarm/errors.py
    - src/alphaswarm/worker.py
    - modelfiles/Modelfile.orchestrator
    - modelfiles/Modelfile.worker
  modified:
    - src/alphaswarm/types.py
    - src/alphaswarm/config.py
    - src/alphaswarm/governor.py
    - pyproject.toml
    - uv.lock
    - tests/test_config.py
    - tests/test_app.py
    - .env.example

key-decisions:
  - "Model tags updated from qwen3:32b/qwen3.5:4b to qwen3.5:32b/qwen3.5:7b per user CONTEXT.md locked decision"
  - "Model aliases (alphaswarm-orchestrator/alphaswarm-worker) added to OllamaSettings for Modelfile-registered tags"
  - "WorkerPersonaConfig uses TypedDict (not Pydantic) for hot-path performance per user locked decision"
  - "persona_to_worker_config uses lazy import to avoid circular dependency between config.py and worker.py"
  - "Pre-existing ruff UP042 and mypy no-any-return errors left as deferred items (Phase 1 scope)"

patterns-established:
  - "Domain exception hierarchy: OllamaInferenceError -> ModelLoadError, separate ParseError"
  - "TypedDict for hot-path data: WorkerPersonaConfig derived from frozen Pydantic AgentPersona"
  - "Modelfile-based model config: num_ctx and temperature baked into Modelfiles, never per-request"
  - "BoundedSemaphore backpressure: governor.acquire() blocks when all slots held"

requirements-completed: [INFRA-03, INFRA-04, INFRA-08]

# Metrics
duration: 5min
completed: 2026-03-24
---

# Phase 02 Plan 01: Foundation Types and Infrastructure Summary

**Domain exceptions, AgentDecision model with PARSE_ERROR signal, BoundedSemaphore governor, WorkerPersonaConfig TypedDict, Modelfiles, and ollama/backoff dependency installation**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-24T23:26:13Z
- **Completed:** 2026-03-24T23:30:42Z
- **Tasks:** 2
- **Files modified:** 13

## Accomplishments

- Created domain exception hierarchy (OllamaInferenceError, ModelLoadError, ParseError) for clean error handling across Phase 2
- Added PARSE_ERROR to SignalType and AgentDecision frozen model for structured LLM output validation
- Upgraded ResourceGovernor from no-op stub to real asyncio.BoundedSemaphore with functional acquire/release
- Established WorkerPersonaConfig TypedDict and Modelfile-based model configuration pattern
- Installed ollama>=0.6.1 and backoff>=2.2.1 as Phase 2 dependencies

## Task Commits

Each task was committed atomically:

1. **Task 1: Domain exceptions, type additions, config update, governor upgrade, deps** - `50812fa` (feat)
2. **Task 2: WorkerPersonaConfig TypedDict and Modelfiles** - `e84a879` (feat)
3. **Fix: TYPE_CHECKING import for WorkerPersonaConfig** - `6b4c5f7` (fix)

## Files Created/Modified

- `src/alphaswarm/errors.py` - Domain exceptions: OllamaInferenceError, ModelLoadError, ParseError
- `src/alphaswarm/types.py` - Added PARSE_ERROR to SignalType, AgentDecision frozen model
- `src/alphaswarm/config.py` - Updated model defaults to qwen3.5:32b/7b, added aliases, persona_to_worker_config
- `src/alphaswarm/governor.py` - Upgraded to real asyncio.BoundedSemaphore backpressure
- `src/alphaswarm/worker.py` - WorkerPersonaConfig TypedDict with 6 fields
- `modelfiles/Modelfile.orchestrator` - FROM qwen3.5:32b, num_ctx 8192, with registration command
- `modelfiles/Modelfile.worker` - FROM qwen3.5:7b, num_ctx 4096, with registration command
- `pyproject.toml` - Added ollama>=0.6.1 and backoff>=2.2.1 dependencies
- `uv.lock` - Updated lockfile with new dependencies
- `tests/test_config.py` - Updated model tag assertions to qwen3.5:32b/7b
- `tests/test_app.py` - Updated banner assertions to qwen3.5:32b/7b
- `.env.example` - Updated model tags and added alias env vars

## Decisions Made

- Model tags updated from qwen3:32b/qwen3.5:4b to qwen3.5:32b/qwen3.5:7b per user CONTEXT.md locked decision
- Model aliases (alphaswarm-orchestrator/alphaswarm-worker) added to OllamaSettings for Modelfile-registered tags
- Used lazy import in persona_to_worker_config to avoid circular dependency between config.py and worker.py
- Pre-existing lint/type issues logged to deferred-items.md rather than fixing out-of-scope Phase 1 code

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added TYPE_CHECKING import for WorkerPersonaConfig annotation**
- **Found during:** Task 1 (config.py update)
- **Issue:** ruff F821 flagged undefined name `WorkerPersonaConfig` in return type annotation
- **Fix:** Added `from typing import TYPE_CHECKING` and conditional import for type checker
- **Files modified:** src/alphaswarm/config.py
- **Verification:** ruff check passes on config.py, runtime import still works inside function body
- **Committed in:** 6b4c5f7

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Minor fix for ruff compliance. No scope creep.

## Issues Encountered

- Pre-existing ruff UP042 (str+Enum pattern) and I001 (import sorting in __main__.py) errors from Phase 1 remain. Logged to deferred-items.md. These do not affect Phase 2 code.
- Pre-existing mypy no-any-return error in logging.py from Phase 1. Logged to deferred-items.md.

## Known Stubs

None. All artifacts are fully implemented per plan specification.

## User Setup Required

None - no external service configuration required. Models (qwen3.5:32b, qwen3.5:7b) must be pre-pulled via `ollama pull` but that is out of scope per CONTEXT.md.

## Next Phase Readiness

- All artifacts required by Plan 02 (OllamaClient wrapper, model manager) and Plan 03 (agent_worker, parsing) are in place
- errors.py provides exception types for OllamaClient backoff giveup handler
- types.py provides AgentDecision for parsing module
- governor.py provides real semaphore for agent_worker context manager
- worker.py provides WorkerPersonaConfig for agent_worker dispatch
- Modelfiles document the model registration commands for setup

## Self-Check: PASSED

- All 8 key files verified present on disk
- All 3 commit hashes (50812fa, e84a879, 6b4c5f7) verified in git log
- 21/21 tests passing
- Inline verification scripts all exit 0

---
*Phase: 02-ollama-integration*
*Completed: 2026-03-24*
