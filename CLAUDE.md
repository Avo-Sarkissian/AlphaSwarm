# AlphaSwarm: Core Development Directives

## Identity & Role
You are a Senior Quantitative AI Engineer building a high-performance, local-first market simulation engine. Your code must be modular, strongly typed (Python 3.11+), and heavily asynchronous.

## Tech Stack & Architecture
- **Orchestration:** Ruflo v3.5 (Hierarchical Swarm logic).
- **Intelligence:** Ollama API (`llama4:70b` for orchestration, `qwen3.5:7b` for worker agents).
- **Memory/State:** Neo4j (GraphRAG for interaction history and consensus tracking).
- **UI/UX:** `textual` framework for a clean, minimalist terminal dashboard.
- **Visuals:** Miro REST API v2 for dynamic network visualization.

## Hardware Optimization (M1 Max 64GB)
- **Concurrency is mandatory:** Use `asyncio` for all LLM inference and API calls.
- **Ollama Constraints:** Assume `OLLAMA_NUM_PARALLEL=16` and `OLLAMA_MAX_LOADED_MODELS=2`.
- **Memory Pressure:** Implement basic telemetry to monitor local RAM. If pressure is high, pause the task queue.

## API & Rate Limit Rules
- **Miro API:** Strict 2-second buffer/batching for all `POST` and `PATCH` requests. Never send single-node updates. Bulk create items to avoid 429 Too Many Requests errors.

<!-- GSD:project-start source:PROJECT.md -->
## Project

**AlphaSwarm**

A localized, multi-agent financial simulation engine that ingests a single "Seed Rumor" and simulates cascading market reactions across 100 distinct AI personas. The system runs a 3-round iterative consensus cascade on local hardware (M1 Max 64GB), visualizing real-time agent state via a Textual TUI dashboard and persisting interaction history in Neo4j.

**Core Value:** The 3-round consensus cascade must produce believable, diverse market reactions from 100 agents with dynamic influence topology — the simulation engine is the product.

### Constraints

