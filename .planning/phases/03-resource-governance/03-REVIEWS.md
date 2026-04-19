---
phase: 3
reviewers: [gemini]
reviewed_at: 2026-03-24
plans_reviewed: [03-01-PLAN.md, 03-02-PLAN.md]
---

# Cross-AI Plan Review — Phase 3

## Gemini Review

This review covers **Plan 03-01 (Core ResourceGovernor)** and **Plan 03-02 (Batch Dispatch Layer)** for the AlphaSwarm Phase 3 implementation.

### 1. Summary
The proposed plans represent a sophisticated and hardware-aware approach to resource management on Apple Silicon. By prioritizing the macOS kernel's `vm_pressure_level` over standard `psutil` metrics, the system avoids the common pitfall of "ghost" memory usage reporting on M1/M2/M3 chips. The transition from a static `BoundedSemaphore` to a `Queue`-based `TokenPool` provides the necessary elasticity to meet the dynamic scaling requirements (8 to 16 slots). The architecture correctly balances high-concurrency goals with the volatile nature of local LLM inference, ensuring that a single failing agent or a sudden system-wide memory spike does not crash the entire simulation.

### 2. Strengths
*   **Hardware-Specific Sensing**: Using `sysctl kern.memorystatus_vm_pressure_level` as the master signal is an excellent engineering choice. `psutil` is notoriously unreliable on macOS due to how "Wired" and "Compressed" memory are reported; kernel pressure is the only true indicator of impending OOM.
*   **Elastic Concurrency**: Implementing a custom `TokenPool` via `asyncio.Queue` solves the "non-resizable semaphore" limitation in Python's `asyncio` library cleanly.
*   **Task Isolation**: The use of `asyncio.TaskGroup` combined with a `_safe_agent_inference` wrapper ensures the system adheres to the "all-or-nothing" cancellation logic of TaskGroups while still allowing individual agent failures (like parsing errors) to be handled gracefully.
*   **Crisis Management**: The 5-minute sustained crisis timeout (D-07) and the "reset to baseline" (D-03) policy provide clear guardrails against infinite loops in a degraded state.
*   **Jitter Implementation**: Adding 0.5s-1.5s jitter is a professional-grade touch that prevents "thundering herd" issues when Ollama attempts to load model weights into VRAM simultaneously for multiple requests.

### 3. Concerns
*   **TokenPool Shrinking Logic (Severity: MEDIUM)**:
    If the governor decides to shrink the pool from 8 to 6 while all 8 tokens are currently "checked out," the logic must account for "debt." The plan should specify if `shrink()` immediately removes items from the queue or waits for them to be returned. If not handled carefully, the pool size could become inconsistent.
*   **Exception Shadowing (Severity: MEDIUM)**:
    In `_safe_agent_inference`, the plan mentions a `try/except` wrapper. It is critical that this wrapper does **not** catch `BaseException` (like `KeyboardInterrupt`) or `asyncio.CancelledError`, as this would break the user's ability to stop the CLI and the `TaskGroup`'s ability to clean up.
*   **Dual-Signal Conflict (Severity: LOW)**:
    If `psutil` reports 85% (Throttle) but `sysctl` reports GREEN (Run), the plan implies `sysctl` is master. However, the logic for "is_throttle_zone" should clearly define the precedence to avoid "flapping" between states if the two sensors disagree.
*   **Ollama Loaded Model State (Severity: LOW)**:
    The governor monitors system memory, but Ollama often keeps models in VRAM for a timeout period. The governor doesn't seem to have visibility into Ollama's internal cache state, which might lead to aggressive scaling right before Ollama decides to load a second/third model.

### 4. Suggestions
*   **Token Debt Pattern**: For `TokenPool.shrink(n)`, implement a "debt" counter. When tokens are released, check the debt; if debt > 0, discard the token instead of putting it back in the queue. This avoids blocking the `shrink` call while waiting for active tasks to finish.
*   **State Transition Logging**: Ensure the `ResourceGovernor` logs not just the *new* state, but the *reason* (e.g., "Throttling: sysctl=YELLOW, psutil=82%"). This will be vital for debugging the TUI during the 100-agent stress tests.
*   **Backoff Reset**: In `OllamaClient`, ensure the exponential backoff resets after a successful call. If the 20% failure threshold is hit and the governor shrinks, the remaining agents should start with a clean backoff timer to prevent unnecessary delays during recovery.
*   **Explicit Cleanup**: Add a `stop()` method to `ResourceGovernor` to explicitly cancel the `_monitor_loop` and clear the `TokenPool` to ensure a clean shutdown in the TUI.

### 5. Risk Assessment
**Risk Level: LOW**

**Justification**:
The plan is highly aligned with the project's specific constraints (local M1 hardware, async Python). The dependency ordering (Core Governor -> Batch Dispatcher) is correct. The most significant risks -- OOM crashes and silent task death -- are directly addressed by the dual-signal sensing and `TaskGroup` requirements. As long as the `TokenPool` resizing logic is implemented with "debt" handling, the transition to Phase 3 should be stable.

---

## Codex Review

*Codex CLI invocation failed — review not available.*

---

## Consensus Summary

*(Single reviewer — consensus analysis requires 2+ reviewers)*

### Key Concerns to Address

1. **TokenPool shrink debt handling (MEDIUM)** — When all tokens are checked out, shrink() needs a "debt" pattern to avoid pool size inconsistency
2. **Exception shadowing in _safe_agent_inference (MEDIUM)** — Must not catch BaseException/CancelledError — only catch Exception to preserve TaskGroup cleanup and Ctrl+C
3. **Dual-signal precedence clarity (LOW)** — Define explicit precedence when psutil and sysctl disagree
4. **State transition reason logging (suggestion)** — Log both new state AND the trigger reason

### Overall Risk: LOW
Plans are well-aligned with hardware constraints and project architecture.
