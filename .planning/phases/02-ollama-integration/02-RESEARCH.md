# Phase 2: Ollama Integration - Research

**Researched:** 2026-03-24
**Domain:** Local LLM inference via Ollama AsyncClient, structured output parsing, sequential model management
**Confidence:** HIGH

## Summary

Phase 2 builds the async LLM client layer for AlphaSwarm: an Ollama AsyncClient wrapper with sequential model loading, a typed AgentWorker factory as an async context manager, structured output parsing with multi-tier fallback, and full resilience (backoff + semaphore guarding). The output is a verified single-agent inference path: load model, acquire semaphore, call Ollama, parse Pydantic model, release, unload.

The ollama Python library (v0.6.1) provides `AsyncClient` with `chat()`, `generate()`, and model management methods (`create()`, `delete()`, `ps()`). Model unloading is done via `keep_alive=0` on a chat/generate call with empty content -- NOT via `delete()` (which permanently removes the model). The `format` parameter accepts `"json"` for JSON mode or a JSON schema dict for schema-constrained output. The `think` parameter enables reasoning mode on Qwen3 models.

**Primary recommendation:** Build an `OllamaClient` wrapper class around `ollama.AsyncClient` that enforces the project's contracts (no per-request num_ctx, mandatory semaphore acquisition, backoff on transient errors). Use the `backoff` library (v2.2.1) to decorate all Ollama calls with exponential retry on `httpx.ConnectError`, `ollama.ResponseError`, and `ConnectionError`. Create Modelfiles via CLI during setup (not at runtime); the Python client uses model tags that reference pre-created Modelfile-based models.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **Model Tags:** Orchestrator is `qwen3.5:32b`, Worker is `qwen3.5:7b`. These override Phase 1 defaults. User has confirmed these as the correct tags despite research showing these exact tags do not exist in the current Ollama library (see Open Questions).
- **Sequential Model Loading (INFRA-03):** Orchestrator loads for seed injection, unloads completely before worker loads. No dual-model coexistence. Enforce via explicit unload calls between phases.
- **Ollama AsyncClient Wrapper (INFRA-04):** All calls through single `OllamaClient` wrapper. `num_ctx` ONLY via Modelfiles, never per-request. Modelfiles in `modelfiles/` at project root.
- **AgentWorker as asynccontextmanager:** Implemented via `contextlib.asynccontextmanager`, not class with `__aenter__`/`__aexit__`. Every LLM call through worker MUST use `agent_worker(persona)`.
- **WorkerPersonaConfig as TypedDict:** Runtime persona config is TypedDict, not Pydantic model. Derived from frozen AgentPersona at dispatch time.
- **Governor Semaphore:** Every LLM call acquires `governor.acquire()` before dispatching. Phase 2 uses Phase 1 stub (no-op). Initial slots: 8.
- **Backoff + Resilience (INFRA-08):** `backoff` library for all httpx Ollama calls: `@backoff.on_exception(backoff.expo, ..., max_tries=3)`. Raises domain-specific `OllamaInferenceError`.
- **Structured Output Parsing (INFRA-08):** 3-tier fallback: JSON mode -> regex extraction -> PARSE_ERROR status. Implement as `parse_agent_decision(raw: str) -> AgentDecision`.
- **num_ctx via Modelfiles ONLY:** Per-request num_ctx causes silent model reloads. Modelfiles: `Modelfile.orchestrator` and `Modelfile.worker`.
- **Scope:** No dynamic slot scaling (Phase 3), no hybrid memory sensing (Phase 3), no random jitter (Phase 3), no Neo4j writes (Phase 4), no TUI updates (Phase 9).

### Claude's Discretion

- Internal method names on OllamaClient beyond required `generate` / `chat` interface
- Error hierarchy depth (OllamaInferenceError subclasses)
- Test fixture design for mocking Ollama responses
- Whether to use separate `ModelfileManager` class or inline Modelfile path resolution

### Deferred Ideas (OUT OF SCOPE)

