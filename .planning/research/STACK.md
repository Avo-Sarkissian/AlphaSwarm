# Technology Stack

**Project:** AlphaSwarm
**Researched:** 2026-03-24

## Critical Findings Before Stack Decisions

### Ruflo v3.5 Is NOT a Python Library

The CLAUDE.md lists "Ruflo v3.5 (Hierarchical Swarm logic)" as the orchestration layer. **This is incorrect for this project.** Ruflo (formerly Claude Flow) is a Node.js/TypeScript enterprise platform for orchestrating Claude Code agents via MCP. It is distributed as npm packages, uses WASM kernels written in Rust, and has no Python SDK or API.

**Recommendation:** Replace Ruflo with a custom Python orchestration layer. The swarm mechanics in AlphaSwarm (batched inference, 3-round cascade, influence topology) are domain-specific enough that no off-the-shelf multi-agent framework fits cleanly. Build a lightweight `SwarmOrchestrator` class using native `asyncio` primitives. This is ~300 lines of code, not a framework dependency.

**Confidence:** HIGH -- verified via GitHub repo, PyPI (no Python package exists), and Ruflo v3.5 release notes.

### Llama 4 70B Does Not Exist

The spec references `llama4:70b` as the orchestrator model. **Llama 4 does not come in a 70B variant.** Llama 4 models use a Mixture-of-Experts (MoE) architecture:

- **Llama 4 Scout:** 109B total params, 17B active, 16 experts -- 67GB download (Q4_K_M)
- **Llama 4 Maverick:** 400B total params, 17B active, 128 experts -- 245GB download

The 67GB Scout model exceeds the M1 Max 64GB unified memory. It cannot be loaded alongside any worker model.

**Recommendation:** Use `llama3.3:70b` (Q4_K_M, ~40GB) as the orchestrator model. It fits in 64GB with headroom for a worker model and OS overhead. The Llama 3.3 70B achieves comparable quality to Llama 3.1 405B for instruction-following tasks. On M1 Max 64GB, expect ~6-8 tok/s.

**Confidence:** HIGH -- verified via Ollama model library and Apple Silicon benchmark threads.

### Qwen 3.5 7B Does Not Exist

The spec references `qwen3.5:7b` as the worker model. **Qwen 3.5 does not have a 7B variant.** Available sizes: 0.8B, 2B, 4B, 9B, 27B, 35B, 122B.

**Recommendation:** Use `qwen3.5:4b` (3.4GB) as the worker model. The 4B is the largest model that allows comfortable dual-model loading alongside the 70B orchestrator within 64GB. The 9B (6.6GB) is feasible but leaves less headroom for 16 parallel context slots.

**Confidence:** HIGH -- verified via Ollama model library page for qwen3.5.

### Dual-Model Memory Budget (M1 Max 64GB)

| Component | Memory |
|-----------|--------|
| macOS + system overhead | ~8GB |
| Orchestrator: llama3.3:70b Q4_K_M | ~40GB |
| Worker: qwen3.5:4b | ~3.4GB |
| Neo4j (Docker) | ~2GB |
| Python runtime + Textual | ~1GB |
| **Remaining headroom** | **~10GB** |

With OLLAMA_NUM_PARALLEL=16 on a 4B model, each parallel slot adds ~200MB (rough estimate for 4B at Q4). 16 slots = ~3.2GB additional, which fits within the 10GB headroom.

**Critical constraint:** The orchestrator and worker model cannot both be loaded simultaneously at the default model sizes. The ResourceGovernor must sequence model loading: load orchestrator for seed parsing, unload, then load worker for 100-agent inference. Alternatively, run with only the worker model loaded and use a smaller orchestrator like `llama3.1:8b`.

**Alternative dual-load strategy:**
| Component | Memory |
|-----------|--------|
| Orchestrator: llama3.1:8b (4.7GB) | ~5GB |
| Worker: qwen3.5:4b (3.4GB) | ~4GB |
| Both loaded simultaneously | ~9GB total model memory |
| 16 parallel slots on worker | ~12GB total |
| **This fits comfortably in 64GB** | **Yes** |

