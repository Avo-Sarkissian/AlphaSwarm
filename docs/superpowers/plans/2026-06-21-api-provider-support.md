# API Inference Provider Support — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional, opt-in cloud inference path (OpenAI-compatible + native Anthropic) alongside the existing local Ollama path, configured per-role via a settings menu, with adaptive rate limiting and a hard spend cap — local stays the default and behaves identically.

**Architecture:** Introduce an `InferenceProvider` protocol with three adapters (Ollama pass-through, OpenAI-compatible, Anthropic). All five inference callers depend on the protocol. A parallel `ConcurrencyController` protocol has two implementations — the existing memory governor (local) and a new token-bucket rate-limit controller (cloud) with a `BudgetMeter`. Runtime provider/model/key selection persists to a gitignored config file, edited through new settings endpoints + UI.

**Tech Stack:** Python 3.11 (strict mypy), `httpx` (OpenAI-compatible transport, already a dep), `anthropic` SDK (new dep), pydantic / pydantic-settings, FastAPI, React + TypeScript + Vite, pytest-asyncio.

## Global Constraints

- 100% async; no blocking I/O on the event loop (offload sync work via `asyncio.to_thread`).
- Local-first: default config = both roles Ollama with current MLX models; `.secrets/inference.toml` need not exist for local to work.
- Secrets never reach the browser or logs; `GET /api/settings` masks keys; structlog redaction covers `api_key`/`authorization`.
- All new unit tests run under the `pytest-socket` block (`--disable-socket`); real network calls only behind `@pytest.mark.enable_socket` in `tests/integration/`.
- mypy strict must pass; ruff (E,F,I,N,W,UP,B,SIM) clean; import-linter contract intact.
- The existing test suite must keep passing unchanged (additive only).
- `BudgetExceededError` and `GovernorCrisisError` are never swallowed by `_safe_agent_inference`.
- Decimal for money; never float for cost.

---

## File Structure

**New (`src/alphaswarm/inference/`)**
- `__init__.py` — package exports.
- `types.py` — `InferenceMessage`, `InferenceResult`, `ProviderRole`.
- `provider.py` — `InferenceProvider` protocol.
- `schema.py` — JSON-Schema → provider-specific structured-output translation helpers.
- `ollama_provider.py` — `OllamaProvider` (wraps `OllamaClient` + `OllamaModelManager`).
- `openai_provider.py` — `OpenAICompatProvider` (httpx).
- `anthropic_provider.py` — `AnthropicProvider` (anthropic SDK).
- `factory.py` — `build_providers`, `build_controller`.
- `concurrency.py` — `ConcurrencyController` protocol.
- `rate_limit.py` — `RateLimitController` + token buckets.
- `budget.py` — `BudgetMeter`, pricing table, cost estimate.

**New (web/frontend/tests)**
- `src/alphaswarm/web/routes/settings.py`
- `frontend/src/api/settings.ts`
- `frontend/src/components/settings_inference.tsx` (section embedded into existing settings)
- `frontend/src/components/run_confirm.tsx` (cloud pre-run estimate modal)
- Tests mirror each module under `tests/` (+ `tests/integration/` for live provider smoke).

**Modified**
- `config.py` (`ProviderType`, `RoleConfig`, `InferenceConfig`, file loader)
- `errors.py` (`InferenceError`, `BudgetExceededError`, `AuthError`)
- `worker.py`, `seed.py`, `advisory/engine.py`, `report.py`, `interview.py` (depend on protocol)
- `simulation.py` (call `provider.prepare()/teardown()`; pass providers)
- `governor.py` (implement `ConcurrencyController`)
- `batch_dispatcher.py` (controller protocol; never-catch `BudgetExceededError`)
- `web/app.py`, `web/simulation_manager.py` (build providers/controller per active config at run start; estimate; reject settings change mid-run)
- `web/broadcaster.py`, `state.py` (mode-aware metrics)
- `frontend/src/adapter/frame.ts`, KPI strip, mode chip
- structlog redaction processor, `.gitignore`, `.env.example`, `pyproject.toml`

---

## Canonical interfaces (referenced by every task)