- Miro batcher (Phase 8)
- Neo4j graph writes (Phase 4)
- TUI live rendering (Phase 9)
- Dynamic slot scaling beyond initial semaphore (Phase 3)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INFRA-03 | Sequential model loading -- orchestrator loads, unloads, then worker loads | Ollama `keep_alive=0` unloads model from memory. `ps()` verifies model state. `create()` builds Modelfile-based models. |
| INFRA-04 | Ollama AsyncClient wrapper with standardized num_ctx via Modelfiles | `ollama.AsyncClient` provides `chat()` and `generate()` with `format`, `options`, `keep_alive` params. Modelfiles set PARAMETER num_ctx. |
| INFRA-08 | Structured output parsing via Pydantic models with multi-tier fallback | `format="json"` requests JSON output. Pydantic `model_validate_json()` for tier 1. Regex extraction for tier 2. PARSE_ERROR sentinel for tier 3. |
</phase_requirements>

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| ollama | 0.6.1 | Async Ollama client | Official Python client. AsyncClient with typed responses. httpx-based transport. |
| backoff | 2.2.1 | Retry decorator | Exponential backoff with jitter. Supports async functions. User-locked requirement. |
| httpx | >=0.28.x | HTTP transport (transitive) | Required by ollama-python internally. Needed for exception types in backoff decorators. |
| pydantic | >=2.12.5 | Structured output models | Already installed. AgentDecision model for LLM output parsing. |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| structlog | >=25.5.0 | Logging (already installed) | Per-agent correlation in inference calls. DEBUG-level parse tier logging. |
| asyncio (stdlib) | Python 3.11+ | Semaphore, context managers | Governor acquire/release, agent_worker context manager. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| backoff | tenacity | tenacity is more feature-rich but user locked decision specifies backoff. backoff is simpler and sufficient. |
| format="json" | Pydantic JSON schema via format param | Schema-constrained output is more reliable but adds complexity. JSON mode + regex fallback is the user's locked design. |

**Installation:**
```bash
uv add ollama backoff
# httpx is a transitive dependency of ollama, no need to add explicitly
```

**Version verification:**
- ollama: 0.6.1 (verified on PyPI, published 2025-11-13)
- backoff: 2.2.1 (verified on PyPI, published 2022-10-05, stable)
- httpx: transitive dependency, version managed by ollama

## Architecture Patterns

### Recommended Project Structure (Phase 2 additions)
```
src/alphaswarm/
  __init__.py           # Existing
  types.py              # Existing -- ADD AgentDecision, PARSE_ERROR to SignalType
  config.py             # Existing -- UPDATE model tags to qwen3.5:32b / qwen3.5:7b
  governor.py           # Existing stub -- UPGRADE to real semaphore (acquire/release wired)
  app.py                # Existing -- ADD ollama_client field to AppState
  logging.py            # Existing
  state.py              # Existing
  __main__.py           # Existing
  ollama_client.py      # NEW: OllamaClient wrapper
  ollama_models.py      # NEW: OllamaModelManager for sequential load/unload
  worker.py             # NEW: agent_worker context manager, WorkerPersonaConfig
  parsing.py            # NEW: parse_agent_decision with 3-tier fallback
  errors.py             # NEW: OllamaInferenceError and domain exceptions
modelfiles/
  Modelfile.orchestrator  # NEW: FROM qwen3.5:32b, PARAMETER num_ctx 8192
  Modelfile.worker        # NEW: FROM qwen3.5:7b, PARAMETER num_ctx 4096
tests/
  test_ollama_client.py   # NEW: OllamaClient unit tests with mocked responses
  test_parsing.py         # NEW: 3-tier parse fallback tests
  test_worker.py          # NEW: agent_worker context manager tests
  test_models.py          # NEW: sequential load/unload tests
```

### Pattern 1: Ollama AsyncClient Wrapper

