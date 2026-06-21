# API Inference Provider Support — Design

**Date:** 2026-06-21
**Status:** Approved (brainstorming) — ready for implementation planning
**Author:** brainstorming session

## 1. Summary

AlphaSwarm currently runs all LLM inference locally through Ollama. This adds an
optional **cloud inference path** so a run can be pointed at API models
(OpenAI-compatible endpoints and native Anthropic), which removes the local
memory bottleneck and lets the 100-agent swarm run with high parallelism — many
times faster than the M1's local throughput.

The change is **additive and local-first**: Ollama remains the default, every
existing local behavior is preserved byte-for-byte, and the cloud path is opt-in
through a settings menu where the user enters an API key and independently
selects the provider + model for the orchestrator and for the swarm.

## 2. Goals

- Run the full pipeline (seed → 3-round cascade → advisory → report → interview)
  against API models, not just local Ollama.
- High parallelism on the API path, paced to the provider's rate limits.
- A settings menu to enter an API key and pick provider + model for the
  **orchestrator** and the **swarm** independently (they may differ, and either
  may be local while the other is cloud).
- Local Ollama is the default with zero configuration.
- Cost protection: a pre-run estimate with confirmation, plus a hard spend cap
  that aborts a run gracefully.

## 3. Non-goals

- No change to the simulation logic, bracket taxonomy, peer-selection algorithm,
  Neo4j schema, or the WebSocket/replay contracts.
- No streaming token UI for cloud responses (single-shot responses, like today).
- No multi-key rotation, no per-agent provider mixing (provider is chosen per
  *role*: orchestrator and worker, not per individual agent).
- No removal or rewrite of the local memory governor — it stays as the local
  path's concurrency controller.

## 4. Locked decisions

| # | Decision |
|---|----------|
| D1 | Providers: **OpenAI-compatible** (one HTTP client → OpenAI, OpenRouter, Together, Groq, Fireworks, remote vLLM) **+ native Anthropic**. |
| D2 | API concurrency: **adaptive token-bucket** paced to per-provider RPM/TPM limits, with Retry-After backoff and a max-in-flight cap. |
| D3 | Key storage: **backend-owned, gitignored config file**; the browser never receives the raw key. |
| D4 | Cost: **pre-run estimate + confirm**, plus a **hard spend cap** that aborts mid-run gracefully via live cost accounting. |
| D5 | **Local Ollama is the default.** Orchestrator and worker providers are configured independently and may be mixed. |
| D6 | Abstraction shape: **provider protocol + adapters** (Approach A), mirroring the existing phase-37 `MarketDataProvider`/`Fake` pattern. The current tuned local path is left intact. |

## 5. Architecture

### 5.1 New package: `src/alphaswarm/inference/`

The single seam all inference callers depend on.

- **`types.py`** — `InferenceResult` (normalized):
  `content: str`, `input_tokens: int | None`, `output_tokens: int | None`,
  `model: str`, and optional `eval_count` / `eval_duration` (local TPS).
  Also `InferenceMessage` (role, content). This one type keeps both the cost
  meter and the existing dashboard TPS working regardless of provider.

- **`provider.py`** — `InferenceProvider` protocol, one method:

  ```python
  async def chat(
      messages: list[InferenceMessage],
      *,
      response_schema: dict | None = None,  # strict structured JSON
      json_mode: bool = False,              # "valid JSON" without strict schema
      temperature: float | None = None,
      max_tokens: int | None = None,
  ) -> InferenceResult: ...
  ```

  Each provider **instance is pre-bound to a role's config** (provider type,
  model, endpoint, key). The engine therefore holds an `orchestrator_provider`
  and a `worker_provider` — two independently configured instances. This is the
  mechanism behind D5 (independent + mixable roles).

- **`ollama_provider.py`** — wraps today's `OllamaClient` and
  `OllamaModelManager` unchanged. Maps `response_schema → format=<schema>`,
  `json_mode → format="json"`, sets `think=False`, `keep_alive`, per-bracket
  `temperature`; surfaces `eval_count`/`eval_duration`; token cost = 0.

- **`openai_provider.py`** — `httpx` (already a dependency) to
  `POST {base_url}/chat/completions`. Maps `response_schema →
  response_format: {type: "json_schema", strict: true}`; on a model/endpoint
  that rejects strict json_schema, downgrades to `{type: "json_object"}` and
  remembers that per-model. Reads `usage.prompt_tokens` / `completion_tokens`.

- **`anthropic_provider.py`** — the `anthropic` SDK. Splits system messages out
  into the top-level `system` param. Maps `response_schema →` a forced
  single-tool call: one `emit_decision` tool whose `input_schema` is the decision
  schema, with `tool_choice` pinned to it; reads the `tool_use.input` as
  schema-valid JSON. Reads `usage.input_tokens` / `output_tokens`.

