---
phase: 2
reviewers: [claude]
reviewed_at: 2026-03-24T22:30:00Z
plans_reviewed: [02-01-PLAN.md, 02-02-PLAN.md, 02-03-PLAN.md]
---

# Cross-AI Plan Review — Phase 2

## Claude Review

These plans are exceptionally well-structured. The 3-wave decomposition (Foundation -> Core Modules -> Wiring) creates clean dependency boundaries with no circular dependencies. Each plan specifies exact code, precise acceptance criteria, and automated verification. The architecture respects user-locked decisions throughout. The primary risks are around model tag validity and a subtle bug in the backoff/error-wrapping pattern.

### Plan 02-01 (Wave 1: Foundation) — Risk: LOW

**Strengths:**
- Clean layering: errors, types, config updates, and governor upgrade are all leaf-level changes with no cross-dependencies
- Test stubs with pytest.skip() document the expected test surface before implementation exists
- Governor upgrade from no-op to real BoundedSemaphore correctly placed in Wave 1
- AgentDecision as frozen Pydantic model with constrained fields prevents invalid values from propagating

**Concerns:**
- LOW: `_active_count` is not thread-safe (fine in asyncio single-loop, but fragile if multi-threaded)
- LOW: `WorkerPersonaConfig.risk_profile` typed as `str` while `AgentPersona.risk_profile` is `float` — conversion footgun
- LOW: Modelfile temperature 0.7 hardcoded while WorkerPersonaConfig has per-persona temperature field

### Plan 02-02 (Wave 2: Core Modules) — Risk: MEDIUM

**Strengths:**
- Backoff on `_chat_with_backoff` (internal) rather than `chat` (public) is subtle but critical — correctly ensures OllamaInferenceError wrapping only after all retries exhausted
- `_strip_num_ctx` as module-level function makes it independently testable
- OllamaModelManager uses ps() for verification, not just trusting unload succeeded
- 3-tier parsing with greedy regex correctly explained to prevent future "fix" to lazy match

**Concerns:**
- HIGH: Double exception wrapping interaction between backoff decorator and try/except in `chat()` is fragile if someone later adds `on_giveup` or `raise_on_giveup=True` to backoff config. Works correctly now, but add a comment documenting this dependency.
- MEDIUM: `OllamaModelManager.load_model()` sends real "ping" inference request, wasting inference time. `keep_alive="5m"` with `messages=[]` could be faster.
- MEDIUM: Greedy regex `{.*}` may overcapture if LLM outputs multiple JSON objects. Tier 3 is safety net.
- LOW: `OllamaModelManager` calls `client.raw_client.ps()` — mild abstraction leak. Consider adding `ps()` to OllamaClient.
- LOW: `test_parse_logs_tier_used` using capsys is fragile. Use `structlog.testing.capture_logs()` instead.

### Plan 02-03 (Wave 3: Wiring) — Risk: MEDIUM

**Strengths:**
- `agent_worker` with `governor.release()` in `finally:` guarantees cleanup on exception
- `test_governor_backpressure` with single-slot proving semaphore ordering is excellent
- `think=False` prevents thinking output from contaminating JSON parsing
- `with_ollama=False` default preserves backward compatibility with Phase 1 tests
- `peer_context` as system message (not user message) is correct instruction/response boundary design

**Concerns:**
- MEDIUM: `infer()` docstring says "never raises" but `OllamaClient.chat()` CAN raise `OllamaInferenceError` or `RequestError`. Docstring should say "never raises on parse failure" instead.
- MEDIUM: `mock_client_success` uses `OllamaClient.__new__()` bypassing `__init__` — fragile if init changes.
- LOW: `test_governor_backpressure` uses `asyncio.sleep(0.01)` for ordering — racy on loaded CI. Use `asyncio.Event` instead.
- LOW: `agent_worker` defaults model to hardcoded `"qwen3.5:7b"` — should require parameter or pull from config.

### Cross-Plan Concerns

1. **MEDIUM: No test for OllamaInferenceError propagation through agent_worker.** Tests only use generic RuntimeError.
2. **MEDIUM: Model tag validity unverified.** qwen3.5:7b/32b may not exist — add manual verification step to Phase 2 SUMMARY.
3. **LOW: No `__init__.py` updates.** Five new modules created but no re-exports from package init.
4. **LOW: Regex parser edge case with multiple JSON objects.** think=False mitigates for workers, but orchestrator (Phase 5) may hit this.

---

## Consensus Summary

(Single reviewer — no consensus analysis applicable)

### Key Strengths
- Exceptionally well-structured 3-wave decomposition with clean dependency boundaries
- Precise acceptance criteria and automated verification on every task
- Architecture consistently respects user-locked decisions
- Governor upgrade correctly placed in Wave 1 for Wave 2/3 testing

### Top Concerns (by severity)
1. **HIGH:** Backoff/exception-wrapping coupling in OllamaClient.chat() — add documenting comment
2. **MEDIUM:** `infer()` docstring misleadingly says "never raises" — fix during implementation
3. **MEDIUM:** No test for OllamaInferenceError propagation through agent_worker
4. **MEDIUM:** Model tag validity remains unverified at plan level

### Recommendation
**Proceed with execution.** Address the HIGH concern (documenting comment) and MEDIUM concerns (docstring fix, additional test, backpressure test ordering) during implementation. None warrant plan revision.