**Recommendation:** Use `llama3.1:8b` as orchestrator + `qwen3.5:4b` as worker for simultaneous dual-model loading. If orchestrator quality is insufficient for seed parsing, implement a sequential loading pattern with `llama3.3:70b` where models are swapped per-phase.

## Recommended Stack

### Runtime & Packaging

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Python | 3.11+ | Runtime | Required by project constraints. 3.11 added TaskGroup, ExceptionGroup. 3.12+ acceptable but 3.11 is the floor. |
| uv | latest | Package manager | 10-100x faster than pip. Lockfile support. Manages Python versions per-project. Industry standard for new Python projects in 2026. |
| pyproject.toml | PEP 621 | Project metadata | Single source of truth for deps, scripts, tool config. uv reads it natively. |

**Confidence:** HIGH -- uv is the dominant Python package manager as of 2025-2026 per community adoption.

### LLM Inference

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Ollama | latest (server) | Local LLM runtime | Only serious option for local inference on Apple Silicon. Metal acceleration. OLLAMA_NUM_PARALLEL controls concurrency. |
| ollama (Python) | >=0.6.1 | Python SDK | Official client with `AsyncClient` for non-blocking inference. Typed responses. Streaming support. |
| llama3.1:8b or llama3.3:70b | latest | Orchestrator model | 8b for dual-load; 70b for sequential-load high-quality mode. See memory analysis above. |
| qwen3.5:4b | latest | Worker agent model | 3.4GB footprint. Fits 16 parallel slots within memory budget. Good instruction-following for structured JSON output. |

**Confidence:** HIGH -- ollama 0.6.1 verified on PyPI. AsyncClient verified in library source.

### Graph Database

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Neo4j Community Edition | 2026.02.x | Graph state storage | Free, runs locally via Docker. Cypher query language is purpose-built for traversing influence topology. INFLUENCED_BY edges, cycle-scoped sentiment, peer decision reads -- all graph-native operations. |
| neo4j (Python driver) | >=6.1.0 | Async Python driver | Official driver with `AsyncGraphDatabase.driver()`. Connection pooling. Supports Neo4j 2025/2026 versions. Python >=3.10. |
| Docker | latest | Neo4j hosting | Run `neo4j:2026.02-community` image. Mount /data volume for persistence. APOC plugin via NEO4J_PLUGINS env var. |

**Confidence:** HIGH -- neo4j driver 6.1.0 verified on PyPI (released 2026-01-12). Community Edition free license confirmed.

### Terminal UI

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| textual | >=8.1.1 | TUI framework | The only production-grade Python TUI framework. CSS-like styling, reactive programming, 60fps rendering. Worker API for background async tasks. Built by Textualize (same team as Rich). |
| rich | >=14.3.3 | Console rendering | Dependency of Textual. Provides table rendering, color, progress bars. Also useful for non-TUI logging output. |

**Confidence:** HIGH -- textual 8.1.1 verified on PyPI (released 2026-03-10). Worker pattern verified in official docs.

### Orchestration (Custom)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| asyncio (stdlib) | Python 3.11+ | Concurrency runtime | Built-in. TaskGroup for structured concurrency. BoundedSemaphore for concurrency limiting. No external dependency needed. |
| Custom SwarmOrchestrator | n/a | Agent lifecycle, batching, cascade rounds | Domain-specific logic: 3-round cascade, bracket-based batching, influence topology formation. No framework matches these semantics. ~300 LOC. |
| Custom ResourceGovernor | n/a | Memory-aware throttling | Dynamic semaphore adjustment based on psutil memory readings. Pauses task queue at 90% memory utilization. ~150 LOC. |

**Confidence:** HIGH -- asyncio TaskGroup is stdlib. Pattern well-documented.

### System Monitoring

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| psutil | >=7.2.2 | Hardware telemetry | Cross-platform memory/CPU monitoring. `virtual_memory()` for RAM pressure detection. Works on macOS ARM64 (M1). Mature (since 2009), zero dependencies. |