**What:** Thin wrapper around `ollama.AsyncClient` that enforces project contracts.
**When to use:** Every Ollama interaction in the codebase.
**Example:**
```python
# Source: ollama-python README + CONTEXT.md locked decisions
import ollama
from ollama import AsyncClient, ChatResponse, ResponseError

class OllamaClient:
    """Wrapper enforcing project contracts: no per-request num_ctx, backoff, logging."""

    def __init__(self, base_url: str = "http://localhost:11434") -> None:
        self._client = AsyncClient(host=base_url)

    @backoff.on_exception(backoff.expo, (ResponseError, ConnectionError, httpx.ConnectError), max_tries=3)
    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        format: str | dict | None = "json",
        think: bool | None = None,
        keep_alive: float | str | None = None,
    ) -> ChatResponse:
        return await self._client.chat(
            model=model,
            messages=messages,
            format=format,
            think=think,
            keep_alive=keep_alive,
        )
```

### Pattern 2: Sequential Model Loading via keep_alive=0

**What:** Unload a model by sending a chat/generate request with `keep_alive=0` and empty messages.
**When to use:** Between orchestrator and worker model phases.
**Critical detail:** `keep_alive=0` unloads the currently loaded model from memory. `delete()` permanently removes the model files. Use `keep_alive=0` for runtime unloading. Use `ps()` to verify what is loaded.
**Example:**
```python
# Source: Ollama FAQ, API docs
# Unload a model from memory (does NOT delete it)
await self._client.chat(model="qwen3.5:32b", messages=[], keep_alive=0)

# Verify model is unloaded
ps_response = await self._client.ps()
# ps_response.models should not contain qwen3.5:32b

# Now safe to load worker
response = await self._client.chat(model="qwen3.5:7b", messages=[...])
```

### Pattern 3: Agent Worker as asynccontextmanager

**What:** Context manager that acquires governor semaphore and provides typed worker interface.
**When to use:** Every agent inference call.
**Example:**
```python
# Source: CONTEXT.md locked decision
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

@asynccontextmanager
async def agent_worker(
    persona: WorkerPersonaConfig,
    governor: ResourceGovernor,
    ollama_client: OllamaClient,
) -> AsyncGenerator[AgentWorker, None]:
    await governor.acquire()
    try:
        yield AgentWorker(persona, ollama_client)
    finally:
        governor.release()
```

### Pattern 4: Multi-Tier Structured Output Parsing

**What:** 3-level fallback for extracting Pydantic models from LLM text output.
**When to use:** Every LLM response that should produce an AgentDecision.
**Example:**
```python
# Source: CONTEXT.md locked decision
def parse_agent_decision(raw: str) -> AgentDecision:
    # Tier 1: Direct JSON validation
    try:
        return AgentDecision.model_validate_json(raw)
    except ValidationError:
        pass

    # Tier 2: Regex extraction
    match = re.search(r'\{.*?\}', raw, re.DOTALL)
    if match:
        try:
            return AgentDecision.model_validate_json(match.group())
        except ValidationError:
            pass

    # Tier 3: PARSE_ERROR fallback
    return AgentDecision(
        signal=SignalType.PARSE_ERROR,
        confidence=0.0,
        rationale=f"Parse failed: {raw[:200]}",
    )
```

### Pattern 5: Modelfile-Based Configuration

**What:** num_ctx, temperature defaults, and system prompts baked into Modelfiles created via CLI.
**When to use:** One-time model setup before running the application.
**Critical detail:** The Python `create()` API does NOT accept a Modelfile path. It uses `from_` and inline parameters. For Modelfile-based creation, use the CLI: `ollama create alphaswarm-orchestrator -f modelfiles/Modelfile.orchestrator`. The Python client then references the custom model tag.
**Example Modelfile:**
```
# modelfiles/Modelfile.orchestrator
FROM qwen3.5:32b
PARAMETER num_ctx 8192
PARAMETER temperature 0.7
```

### Anti-Patterns to Avoid