- **Hardware**: M1 Max 64GB — all inference local, no cloud APIs. Memory pressure is the primary bottleneck.
- **Ollama**: Max 2 models loaded simultaneously, 16 parallel baseline (dynamically adjusted). Cold-loading a 70B model takes ~30s.
- **Miro API**: 2-second minimum buffer between POST/PATCH. Bulk operations only. 429 handling mandatory.
- **Concurrency**: All LLM calls and API interactions must be async (asyncio). No blocking I/O on the main event loop.
- **Python**: 3.11+ required. Strong typing throughout.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## Critical Findings Before Stack Decisions
### Ruflo v3.5 Is NOT a Python Library
### Llama 4 70B Does Not Exist
- **Llama 4 Scout:** 109B total params, 17B active, 16 experts -- 67GB download (Q4_K_M)
- **Llama 4 Maverick:** 400B total params, 17B active, 128 experts -- 245GB download
### Qwen 3.5 7B Does Not Exist
### Dual-Model Memory Budget (M1 Max 64GB)
| Component | Memory |
|-----------|--------|
| macOS + system overhead | ~8GB |
| Orchestrator: llama3.3:70b Q4_K_M | ~40GB |
| Worker: qwen3.5:4b | ~3.4GB |
| Neo4j (Docker) | ~2GB |
| Python runtime + Textual | ~1GB |
| **Remaining headroom** | **~10GB** |
| Component | Memory |
|-----------|--------|
| Orchestrator: llama3.1:8b (4.7GB) | ~5GB |
| Worker: qwen3.5:4b (3.4GB) | ~4GB |
| Both loaded simultaneously | ~9GB total model memory |
| 16 parallel slots on worker | ~12GB total |
| **This fits comfortably in 64GB** | **Yes** |
## Recommended Stack
### Runtime & Packaging
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Python | 3.11+ | Runtime | Required by project constraints. 3.11 added TaskGroup, ExceptionGroup. 3.12+ acceptable but 3.11 is the floor. |
| uv | latest | Package manager | 10-100x faster than pip. Lockfile support. Manages Python versions per-project. Industry standard for new Python projects in 2026. |
| pyproject.toml | PEP 621 | Project metadata | Single source of truth for deps, scripts, tool config. uv reads it natively. |
### LLM Inference
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Ollama | latest (server) | Local LLM runtime | Only serious option for local inference on Apple Silicon. Metal acceleration. OLLAMA_NUM_PARALLEL controls concurrency. |
| ollama (Python) | >=0.6.1 | Python SDK | Official client with `AsyncClient` for non-blocking inference. Typed responses. Streaming support. |
| llama3.1:8b or llama3.3:70b | latest | Orchestrator model | 8b for dual-load; 70b for sequential-load high-quality mode. See memory analysis above. |
| qwen3.5:4b | latest | Worker agent model | 3.4GB footprint. Fits 16 parallel slots within memory budget. Good instruction-following for structured JSON output. |
### Graph Database
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Neo4j Community Edition | 2026.02.x | Graph state storage | Free, runs locally via Docker. Cypher query language is purpose-built for traversing influence topology. INFLUENCED_BY edges, cycle-scoped sentiment, peer decision reads -- all graph-native operations. |
| neo4j (Python driver) | >=6.1.0 | Async Python driver | Official driver with `AsyncGraphDatabase.driver()`. Connection pooling. Supports Neo4j 2025/2026 versions. Python >=3.10. |
| Docker | latest | Neo4j hosting | Run `neo4j:2026.02-community` image. Mount /data volume for persistence. APOC plugin via NEO4J_PLUGINS env var. |
### Terminal UI
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| textual | >=8.1.1 | TUI framework | The only production-grade Python TUI framework. CSS-like styling, reactive programming, 60fps rendering. Worker API for background async tasks. Built by Textualize (same team as Rich). |
| rich | >=14.3.3 | Console rendering | Dependency of Textual. Provides table rendering, color, progress bars. Also useful for non-TUI logging output. |
### Orchestration (Custom)
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| asyncio (stdlib) | Python 3.11+ | Concurrency runtime | Built-in. TaskGroup for structured concurrency. BoundedSemaphore for concurrency limiting. No external dependency needed. |
| Custom SwarmOrchestrator | n/a | Agent lifecycle, batching, cascade rounds | Domain-specific logic: 3-round cascade, bracket-based batching, influence topology formation. No framework matches these semantics. ~300 LOC. |
| Custom ResourceGovernor | n/a | Memory-aware throttling | Dynamic semaphore adjustment based on psutil memory readings. Pauses task queue at 90% memory utilization. ~150 LOC. |
### System Monitoring
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| psutil | >=7.2.2 | Hardware telemetry | Cross-platform memory/CPU monitoring. `virtual_memory()` for RAM pressure detection. Works on macOS ARM64 (M1). Mature (since 2009), zero dependencies. |
### Data Validation & Configuration
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| pydantic | >=2.12.5 | Data models, agent config | Runtime validation, JSON schema generation, structured LLM output parsing. Industry standard for typed Python. |
| pydantic-settings | >=2.13.1 | Environment/config loading | Load OLLAMA_NUM_PARALLEL, Neo4j credentials, memory thresholds from .env files with type validation. |
### Logging
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| structlog | >=25.5.0 | Structured async logging | Native async log methods (ainfo, adebug, etc.). JSON output for machine parsing. Context binding for per-agent log correlation (agent_id, bracket, cycle_id). Zero performance overhead compared to stdlib logging. |
### HTTP (Miro API, future integrations)
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| httpx | >=0.28.x | Async HTTP client | Dual sync/async API. HTTP/2 support. Connection pooling. Type-annotated. Required by ollama-python internally. Use directly for Miro API calls rather than adding miro-api SDK (avoids heavy dependency for a deferred feature). |
### Visualization (Phase 2, Deferred)
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| miro-api | >=2.2.4 | Miro REST API v2 client | Official Python SDK. Bulk item creation (up to 20 items per call). Requires Python 3.9+. **Deferred to Phase 2** -- stub the batcher interface now, implement later. |
### Testing
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| pytest | >=8.x | Test runner | Industry standard. Plugin ecosystem. |
| pytest-asyncio | >=0.24.x | Async test support | Required for testing async Ollama calls, Neo4j queries, orchestrator logic. |
| pytest-cov | >=6.x | Coverage reporting | Track test coverage. |
### Development Tools
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| ruff | latest | Linter + formatter | Replaces flake8, isort, black. Single tool. 10-100x faster (Rust-based). |
| mypy | latest | Type checker | Enforces strong typing requirement from project constraints. |
| pre-commit | latest | Git hooks | Run ruff + mypy before commits. |
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
# Initialize project with uv
# Core dependencies
# Dev dependencies
# External services (run separately)
# Ollama: https://ollama.com/download
# For high-quality orchestrator mode (sequential loading):
# Neo4j via Docker
## Model Loading Strategy
# .env configuration
# Strategy A: Dual-Load (recommended for development, lower quality orchestrator)
# Strategy B: Sequential-Load (for production runs, higher quality orchestrator)
# ResourceGovernor will unload orchestrator before loading worker
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
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
