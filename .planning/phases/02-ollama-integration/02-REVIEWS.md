---
phase: 2
reviewers: [gemini, codex]
reviewed_at: 2026-03-24T23:00:00Z
plans_reviewed: [02-01-PLAN.md, 02-02-PLAN.md, 02-03-PLAN.md]
---

# Cross-AI Plan Review — Phase 2

## Gemini Review

This review evaluates the implementation plans for **Phase 2: Ollama Integration** of the AlphaSwarm project.

### 1. Summary
The plans provide a robust and architecturally sound approach to integrating local LLM inference while respecting the strict hardware and concurrency constraints of the M1 Max environment. The three-wave structure logically separates infrastructure (02-01), core logic (02-02), and integration (02-03). The use of Modelfiles to lock `num_ctx` and the 3-tier parsing fallback strategy directly addresses the most common failure modes in local Ollama deployments.

### 2. Strengths
*   **Context Control:** Hard-coding `num_ctx` in Modelfiles instead of per-request options is a high-signal decision that prevents the 10-30s reload latency often seen in dynamic Ollama usage.
*   **Memory Discipline:** The use of `keep_alive=0` for sequential model unloading is the correct mechanism for managing 64GB unified memory when switching between 32B and 7B models.
*   **Resilience:** The 3-tier parsing strategy (JSON mode -> Regex -> `PARSE_ERROR` object) ensures the simulation never crashes due to a "creative" LLM response, which is critical for a 100-agent cascade.
*   **Performance Awareness:** Using `TypedDict` for `WorkerPersonaConfig` in the hot path (100 agents) minimizes the overhead compared to Pydantic validation during high-concurrency initialization.
*   **Governor Integration:** Implementing the `agent_worker` context manager to wrap the governor semaphore ensures that backpressure is handled at the resource acquisition level, preventing event loop starvation.

### 3. Concerns
*   **Model Creation (MEDIUM):** The plans mention *creating* Modelfiles but do not explicitly define a task for *registering* them with Ollama (e.g., `ollama create alphaswarm-worker -f modelfiles/Modelfile.worker`). Without this, the system will attempt to pull base tags and lose the `num_ctx` configuration.
*   **State Leakage on Failure (MEDIUM):** While `ensure_clean_state()` is mentioned, the plan lacks a clear "Cleanup/Teardown" hook in the application lifecycle. If the orchestrator crashes before unloading, the worker model may fail to load due to OOM on the M1 Max.
*   **Backoff Scope (LOW):** Applying `@backoff` to an internal `_chat_with_backoff` method is good, but ensure the timeout settings on `httpx` (within the `AsyncClient`) are high enough to accommodate the 32B model's "thinking" time or initial load time.
*   **JSON Mode Hallucination (LOW):** qwen3.5:7b is generally good at JSON, but occasionally it may wrap the JSON in Markdown blocks even with `format="json"`. The Tier 2 regex needs to be robust enough to handle leading/trailing text.