- **Per-request num_ctx:** NEVER pass `num_ctx` in the `options` parameter of `chat()` or `generate()`. This causes Ollama to silently reload the model with new context settings, adding 10-30 seconds of latency per call. All context window configuration goes in Modelfiles.
- **Using delete() for model unloading:** `delete()` permanently removes model files. Use `keep_alive=0` to unload from memory while keeping files on disk.
- **Raw ollama client calls outside wrapper:** All inference must go through `OllamaClient` to ensure backoff, logging, and contract enforcement. No direct `AsyncClient` usage.
- **Catching broad Exception in backoff:** Only catch specific transient errors (`ResponseError`, `ConnectionError`, `httpx.ConnectError`). Do not retry on `RequestError` (client-side validation failure) or `ValueError`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Exponential backoff with jitter | Custom retry loops with sleep | `backoff.on_exception(backoff.expo, ...)` | Full jitter, configurable max_tries, async-native, handles edge cases (max_time, giveup predicates) |
| JSON extraction from LLM output | Custom recursive descent parser | `re.search(r'\{.*?\}', text, re.DOTALL)` + Pydantic `model_validate_json()` | LLMs produce near-valid JSON in 80%+ of cases. Regex captures the JSON block; Pydantic validates. No need for a custom parser. |
| HTTP connection pooling | Manual httpx client lifecycle | `ollama.AsyncClient` (wraps httpx internally) | Ollama client manages connection pooling, keep-alive, and transport lifecycle. |
| Model state tracking | Custom in-memory model registry | `ollama.AsyncClient.ps()` | Returns currently loaded models with their memory usage. Source of truth for what Ollama has loaded. |

**Key insight:** The ollama-python library already handles HTTP transport, connection pooling, streaming, and response typing. Phase 2's wrapper adds project-specific contracts (no num_ctx, backoff, semaphore) on top, not a reimplementation.

## Ollama Python Library API Reference

### Key Types (from `ollama._types`)

| Type | Fields | Notes |
|------|--------|-------|
| `ChatResponse` | `message: Message`, `model`, `created_at`, `done`, `done_reason`, `total_duration`, `load_duration`, `prompt_eval_count`, `eval_count`, `eval_duration` | Inherits from `BaseGenerateResponse` |
| `GenerateResponse` | `response: str`, `thinking: str | None`, `context: list[int]`, same base fields | For `generate()` calls |
| `Message` | `role: str`, `content: str`, `thinking: str | None`, `images`, `tool_calls` | Chat message type |
| `ResponseError` | `error: str`, `status_code: int` | Server-side API errors |
| `RequestError` | `error: str` | Client-side validation errors |
| `ProcessResponse` | `models: list[ProcessModel]` | From `ps()` -- currently loaded models |

### Exception Mapping

| httpx Exception | Mapped to | Retry? |
|-----------------|-----------|--------|
| `httpx.HTTPStatusError` | `ollama.ResponseError` | Yes (transient server errors) |
| `httpx.ConnectError` | `ConnectionError` (builtin) | Yes (Ollama server not ready) |
| Client validation failure | `ollama.RequestError` | No (fix the request) |

### Method Signatures (AsyncClient)

```python
# Chat completion
async def chat(
    model: str,
    messages: Sequence[Union[dict, Message]],
    tools: Optional[Sequence] = None,
    stream: bool = False,
    think: Optional[Union[bool, Literal['low', 'medium', 'high']]] = None,
    format: Optional[Union[Literal['', 'json'], JsonSchemaValue]] = None,
    options: Optional[Union[Mapping, Options]] = None,
    keep_alive: Optional[Union[float, str]] = None,
) -> Union[ChatResponse, AsyncIterator[ChatResponse]]

# Model creation (NOT from Modelfile path -- uses inline params)
async def create(
    model: str,
    from_: str,
    files: Optional[Mapping[str, str]] = None,
    stream: bool = False,
) -> Union[ProgressResponse, AsyncIterator[ProgressResponse]]

# Model deletion (PERMANENT -- removes files)
async def delete(model: str) -> StatusResponse

# List running models
async def ps() -> ProcessResponse
```

### Thinking Mode (Qwen3 models)

- Qwen3 models have thinking enabled by default
- `think=True` explicitly enables reasoning trace
- `think=False` disables reasoning
- Thinking output appears in `message.thinking` (separate from `message.content`)
- For orchestrator High Reasoning mode: pass `think=True` in chat calls
- Thinking adds latency but improves multi-step reasoning quality

## Common Pitfalls

### Pitfall 1: Silent Model Reload from per-request num_ctx

