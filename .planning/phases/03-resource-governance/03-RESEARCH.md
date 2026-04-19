# Phase 3: Resource Governance - Research

**Researched:** 2026-03-24
**Domain:** Async concurrency control, memory monitoring, batch dispatch, failure tracking
**Confidence:** HIGH

## Summary

Phase 3 transforms the `ResourceGovernor` stub (Phase 2's `BoundedSemaphore`-based implementation) into a fully dynamic concurrency controller with dual-signal memory monitoring, adaptive slot scaling, batch dispatch via `asyncio.TaskGroup`, inference failure tracking with governor shrinkage, and crisis abort logic. The core challenge is replacing the fixed `BoundedSemaphore` with a resizable concurrency primitive while maintaining the existing `acquire()`/`release()` interface contract that `agent_worker()` depends on.

Key technical discoveries during research: (1) `asyncio.BoundedSemaphore` cannot be resized after creation -- a queue-based token pool is the correct replacement, (2) the Phase 2 forward decision references parsing `/usr/bin/memory_pressure` output for "Green/Yellow/Red" levels, but this command is actually a *stress testing* tool, not a monitoring tool -- the actual macOS pressure level comes from `sysctl -n kern.memorystatus_vm_pressure_level` which returns 1 (NORMAL/Green), 2 (WARN/Yellow), or 4 (CRITICAL/Red), (3) `asyncio.TaskGroup` cancels ALL remaining tasks when ANY task raises an exception, so each agent inference must be wrapped in try/except internally to prevent partial batch failures from killing the entire wave.

**Primary recommendation:** Replace `BoundedSemaphore` with an `asyncio.Queue`-based token pool for O(1) dynamic resizing. Use `sysctl kern.memorystatus_vm_pressure_level` (not `/usr/bin/memory_pressure` command output) as the macOS pressure signal. Wrap each agent task in try/except inside TaskGroup to enable graceful partial failures.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Gradual ramp recovery -- restore +2 slots per `check_interval` (2s) until baseline is reached after a Yellow/Red to Green transition. No instant snap-back.
- **D-02:** Scale above baseline when safe -- if memory is under 60% utilization for 3 consecutive Green `memory_pressure` checks, gradually add slots above baseline up to `max_parallel` (16).
- **D-03:** After any crisis recovery, reset to baseline (8), not the pre-incident slot count. Normal scale-up logic handles going higher again.
- **D-04:** Batch failure threshold uses per-wave scope (8-16 agents per dispatch wave). If >=20% of a wave fails, trigger governor shrinkage.
- **D-05:** Shrink by subtracting 2 slots per trigger (minimum 1). Gradual degradation, not halving.
- **D-06:** No batch-level retry -- OllamaClient's 3x exponential backoff is sufficient. Failed agents get PARSE_ERROR signal and move on.
- **D-07:** Timeout + abort after 5 minutes of sustained Red/Yellow pressure with no successful inferences. Raises a clear error and aborts the simulation.
- **D-08:** Crisis timeout clock resets on any successful inference, even at 1 slot.
- **D-09:** Dual output -- structlog for operators + SharedStateStore writes for future TUI telemetry (Phase 10). No TUI code in Phase 3, just the data contract.
- **D-10:** Log levels: INFO for routine slot adjustments, WARNING for throttle/pause events, ERROR for abort.
- **D-11:** StateStore emissions on state change only (slot count, pressure level, or governor state changes). Not every check interval.
- **D-12:** Hybrid memory sensing -- `psutil.virtual_memory().percent` (Signal A) + `/usr/bin/memory_pressure` subprocess (Signal B, master). Dual-signal check on every `governor.acquire()` and on background polling interval.
- **D-13:** `memory_pressure` master signal -- Yellow or Red immediately halt queue AND drop active slots to 1. Green begins gradual recovery (D-01).
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

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INFRA-01 | ResourceGovernor implements dynamic concurrency control via asyncio token-pool pattern, starting at 8 parallel slots (adjustable up to 16) | Queue-based token pool pattern verified as correct approach; `asyncio.Queue` provides O(1) grow/shrink; tested on project Python 3.11 |
| INFRA-02 | psutil + macOS `memory_pressure` command monitors system memory; ResourceGovernor throttles at 80% utilization and pauses task queue at 90% | `psutil 7.2.2` installed; `sysctl kern.memorystatus_vm_pressure_level` verified returns 1/2/4 for Green/Yellow/Red; dual-signal approach validated |
| INFRA-07 | All agent batch processing uses asyncio.TaskGroup (no bare create_task) to prevent silent task garbage collection | `asyncio.TaskGroup` available in Python 3.11; cancellation behavior requires try/except wrapping per task for partial failure tolerance |
| INFRA-09 | Exponential backoff for Ollama failures (1s, 2s, 4s; shrink governor on >20% batch failure rate) | Per-call backoff already on `OllamaClient._chat_with_backoff`; Phase 3 adds batch-level failure tracking and governor shrinkage on top |

</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| psutil | 7.2.2 | System memory monitoring (Signal A) | Already in pyproject.toml; cross-platform memory stats |
| asyncio (stdlib) | Python 3.11 | TaskGroup, Queue-based token pool, event loop | Built-in structured concurrency; no external deps needed |
| structlog | 25.5.0 | Component-scoped logging with context binding | Already in use project-wide; matches D-09/D-10 |
| subprocess (stdlib) | Python 3.11 | macOS sysctl calls for pressure level (Signal B) | Lightweight; no additional deps for OS-level queries |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| backoff | 2.2.1 | Per-call exponential backoff on OllamaClient | Already wired in Phase 2; Phase 3 does not modify this |
| pydantic | 2.12.5+ | GovernorSettings validation, new config fields | Existing pattern; add crisis_timeout_seconds, scale_up_threshold_percent |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Queue token pool | aiometer / AsyncIOLimiter | External dep for something achievable with stdlib Queue; overkill for this use case |
| sysctl subprocess | ctypes/cffi to kern.memorystatus_vm_pressure_level | More complex, brittle across macOS versions; subprocess is simpler and reliable |
| Manual slot tracking | asyncio.Semaphore hacking (acquire surplus slots to shrink) | Deadlock-prone, hard to reason about; Queue is cleaner |

**Installation:**
```bash
# No new dependencies required -- all libraries already in pyproject.toml
uv sync
```

## Architecture Patterns

### Recommended Module Structure

Based on the complexity of Phase 3, splitting into multiple files is recommended:

```
src/alphaswarm/
    governor.py              # ResourceGovernor (token pool, acquire/release, slot scaling)
    memory_monitor.py        # MemoryMonitor (psutil + sysctl dual-signal, pressure enum)
    batch_dispatcher.py      # BatchDispatcher (TaskGroup dispatch, jitter, failure tracking)
    config.py                # GovernorSettings (add new fields: crisis_timeout, scale_up_threshold)
    state.py                 # StateStore (add governor metric writes)
    errors.py                # Add GovernorCrisisError
```

**Rationale:** The governor has three distinct responsibilities (slot management, memory sensing, batch dispatch) that benefit from separation. Each can be tested independently. The `ResourceGovernorProtocol` interface in `governor.py` remains the public contract.

### Pattern 1: Queue-Based Token Pool (replaces BoundedSemaphore)

**What:** Use `asyncio.Queue` as a dynamically-resizable concurrency limiter. Tokens (True values) represent available slots. `acquire()` gets a token (blocks if empty), `release()` puts a token back. Growing adds tokens; shrinking removes them.

**When to use:** Any time the concurrency limit needs to change at runtime based on external signals.

**Example:**
```python
# Source: Verified pattern from project ARCHITECTURE.md + local testing
import asyncio

class TokenPool:
    """Dynamically resizable concurrency limiter via asyncio.Queue."""

    def __init__(self, initial_size: int) -> None:
        self._pool: asyncio.Queue[bool] = asyncio.Queue()
        self._current_limit = initial_size
        for _ in range(initial_size):
            self._pool.put_nowait(True)

    async def acquire(self) -> None:
        """Block until a concurrency slot is available."""
        await self._pool.get()

    def release(self) -> None:
        """Return a concurrency slot to the pool."""
        self._pool.put_nowait(True)

    def grow(self, amount: int) -> None:
        """Add slots to the pool (non-blocking)."""
        for _ in range(amount):
            self._pool.put_nowait(True)
            self._current_limit += 1

    async def shrink(self, amount: int) -> int:
        """Remove slots from pool. Returns actual number removed.

        Uses wait_for with short timeout -- cannot shrink slots
        that are currently checked out by active workers.
        """
        removed = 0
        for _ in range(amount):
            try:
                await asyncio.wait_for(self._pool.get(), timeout=0.05)
                self._current_limit -= 1
                removed += 1
            except asyncio.TimeoutError:
                break  # No more free tokens to remove
        return removed

    @property
    def current_limit(self) -> int:
        return self._current_limit

    @property
    def available(self) -> int:
        return self._pool.qsize()
```

### Pattern 2: Dual-Signal Memory Monitor

**What:** Combine psutil percentage (fast, cross-platform) with macOS kernel pressure level (OS-native, accounts for compression/swap). The kernel signal is the master -- it sees things psutil cannot (memory compression, swap pressure).

**When to use:** Every `acquire()` call and on a background polling interval (2s).

**CRITICAL RESEARCH FINDING:** The Phase 2 forward decisions reference parsing `/usr/bin/memory_pressure` output for "System memory pressure level: Green/Yellow/Red". This is INCORRECT. The `memory_pressure` command (per `man memory_pressure`) is a **stress testing tool** that applies or simulates pressure -- it does NOT report the current pressure level in Green/Yellow/Red format. Its output shows pages free/active/wired and "System-wide memory free percentage: N%".

The actual macOS pressure level comes from:
```bash
sysctl -n kern.memorystatus_vm_pressure_level
# Returns: 1 (NORMAL/Green), 2 (WARN/Yellow), 4 (CRITICAL/Red)
```

This was verified on the target machine (macOS Darwin 25.3.0, Apple M1 Max):
- `kern.memorystatus_vm_pressure_level: 1` (Green)
- `vm.memory_pressure: 0` (no pressure)
- `psutil.virtual_memory().percent: 41.2%`

**Example:**
```python
# Source: Verified via subprocess on target machine
import asyncio
import enum
import subprocess

import psutil

class PressureLevel(enum.Enum):
    GREEN = "green"    # Normal -- scale up eligible
    YELLOW = "yellow"  # Warn -- halt queue, drop to 1 slot
    RED = "red"        # Critical -- halt queue, drop to 1 slot

# Mapping from sysctl kern.memorystatus_vm_pressure_level values
_SYSCTL_PRESSURE_MAP: dict[int, PressureLevel] = {
    1: PressureLevel.GREEN,
    2: PressureLevel.YELLOW,
    4: PressureLevel.RED,
}

async def read_macos_pressure() -> PressureLevel:
    """Read macOS kernel memory pressure level via sysctl.

    Uses asyncio.create_subprocess_exec to avoid blocking the event loop.
    Falls back to GREEN on parse errors (fail-open for non-macOS).
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "sysctl", "-n", "kern.memorystatus_vm_pressure_level",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=2.0)
        raw = int(stdout.decode().strip())
        return _SYSCTL_PRESSURE_MAP.get(raw, PressureLevel.GREEN)
    except (asyncio.TimeoutError, ValueError, OSError):
        return PressureLevel.GREEN  # Fail-open
```

### Pattern 3: TaskGroup with Internal Exception Handling

**What:** Wrap each agent inference in try/except inside the TaskGroup task so that individual failures produce PARSE_ERROR results instead of cancelling the entire batch.

**When to use:** All batch agent dispatch (INFRA-07).

**CRITICAL RESEARCH FINDING:** `asyncio.TaskGroup` cancels ALL remaining tasks when ANY task raises an unhandled exception. This is by design (structured concurrency). For AlphaSwarm's batch dispatch where we want partial failures (D-06: failed agents get PARSE_ERROR signal), each task function MUST catch its own exceptions internally.

**Example:**
```python
# Source: Verified via local Python 3.11 testing
import asyncio
import random

from alphaswarm.types import AgentDecision, SignalType

async def _safe_agent_inference(
    persona: WorkerPersonaConfig,
    governor: ResourceGovernor,
    client: OllamaClient,
    model: str,
    user_message: str,
) -> AgentDecision:
    """Run single agent inference, catching errors to prevent TaskGroup cancellation."""
    try:
        await asyncio.sleep(random.uniform(0.5, 1.5))  # D-14: jitter
        async with agent_worker(persona, governor, client, model) as worker:
            return await worker.infer(user_message=user_message)
    except Exception:
        # D-06: Failed agents get PARSE_ERROR signal
        return AgentDecision(
            signal=SignalType.PARSE_ERROR,
            confidence=0.0,
            rationale=f"Inference failed for {persona['agent_id']}",
        )

async def dispatch_wave(
    personas: list[WorkerPersonaConfig],
    governor: ResourceGovernor,
    client: OllamaClient,
    model: str,
    user_message: str,
) -> list[AgentDecision]:
    """Dispatch a wave of agents using TaskGroup (INFRA-07)."""
    results: list[AgentDecision] = []
    async with asyncio.TaskGroup() as tg:
        tasks = [
            tg.create_task(_safe_agent_inference(p, governor, client, model, user_message))
            for p in personas
        ]
    # All tasks complete -- collect results
    results = [t.result() for t in tasks]
    return results
```

### Pattern 4: Governor State Machine

**What:** The governor operates as a state machine with explicit transitions driven by memory signals.

**States and transitions:**
```
RUNNING (normal operation)
    |--- psutil >= 80% ---> THROTTLED (reduce dispatch rate)
    |--- psutil >= 90% ---> PAUSED (stop new dispatches)
    |--- Yellow/Red ------> CRISIS (drop to 1 slot, start timeout)

THROTTLED
    |--- psutil < 80% ----> RUNNING (gradual +2 recovery)
    |--- psutil >= 90% ---> PAUSED
    |--- Yellow/Red ------> CRISIS

PAUSED
    |--- psutil < 90% ----> THROTTLED
    |--- psutil < 80% ----> RUNNING (gradual recovery)
    |--- Yellow/Red ------> CRISIS

CRISIS
    |--- Green + success --> RECOVERING (reset to baseline, gradual ramp)
    |--- 5min no success --> ABORTED (raise GovernorCrisisError)

RECOVERING
    |--- Green stable -----> RUNNING (after reaching baseline)
    |--- Yellow/Red ------> CRISIS (re-enter)
```

### Anti-Patterns to Avoid

- **Resizing BoundedSemaphore:** `asyncio.BoundedSemaphore` has no API to change `_value` or `_bound_value` after creation. Monkey-patching internals breaks across Python versions. Use Queue token pool instead.
- **Blocking subprocess in acquire():** Calling `subprocess.run()` synchronously in `acquire()` blocks the event loop. Use `asyncio.create_subprocess_exec()` or cache the last-known pressure level from the background monitor.
- **TaskGroup without per-task try/except:** Letting inference exceptions propagate cancels the entire wave. Wrap each task.
- **Polling memory on every acquire():** Running a subprocess on every `acquire()` call (up to 100 times per wave) is excessive. Cache the pressure level from the background monitor (2s interval) and check the cached value in `acquire()`. Run psutil inline (it is fast, ~0.1ms) but use the cached sysctl value.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Per-call retry/backoff | Custom retry loops | `backoff` library (already on OllamaClient) | Edge cases: jitter, max_time, giveup conditions |
| Memory percentage reading | Manual `/proc/meminfo` parsing | `psutil.virtual_memory().percent` | Cross-platform, handles macOS unified memory correctly |
| Structured logging | print/logging.getLogger | `structlog` with component binding | Already project-wide; context vars for correlation IDs |
| Settings validation | Manual env parsing | `pydantic-settings` GovernorSettings | Already established pattern; field validation built-in |

**Key insight:** Phase 3's complexity is in the *orchestration logic* (state machine, recovery policies, failure tracking), not in the individual primitives. Each primitive (memory reading, token pool, TaskGroup) is straightforward -- the challenge is wiring them together correctly with the right state transitions.

## Common Pitfalls

### Pitfall 1: Shrinking Below Active Count
**What goes wrong:** Attempting to shrink the token pool below the number of currently checked-out tokens causes `wait_for` timeout on every attempt, or worse, deadlock if using blocking `get()`.
**Why it happens:** If 6 slots are active and you try to shrink to 4, only 2 tokens are in the pool. You can remove those 2, but the remaining 4 are "checked out" by active workers and will return when workers finish.
**How to avoid:** Track `_current_limit` separately from pool size. Set `_current_limit` to the target, and when workers `release()`, check if `_current_limit` has shrunk and discard the token instead of returning it to the pool.
**Warning signs:** Pool size stays at 0 for extended periods; `shrink()` returns fewer removed than requested.

### Pitfall 2: Race Between Monitor and Acquire
**What goes wrong:** Background monitor reads Green, starts growing. Simultaneously, a burst of acquires drains the pool. Monitor adds tokens that are immediately consumed, exceeding the intended limit.
**Why it happens:** No lock coordination between the monitor's grow/shrink operations and the acquire/release fast path.
**How to avoid:** Use a single `asyncio.Lock` for all slot count modifications (grow, shrink, limit changes). The acquire/release path uses the lock-free Queue; only the *adjustment* operations need the lock.
**Warning signs:** `active_count` exceeds `current_limit`; slot count oscillates rapidly.

### Pitfall 3: Subprocess Blocking Event Loop
**What goes wrong:** Using `subprocess.run()` (synchronous) to read sysctl blocks the entire asyncio event loop for the subprocess duration.
**Why it happens:** `subprocess.run()` is a blocking call. Even though sysctl is fast (<10ms), under memory pressure the OS may delay subprocess creation significantly.
**How to avoid:** Use `asyncio.create_subprocess_exec()` for all subprocess calls. Cache the result and use the cached value in the hot path (`acquire()`).
**Warning signs:** Event loop lag spikes correlating with memory checks; tasks appear to stall periodically.

### Pitfall 4: TaskGroup Cancellation Cascade
**What goes wrong:** One agent's `OllamaInferenceError` propagates out of its task, causing TaskGroup to cancel all other agents in the wave. A single flaky inference kills 15 healthy ones.
**Why it happens:** TaskGroup's structured concurrency design: any unhandled exception in any task triggers cancellation of all siblings.
**How to avoid:** Wrap each agent task in try/except that catches all exceptions and returns a PARSE_ERROR `AgentDecision`. Only truly unrecoverable errors (like GovernorCrisisError) should propagate.
**Warning signs:** Waves producing 100% PARSE_ERROR after a single Ollama hiccup.

### Pitfall 5: Crisis Timeout Never Resetting
**What goes wrong:** The 5-minute crisis timeout fires even though agents are successfully completing inferences, because the timeout clock is not properly connected to inference completion signals.
**Why it happens:** The crisis timer runs in the background monitor, but successful inference happens in agent_worker/batch_dispatcher. Without a shared signal, the monitor cannot see successes.
**How to avoid:** Use an `asyncio.Event` or a monotonic timestamp attribute (`_last_successful_inference: float`) on the governor that `release()` updates on success and the monitor reads.
**Warning signs:** Simulation aborts despite agents completing; crisis timeout fires during healthy operation under moderate memory pressure.

### Pitfall 6: psutil Misleading on Apple Silicon
**What goes wrong:** `psutil.virtual_memory().percent` reports high usage (70-80%) even when the system is comfortable, because macOS aggressively uses memory for file caching and compressed pages.
**Why it happens:** psutil counts file cache and compressed memory as "used". macOS reclaims this instantly when needed. The kernel's `memorystatus_vm_pressure_level` accounts for this; psutil does not.
**How to avoid:** This is exactly why D-12 specifies dual-signal with kernel pressure as *master*. Never make critical decisions (halt, abort) based on psutil alone. Use psutil for gradual throttle/scale decisions; use kernel pressure level for crisis decisions.
**Warning signs:** Governor throttling at 80% psutil while `kern.memorystatus_vm_pressure_level` is still 1 (Green).

## Code Examples

### GovernorSettings Extensions
```python
# Source: Existing config.py pattern + CONTEXT.md decisions
class GovernorSettings(BaseModel):
    """Resource governor thresholds for memory-aware throttling."""

    baseline_parallel: int = Field(default=8, ge=1, le=32)
    max_parallel: int = Field(default=16, ge=1, le=32)
    memory_throttle_percent: float = Field(default=80.0, ge=50.0, le=95.0)
    memory_pause_percent: float = Field(default=90.0, ge=60.0, le=99.0)
    check_interval_seconds: float = Field(default=2.0, ge=0.5, le=10.0)
    # New for Phase 3:
    scale_up_threshold_percent: float = Field(default=60.0, ge=30.0, le=80.0)
    scale_up_consecutive_checks: int = Field(default=3, ge=1, le=10)
    crisis_timeout_seconds: float = Field(default=300.0, ge=30.0, le=600.0)
    slot_adjustment_step: int = Field(default=2, ge=1, le=4)
    batch_failure_threshold_percent: float = Field(default=20.0, ge=5.0, le=50.0)
    jitter_min_seconds: float = Field(default=0.5, ge=0.0, le=2.0)
    jitter_max_seconds: float = Field(default=1.5, ge=0.5, le=5.0)
```

### GovernorCrisisError
```python
# Source: Existing errors.py pattern
class GovernorCrisisError(Exception):
    """Raised when governor crisis timeout expires.

    5 minutes of sustained Yellow/Red pressure with no successful
    inference triggers simulation abort (D-07).
    """
    def __init__(self, message: str, duration_seconds: float) -> None:
        super().__init__(message)
        self.duration_seconds = duration_seconds
```

### StateStore Governor Metrics (Data Contract for Phase 10)
```python
# Source: D-09, D-11 from CONTEXT.md
# Emitted on state change only, not every check interval

@dataclass(frozen=True)
class GovernorMetrics:
    """Governor telemetry snapshot for TUI consumption (Phase 10)."""
    current_slots: int          # Current slot count (1-16)
    active_count: int           # Currently checked-out slots
    pressure_level: str         # "green", "yellow", "red"
    memory_percent: float       # psutil percent used
    governor_state: str         # "running", "throttled", "paused", "crisis", "recovering"
    timestamp: float            # monotonic clock
```

### ResourceGovernorProtocol Extensions
```python
# Source: Existing governor.py Protocol
class ResourceGovernorProtocol(Protocol):
    """Interface contract for ResourceGovernor."""

    async def acquire(self) -> None: ...
    def release(self, *, success: bool = True) -> None: ...  # NEW: success flag
    async def start_monitoring(self) -> None: ...
    async def stop_monitoring(self) -> None: ...

    @property
    def current_limit(self) -> int: ...

    @property
    def active_count(self) -> int: ...

    @property
    def is_paused(self) -> bool: ...  # NEW: for batch dispatcher
```

Note: The `release(success=True)` signature change is backward-compatible (keyword-only with default). The `agent_worker()` context manager in `worker.py` will need a minor update to pass `success=False` when inference fails, enabling the governor to track batch failure rates for D-04/D-05.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `asyncio.gather(*tasks)` | `asyncio.TaskGroup` | Python 3.11 (Oct 2022) | Structured concurrency; no silent task GC; ExceptionGroup support |
| `asyncio.Semaphore` for concurrency | Queue token pool for dynamic limits | Pattern, not version change | Enables runtime resizing without deadlock risk |
| `/usr/bin/memory_pressure` parsing | `sysctl -n kern.memorystatus_vm_pressure_level` | macOS native API | Correct API for reading (not stressing) memory pressure |
| `except Exception` blocks | `except* ExceptionType` (ExceptionGroup) | Python 3.11 (Oct 2022) | Required for proper TaskGroup exception handling |

**Deprecated/outdated:**
- **`/usr/bin/memory_pressure` for monitoring:** This is a stress-testing tool, not a monitoring tool. The CONTEXT.md D-12 references it as "Signal B" but the actual implementation should use `sysctl kern.memorystatus_vm_pressure_level` instead. The intent (read macOS kernel pressure level) is correct; the mechanism (parse memory_pressure output) is incorrect.

## Open Questions

1. **Release success tracking granularity**
   - What we know: D-04 says batch failure threshold is per-wave (8-16 agents). Governor needs to know which releases were from successful vs failed inferences.
   - What's unclear: Should the governor itself track success/failure, or should the batch dispatcher track it externally and call `governor.shrink()` when threshold is exceeded?
   - Recommendation: Batch dispatcher tracks failure count per wave and calls governor methods. Governor provides `shrink()` and `report_wave_result(success_count, failure_count)` but does not internally distinguish success/failure on release. This keeps the governor focused on slot management.

2. **Cached pressure level staleness**
   - What we know: Background monitor polls every 2s. `acquire()` should use the cached value, not run a subprocess.
   - What's unclear: Is 2s staleness acceptable for crisis detection? A pressure spike between polls could allow 2s of over-dispatch.
   - Recommendation: 2s is acceptable. The kernel's own memory pressure response (terminating processes, compressing pages) operates on similar timescales. The psutil check in `acquire()` provides a faster signal for gradual throttling.

3. **Worker.py changes for success tracking**
   - What we know: `agent_worker()` calls `governor.release()` in the finally block. Phase 3 needs to distinguish success vs failure releases for D-04.
   - What's unclear: How to detect success/failure inside the context manager without changing the yield pattern.
   - Recommendation: Add `success: bool = True` kwarg to `release()`. The batch dispatcher's `_safe_agent_inference` wrapper (which catches exceptions) can set a flag, and the `agent_worker` finally block can pass it through. Alternatively, track at the batch dispatcher level by inspecting returned `AgentDecision.signal`.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11+ | asyncio.TaskGroup, except* syntax | Yes | 3.11.5 (via uv) | -- |
| psutil | Memory monitoring (Signal A) | Yes | 7.2.2 | -- |
| sysctl command | Memory pressure level (Signal B) | Yes | macOS Darwin 25.3.0 | Fall back to psutil-only on non-macOS |
| structlog | Logging (D-09, D-10) | Yes | 25.5.0 | -- |
| backoff | OllamaClient retry (D-16) | Yes | 2.2.1 | -- |
| kern.memorystatus_vm_pressure_level | macOS pressure enum | Yes | Returns 1 (verified) | -- |

**Missing dependencies with no fallback:**
- None

**Missing dependencies with fallback:**
- None

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.0+ with pytest-asyncio 0.24.0+ |
| Config file | `pyproject.toml` [tool.pytest.ini_options] asyncio_mode = "auto" |
| Quick run command | `uv run pytest tests/test_governor.py tests/test_batch_dispatcher.py tests/test_memory_monitor.py -x -q` |
| Full suite command | `uv run pytest tests/ -x --tb=short` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INFRA-01 | Token pool starts at 8, scales to 16, acquire/release contract | unit | `uv run pytest tests/test_governor.py -x` | No -- Wave 0 |
| INFRA-02-a | psutil threshold triggers throttle at 80%, pause at 90% | unit | `uv run pytest tests/test_memory_monitor.py -x` | No -- Wave 0 |
| INFRA-02-b | sysctl pressure level Yellow/Red triggers crisis (drop to 1) | unit | `uv run pytest tests/test_memory_monitor.py -x` | No -- Wave 0 |
| INFRA-07 | Batch dispatch uses TaskGroup, partial failures produce PARSE_ERROR | unit | `uv run pytest tests/test_batch_dispatcher.py -x` | No -- Wave 0 |
| INFRA-09-a | Batch failure rate >=20% triggers governor shrinkage | unit | `uv run pytest tests/test_batch_dispatcher.py -x` | No -- Wave 0 |
| INFRA-09-b | Governor shrinks by 2 per trigger, minimum 1 | unit | `uv run pytest tests/test_governor.py -x` | No -- Wave 0 |
| D-01 | Gradual recovery +2 slots per check_interval after crisis | unit | `uv run pytest tests/test_governor.py::test_gradual_recovery -x` | No -- Wave 0 |
| D-02 | Scale above baseline after 3 consecutive Green checks under 60% | unit | `uv run pytest tests/test_governor.py::test_scale_up_above_baseline -x` | No -- Wave 0 |
| D-03 | Crisis recovery resets to baseline (8), not pre-incident | unit | `uv run pytest tests/test_governor.py::test_crisis_recovery_resets_to_baseline -x` | No -- Wave 0 |
| D-07 | 5-minute crisis timeout raises GovernorCrisisError | unit | `uv run pytest tests/test_governor.py::test_crisis_timeout_abort -x` | No -- Wave 0 |
| D-08 | Crisis timeout resets on successful inference | unit | `uv run pytest tests/test_governor.py::test_crisis_timeout_resets_on_success -x` | No -- Wave 0 |
| D-14 | Random jitter 0.5-1.5s applied before each agent dispatch | unit | `uv run pytest tests/test_batch_dispatcher.py::test_jitter_applied -x` | No -- Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_governor.py tests/test_batch_dispatcher.py tests/test_memory_monitor.py -x -q`
- **Per wave merge:** `uv run pytest tests/ -x --tb=short`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_governor.py` -- covers INFRA-01, D-01, D-02, D-03, D-07, D-08, INFRA-09-b (token pool, scaling, recovery, crisis)
- [ ] `tests/test_memory_monitor.py` -- covers INFRA-02 (psutil thresholds, sysctl parsing, dual-signal logic)
- [ ] `tests/test_batch_dispatcher.py` -- covers INFRA-07, INFRA-09-a, D-14 (TaskGroup dispatch, failure tracking, jitter)
- [ ] `tests/conftest.py` -- add fixtures for mock memory readings, mock governor, mock OllamaClient

### Test Design Notes for Memory Simulation

Testing memory pressure requires mocking since we cannot actually stress the machine in CI:

```python
# Fixture pattern for mocking psutil memory readings
@pytest.fixture()
def mock_memory(monkeypatch: pytest.MonkeyPatch):
    """Fixture to simulate different memory pressure levels."""
    def _set_percent(percent: float):
        mock_vm = MagicMock()
        mock_vm.percent = percent
        mock_vm.total = 68719476736  # 64GB
        mock_vm.available = int(68719476736 * (1 - percent / 100))
        monkeypatch.setattr("psutil.virtual_memory", lambda: mock_vm)
    return _set_percent

# Fixture pattern for mocking sysctl pressure level
@pytest.fixture()
def mock_pressure_level(monkeypatch: pytest.MonkeyPatch):
    """Fixture to simulate macOS pressure levels (1=Green, 2=Yellow, 4=Red)."""
    async def _set_level(level: int):
        async def fake_subprocess(*args, **kwargs):
            proc = MagicMock()
            async def communicate():
                return (str(level).encode(), b"")
            proc.communicate = communicate
            proc.returncode = 0
            return proc
        monkeypatch.setattr(
            "asyncio.create_subprocess_exec", fake_subprocess
        )
    return _set_level
```

## Sources

### Primary (HIGH confidence)
- `psutil.virtual_memory()` -- verified on target machine: returns `percent=41.2`, `total=68719476736` (64GB)
- `sysctl kern.memorystatus_vm_pressure_level` -- verified on target machine: returns 1 (NORMAL/Green); values: 1=NORMAL, 2=WARN, 4=CRITICAL
- `asyncio.TaskGroup` -- verified via Python 3.11.5 in project uv environment; cancellation behavior tested
- `asyncio.Queue` token pool -- tested locally; grow/shrink operations verified
- [Python 3.11 asyncio docs - Synchronization Primitives](https://docs.python.org/3/library/asyncio-sync.html)
- [Python 3.11 asyncio docs - TaskGroup](https://docs.python.org/3/library/asyncio-task.html)

### Secondary (MEDIUM confidence)
- [No pressure, Mon! - macOS memory pressure internals](https://newosxbook.com/articles/MemoryPressure.html) -- documents kern.memorystatus_vm_pressure_level values
- [Apple Developer - DISPATCH_SOURCE_TYPE_MEMORYPRESSURE](https://developer.apple.com/documentation/dispatch/dispatch_source_type_memorypressure) -- confirms macOS pressure level API
- [exelban/stats issue #1453](https://github.com/exelban/stats/issues/1453) -- community discussion of RAM pressure monitoring on macOS

### Tertiary (LOW confidence)
- None

## Project Constraints (from CLAUDE.md)

These directives from CLAUDE.md constrain all Phase 3 implementation:

1. **100% async (`asyncio`)** -- No blocking I/O on the main event loop. All subprocess calls must use `asyncio.create_subprocess_exec()`.
2. **Local First** -- All inference local via Ollama. Max 2 models loaded simultaneously.
3. **Memory Safety** -- Monitor RAM via `psutil`. Dynamically throttle `asyncio` semaphores; pause task queue at 90% utilization.
4. **Runtime:** Python 3.11+ (Strict typing), `uv` (Package manager), `pytest-asyncio`.
5. **Inference:** `ollama-python` (>=0.6.1). Models: `qwen3.5:35b` (Orchestrator) & `qwen3.5:9b` (Workers). Note: Phase 2 decisions updated these to `qwen3.5:32b` / `qwen3.5:7b`.
6. **Validation/Config:** `pydantic`, `pydantic-settings`.
7. **Logging:** `structlog`.
8. **GSD Workflow Enforcement:** All changes through GSD workflow.
9. **Strict typing** enforced via `mypy --strict`.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all libraries already installed and verified on target machine
- Architecture: HIGH - token pool pattern tested; sysctl verified; TaskGroup behavior confirmed
- Pitfalls: HIGH - each pitfall verified through local testing or official documentation

**Research date:** 2026-03-24
**Valid until:** 2026-04-24 (stable domain -- asyncio and psutil APIs are mature)