```python
# inference/types.py
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypedDict

class ProviderRole(str, Enum):
    ORCHESTRATOR = "orchestrator"
    WORKER = "worker"

class InferenceMessage(TypedDict):
    role: str      # "system" | "user" | "assistant"
    content: str

@dataclass(frozen=True)
class InferenceResult:
    content: str
    model: str
    input_tokens: int | None = None     # billable prompt tokens (cloud)
    output_tokens: int | None = None    # billable completion tokens (cloud)
    eval_count: int | None = None       # local decode tokens (for TPS)
    eval_duration_ns: int | None = None # local decode duration (for TPS)
```

```python
# inference/provider.py
from typing import Any, Protocol, runtime_checkable
from alphaswarm.inference.types import InferenceMessage, InferenceResult, ProviderRole

@runtime_checkable
class InferenceProvider(Protocol):
    role: ProviderRole
    model: str
    def is_local(self) -> bool: ...
    async def prepare(self) -> None: ...        # load local model / no-op cloud
    async def teardown(self) -> None: ...       # unload local model / no-op cloud
    async def chat(
        self,
        messages: list[InferenceMessage],
        *,
        response_schema: dict[str, Any] | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> InferenceResult: ...
    async def aclose(self) -> None: ...          # close transport
```

```python
# inference/concurrency.py
from typing import Protocol
class ConcurrencyController(Protocol):
    async def acquire(self) -> None: ...
    def release(self, *, success: bool = True, result_tokens: int | None = None) -> None: ...
    def report_wave_failures(self, success_count: int, failure_count: int) -> None: ...
    async def start_monitoring(self) -> None: ...
    async def stop_monitoring(self) -> None: ...
```

> Note: the existing `ResourceGovernor.release(success: bool)` gains an optional
> `result_tokens` kwarg (ignored locally) so both controllers share one signature.
> `agent_worker` passes `result_tokens=result.output_tokens` after a successful call.

---

## Wave 1 — Inference abstraction core (no behavior change)

### Task 1: Normalized inference types

**Files:**
- Create: `src/alphaswarm/inference/__init__.py`, `src/alphaswarm/inference/types.py`
- Test: `tests/inference/test_types.py`

**Interfaces:**
- Produces: `InferenceMessage`, `InferenceResult`, `ProviderRole` (signatures above).

- [ ] **Step 1: Failing test**
```python
from alphaswarm.inference.types import InferenceResult, ProviderRole

def test_inference_result_defaults():
    r = InferenceResult(content='{"signal":"buy"}', model="m")
    assert r.input_tokens is None and r.output_tokens is None
    assert r.content == '{"signal":"buy"}'

def test_provider_role_values():
    assert ProviderRole.WORKER.value == "worker"
```
- [ ] **Step 2:** `pytest tests/inference/test_types.py -v` → FAIL (module missing)
- [ ] **Step 3:** Implement `types.py` exactly per canonical interfaces; `__init__.py` re-exports them.
- [ ] **Step 4:** `pytest tests/inference/test_types.py -v` → PASS
- [ ] **Step 5:** Commit `feat(inference): normalized inference result + message types`

### Task 2: Provider protocol + error hierarchy + FakeInferenceProvider

**Files:**
- Create: `src/alphaswarm/inference/provider.py`
- Modify: `src/alphaswarm/errors.py` (add `InferenceError`, `AuthError`, `BudgetExceededError`)
- Create: `tests/inference/fakes.py` (test helper), `tests/inference/test_provider_contract.py`

**Interfaces:**
- Produces: `InferenceProvider` protocol; `InferenceError(message, *, provider, model, original_error=None)`, `AuthError(InferenceError)`, `BudgetExceededError(spent_usd, cap_usd)`.
- `FakeInferenceProvider(role, model, *, scripted: list[InferenceResult] | Callable)` returning canned results, recording calls.

- [ ] **Step 1: Failing test**
```python
from alphaswarm.inference.provider import InferenceProvider
from alphaswarm.inference.types import InferenceResult, ProviderRole
from tests.inference.fakes import FakeInferenceProvider

async def test_fake_provider_satisfies_protocol_and_records():
    fake = FakeInferenceProvider(ProviderRole.WORKER, "fake",
                                 scripted=[InferenceResult(content='{"signal":"hold"}', model="fake")])
    assert isinstance(fake, InferenceProvider)
    out = await fake.chat([{"role": "user", "content": "hi"}], response_schema={"type": "object"})
    assert out.content == '{"signal":"hold"}'
    assert fake.calls[0]["response_schema"] == {"type": "object"}
```
- [ ] **Step 2:** Run → FAIL
- [ ] **Step 3:** Implement `provider.py` protocol; add errors; implement `FakeInferenceProvider` (prepare/teardown/aclose no-ops, `is_local()=True`, records each `chat` kwargs into `self.calls`, pops scripted results, raises if exhausted).
- [ ] **Step 4:** Run → PASS
- [ ] **Step 5:** Commit `feat(inference): provider protocol, error hierarchy, test fake`