**What goes wrong:** Passing `options={"num_ctx": 4096}` in a `chat()` or `generate()` call causes Ollama to unload and reload the model with the new context size. This adds 10-30 seconds per call.
**Why it happens:** Ollama treats num_ctx as a model-level setting. Changing it at request time forces a model reconfiguration.
**How to avoid:** Set num_ctx ONLY in Modelfiles. Never pass it in `options`. The `OllamaClient` wrapper should NOT expose num_ctx as a parameter.
**Warning signs:** Inference calls taking >10 seconds when they should take 2-5 seconds. `load_duration` in response is abnormally high.

### Pitfall 2: Using delete() Instead of keep_alive=0 for Unloading

**What goes wrong:** Calling `await client.delete("qwen3.5:32b")` removes the model files from disk. Next time you need it, you must re-pull (minutes of download time).
**Why it happens:** Confusion between "unload from memory" and "delete from disk."
**How to avoid:** Use `keep_alive=0` with empty messages to unload from memory. Use `ps()` to verify. Reserve `delete()` for permanent removal only.
**Warning signs:** Models disappearing from `ollama list`. Unexpected download operations.

### Pitfall 3: Thinking Output Contaminating JSON Parsing

**What goes wrong:** When `think=True`, the `message.content` may include reasoning traces or the model may put JSON in `message.thinking` instead of `message.content`.
**Why it happens:** Qwen3 models in thinking mode produce a thinking trace before the final answer. If the model is confused about what goes where, content bleeds.
**How to avoid:** For worker inference where structured JSON output is needed, use `think=False`. Reserve `think=True` for orchestrator tasks where reasoning quality matters more than parseable output. When parsing, always use `message.content` not `message.thinking`.
**Warning signs:** JSON parse failures that contain `<think>` tags or reasoning text.

### Pitfall 4: Backoff Retrying Non-Transient Errors

**What goes wrong:** Retrying on `RequestError` (e.g., invalid model name) wastes time and never succeeds.
**Why it happens:** Catching too broad an exception set in the backoff decorator.
**How to avoid:** Only catch `ResponseError`, `ConnectionError`, and `httpx.ConnectError`. Do NOT catch `RequestError` or `ValueError`.
**Warning signs:** Three retries all failing with the same error message.

### Pitfall 5: ResourceGovernor Stub Providing No Backpressure

**What goes wrong:** In Phase 2, the governor stub is a no-op. If you run the integration test with many concurrent calls, all hit Ollama simultaneously, potentially causing OOM or queue overflow.
**Why it happens:** Phase 1 governor.acquire() does nothing.
**How to avoid:** Phase 2 must upgrade the governor stub to use a real `asyncio.BoundedSemaphore(8)` for acquire/release. The full dynamic adjustment logic is Phase 3, but the basic semaphore must be functional in Phase 2 for the integration test to be meaningful.
**Warning signs:** Integration test hangs or Ollama server crashes under concurrent load.

### Pitfall 6: Modelfile Creation via Python API Limitations

**What goes wrong:** Trying to pass a Modelfile path to `ollama.AsyncClient.create()`. The Python API does NOT accept file paths -- it uses `from_` (base model tag) and inline parameters.
**Why it happens:** Confusion between CLI (`ollama create -f Modelfile`) and Python API.
**How to avoid:** Create Modelfile-based models via CLI as a setup step. Document this in the project README/setup instructions. The Python code references the resulting model tag (e.g., `alphaswarm-orchestrator`). Alternatively, create models programmatically using `create(model="alphaswarm-orchestrator", from_="qwen3.5:32b")` but note this does not support all Modelfile instructions.
**Warning signs:** `create()` calls failing with parameter errors.

## Code Examples

### AgentDecision Pydantic Model (to add to types.py)

```python
# Source: CONTEXT.md specification + existing SignalType enum
class AgentDecision(BaseModel, frozen=True):
    """Structured decision output from an agent inference call."""
    signal: SignalType  # BUY, SELL, HOLD, or PARSE_ERROR
    confidence: float = Field(ge=0.0, le=1.0)
    sentiment: float = Field(ge=-1.0, le=1.0, default=0.0)
    rationale: str = ""
    cited_agents: list[str] = Field(default_factory=list)
```

Note: `SignalType` needs a `PARSE_ERROR = "parse_error"` member added.