- **`factory.py`** — `build_providers(inference_config)` returns the two
  role-bound providers from the active config.

### 5.2 Caller migration

The five callers stop importing `OllamaClient` and depend on
`InferenceProvider`:

- `worker.py` (`AgentWorker.infer`) — passes the decision `response_schema`.
- `seed.py` — entity extraction `response_schema`.
- `advisory/engine.py` — advisory `response_schema` / json_mode.
- `report.py` — plain `chat` (no schema; ReACT loop).
- `interview.py` — plain `chat`.

`OllamaProvider` is a thin pass-through, so the local path is unchanged.

### 5.3 Structured output strategy

The decision schema (`{signal, confidence, sentiment, rationale, cited_agents}`)
stays defined once as a provider-agnostic JSON Schema and is translated by each
adapter (5.1). Every adapter returns a `content` string that is JSON, and the
existing 3-tier fallback in `parsing.py` remains the universal safety net — a
malformed cloud response degrades to `PARSE_ERROR` exactly like a bad local one.
No caller parsing logic changes.

### 5.4 Concurrency: `ConcurrencyController` protocol

`agent_worker` only calls `acquire()` / `release(success=...)`, and the
dispatcher calls `report_wave_failures()`. These lift into a
`ConcurrencyController` protocol:

- **`MemoryGovernor`** = today's `ResourceGovernor`, unchanged. Local path.
- **`RateLimitController`** (new) — API path:
  - Token bucket for RPM and one for TPM, seeded from per-provider configured
    limits. `acquire()` waits for a request slot **and** an estimated-token slot;
    `release()` reconciles actual token usage from the `InferenceResult`.
  - Configurable max-in-flight cap bounds raw parallelism.
  - On HTTP 429 the adapter honors `Retry-After` with exponential backoff;
    bucket pacing keeps 429s rare.
  - Emits metrics to the StateStore (in-flight, RPM/TPM utilization, running
    spend) so the dashboard shows cloud state instead of RAM%. Note: the
    WebSocket broadcaster currently force-overlays live psutil RAM% onto every
    snapshot (MEM-01/02/03). That overlay and the `GovernorMetrics` shape must
    become **mode-aware** — on a cloud run RAM% is meaningless and is replaced
    by the cloud metrics above; the frontend telemetry adapter and KPI strip
    branch on mode accordingly.

### 5.5 Cost accounting + spend cap

- **`BudgetMeter`** sums cost from each result's token usage against a small
  per-model pricing table (in config, user-overridable).
- When actual or next-call-projected spend crosses the cap, the controller
  raises **`BudgetExceededError`**. Like `GovernorCrisisError`, it is on the
  never-swallow list, so the `TaskGroup` unwinds and the run halts cleanly —
  rounds already written to Neo4j are preserved.
- **Pre-run estimate**: projected calls (`agents × rounds + orchestrator +
  advisory + report`) × average tokens × price → a ballpark cost range.
- Local path: `BudgetMeter` is a no-op (cost 0, no cap), RAM governor as today.

## 6. Configuration & settings

### 6.1 Config model

Static infra stays in env-based `AppSettings` (Neo4j, governor thresholds,
holdings). A new runtime-mutable `InferenceConfig` is persisted separately:

- `ProviderType` enum: `ollama` | `openai_compatible` | `anthropic`.
- Per-role `RoleConfig`: `{ provider, model, base_url?, api_key? }` for
  `orchestrator` and `worker`.
- `rate_limits` (RPM/TPM per provider), `spend_cap_usd`, optional
  `pricing_overrides`.
- **Default**: both roles `ollama` with the current MLX models. The file does
  not exist until the user changes something.

### 6.2 Persistence & secrecy

- File at `.secrets/inference.toml`; `.secrets/` added to `.gitignore`.
- Providers are rebuilt from this file at the **start of each run**, so
  switching local↔cloud needs no restart.
- API keys are added to the phase-37 structlog PII-redaction allowlist
  (`api_key`, `authorization`), so they cannot leak to logs. The existing
  `data_audit` already blocks `sk-` strings from the wire.

### 6.3 Backend settings API (`web/routes/settings.py`)

- `GET /api/settings` → current config with **keys masked**
  (`orchestrator_key_set: bool` + last-4 only). Includes available local Ollama
  models and a curated list of common API models for the dropdowns.
- `PUT /api/settings` → validate and persist the file. Empty key field means
  "leave unchanged". Rejected with 409 while a simulation is running.
- `POST /api/settings/test` → fires a 1-token ping to verify a key/model;
  returns ok/error. (Stretch, but recommended for UX.)
- `GET /api/settings/estimate` → projected call count and cost range for the
  current config (0 / no confirm for local).