### Task 3: OllamaProvider (pass-through wrapper)

**Files:**
- Create: `src/alphaswarm/inference/ollama_provider.py`
- Test: `tests/inference/test_ollama_provider.py`

**Interfaces:**
- Consumes: `OllamaClient`, `OllamaModelManager`, `InferenceProvider`.
- Produces: `OllamaProvider(role, model_tag, client, model_manager, *, keep_alive="5m")`. `chat()` maps `response_schema → format=<schema>`, `json_mode → format="json"`, `think=False`, `temperature → options`. Returns `InferenceResult(content=resp.message.content or "", model=model_tag, eval_count=resp.eval_count, eval_duration_ns=resp.eval_duration)`. `prepare()` → `model_manager.load_model(model_tag)`; `teardown()` → `model_manager.unload(model_tag)`; `is_local()=True`; `aclose()` no-op.

- [ ] **Step 1: Failing test** (fake `OllamaClient` with a recording `chat`)
```python
class _FakeOllama:
    def __init__(self): self.kwargs = None
    async def chat(self, **kw):
        self.kwargs = kw
        class R:
            message = type("M", (), {"content": '{"signal":"buy"}'})()
            eval_count, eval_duration = 12, 1_000_000
        return R()

async def test_ollama_provider_maps_schema_to_format():
    fc = _FakeOllama()
    p = OllamaProvider(ProviderRole.WORKER, "alphaswarm-worker", fc, _NoopManager())
    out = await p.chat([{"role":"user","content":"x"}], response_schema={"a":1}, temperature=0.4)
    assert fc.kwargs["format"] == {"a":1}
    assert fc.kwargs["think"] is False
    assert fc.kwargs["options"]["temperature"] == 0.4
    assert out.eval_count == 12 and out.input_tokens is None
```
- [ ] **Step 2:** Run → FAIL
- [ ] **Step 3:** Implement `OllamaProvider` per interface.
- [ ] **Step 4:** Run → PASS
- [ ] **Step 5:** Commit `feat(inference): OllamaProvider pass-through adapter`

### Task 4: Migrate worker.py to the protocol

**Files:**
- Modify: `src/alphaswarm/worker.py` (`AgentWorker.__init__` takes `provider: InferenceProvider` instead of `ollama_client + model`; `infer()` calls `provider.chat(messages, response_schema=DECISION_JSON_SCHEMA, temperature=persona["temperature"])`; TPS uses `result.eval_count/eval_duration_ns`; pass `result.output_tokens` to `governor.release`)
- Modify: `agent_worker` context manager (accept `provider`, controller `release(success, result_tokens=...)`)
- Modify: `batch_dispatcher.py` (pass provider instead of client+model; thread `result_tokens` through)
- Test: update `tests/test_batch_dispatcher.py`, `tests/test_worker*.py` to inject `FakeInferenceProvider`