### WorkerPersonaConfig TypedDict

```python
# Source: CONTEXT.md locked decision
from typing import TypedDict

class WorkerPersonaConfig(TypedDict):
    agent_id: str
    bracket: str          # BracketType value
    influence_weight: float
    temperature: float
    system_prompt: str
    risk_profile: str
```

### OllamaInferenceError Domain Exception

```python
# Source: CONTEXT.md locked decision
class OllamaInferenceError(Exception):
    """Raised when all backoff retries are exhausted for an Ollama call."""
    def __init__(self, message: str, model: str, original_error: Exception | None = None):
        super().__init__(message)
        self.model = model
        self.original_error = original_error
```

### Backoff Decorator Pattern

```python
# Source: backoff library docs + CONTEXT.md locked decision
import backoff
import httpx
from ollama import ResponseError

@backoff.on_exception(
    backoff.expo,
    (ResponseError, ConnectionError, httpx.ConnectError),
    max_tries=3,
    on_giveup=lambda details: raise_inference_error(details),
)
async def _chat_with_retry(self, **kwargs) -> ChatResponse:
    return await self._client.chat(**kwargs)
```

### Modelfile Examples

```
# modelfiles/Modelfile.orchestrator
FROM qwen3.5:32b
PARAMETER num_ctx 8192
PARAMETER temperature 0.7

# modelfiles/Modelfile.worker
FROM qwen3.5:7b
PARAMETER num_ctx 4096
PARAMETER temperature 0.7
```

### Model Unload Pattern

