# Phase 2: Ollama Integration - Context

**Gathered:** 2026-03-24
**Status:** Ready for planning
**Source:** User-provided design decisions ("Mechanical Heart" brief)

<domain>
## Phase Boundary

Phase 2 builds the async LLM client layer: an Ollama AsyncClient wrapper with sequential model loading, a typed AgentWorker factory as a context manager, structured output parsing with multi-tier fallback, and full resilience (backoff + semaphore guarding). The result is a single verified inference path: load model → acquire semaphore → call Ollama → parse Pydantic model → release → unload. No simulation logic, no graph writes.

</domain>

<decisions>
## Implementation Decisions

### Model Tags (Overrides Phase 1 defaults)

- **Orchestrator:** `qwen3.5:32b` with High Reasoning mode (`/think` flag or equivalent Modelfile option)
- **Worker agents:** `qwen3.5:7b`
- These override the Phase 1 decisions of `qwen3:32b` / `qwen3.5:4b`. Update `AppSettings` model tags accordingly.
- Note: Phase 1 research flagged `qwen3.5:7b` as non-existent at that time. User has confirmed these as the correct tags for the current Ollama library. Use them as specified.

### Sequential Model Loading (INFRA-03)

- Orchestrator (`qwen3.5:32b`) loads for seed injection, unloads completely before worker model loads.
- Worker (`qwen3.5:7b`) loads for agent inference, unloads when batch is complete.
- No dual-model coexistence — enforce via explicit `ollama.AsyncClient.delete()` / unload calls between phases.
- Implemented via `OllamaModelManager` (or equivalent) that tracks currently loaded model and ensures clean transitions.

### Ollama AsyncClient Wrapper (INFRA-04)

- All Ollama calls go through a single `OllamaClient` wrapper class using `ollama.AsyncClient`.
- `num_ctx` is set **only** via Modelfiles, never as a per-request parameter. Per-request `num_ctx` causes silent model reloads and must not appear anywhere in the codebase.
- Modelfiles live in `modelfiles/` at project root: `Modelfile.orchestrator` and `Modelfile.worker`.
- The client wrapper exposes `async def generate(...)` and `async def chat(...)` methods that enforce this contract.

### Worker Factory — AgentWorker (MANDATORY pattern)

- `AgentWorker` is implemented as a `contextlib.asynccontextmanager`, not a class with `__aenter__`/`__aexit__`.
- Pattern:
  ```python
  @asynccontextmanager
  async def agent_worker(persona: WorkerPersonaConfig) -> AsyncGenerator[AgentWorker, None]:
      await governor.acquire()
      try:
          yield AgentWorker(persona, ollama_client)
      finally:
          governor.release()
  ```
- Every LLM call that goes through a worker MUST be wrapped in `agent_worker(persona)`. No raw `ollama_client.generate()` calls outside this context manager.

### TypedDict for Persona Configuration

- Use `TypedDict` (not Pydantic BaseModel) for the runtime persona config passed into the worker context manager:
  ```python
  class WorkerPersonaConfig(TypedDict):
      agent_id: str
      bracket: str          # BracketType value
      influence_weight: float
      temperature: float
      system_prompt: str
      risk_profile: str
  ```
- The existing frozen Pydantic `AgentPersona` model (from Phase 1) is the source of truth. `WorkerPersonaConfig` is derived from it at dispatch time — a lightweight TypedDict for hot-path use, not a replacement.

### Governor Semaphore (INFRA-04 interface)

- Every LLM call acquires `governor.acquire()` before dispatching and releases on exit.
- Phase 2 uses the `ResourceGovernor` stub from Phase 1, with `acquire()`/`release()` wired to the semaphore.
- Full dynamic slot adjustment (Phase 3) builds on this interface — do NOT implement the memory-sensing logic here.
- Governor initial slot count: 8 (from AppSettings, configurable).

### Backoff + Resilience (INFRA-08 supporting pattern)

- Use the `backoff` library for all httpx Ollama calls: `@backoff.on_exception(backoff.expo, httpx.HTTPError, max_tries=3)`.
- Applies to: generate, chat, model load, model unload operations.
- On exhausted retries, raise a domain-specific `OllamaInferenceError` (not a raw httpx exception).
- Add `backoff>=2.2.1` to `pyproject.toml` dependencies.

### Structured Output Parsing — Multi-Tier Fallback (INFRA-08)

Parsing pipeline for every LLM response (in order):