**Confidence:** HIGH -- psutil 7.2.2 verified on PyPI (released 2026-01-28). macOS arm64 support confirmed.

### Data Validation & Configuration

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| pydantic | >=2.12.5 | Data models, agent config | Runtime validation, JSON schema generation, structured LLM output parsing. Industry standard for typed Python. |
| pydantic-settings | >=2.13.1 | Environment/config loading | Load OLLAMA_NUM_PARALLEL, Neo4j credentials, memory thresholds from .env files with type validation. |

**Confidence:** HIGH -- pydantic 2.12.5 verified on PyPI (released 2025-11-26). pydantic-settings 2.13.1 verified.

### Logging

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| structlog | >=25.5.0 | Structured async logging | Native async log methods (ainfo, adebug, etc.). JSON output for machine parsing. Context binding for per-agent log correlation (agent_id, bracket, cycle_id). Zero performance overhead compared to stdlib logging. |

**Confidence:** HIGH -- structlog 25.5.0 verified on PyPI (released 2025-10-27).

### HTTP (Miro API, future integrations)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| httpx | >=0.28.x | Async HTTP client | Dual sync/async API. HTTP/2 support. Connection pooling. Type-annotated. Required by ollama-python internally. Use directly for Miro API calls rather than adding miro-api SDK (avoids heavy dependency for a deferred feature). |

**Confidence:** MEDIUM -- httpx version not confirmed via PyPI fetch (blocked), but 0.28.x is current based on search results. Used internally by ollama-python.

### Visualization (Phase 2, Deferred)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| miro-api | >=2.2.4 | Miro REST API v2 client | Official Python SDK. Bulk item creation (up to 20 items per call). Requires Python 3.9+. **Deferred to Phase 2** -- stub the batcher interface now, implement later. |

**Confidence:** MEDIUM -- miro-api 2.2.4 found on PyPI. Bulk create verified in Miro API docs.

### Testing

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| pytest | >=8.x | Test runner | Industry standard. Plugin ecosystem. |
| pytest-asyncio | >=0.24.x | Async test support | Required for testing async Ollama calls, Neo4j queries, orchestrator logic. |
| pytest-cov | >=6.x | Coverage reporting | Track test coverage. |

**Confidence:** MEDIUM -- versions approximate based on training data. Verify at install time.

### Development Tools

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| ruff | latest | Linter + formatter | Replaces flake8, isort, black. Single tool. 10-100x faster (Rust-based). |
| mypy | latest | Type checker | Enforces strong typing requirement from project constraints. |
| pre-commit | latest | Git hooks | Run ruff + mypy before commits. |

**Confidence:** HIGH -- standard toolchain.

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Orchestration | Custom asyncio | LangGraph | Massive dependency tree, opinionated agent patterns that don't match the 3-round cascade model. Adds complexity without value for this domain. |
| Orchestration | Custom asyncio | CrewAI | Same issue -- designed for role-based agent conversations, not batched financial simulation cascades. Wrong abstraction level. |
| Orchestration | Custom asyncio | OpenAI Agents SDK | Requires OpenAI API. We're local-only with Ollama. |
| Graph DB | Neo4j | NetworkX (in-memory) | No persistence. No Cypher query language. Falls apart at 100 agents x 3 rounds x N cycles of relationship data. |
| Graph DB | Neo4j | ArangoDB | Less Python ecosystem support. Neo4j's Cypher is better suited for influence topology traversal patterns. |
| TUI | Textual | curses/urwid | Ancient. No CSS styling. No reactive programming. No worker pattern. 5-10x slower rendering. |
| TUI | Textual | Streamlit | Web-based, not terminal. Adds HTTP server overhead. Not "local-first terminal" aesthetic. |
| LLM Client | ollama-python | litellm | Abstraction layer adds latency and complexity. We're only talking to Ollama. Direct client is simpler and faster. |
| Package Mgr | uv | poetry | Slower. More complex. uv is the clear winner in 2026. |
| Logging | structlog | loguru | No native async methods. Less structured output. structlog's context binding is better for per-agent correlation. |
| HTTP | httpx | aiohttp | httpx is already a transitive dependency via ollama-python. Adding aiohttp means two async HTTP clients. Unnecessary. |