### 4. Suggestions
*   **Automated Model Registration:** In Plan 02-01, add a utility script or a setup command (e.g., `make setup-models`) that runs the `ollama create` commands for both the orchestrator and worker tags.
*   **Health Checks:** In `OllamaModelManager.load_model()`, implement a heartbeat check beyond just `ps()`. A tiny `generate` call with 1 token ensures the model is actually responsive in the GPU layers.
*   **Explicit Logging of "Thinking":** Since Qwen3.5 supports reasoning, ensure the `OllamaClient` captures and logs the `message.thinking` field (even if it's discarded for the final `AgentDecision`) to aid in debugging agent logic during Phase 3.
*   **Graceful Shutdown:** Update `app.py` or the main entry point to call `OllamaModelManager.ensure_clean_state()` inside a `try...finally` block to guarantee the GPU is cleared.

### 5. Risk Assessment: LOW
The plan is highly detailed and aligns with "Senior Engineer" standards. It prioritizes stability and predictability over feature creep. The primary risks are operational (local Ollama state) rather than architectural. By following the sequential loading and standardized context rules, the project avoids the "latency death spiral" common in multi-model local simulations.

**Verdict:** Proceed to Execution. Ensure the model registration step is accounted for in the first wave.

---

## Codex Review

**Overall**

The wave ordering is sensible, but two gaps keep the phase from being convincingly complete as written: Modelfiles are not yet tied to an actual model-build/alias flow, and no plan includes a real orchestrator -> unload -> worker smoke path. Also normalize the model names first: your "Requirements Addressed" block still says `qwen3:32b` / `qwen3.5:4b`, while the locked decisions and plans use `qwen3.5:32b` / `qwen3.5:7b`.

### Plan 02-01: Foundation

**Summary**
Good foundation wave. It front-loads the right placeholder replacements and keeps most Phase 2 prerequisites out of later waves. The main weakness is that it treats Modelfiles and dependency installation as if they are sufficient by themselves, when the phase goal depends on those pieces being operational, not just present.

**Strengths**
- Good sequencing: config, types, governor, and exceptions come before client code.
- Matches the locked decisions on TypedDict, semaphore-based governor, and new model tags.
- Moves current Phase 1 placeholders toward usable Phase 2 infrastructure.

**Concerns**
- HIGH: Modelfiles alone do not achieve "num_ctx only via Modelfiles." As written, there is no step to create derived Ollama model aliases and point config at those aliases.
- MEDIUM: `WorkerPersonaConfig` duplicates the existing `AgentPersona` path without defining the conversion boundary from current persona generation.
- MEDIUM: "Install via uv" is not enough for a repo plan; `pyproject.toml` and `uv.lock` need explicit updates, and `httpx` should be a direct dependency if imported.
- LOW: Precreating multiple stub/skip tests adds churn and can create false progress.

**Suggestions**
- Add an explicit model alias/build step and name the aliases that runtime code will call.
- Update the old defaults and startup/config tests in the same wave, not later.
- Replace broad test stubs with a smaller set of concrete failing tests or tracked TODOs.

**Risk Assessment**: MEDIUM

### Plan 02-02: Core Modules

**Summary**
This is the critical wave, and it has the right module split, but it also carries the largest correctness risk. Retry behavior, sequential load/unload, and parsing are all here, and the current plan leaves too much ambiguity around wrapper boundaries, concurrency control, and what "clean state" is allowed to touch.

**Strengths**
- Good separation between client wrapper, model manager, and parser.
- Correct instinct to keep retry logic on an internal method, not the public API.
- "Parser never raises" is a strong contract for downstream code.

**Concerns**
- HIGH: `RequestError` "propagates immediately" conflicts with the locked boundary that public Ollama calls should raise `OllamaInferenceError`.
- HIGH: No internal serialization is specified for model transitions. Concurrent async calls can still race and violate sequential loading.
- HIGH: `ensure_clean_state()` unloading all loaded models is too broad and can disrupt unrelated local Ollama work.
- MEDIUM: Retrying all `ResponseError` cases is too coarse; permanent failures like missing models should not be retried.
- MEDIUM: `re.compile(r"\{.*\}", re.DOTALL)` is greedy and brittle with code fences or multiple JSON objects.
- MEDIUM: The plan does not explicitly say model-management calls go through the single `OllamaClient` wrapper.
- MEDIUM: A one-shot `ps()` check is race-prone; load/unload verification needs polling with timeout.

**Suggestions**
- Keep `RequestError` non-retriable, but still wrap it at the public boundary as `OllamaInferenceError`.
- Add an internal `asyncio.Lock` plus `current_model` tracking so load/unload is serialized and idempotent.
- Scope cleanup to AlphaSwarm's configured models, not every loaded model on the machine.
- Prefer schema-constrained output with `AgentDecision.model_json_schema()` over plain `format="json"`.
- Replace the greedy regex with code-fence stripping plus first-object extraction.
- Normalize third-party response shapes inside the wrapper so parser inputs are always plain text.

**Risk Assessment**: HIGH

### Plan 02-03: Integration

**Summary**
This wave wires the happy path, but it does not fully demonstrate the phase goal. The main issue is that it proves only mocked worker inference, while the phase explicitly requires sequential orchestrator/worker behavior and a real single-agent inference script.

**Strengths**
- Good focus on end-to-end flow and backpressure behavior.
- Useful mocked integration cases for parse fallback, peer context, and semaphore blocking.
- Backward compatibility in `AppState` is considered.

**Concerns**
- HIGH: There is no explicit orchestrator -> unload -> worker flow, so success criterion 1 is not actually verified.
- HIGH: Mock-only integration tests do not satisfy the required real smoke path that returns a validated `AgentDecision`.
- MEDIUM: `AgentWorker` class plus `agent_worker` context manager is ambiguous and does not cleanly match the locked design decision.
- MEDIUM: Acquiring the governor for the worker context lifetime is broader than "every LLM call acquires before dispatch," and model load/unload can still bypass it.
- LOW: Hardcoding `qwen3.5:7b` duplicates config and invites drift.
- LOW: `with_ollama=False` introduces optional-client lifecycle complexity without a shutdown story.

**Suggestions**
- Pick one worker abstraction and make it explicit; the simplest path is an async context manager yielding a thin inference helper.
- Move governor acquisition to the actual dispatch boundary and include model-management calls.
- Default model selection from settings/AppState, not string literals.
- Add one opt-in local smoke script/test that does: orchestrator call, verify unload, worker call, validate `AgentDecision`.
- Define client shutdown or keep client creation outside `AppState` until an async app lifecycle exists.

**Risk Assessment**: HIGH

---

## Consensus Summary

### Agreed Strengths
- **Wave structure is sound:** Both reviewers agree the 3-wave decomposition (foundation -> core modules -> integration) is well-sequenced and logical.
- **Modelfile-based num_ctx is correct:** Both confirm this prevents the 10-30s silent reload latency trap.
- **3-tier parsing fallback is resilient:** The "never raises" contract for `parse_agent_decision` is praised by both as critical for 100-agent reliability.
- **Backoff on internal method is good design:** Keeping retry logic on `_chat_with_backoff` rather than the public API is correct.
- **Governor semaphore integration via context manager:** Both agree this is the right pattern for backpressure.

### Agreed Concerns
1. **HIGH -- Modelfile registration gap:** Both reviewers flag that creating Modelfiles is insufficient -- there is no step to run `ollama create` to register derived model aliases. Without this, `num_ctx` settings are never applied at runtime.
2. **HIGH -- No orchestrator -> unload -> worker smoke test:** Both note that the phase's most important success criterion (sequential model loading with no dual-model coexistence) is never actually verified end-to-end, even with mocks.
3. **MEDIUM -- `ensure_clean_state()` too broad:** Both warn that unloading ALL models on the machine risks disrupting unrelated Ollama work. Should be scoped to AlphaSwarm's configured models only.
4. **MEDIUM -- Greedy regex fragility:** Both raise concerns about `re.compile(r"\{.*\}", re.DOTALL)` being brittle with code fences, multiple JSON objects, or nested structures.
5. **MEDIUM -- No graceful shutdown / lifecycle teardown:** Both note there's no `try...finally` cleanup ensuring models are unloaded if the application crashes mid-inference.

### Divergent Views
- **Overall risk level:** Gemini rates the phase LOW risk overall ("proceed to execution"), while Codex rates Plans 02-02 and 02-03 as HIGH risk due to concurrency gaps, the RequestError wrapping boundary, and mock-only integration tests.
- **RequestError handling:** Codex flags that `RequestError` propagating unwrapped conflicts with the OllamaInferenceError boundary contract. Gemini does not raise this concern.
- **Schema-constrained output:** Codex suggests using `AgentDecision.model_json_schema()` with the `format` parameter instead of plain `"json"` mode. Gemini does not suggest this change.
- **Model transition serialization:** Codex wants an `asyncio.Lock` to serialize load/unload operations. Gemini does not flag this, likely because the sequential model usage pattern in the current phase makes races unlikely.
- **Test stub approach:** Codex considers pre-created stub tests as "churn and false progress." Gemini does not comment on test scaffolding strategy.