### 6.4 Frontend (`settings.tsx` + run flow)

- The model section becomes real and writable: per-role provider dropdown,
  model field, base URL (OpenAI-compatible only), password-style key input,
  RPM/TPM, spend cap, and a "Test connection" button. This replaces the stale
  hardcoded `qwen3:8b` label and the read-only model display.
- A header chip shows current mode (Local / Cloud:provider) so the user always
  knows whether a run costs money. (Fixes the existing hardcoded-model chip.)
- When the active config is cloud, clicking Run first fetches
  `GET /api/settings/estimate` and shows a confirm dialog
  (e.g. "~312 calls, est. $0.80–$1.40 — Run?") before
  `POST /api/simulate/start`.
- Secrets never go to localStorage (existing policy); model/provider selection
  lives in the backend config file, not localStorage.

## 7. Error handling

- Provider-agnostic `InferenceError` base in `errors.py`; `OllamaInferenceError`
  becomes a subclass. The dispatcher's existing catch-all still turns any
  per-agent failure into `PARSE_ERROR`, so transient cloud blips degrade
  gracefully.
- 429 / 5xx / connection → retry with backoff (Retry-After honored).
- **Auth failure (401/403) fails fast.** The orchestrator seed call happens
  first, so a bad key aborts the run immediately with a clear message instead of
  burning 100 agents. If auth failures spike during the swarm wave, the
  controller triggers an early halt rather than draining the budget on errors.
- `BudgetExceededError` halts cleanly (never-swallow list, preserves written
  rounds).
- Per-call timeout, configurable per provider (cloud default shorter than the
  local 600s cap).

## 8. Testing

- `FakeInferenceProvider` (mirrors phase-37 fakes) → unit-test all five callers
  with zero network.
- Adapter unit tests with mocked `httpx` / `anthropic`: schema→provider mapping,
  token-usage extraction, 429/Retry-After, and the json_schema-unsupported
  downgrade.
- `RateLimitController` + `BudgetMeter` tests: bucket pacing, cost math, and
  spend-cap → `BudgetExceededError`.
- Invariant test extended (canary style, like holdings isolation): API keys
  never appear in logs, WebSocket frames, or Neo4j.
- Settings route tests: `PUT` persists; `GET` masks keys; `.secrets/`
  gitignored.
- All unit tests stay under the `pytest-socket` block; real provider calls live
  behind the `enable_socket` integration marker (like the existing yfinance/RSS
  integration tests).

## 9. Dependencies

- Add the `anthropic` SDK (clean tool-use handling).
- OpenAI-compatible uses plain `httpx` (already a dependency) to keep `base_url`
  flexible — no `openai` SDK dependency.
- Optional: an import-linter contract so only `inference.*` imports the provider
  SDKs, keeping provider deps isolated.

## 10. Rollout

Everything is additive. The local default is untouched and `OllamaProvider` is a
pass-through, so the existing test suite keeps passing. Cloud is opt-in via
settings. `.env.example` / README gain a short provider note.

## 11. File-touch map (approximate)

**New**
- `src/alphaswarm/inference/{__init__,types,provider,ollama_provider,openai_provider,anthropic_provider,factory}.py`
- `src/alphaswarm/inference/rate_limit.py` (`RateLimitController`, token buckets)
- `src/alphaswarm/inference/budget.py` (`BudgetMeter`, pricing table)
- `src/alphaswarm/web/routes/settings.py`
- Frontend: settings inference section, run-confirm modal, mode chip, `api/settings.ts`
- Tests for each of the above

**Modified**
- `worker.py`, `seed.py`, `advisory/engine.py`, `report.py`, `interview.py`
  (depend on `InferenceProvider`)
- `config.py` (`InferenceConfig`, `ProviderType`, `RoleConfig`, loader)
- `governor.py` (implement `ConcurrencyController`; likely rename to `MemoryGovernor` alias)
- `batch_dispatcher.py` (controller protocol; `BudgetExceededError` in never-catch tuple)
- `errors.py` (`InferenceError` base, `BudgetExceededError`)
- `web/app.py` (build providers + controller from active config at run start)
- `web/simulation_manager.py` (reject settings changes mid-run; surface estimate)
- `web/broadcaster.py` (mode-aware metrics overlay — RAM% only for local) and
  `state.py` `GovernorMetrics` (carry a mode discriminator + cloud fields)
- Frontend `adapter/frame.ts` + KPI strip (branch telemetry on local/cloud mode)
- structlog redaction processor (key allowlist), `.gitignore`, `.env.example`, `pyproject.toml`

## 12. Open questions

None blocking. Pricing-table accuracy is best-effort (user-overridable); the
"Test connection" endpoint is recommended but can be deferred without blocking
the core path.