**Interfaces:**
- Consumes: `InferenceProvider`, `ConcurrencyController` (Task 12 — for now keep concrete `ResourceGovernor`, which gains the `result_tokens` kwarg in Task 12; here just pass it positionally-safe via keyword and have governor ignore unknown until Task 12 — SEQUENCING: do Task 12's `release` signature change first if executing strictly in order; see note).

> **Sequencing note:** apply the `release(*, success, result_tokens=None)` signature
> to `ResourceGovernor` as the first step of this task (it's a 1-line additive kwarg),
> so the worker can pass `result_tokens` immediately. Full `RateLimitController`
> arrives in Wave 4.

- [ ] **Step 1:** Add `result_tokens: int | None = None` kwarg to `ResourceGovernor.release` (ignored). Run governor tests → PASS unchanged.
- [ ] **Step 2: Failing test** — `AgentWorker(FakeInferenceProvider(...))` then `infer()` returns parsed decision; assert provider received `response_schema` and `temperature`.
- [ ] **Step 3:** Run → FAIL
- [ ] **Step 4:** Refactor `AgentWorker`/`agent_worker`/`dispatch_wave` to consume a provider. Keep the message-stack construction identical.
- [ ] **Step 5:** Run worker + dispatcher tests → PASS
- [ ] **Step 6:** Commit `refactor(worker): depend on InferenceProvider not OllamaClient`

### Task 5: Migrate orchestrator callers (seed, advisory, report, interview)

**Files:**
- Modify: `src/alphaswarm/seed.py`, `advisory/engine.py`, `report.py`, `interview.py` to accept an `InferenceProvider` (orchestrator-bound) and call `provider.chat(...)`; `seed`/`advisory` pass `response_schema`; `report`/`interview` use plain chat. Replace `model_manager.load/unload` calls with `provider.prepare()/teardown()`.
- Modify: `simulation.py` to construct/own providers and call prepare/teardown around seed and waves.
- Test: update `tests/test_seed*.py`, `tests/unit/test_advisory*.py`, `tests/test_web_report.py`, `tests/test_web_interview.py` (where they touch inference) to inject fakes.

- [ ] **Step 1: Failing tests** per caller using `FakeInferenceProvider` (assert schema passed for seed/advisory; assert plain chat for report/interview).
- [ ] **Step 2:** Run → FAIL
- [ ] **Step 3:** Implement migrations; keep prompts/parsing identical.
- [ ] **Step 4:** Run the affected suites → PASS
- [ ] **Step 5:** Commit `refactor(callers): route seed/advisory/report/interview through provider`

---

## Wave 2 — Cloud adapters

### Task 6: Schema translation helpers

**Files:** Create `src/alphaswarm/inference/schema.py`; Test `tests/inference/test_schema.py`

**Interfaces:**
- Produces: `to_openai_response_format(schema) -> dict` (`{"type":"json_schema","json_schema":{"name":"decision","schema":<strict-normalized>,"strict":True}}`, normalizing `additionalProperties:false` + `required` = all keys); `to_openai_json_object() -> dict`; `to_anthropic_tool(schema, name="emit_decision") -> dict`; `extract_anthropic_tool_json(content_blocks, name) -> str`.

- [ ] **Step 1:** Failing tests asserting exact dict shapes for a sample decision schema, and that `extract_anthropic_tool_json` returns the `json.dumps` of the tool_use input block.
- [ ] **Step 2:** Run → FAIL
- [ ] **Step 3:** Implement helpers (pure functions, no I/O).
- [ ] **Step 4:** Run → PASS
- [ ] **Step 5:** Commit `feat(inference): schema translation helpers for cloud providers`

### Task 7: OpenAICompatProvider

**Files:** Create `src/alphaswarm/inference/openai_provider.py`; Test `tests/inference/test_openai_provider.py`

**Interfaces:**
- Produces: `OpenAICompatProvider(role, model, *, base_url, api_key, rpm=None, request_timeout_s=120.0, extra_headers=None)`. `chat()` builds `{model, messages, temperature?, max_tokens?, response_format?}`, POSTs `{base_url}/chat/completions` via shared `httpx.AsyncClient`. `response_schema` → `to_openai_response_format`; on 400 mentioning json_schema/response_format unsupported → retry once with `json_object` and cache downgrade on `self._no_strict=True`. Parses `choices[0].message.content`; `input_tokens=usage.prompt_tokens`, `output_tokens=usage.completion_tokens`. 401/403 → `AuthError`. 429 → honor `Retry-After`, raise retryable `InferenceError` after bounded retries. `is_local()=False`; `prepare/teardown` no-op; `aclose()` closes client.

- [ ] **Step 1: Failing tests** with monkeypatched httpx transport (use `httpx.MockTransport`):
  - schema → request body has `response_format.type == "json_schema"`.
  - happy path returns content + token usage.
  - 401 → `AuthError`.
  - strict-unsupported 400 → second call uses `json_object` and succeeds.
  - 429 with `Retry-After: 0` → retries then raises `InferenceError` if persistent.
- [ ] **Step 2:** Run → FAIL
- [ ] **Step 3:** Implement provider with `httpx.AsyncClient(transport=...)` injectable for tests (constructor accepts optional `client` / `transport`).
- [ ] **Step 4:** Run → PASS
- [ ] **Step 5:** Commit `feat(inference): OpenAI-compatible provider adapter`

### Task 8: AnthropicProvider + dependency

**Files:** Create `src/alphaswarm/inference/anthropic_provider.py`; Modify `pyproject.toml` (add `anthropic>=0.40`); Test `tests/inference/test_anthropic_provider.py`

**Interfaces:**
- Produces: `AnthropicProvider(role, model, *, api_key, rpm=None, max_tokens_default=1024, client=None)`. Splits `system` messages into top-level `system` string; maps `response_schema` → forced tool via `to_anthropic_tool` + `tool_choice={"type":"tool","name":"emit_decision"}`; extracts JSON via `extract_anthropic_tool_json`. Plain chat (no schema) → returns concatenated text blocks. `input_tokens=usage.input_tokens`, `output_tokens=usage.output_tokens`. Maps `anthropic.AuthenticationError → AuthError`, `RateLimitError → retryable InferenceError` (honor `retry-after`). `is_local()=False`; `client` injectable (a fake AsyncAnthropic) for tests.

- [ ] **Step 1: Failing tests** with a fake `AsyncAnthropic` client:
  - schema path sends a `tools=[...]` + `tool_choice` and returns the tool input JSON.
  - system message hoisted to `system=` param, not in `messages`.
  - plain chat returns text.
  - auth error → `AuthError`.
- [ ] **Step 2:** Run → FAIL
- [ ] **Step 3:** Implement provider; add dep; `uv sync`.
- [ ] **Step 4:** Run → PASS
- [ ] **Step 5:** Commit `feat(inference): native Anthropic provider adapter + dependency`

---

## Wave 3 — Config, factory, persistence

### Task 9: Inference config models + file loader

**Files:** Modify `config.py`; Create `tests/test_inference_config.py`; Modify `.gitignore` (add `.secrets/`)

**Interfaces:**
- Produces: `ProviderType(str, Enum) = {OLLAMA, OPENAI_COMPATIBLE, ANTHROPIC}`; `RoleConfig(BaseModel)` = `{provider, model, base_url: str|None, api_key: str|None}`; `ProviderLimits(BaseModel)` = `{requests_per_min:int|None, tokens_per_min:int|None}`; `InferenceConfig(BaseModel)` = `{orchestrator: RoleConfig, worker: RoleConfig, limits: dict[ProviderType, ProviderLimits], spend_cap_usd: Decimal|None, pricing_overrides: dict[str, ModelPrice]}`. Functions: `default_inference_config(app_settings) -> InferenceConfig` (both roles Ollama w/ current MLX models); `load_inference_config(path=".secrets/inference.toml", app_settings) -> InferenceConfig` (file → defaults fallback); `save_inference_config(cfg, path)`; `masked_config(cfg) -> dict` (keys replaced with `{"set": bool, "last4": str|None}`).

- [ ] **Step 1: Failing tests:** default is all-Ollama; round-trip save/load (tmp path) preserves fields; `masked_config` never contains raw key but reports `set`/`last4`; loading missing file → defaults.
- [ ] **Step 2:** Run → FAIL
- [ ] **Step 3:** Implement models + loader (use stdlib `tomllib` to read, `tomli-w` or hand-serialize to write — prefer hand-serialize to avoid a dep; Decimal stored as string).
- [ ] **Step 4:** Run → PASS; add `.secrets/` to `.gitignore`.
- [ ] **Step 5:** Commit `feat(config): inference config models + gitignored file persistence`

### Task 10: Provider + controller factory

**Files:** Create `src/alphaswarm/inference/factory.py`; Test `tests/inference/test_factory.py`

**Interfaces:**
- Consumes: `InferenceConfig`, all providers, `OllamaClient`/`OllamaModelManager`, controllers.
- Produces: `build_providers(cfg, *, ollama_client, ollama_model_manager) -> tuple[InferenceProvider, InferenceProvider]` (orchestrator, worker); shares one `OllamaModelManager` across local roles. `inference_mode(cfg) -> Literal["local","cloud","mixed"]`. `build_controller(cfg, governor_settings, *, state_store) -> ConcurrencyController` (returns `ResourceGovernor` when worker role is local; `RateLimitController` when worker role is cloud — worker role drives the swarm's concurrency).

- [ ] **Step 1: Failing tests:** all-Ollama cfg → two `OllamaProvider`, controller is `ResourceGovernor`; worker=anthropic cfg → worker provider is `AnthropicProvider`, controller is `RateLimitController`; mixed cfg respected.
- [ ] **Step 2:** Run → FAIL
- [ ] **Step 3:** Implement factory.
- [ ] **Step 4:** Run → PASS
- [ ] **Step 5:** Commit `feat(inference): provider + controller factory`

---

## Wave 4 — Concurrency controller, budget, dispatcher integration

### Task 11: ConcurrencyController protocol + governor conformance

**Files:** Create `src/alphaswarm/inference/concurrency.py`; Modify `governor.py` (add `result_tokens` kwarg already done in Task 4; add `stop_monitoring` alias if missing; assert `isinstance(governor, ConcurrencyController)`); Test `tests/inference/test_concurrency_protocol.py`

- [ ] **Step 1: Failing test:** `assert isinstance(ResourceGovernor(...), ConcurrencyController)` (runtime_checkable).
- [ ] **Step 2:** Run → FAIL
- [ ] **Step 3:** Define protocol; reconcile governor method names.
- [ ] **Step 4:** Run → PASS
- [ ] **Step 5:** Commit `feat(inference): ConcurrencyController protocol; governor conforms`

### Task 12: BudgetMeter + pricing

**Files:** Create `src/alphaswarm/inference/budget.py`; Test `tests/inference/test_budget.py`

**Interfaces:**
- Produces: `ModelPrice(input_per_mtok: Decimal, output_per_mtok: Decimal)`; `DEFAULT_PRICING: dict[str, ModelPrice]` (a small curated table; unknown model → `Decimal(0)` with a logged warning, treated as free for estimation but still capped if cap set); `BudgetMeter(cap_usd: Decimal|None, pricing: dict[str, ModelPrice])` with `record(model, input_tokens, output_tokens) -> Decimal` (returns running total), `spent() -> Decimal`, `would_exceed(model, est_in, est_out) -> bool`, `check()` raising `BudgetExceededError` when `spent() >= cap`. `estimate_run(cfg, *, agents:int, rounds:int, avg_in:int, avg_out:int) -> RunEstimate{calls:int, low_usd, high_usd}`.

- [ ] **Step 1: Failing tests:** cost math (1M tok → exact Decimal), `would_exceed`, `check()` raises at/over cap, `estimate_run` call count = `agents*rounds + 3` and cost = calls*price band.
- [ ] **Step 2:** Run → FAIL
- [ ] **Step 3:** Implement (all Decimal).
- [ ] **Step 4:** Run → PASS
- [ ] **Step 5:** Commit `feat(inference): budget meter, pricing table, run estimator`

### Task 13: RateLimitController

**Files:** Create `src/alphaswarm/inference/rate_limit.py`; Test `tests/inference/test_rate_limit.py`

**Interfaces:**
- Consumes: `ConcurrencyController`, `BudgetMeter`, `StateStore`.
- Produces: `RateLimitController(*, max_in_flight:int, requests_per_min:int|None, tokens_per_min:int|None, budget: BudgetMeter, state_store=None, avg_tokens_per_call:int=1500)`. `acquire()` awaits a max-in-flight slot AND request-bucket token AND estimated-token budget; calls `budget.check()` and raises `BudgetExceededError` if already over. `release(*, success, result_tokens=None)` refunds/charges the TPM bucket with actual tokens, decrements in-flight. `report_wave_failures` shrinks `max_in_flight` on high failure (mirror governor's 20% rule) — auth-failure spike triggers immediate `AuthError` re-raise via a flag set by adapters. `start/stop_monitoring` runs a metrics emitter (in-flight, rpm/tpm utilization, spent_usd) to state_store. Token buckets refill continuously based on a monotonic clock passed in (inject a `now()` callable for deterministic tests — note: scripts forbid `Date.now`, but this is server Python, real `time.monotonic` is fine; tests inject a fake clock).

- [ ] **Step 1: Failing tests** with injected fake clock + fake state_store:
  - blocks past `max_in_flight`; releases unblock.
  - RPM bucket paces (N+1th acquire waits until refill).
  - `acquire` raises `BudgetExceededError` once `budget.spent() >= cap`.
  - `report_wave_failures(80,20)` shrinks `max_in_flight`.
- [ ] **Step 2:** Run → FAIL
- [ ] **Step 3:** Implement controller + buckets.
- [ ] **Step 4:** Run → PASS
- [ ] **Step 5:** Commit `feat(inference): adaptive rate-limit controller with spend cap`

### Task 14: Dispatcher never-catch + provider/controller wiring

**Files:** Modify `batch_dispatcher.py` (add `BudgetExceededError` to never-catch tuple alongside `GovernorCrisisError`; pass `result_tokens` to `release`); Test `tests/test_batch_dispatcher.py` (a `FakeInferenceProvider` that raises `BudgetExceededError` propagates out of `dispatch_wave`, not swallowed to PARSE_ERROR).

- [ ] **Step 1: Failing test** as above.
- [ ] **Step 2:** Run → FAIL
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS
- [ ] **Step 5:** Commit `feat(dispatch): propagate BudgetExceededError; thread token usage`

---

## Wave 5 — Web integration

### Task 15: Build providers/controller per run; mode-aware metrics

**Files:** Modify `web/app.py` (lifespan builds `OllamaClient`/`OllamaModelManager` once; loads `InferenceConfig`; stores on app.state), `web/simulation_manager.py` + `simulation.py` (at run start call `build_providers`/`build_controller`, pass into `run_simulation`; reject `PUT /api/settings` while running), `web/broadcaster.py` + `state.py` (`GovernorMetrics` gains `mode: str` + optional `spent_usd`, `rpm_util`, `tpm_util`; broadcaster only overlays RAM% when `mode=="local"`). Tests: `tests/test_web.py` (settings rejected mid-run), broadcaster mode test.

- [ ] **Step 1: Failing tests:** snapshot in cloud mode has `mode="cloud"` and does not force RAM overlay; `PUT /api/settings` returns 409 while sim running.
- [ ] **Step 2:** Run → FAIL
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS
- [ ] **Step 5:** Commit `feat(web): per-run provider build + mode-aware telemetry`

### Task 16: Settings routes

**Files:** Create `web/routes/settings.py`; Modify `web/app.py` (register router); Test `tests/test_web_settings.py`

**Interfaces:**
- `GET /api/settings` → 200 `masked_config(cfg)` + `available_local_models` (from `ollama list`, tolerate failure → []) + `known_api_models` (static curated list).
- `PUT /api/settings` → 200 on validate+save; 409 if sim running; 400 on invalid; empty key field leaves stored key unchanged.
- `POST /api/settings/test` → builds a transient provider for the posted role and does a 1-token `chat`; returns `{ok, error?}`; never persists.
- `GET /api/settings/estimate` → `RunEstimate` for current cfg (local → `{calls, low_usd:0, high_usd:0}`).

- [ ] **Step 1: Failing tests** (FastAPI `TestClient`, monkeypatch provider build to fakes): GET masks keys; PUT persists to tmp path; PUT mid-run → 409; estimate returns calls count.
- [ ] **Step 2:** Run → FAIL
- [ ] **Step 3:** Implement routes.
- [ ] **Step 4:** Run → PASS
- [ ] **Step 5:** Commit `feat(web): settings endpoints for inference config`

### Task 17: Secret redaction + key-leak invariant

**Files:** Modify structlog redaction processor (add `api_key`, `authorization`, `orchestrator_key`, `worker_key` to allowlist); Test `tests/invariants/test_secret_isolation.py` (canary key string never appears in captured logs, WS frame, or Neo4j props after a settings save + minimal flow).

- [ ] **Step 1: Failing test** with a sentinel key `SNTL_API_KEY_DONOTLOG`.
- [ ] **Step 2:** Run → FAIL
- [ ] **Step 3:** Extend redaction allowlist.
- [ ] **Step 4:** Run → PASS
- [ ] **Step 5:** Commit `feat(security): redact API keys from logs; key-leak invariant test`

---

## Wave 6 — Frontend

### Task 18: Settings API client + types

**Files:** Create `frontend/src/api/settings.ts`; Test `frontend/src/__tests__/settings.test.ts`

**Interfaces:**
- `getSettings(): Promise<SettingsView>`, `putSettings(body): Promise<void>`, `testConnection(role): Promise<{ok:boolean,error?:string}>`, `getEstimate(): Promise<RunEstimate>`. Types mirror backend masked config.

- [ ] **Step 1: Failing test** (mock fetch): `getSettings` parses masked config; `putSettings` omits empty key.
- [ ] **Step 2–4:** Implement; vitest PASS.
- [ ] **Step 5:** Commit `feat(ui): settings API client`

### Task 19: Inference settings section + mode chip

**Files:** Create `frontend/src/components/settings_inference.tsx`; Modify `frontend/src/components/settings.tsx` (embed section, remove hardcoded `qwen3:8b`), header mode chip in `app_v2.tsx`/`ModelStatus`. Modify `adapter/frame.ts` + KPI strip to branch on `mode`.

- [ ] **Step 1:** Failing component tests (vitest + RTL): renders per-role provider select; password key field shows "set ••••1234" when `key_set`; switching provider to cloud reveals base URL/key fields.
- [ ] **Step 2–4:** Implement; vitest PASS; `tsc -b --noEmit` clean.
- [ ] **Step 5:** Commit `feat(ui): inference settings section + live mode chip`

### Task 20: Pre-run cost confirm

**Files:** Create `frontend/src/components/run_confirm.tsx`; Modify the Run handler (onboarding + control bar) to, when mode != local, fetch estimate and show confirm before `simStart`.

- [ ] **Step 1:** Failing test: cloud mode → confirm modal shown with calls/cost; confirm → `simStart` called; local mode → `simStart` called directly.
- [ ] **Step 2–4:** Implement; vitest PASS.
- [ ] **Step 5:** Commit `feat(ui): pre-run cost estimate confirmation for cloud runs`

---

## Wave 7 — Integration, verification, docs

### Task 21: Live provider smoke (opt-in)

**Files:** Create `tests/integration/test_cloud_inference.py` (`@pytest.mark.enable_socket`, skipped unless `ALPHASWARM_TEST_OPENAI_KEY`/`ALPHASWARM_TEST_ANTHROPIC_KEY` present) — one real decision call per configured provider, asserts schema-valid JSON + token usage populated.

- [ ] **Step 1–4:** Implement guarded smoke; runs only when keys present (skip otherwise).
- [ ] **Step 5:** Commit `test(integration): opt-in live cloud provider smoke`

### Task 22: Full verification gate + docs

**Files:** Modify `.env.example`, `README.md` (provider note), `AlphaSwarm` settings docs.

- [ ] **Step 1:** Run full gate and fix everything:
  - `uv run pytest -q --ignore=tests/test_graph_integration.py --ignore=tests/test_integration_inference.py`
  - `uv run mypy src`
  - `uv run ruff check .`
  - `uv run lint-imports`
  - `cd frontend && npx tsc -b --noEmit && npx vitest run && npm run build`
- [ ] **Step 2:** Update `.env.example` + README with the cloud-provider section.
- [ ] **Step 3:** Commit `docs: document API inference provider configuration`
- [ ] **Step 4:** Final commit / open PR readiness.

---

## Self-Review

**Spec coverage:** providers (T3,7,8) ✓; structured output (T6) ✓; concurrency token-bucket (T13) ✓; spend cap + abort (T12,13,14) ✓; estimate+confirm (T12,16,20) ✓; key file storage (T9) ✓; masked GET / no browser secret (T9,16) ✓; redaction + leak invariant (T17) ✓; mode-aware metrics (T15,19) ✓; per-role independent/mixed (T9,10) ✓; local default unchanged (T3,4,5,10) ✓; tests behind socket gate / enable_socket (all + T21) ✓; deps (T8) ✓; docs (T22) ✓.

**Placeholder scan:** interfaces carry concrete signatures; representative test code per task; no TBD. Adapter internals (full bodies) are specified by interface + test assertions rather than line-by-line source — executors write the minimal code to satisfy the stated tests, per TDD.

**Type consistency:** `InferenceResult`/`InferenceMessage`/`ProviderRole` used uniformly; `release(*, success, result_tokens=None)` consistent across governor + rate controller + `agent_worker`; `response_schema`/`json_mode` consistent across protocol, adapters, callers; `BudgetExceededError` defined once (T2) and used in T12/13/14.