```python
# Source: Ollama FAQ + API docs
async def unload_model(self, model: str) -> None:
    """Unload model from memory without deleting files."""
    await self._client.chat(model=model, messages=[], keep_alive=0)

async def ensure_model_loaded(self, model: str) -> None:
    """Verify model is loaded, trigger load if not."""
    ps = await self._client.ps()
    loaded_names = [m.model for m in ps.models]
    if model not in loaded_names:
        # Sending a minimal request loads the model
        await self._client.chat(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            keep_alive="5m",
        )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Modelfile path in `create()` | `from_` + inline params in `create()` | ollama-python 0.4+ | Cannot create from Modelfile path via Python API. Use CLI for Modelfile creation. |
| `format="json"` only | `format` accepts JSON schema dict | ollama-python 0.5+ | Can request schema-constrained output, but user decision locks us to `"json"` mode + regex fallback. |
| No thinking support | `think` parameter on chat/generate | ollama 0.8+ | Qwen3 models produce separate `message.thinking` field. Must account for in parsing. |
| `num_ctx` as request option | Still supported but causes silent reload | Always | Core architectural constraint: never use per-request num_ctx. |

**Deprecated/outdated:**
- `modelfile` parameter on `create()`: Replaced by `from_` + inline configuration
- Direct import of `ollama.AsyncClient` response fields as dicts: Now returns typed `ChatResponse` / `GenerateResponse` objects (still subscriptable for backward compat)

## Open Questions

1. **Model Tag Validity: qwen3.5:7b and qwen3.5:32b**
   - What we know: The Ollama model library for qwen3.5 lists sizes 0.8b, 2b, 4b, 9b, 27b, 35b, 122b. There is no 7b or 32b tag.
   - What's unclear: The user has explicitly confirmed these tags ("User has confirmed these as the correct tags for the current Ollama library"). Ollama may have added these tags after the library page was cached, or they may be aliases. The 7b could map to the 9b quantized, and 32b could be a specific quantization of the 35b.
   - Recommendation: Use the tags as specified by the user (`qwen3.5:32b`, `qwen3.5:7b`). If `ollama pull` fails at runtime, the error will be immediate and clear. Document in the Modelfiles that these tags are user-specified and may need adjustment. The planner should include a verification step that attempts `ollama pull qwen3.5:32b` and `ollama pull qwen3.5:7b` early.

2. **Modelfile Creation Strategy: CLI vs Python API**
   - What we know: Python `create()` uses `from_` + inline parameters. CLI uses `ollama create -f Modelfile`. The CONTEXT.md specifies Modelfiles in `modelfiles/` directory.
   - What's unclear: Should Phase 2 create Modelfile-based custom model tags (e.g., `alphaswarm-orchestrator`) via CLI setup script, or should the Python code just use the base model tags with Modelfile parameters embedded?
   - Recommendation: Create Modelfiles as documentation and for CLI-based setup. For the Python runtime, use `create()` programmatically with `from_` and the parameters that would be in the Modelfile. This keeps everything in-code and testable. The `OllamaModelManager` can call `create()` on startup if the custom model tag does not already exist.

3. **Governor Upgrade Scope in Phase 2**
   - What we know: Phase 1 governor is a no-op stub. Phase 3 adds full dynamic scaling. CONTEXT.md says "Phase 2 uses the ResourceGovernor stub from Phase 1."
   - What's unclear: The stub has no real semaphore -- acquire/release do nothing. If Phase 2's integration test dispatches concurrent calls, there is no backpressure.
   - Recommendation: Phase 2 should wire a real `asyncio.BoundedSemaphore(baseline_parallel)` into the governor's `acquire()`/`release()` methods. This is the minimum needed for the agent_worker pattern to function. Dynamic adjustment remains Phase 3.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Ollama server | LLM inference | Installed (not running) | 0.18.1 (CLI) | Must be running for integration tests. Unit tests use mocks. |
| Python | Runtime | Available | 3.11.5 | -- |
| uv | Package management | Available | Yes | -- |
| Docker | Neo4j (future) | Not installed | -- | Not needed for Phase 2 |
| ollama (Python) | AsyncClient | Not installed | Will install 0.6.1 | `uv add ollama` |
| backoff | Retry decorator | Not installed | Will install 2.2.1 | `uv add backoff` |
| httpx | Transitive via ollama | Not installed | Installed with ollama | -- |

**Missing dependencies with no fallback:**
- Ollama server must be running for integration tests. Unit tests can mock the client.

**Missing dependencies with fallback:**
- None. All Python packages can be installed via `uv add`.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.24.x |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest tests/ -x -q` |
| Full suite command | `uv run pytest tests/ -v --tb=short` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INFRA-03 | Sequential model loading: orchestrator loads, unloads, worker loads | integration | `uv run pytest tests/test_models.py -x` | Wave 0 |
| INFRA-03 | Model unload via keep_alive=0 | unit | `uv run pytest tests/test_models.py::test_unload_model -x` | Wave 0 |
| INFRA-03 | ps() verification after unload | unit | `uv run pytest tests/test_models.py::test_verify_unloaded -x` | Wave 0 |
| INFRA-04 | OllamaClient.chat() enforces no per-request num_ctx | unit | `uv run pytest tests/test_ollama_client.py::test_no_num_ctx -x` | Wave 0 |
| INFRA-04 | OllamaClient wraps AsyncClient with backoff | unit | `uv run pytest tests/test_ollama_client.py::test_backoff_retry -x` | Wave 0 |
| INFRA-04 | Modelfile creation with correct parameters | unit | `uv run pytest tests/test_models.py::test_modelfile_content -x` | Wave 0 |
| INFRA-08 | Tier 1: JSON mode parse success | unit | `uv run pytest tests/test_parsing.py::test_tier1_json_parse -x` | Wave 0 |
| INFRA-08 | Tier 2: Regex extraction fallback | unit | `uv run pytest tests/test_parsing.py::test_tier2_regex_extract -x` | Wave 0 |
| INFRA-08 | Tier 3: PARSE_ERROR sentinel | unit | `uv run pytest tests/test_parsing.py::test_tier3_parse_error -x` | Wave 0 |
| INFRA-08 | AgentDecision Pydantic model validates correctly | unit | `uv run pytest tests/test_parsing.py::test_agent_decision_model -x` | Wave 0 |
| INFRA-08 | agent_worker acquires/releases governor semaphore | unit | `uv run pytest tests/test_worker.py::test_semaphore_lifecycle -x` | Wave 0 |
| INFRA-08 | OllamaInferenceError raised after max retries | unit | `uv run pytest tests/test_ollama_client.py::test_max_retries_error -x` | Wave 0 |
| ALL | Integration: single agent inference returns AgentDecision | integration | `uv run pytest tests/test_integration_inference.py -x` | Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/ -x -q`
- **Per wave merge:** `uv run pytest tests/ -v --tb=short`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_ollama_client.py` -- OllamaClient wrapper unit tests with mocked AsyncClient
- [ ] `tests/test_parsing.py` -- 3-tier parse fallback tests with sample LLM outputs
- [ ] `tests/test_worker.py` -- agent_worker context manager semaphore lifecycle tests
- [ ] `tests/test_models.py` -- sequential model load/unload tests with mocked ps() responses
- [ ] `tests/test_integration_inference.py` -- end-to-end single agent inference (requires running Ollama or comprehensive mock)
- [ ] `src/alphaswarm/errors.py` -- OllamaInferenceError exception class