## Installation

```bash
# Initialize project with uv
uv init alphaswarm
cd alphaswarm

# Core dependencies
uv add ollama textual rich neo4j pydantic pydantic-settings psutil structlog httpx

# Dev dependencies
uv add --dev pytest pytest-asyncio pytest-cov ruff mypy pre-commit textual-dev

# External services (run separately)
# Ollama: https://ollama.com/download
ollama pull llama3.1:8b
ollama pull qwen3.5:4b
# For high-quality orchestrator mode (sequential loading):
ollama pull llama3.3:70b

# Neo4j via Docker
docker run -d \
  --name alphaswarm-neo4j \
  -p 7474:7474 -p 7687:7687 \
  -v alphaswarm-neo4j-data:/data \
  -e NEO4J_AUTH=neo4j/alphaswarm \
  -e NEO4J_PLUGINS='["apoc"]' \
  neo4j:2026.02-community
```

## Model Loading Strategy

```
# .env configuration
OLLAMA_NUM_PARALLEL=16
OLLAMA_MAX_LOADED_MODELS=2

# Strategy A: Dual-Load (recommended for development, lower quality orchestrator)
ALPHASWARM_ORCHESTRATOR_MODEL=llama3.1:8b
ALPHASWARM_WORKER_MODEL=qwen3.5:4b

# Strategy B: Sequential-Load (for production runs, higher quality orchestrator)
ALPHASWARM_ORCHESTRATOR_MODEL=llama3.3:70b
ALPHASWARM_WORKER_MODEL=qwen3.5:4b
# ResourceGovernor will unload orchestrator before loading worker
```

## Sources

- [Ollama Python library (GitHub)](https://github.com/ollama/ollama-python)
- [Ollama Python on PyPI (v0.6.1)](https://pypi.org/project/ollama/)
- [Ollama model library - Llama 4](https://ollama.com/library/llama4)
- [Ollama model library - Qwen 3.5](https://ollama.com/library/qwen3.5)
- [Textual on PyPI (v8.1.1)](https://pypi.org/project/textual/)
- [Textual Workers documentation](https://textual.textualize.io/guide/workers/)
- [Neo4j Python driver on PyPI (v6.1.0)](https://pypi.org/project/neo4j/)
- [Neo4j Docker deployment](https://neo4j.com/docs/operations-manual/current/docker/introduction/)
- [psutil on PyPI (v7.2.2)](https://pypi.org/project/psutil/)
- [Pydantic on PyPI (v2.12.5)](https://pypi.org/project/pydantic/)
- [pydantic-settings on PyPI (v2.13.1)](https://pypi.org/project/pydantic-settings/)
- [structlog on PyPI (v25.5.0)](https://pypi.org/project/structlog/)
- [Ruflo GitHub (Node.js, NOT Python)](https://github.com/ruvnet/ruflo)
- [Ruflo v3.5.0 release notes](https://github.com/ruvnet/ruflo/issues/1240)
- [Miro API bulk create documentation](https://developers.miro.com/reference/create-items)
- [miro-api on PyPI (v2.2.4)](https://pypi.org/project/miro-api/)
- [Ollama parallel request handling](https://www.glukhov.org/post/2025/05/how-ollama-handles-parallel-requests/)
- [Llama 3.3 70B on M3 Max benchmarks](https://deepnewz.com/ai-modeling/llama-3-3-70b-model-achieves-10-tokens-per-second-on-64gb-m3-max-12-tokens-per-980c01a7)
- [Apple Silicon LLM performance discussion](https://github.com/ggml-org/llama.cpp/discussions/4167)
- [uv package manager docs](https://docs.astral.sh/uv/guides/projects/)