1. **Tier 1 — Native JSON mode:** Request structured output via `format="json"` in the Ollama call. Attempt `AgentDecision.model_validate_json(response.message.content)`.
2. **Tier 2 — Regex extraction:** If Tier 1 fails, extract JSON block via `re.search(r'\{.*?\}', content, re.DOTALL)` and retry `model_validate_json`.
3. **Tier 3 — PARSE_ERROR:** If both fail, return `AgentDecision` with `signal=Signal.PARSE_ERROR`, `confidence=0.0`, `rationale="Parse failed: {raw[:200]}"`.

- Implement as `parse_agent_decision(raw: str) -> AgentDecision` in `src/alphaswarm/parsing.py`.
- Log tier used and any parse failures at DEBUG level with the raw content (truncated to 500 chars).

### Scope Constraints

- Do NOT implement dynamic slot scaling (Phase 3).
- Do NOT implement hybrid memory sensing — psutil + memory_pressure dual-signal is Phase 3.
- Do NOT implement random jitter in batching — that is Phase 3.
- Do NOT write to Neo4j (Phase 4).
- Do NOT implement the TUI update path (Phase 9).
- Modelfiles are created but model pull is out of scope — assume models are pre-pulled.

### Claude's Discretion

- Internal method names on OllamaClient beyond the required `generate` / `chat` interface.
- Error hierarchy depth (OllamaInferenceError subclasses).
- Test fixture design for mocking Ollama responses.
- Whether to use a separate `ModelfileManager` class or inline Modelfile path resolution.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Foundation (Phase 1 outputs)
- `.planning/phases/01-project-foundation/01-CONTEXT.md` — AppState, ResourceGovernor stub, AgentPersona types
- `.planning/phases/01-project-foundation/01-01-PLAN.md` — AgentPersona, BracketConfig, AppSettings definitions
- `.planning/phases/01-project-foundation/01-02-PLAN.md` — AppState container, ResourceGovernor stub interface

### Project Context
- `.planning/REQUIREMENTS.md` — INFRA-03, INFRA-04, INFRA-08 definitions
- `.planning/ROADMAP.md` — Phase 2 success criteria
- `.planning/research/STACK.md` — ollama-python, httpx, backoff library versions
- `.planning/research/ARCHITECTURE.md` — Component boundaries
- `CLAUDE.md` — Project constraints (sequential loading, async, M1 Max memory)

</canonical_refs>

<specifics>
## Specific Ideas

- Modelfiles directory: `modelfiles/Modelfile.orchestrator`, `modelfiles/Modelfile.worker`
- Orchestrator Modelfile sets `PARAMETER num_ctx 8192` and enables thinking mode if supported
- Worker Modelfile sets `PARAMETER num_ctx 4096` and `PARAMETER temperature 0.7` (overridden per-bracket via system prompt)
- Integration test: `test_integration_inference.py` — loads worker model, calls generate, validates returned `AgentDecision` object
- `AgentDecision` already defined in Phase 1 types — do not redefine, import from `alphaswarm.types`

</specifics>

<forward_decisions>
## Forward Decisions (Phase 3 Scope — DO NOT implement in Phase 2)

These decisions were provided with the Phase 2 brief and MUST be implemented in Phase 3:

### Hybrid Memory Sensing (Phase 3 — INFRA-01, INFRA-02)
- **Signal A:** `psutil.virtual_memory().percent` — target threshold < 90%
- **Signal B (Master):** subprocess call to `/usr/bin/memory_pressure` — parse output for `System memory pressure level: Green/Yellow/Red`
  - If `Yellow` or `Red`: immediately halt queue AND drop active slots to 1
  - If returns to `Green`: restore slot count and resume queue
- Dual-signal check runs on every `governor.acquire()` call and on a background polling interval

### Random Jitter in Batching (Phase 3 — INFRA-07)
- Before dispatching each agent call in a batch, apply `await asyncio.sleep(random.uniform(0.5, 1.5))`
- Prevents 100 agents hitting the memory controller at the same millisecond
- Applied in the batch dispatcher, not inside the worker context manager

</forward_decisions>

<deferred>
## Deferred Ideas

- Miro batcher (Phase 8)
- Neo4j graph writes (Phase 4)
- TUI live rendering (Phase 9)
- Dynamic slot scaling beyond initial semaphore (Phase 3)

</deferred>

---

*Phase: 02-ollama-integration*
*Context gathered: 2026-03-24 via user-provided design decisions*