## Project Constraints (from CLAUDE.md)

- **Python 3.11+** required. `asyncio.TaskGroup` and `ExceptionGroup` available.
- **All LLM calls async** via `asyncio`. No blocking I/O on main event loop.
- **Strong typing throughout.** mypy strict mode enabled in pyproject.toml.
- **M1 Max 64GB** -- sequential model loading mandatory. Memory pressure is primary bottleneck.
- **Ollama constraints:** `OLLAMA_NUM_PARALLEL=16`, `OLLAMA_MAX_LOADED_MODELS=2`. Phase 2 enforces sequential loading (max 1 model at a time).
- **uv** for package management. `uv add` for dependency installation.
- **structlog** for all logging. Per-agent correlation IDs via contextvars.
- **ruff** for linting/formatting. **mypy** for type checking. Both must pass.

## Sources

### Primary (HIGH confidence)
- [ollama-python GitHub](https://github.com/ollama/ollama-python) -- AsyncClient API, exception types, response types
- [ollama-python DeepWiki Client Classes](https://deepwiki.com/ollama/ollama-python/3.1-client-classes) -- Full method signatures including `think` parameter
- [ollama-python DeepWiki Error Handling](https://deepwiki.com/ollama/ollama-python/5.3-error-handling) -- Exception mapping from httpx
- [ollama-python DeepWiki Model Management](https://deepwiki.com/ollama/ollama-python/4.5-model-management) -- create, delete, ps methods
- [Ollama Thinking Docs](https://docs.ollama.com/capabilities/thinking) -- think parameter behavior, response fields
- [Ollama Modelfile Reference](https://docs.ollama.com/modelfile) -- PARAMETER options, num_ctx, temperature
- [Ollama FAQ](https://docs.ollama.com/faq) -- keep_alive=0 for model unloading
- [ollama PyPI](https://pypi.org/project/ollama/) -- v0.6.1, published 2025-11-13
- [backoff PyPI](https://pypi.org/project/backoff/) -- v2.2.1, published 2022-10-05
- [qwen3.5 Ollama Tags](https://ollama.com/library/qwen3.5/tags) -- Available sizes: 0.8b, 2b, 4b, 9b, 27b, 35b, 122b

### Secondary (MEDIUM confidence)
- [Ollama API Reference](https://ollama.readthedocs.io/en/api/) -- REST API endpoints for create, chat, generate
- [Paul Easterbrooks - Unloading Ollama Models](https://pauleasterbrooks.com/articles/technology/clearing-ollama-memory) -- keep_alive=0 pattern verification

### Tertiary (LOW confidence)
- [Markaicode Ollama API Reference 2026](https://markaicode.com/ollama-python-library-api-reference/) -- Community documentation, cross-verified against official sources

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- ollama-python 0.6.1 and backoff 2.2.1 verified on PyPI. API signatures verified via official GitHub source and DeepWiki.
- Architecture: HIGH -- All patterns derived from locked CONTEXT.md decisions with official API verification.
- Pitfalls: HIGH -- keep_alive vs delete, num_ctx reload, thinking contamination all verified against official docs.
- Model tags: MEDIUM -- qwen3.5:7b and qwen3.5:32b not found in official tag list, but user explicitly confirmed. Flagged in Open Questions.

**Research date:** 2026-03-24
**Valid until:** 2026-04-24 (stable libraries, Ollama model library may update sooner)
