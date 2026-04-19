# Phase 3: Resource Governance - Context

**Gathered:** 2026-03-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 3 transforms the ResourceGovernor stub (Phase 2) into a fully dynamic concurrency controller. It adds dual-signal memory monitoring (psutil + macOS `memory_pressure`), adaptive slot scaling (8 baseline to 16 max), batch dispatch with jitter via `asyncio.TaskGroup`, inference failure tracking with governor shrinkage, and crisis abort logic. The result is a governor that prevents OOM crashes, recovers gracefully, and exposes metrics for the future TUI telemetry footer.

</domain>

<decisions>
## Implementation Decisions

### Recovery Strategy
- **D-01:** Gradual ramp recovery — restore +2 slots per `check_interval` (2s) until baseline is reached after a Yellow/Red → Green transition. No instant snap-back.
- **D-02:** Scale above baseline when safe — if memory is under 60% utilization for 3 consecutive Green `memory_pressure` checks, gradually add slots above baseline up to `max_parallel` (16).
- **D-03:** After any crisis recovery, reset to baseline (8), not the pre-incident slot count. Normal scale-up logic handles going higher again.

### Failure Scope
- **D-04:** Batch failure threshold uses per-wave scope (8-16 agents per dispatch wave). If ≥20% of a wave fails, trigger governor shrinkage.
- **D-05:** Shrink by subtracting 2 slots per trigger (minimum 1). Gradual degradation, not halving.
- **D-06:** No batch-level retry — OllamaClient's 3x exponential backoff is sufficient. Failed agents get PARSE_ERROR signal and move on.

### Crisis Policy
- **D-07:** Timeout + abort after 5 minutes of sustained Red/Yellow pressure with no successful inferences. Raises a clear error and aborts the simulation.
- **D-08:** Crisis timeout clock resets on any successful inference, even at 1 slot.

### Observability
- **D-09:** Dual output — structlog for operators + SharedStateStore writes for future TUI telemetry (Phase 10). No TUI code in Phase 3, just the data contract.
- **D-10:** Log levels: INFO for routine slot adjustments, WARNING for throttle/pause events, ERROR for abort.
- **D-11:** StateStore emissions on state change only (slot count, pressure level, or governor state changes). Not every check interval.

### Carried Forward (Locked in Phase 2)
- **D-12:** Hybrid memory sensing — `psutil.virtual_memory().percent` (Signal A) + `/usr/bin/memory_pressure` subprocess (Signal B, master). Dual-signal check on every `governor.acquire()` and on background polling interval.
- **D-13:** `memory_pressure` master signal — Yellow or Red → immediately halt queue AND drop active slots to 1. Green → begin gradual recovery (D-01).
- **D-14:** Random jitter `await asyncio.sleep(random.uniform(0.5, 1.5))` before each agent dispatch in batch. Applied in batch dispatcher, not inside worker context manager.
- **D-15:** `asyncio.TaskGroup` for all batch agent processing. No bare `create_task` calls.
- **D-16:** Exponential backoff 1s, 2s, 4s for Ollama failures (already on OllamaClient via `backoff` library).
- **D-17:** Governor starts at 8 baseline slots (from `GovernorSettings.baseline_parallel`), max 16 (from `GovernorSettings.max_parallel`). 80% memory = throttle, 90% = pause.

### Claude's Discretion
- Internal implementation of the semaphore replacement (may need to swap `BoundedSemaphore` for a resizable approach since `BoundedSemaphore` doesn't support dynamic limit changes)
- `memory_pressure` subprocess parsing details
- StateStore metric key names and data shape
- Test fixture design for simulating memory pressure states
- Whether to split governor into multiple files (e.g., `governor.py`, `memory_monitor.py`, `batch_dispatcher.py`) or keep consolidated

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 2 Forward Decisions (Primary)
- `.planning/phases/02-ollama-integration/02-CONTEXT.md` §forward_decisions — Hybrid memory sensing spec, random jitter spec (MANDATORY — these are locked implementation requirements for Phase 3)

### Existing Implementation
- `src/alphaswarm/governor.py` — Current ResourceGovernor stub with BoundedSemaphore, Protocol, acquire/release/start_monitoring/stop_monitoring
- `src/alphaswarm/worker.py` — agent_worker context manager, AgentWorker class, WorkerPersonaConfig TypedDict
- `src/alphaswarm/ollama_client.py` — OllamaClient with backoff, _chat_with_backoff pattern
- `src/alphaswarm/config.py` — GovernorSettings (baseline_parallel, max_parallel, memory_throttle_percent, memory_pause_percent, check_interval_seconds)
- `src/alphaswarm/errors.py` — OllamaInferenceError, ModelLoadError, ParseError
- `src/alphaswarm/state.py` — SharedStateStore interface
- `src/alphaswarm/app.py` — AppState container with create_app_state factory

### Requirements
- `.planning/REQUIREMENTS.md` — INFRA-01, INFRA-02, INFRA-07, INFRA-09 definitions
- `.planning/ROADMAP.md` — Phase 3 success criteria and dependencies

### Research
- `.planning/research/ARCHITECTURE.md` — Component boundaries and data flow

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ResourceGovernor` class in `governor.py` — has acquire/release/start_monitoring/stop_monitoring stubs, BoundedSemaphore, active_count tracking, async context manager support
- `ResourceGovernorProtocol` — defines the interface contract (Phase 3 must maintain backward compatibility)
- `GovernorSettings` in `config.py` — already has all threshold fields (baseline_parallel, max_parallel, memory_throttle_percent, memory_pause_percent, check_interval_seconds)
- `agent_worker()` context manager — calls `governor.acquire()` / `governor.release()` — Phase 3 changes are transparent to callers
- `OllamaClient._chat_with_backoff` — already has per-call backoff; Phase 3 adds batch-level failure tracking on top

### Established Patterns
- `asynccontextmanager` for resource lifecycle (agent_worker pattern)
- `structlog.get_logger(component="...")` for component-scoped logging
- `TYPE_CHECKING` guard for circular import avoidance
- Pydantic `BaseModel` for settings, `TypedDict` for hot-path configs
- `backoff.on_exception` decorator for retry logic

### Integration Points
- `governor.acquire()` / `release()` — called by `agent_worker()` in `worker.py`
- `governor.start_monitoring()` / `stop_monitoring()` — called during app lifecycle in `app.py`
- `GovernorSettings` — fed into ResourceGovernor constructor
- `SharedStateStore` — Phase 3 writes governor metrics here for Phase 10 TUI

</code_context>

<specifics>
## Specific Ideas

- `BoundedSemaphore` doesn't support dynamic limit changes — will likely need a custom semaphore or token-pool pattern (INFRA-01 mentions "token-pool pattern")
- `memory_pressure` command returns text like "System memory pressure level: Green/Yellow/Red" — parse via subprocess + regex
- The 5-minute crisis timeout resets on any successful inference, not just on Green pressure
- Scale-up threshold (60% utilization) is separate from throttle (80%) and pause (90%) — there's a comfort zone between 60-80% where the governor holds steady

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 03-resource-governance*
*Context gathered: 2026-03-24*
