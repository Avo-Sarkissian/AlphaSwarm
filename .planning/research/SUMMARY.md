# Project Research Summary

**Project:** AlphaSwarm
**Domain:** Local-first multi-agent LLM financial market simulation engine
**Researched:** 2026-03-24
**Confidence:** HIGH

## Executive Summary

AlphaSwarm is a local-first, multi-agent financial simulation engine that runs 100 LLM-powered agents through a 3-round consensus cascade on an M1 Max 64GB machine. Research across comparable systems (TradingAgents, TwinMarket, StockSim, MiroFish-Offline, OASIS) confirms that this is a viable and differentiated product concept. The consensus cascade with dynamic influence topology -- where agents cite peers and form emergent INFLUENCED_BY edges tracked in a graph database -- is novel among surveyed systems. Most comparable frameworks use fixed role hierarchies or single-shot inference; AlphaSwarm's iterative peer-influence mechanism is the primary differentiator.

The recommended approach is a custom Python asyncio orchestration layer (replacing the originally specified Ruflo, which is a Node.js platform incompatible with this project), Ollama for local inference, Neo4j for graph state, and Textual for a real-time terminal dashboard. Three critical corrections to the original spec emerged from research: (1) Ruflo v3.5 is not a Python library and must be replaced with custom asyncio orchestration, (2) `llama4:70b` does not exist -- use `llama3.1:8b` for dual-load development or `llama3.3:70b` for sequential high-quality mode, and (3) `qwen3.5:7b` does not exist -- use `qwen3.5:4b` instead. These corrections are non-negotiable and must be applied before any code is written.

The dominant risk is memory exhaustion on the M1 Max 64GB. The dual-model loading strategy, 16 parallel inference slots, Neo4j, and the Python runtime push total memory consumption to 53-65 GB, exceeding the Metal GPU allocation ceiling. Prevention requires sequential model loading (orchestrator and worker models swap rather than coexist), reduced parallelism (start at 8, not 16), KV cache quantization, and a ResourceGovernor that monitors actual system pressure -- not just psutil percentages, which are unreliable on Apple Silicon unified memory. Secondary risks include Neo4j write deadlocks on high-influence "hot nodes," the echo chamber effect where agents converge to homogeneous consensus, and silent asyncio task garbage collection dropping agents from the simulation.

## Key Findings

### Recommended Stack

The stack is pure Python 3.11+ with no external orchestration framework. Core inference runs through Ollama's official Python SDK (`ollama>=0.6.1`) with `AsyncClient` for non-blocking calls. Graph state lives in Neo4j Community Edition (Docker, async driver `neo4j>=6.1.0`). The TUI uses Textual (`>=8.1.1`). Data validation and structured LLM output parsing use Pydantic (`>=2.12.5`). All concurrency is native asyncio with custom `SwarmOrchestrator` and `ResourceGovernor` classes (~450 LOC combined).

**Core technologies:**
- **Python 3.11+ / uv**: Runtime and packaging -- TaskGroup for structured concurrency, uv for fast dependency management
- **Ollama + ollama-python (>=0.6.1)**: Local LLM inference -- AsyncClient, Metal acceleration, 16-parallel slot support
- **llama3.1:8b (dev) / llama3.3:70b (prod)**: Orchestrator model -- seed parsing and consensus aggregation (corrected from nonexistent `llama4:70b`)
- **qwen3.5:4b**: Worker agent model -- 3.4GB footprint, fits 16 parallel slots (corrected from nonexistent `qwen3.5:7b`)
- **Neo4j Community Edition (Docker)**: Graph state -- cycle-scoped sentiment, influence topology, Cypher queries
- **neo4j Python driver (>=6.1.0)**: Async graph access -- session-per-coroutine pattern, UNWIND batch writes
- **Textual (>=8.1.1)**: Terminal dashboard -- 10x10 agent grid, snapshot-based 200ms rendering
- **Pydantic (>=2.12.5)**: Data models -- agent config, structured LLM output schemas, settings management
- **psutil (>=7.2.2)**: Memory telemetry -- ResourceGovernor feedback loop (with macOS-specific calibration)
- **structlog (>=25.5.0)**: Structured logging -- per-agent correlation via context binding
- **httpx (>=0.28.x)**: Async HTTP -- Miro API calls (Phase 2), already a transitive dependency of ollama-python

**Critical version/tag corrections from original spec:**
- `llama4:70b` --> `llama3.1:8b` or `llama3.3:70b` (Llama 4 has no 70B variant)
- `qwen3.5:7b` --> `qwen3.5:4b` (Qwen 3.5 has no 7B variant; 4B is the largest that fits dual-load)
- Ruflo v3.5 --> custom asyncio SwarmOrchestrator (Ruflo is Node.js, not Python)

### Expected Features

**Must have (table stakes):**
- Heterogeneous agent personas -- 10 bracket archetypes with distinct risk profiles, information biases, and decision heuristics
- 3-round consensus cascade -- Initial Reaction, Peer Influence, Final Consensus Lock
- Seed rumor injection with entity extraction -- NER grounds agent reasoning in specific entities
- Async concurrent execution with ResourceGovernor -- batched waves of 16 (adjustable) via Ollama
- Neo4j persistence -- cycle-scoped sentiment, rationale, and influence edges
- Structured output parsing -- JSON-mode with strict schema (sentiment, action, confidence, rationale, cited_agents)
- Agent decision logging -- every response persisted with full context for post-hoc analysis
- Per-agent sentiment/position output -- normalized score (-1.0 to 1.0) plus categorical action

**Should have (differentiators):**
- Dynamic influence topology -- INFLUENCED_BY edges form from citation/agreement patterns in Neo4j (strongest differentiator; no comparable system does this)
- Real-time TUI dashboard -- 10x10 agent grid with color-coded sentiment, rationale sidebar, hardware telemetry footer
- Bracket-level aggregate analytics -- "Quants are 80% bearish while Degens are 90% bullish"
- Consensus cascade with peer influence -- Round 2 injects actual neighbor opinions via Neo4j topology queries
- Simulation replay / time-travel -- re-examine stored decisions without re-running LLM inference

**Defer (v2+):**
- Miro network visualization -- API-constrained, requires credit-aware rate limiting batcher
- Exportable simulation reports -- markdown/HTML post-simulation summaries
- Mid-simulation shock injection -- "Fed announces emergency rate hike during Round 2"
- Configurable agent count -- hardcode 100/10 for Phase 1, parameterize later

**Never build:**
- Real market data feeds, trade execution, backtesting, fine-tuned models, multi-user mode, GPU/cloud inference, order book microstructure, or RL-based adaptive agents

### Architecture Approach

The system is a **pipeline-with-feedback-loop** architecture: three sequential cascade rounds, with each round reading peer state from a shared graph (Neo4j) to create emergent influence topology. Five major subsystems communicate through async interfaces and a shared StateStore for TUI decoupling. The TUI is snapshot-based (200ms tick) and never directly coupled to agent coroutines. All Neo4j writes use UNWIND batch operations (one transaction per round, not per agent). The ResourceGovernor uses a token-pool pattern (asyncio.Queue) rather than semaphore hacking for cleaner dynamic concurrency adjustment.

**Major components:**
1. **SeedInjector** -- transforms raw rumor text into structured SeedEvent via orchestrator LLM (entity extraction, sentiment hint, rumor classification)
2. **SimulationEngine** -- state machine orchestrating 3-round cascade, round transitions, model loading sequencing
3. **AgentPool** -- manages 100 agent personas, dispatches inference through ResourceGovernor, collects structured decisions
4. **ResourceGovernor** -- dynamic concurrency control via token-pool pattern, psutil + macOS memory_pressure monitoring, backpressure gate
5. **GraphStateManager** -- all Neo4j reads/writes encapsulated, session-per-coroutine, UNWIND batch operations, composite indexes for sub-5ms queries
6. **StateStore** -- thread-safe shared state with immutable snapshot production for TUI consumption
7. **TUI Dashboard (Textual)** -- 10x10 AgentGrid, RationaleSidebar, TelemetryFooter, 200ms polling from StateStore
8. **MiroBatcher (stubbed)** -- Phase 2 implementation, credit-aware rate limiting, bulk API operations

### Critical Pitfalls

1. **Memory budget does not close (CRITICAL)** -- The 70B + worker model + 16 parallel KV caches + Neo4j + system overhead exceeds 64GB. Prevention: sequential model loading (swap orchestrator/worker per phase), reduce OLLAMA_NUM_PARALLEL to 8, enable KV cache quantization (`OLLAMA_KV_CACHE_TYPE=q8_0`), apply Metal GPU override (`sysctl iogpu.wired_limit_mb=57344`), throttle at 80% memory (not 90%).

2. **Ollama context size mismatch triggers silent model reloads (CRITICAL)** -- Different `num_ctx` values between requests force full model teardown and reload (30-45s for 70B). Prevention: standardize num_ctx via Ollama Modelfiles, never pass num_ctx in API requests.

3. **Neo4j AsyncSession is not concurrency-safe (CRITICAL)** -- Sharing one session across 100 agent coroutines causes corrupted reads and crashes. Prevention: session-per-coroutine via `async with driver.session()`, or use `driver.execute_query()` which handles session lifecycle internally. Install `neo4j-rust-ext` for 3-10x driver speedup.

4. **Neo4j write deadlocks on hot nodes (CRITICAL)** -- High-influence agents (Whales, Quants) become contention points during concurrent INFLUENCED_BY edge creation. Prevention: batch all edge writes for a round into a single UNWIND transaction, separate read and write phases (all agents read in parallel, then one batch write).

5. **asyncio task garbage collection drops agents silently (CRITICAL)** -- `create_task()` without stored references allows GC to destroy running tasks. Prevention: use `asyncio.TaskGroup` for all agent batch processing, or store task references in a set with done callbacks.

6. **Echo chamber effect (MODERATE)** -- Agents converge to homogeneous consensus by Round 3 if prompts are insufficiently differentiated. Prevention: per-archetype temperature variance (Degens at 1.2, Suits at 0.3), explicit contrarian constraints in Doom-Poster prompts, diversity metric monitoring with standard deviation threshold.

7. **psutil reports misleading memory on Apple Silicon (MODERATE)** -- Unified memory architecture breaks traditional available/used memory semantics. Prevention: supplement psutil with macOS `memory_pressure` command, Ollama `/api/ps` endpoint, and swap usage monitoring as the true pressure signal.

## Implications for Roadmap

Based on combined research across all four dimensions, the simulation has clear dependency chains that dictate build order. The architecture research and pitfalls research strongly agree on a foundation-first, headless-engine-second, TUI-third approach.

### Phase 1: Foundation and Infrastructure

**Rationale:** Every other component depends on the project scaffold, configuration system, type definitions, and the two critical infrastructure components (ResourceGovernor and GraphStateManager). These must be built and tested in isolation before the simulation engine exists. The memory budget pitfall (Pitfall 1) and Neo4j session safety (Pitfall 4) are Phase 1 killers that must be addressed in the infrastructure layer.

**Delivers:** Project scaffold with uv, Pydantic config/settings, all type definitions (AgentPersona, SeedEvent, AgentDecision, BracketType), Ollama AsyncClient wrapper with standardized num_ctx via Modelfiles, Neo4j Docker setup with schema/indexes, GraphStateManager with session-per-coroutine and UNWIND batch writes, ResourceGovernor with token-pool pattern and psutil + macOS memory_pressure monitoring, 100 agent persona definitions across 10 brackets.

**Addresses features:** Resource/memory management, configurable agent types (definitions only), structured output schemas, agent decision logging (persistence layer).

**Avoids pitfalls:** Memory budget arithmetic (#1), context size mismatch (#2), Ruflo incompatibility (#3), AsyncSession sharing (#4), write deadlocks (#6), psutil inaccuracy (#9), composite index partial match (#13), Python version pinning (#15).

### Phase 2: Core Simulation Engine (Headless)

**Rationale:** The 3-round cascade is the core product. Building it headless (CLI-driven, no TUI) allows focused debugging of the inference pipeline, prompt engineering, and graph state management without UI complexity. The echo chamber pitfall (Pitfall 11) must be detected and mitigated here through prompt engineering iteration. The asyncio task GC pitfall (Pitfall 5) and semaphore permit leak (Pitfall 8) surface during batch inference.

**Delivers:** SeedInjector with entity extraction, AgentPool with batched inference dispatch, SimulationEngine 3-round state machine, structured output parsing with Pydantic validation, dynamic influence topology (INFLUENCED_BY edge creation from citation patterns), bracket-level sentiment aggregation, CLI entry point that runs a full simulation and writes results to Neo4j.

**Addresses features:** Seed rumor injection, entity extraction, heterogeneous agent personas, 3-round consensus cascade, async concurrent execution, Neo4j persistence, structured output parsing, dynamic influence topology, bracket-level aggregation.

**Avoids pitfalls:** Task GC Heisenbug (#5), semaphore permit leak (#8), echo chamber effect (#11), TaskGroup cancellation (#12), Ollama queue saturation (#14).

### Phase 3: TUI Dashboard

**Rationale:** The TUI depends on a working simulation engine and StateStore. Building it after the headless engine is stable avoids the trap of debugging inference logic through a UI layer. The snapshot-based architecture (200ms tick) must be the only data path from simulation to UI -- this is a hard architectural constraint from Pitfall 7.

**Delivers:** StateStore with immutable snapshot production, Textual app shell with CSS layout, 10x10 AgentGrid widget with color-coded sentiment cells, RationaleSidebar with streaming rationale log, TelemetryFooter with RAM/TPS/queue depth, wiring between SimulationEngine and StateStore.

**Addresses features:** Real-time TUI dashboard, bracket-level aggregate display, hardware telemetry visualization.

**Avoids pitfalls:** Per-agent UI update freeze (#7), event loop starvation from direct widget updates.

### Phase 4: Polish, Replay, and Miro Visualization

**Rationale:** These features add analytical depth and external integration but do not affect the core simulation loop. Miro's credit-based rate limiting (Pitfall 10) requires careful batcher implementation that should not block the core product. Replay leverages data already stored in Neo4j from Phase 2.

**Delivers:** Simulation replay from stored Neo4j state (re-render without re-inference), exportable markdown/HTML simulation reports, MiroBatcher with credit-aware rate limiting (parse X-RateLimit headers), Miro board export of final-round influence topology, mid-simulation shock injection (optional Round 2 event parameter).

**Addresses features:** Simulation replay/time-travel, exportable reports, Miro network visualization, prompt injection for scenario variants.

**Avoids pitfalls:** Miro credit-based rate limiting (#10).

### Phase Ordering Rationale

- **Foundation before engine:** ResourceGovernor and GraphStateManager are dependencies for every inference call. Building them first with mock loads allows isolated testing of the memory and concurrency subsystems that are the project's primary technical risk.
- **Headless engine before TUI:** Debugging LLM output quality, prompt engineering, and graph state correctness is dramatically easier without a UI layer. The CLI milestone provides a fully functional simulation that can be validated with Neo4j Browser queries.
- **TUI as separate phase:** The snapshot architecture creates a clean boundary. The TUI reads from StateStore and has zero knowledge of agents, Ollama, or Neo4j. This separation is both an architectural pattern and a development strategy.
- **Miro and polish last:** These are additive features with external API dependencies. The core product (simulation + TUI) must be solid before introducing rate-limited external integrations.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 1 (ResourceGovernor):** The psutil-on-Apple-Silicon issue (Pitfall 9) requires empirical calibration. The memory_pressure command output format and Ollama /api/ps response schema need verification during implementation. Recommend `/gsd:research-phase` for this component.
- **Phase 2 (Prompt Engineering):** The echo chamber mitigation strategy (per-archetype temperatures, contrarian biases, diversity metrics) is theoretically sound but requires empirical tuning with actual LLM outputs. Research cannot substitute for experimentation here. Recommend iterative testing with small agent counts (10-20) before scaling to 100.
- **Phase 4 (Miro Integration):** The credit-based rate limiting tiers and bulk create API (up to 20 items per call) need API-level research during Phase 4 planning. Deferred and well-contained.

Phases with standard patterns (skip research-phase):
- **Phase 1 (Neo4j setup, Pydantic models, project scaffold):** Well-documented, verified library versions, standard patterns.
- **Phase 3 (Textual TUI):** Textual's Worker API, reactive attributes, and CSS layout are thoroughly documented. The snapshot pattern is well-established.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All library versions verified on PyPI. Model tag corrections verified against Ollama model library. Ruflo incompatibility confirmed via GitHub repo. Memory budget arithmetic cross-referenced against multiple Apple Silicon benchmark sources. |
| Features | HIGH | 8 comparable systems surveyed (TradingAgents, StockSim, TwinMarket, MiroFish-Offline, OASIS, AlphaAgents, FCLAgent, ScaleSim). Table stakes and differentiators validated against field. Anti-features list well-justified. |
| Architecture | HIGH | Pipeline-with-feedback-loop pattern verified against OASIS and TwinMarket architectures. Neo4j async patterns verified against official driver docs. Textual snapshot pattern verified against Textualize blog posts and docs. |
| Pitfalls | HIGH | 15 pitfalls identified, 6 critical. Memory budget arithmetic, Ollama context reload behavior, Neo4j session safety, and asyncio task GC are all documented in official sources. Apple Silicon memory monitoring (Pitfall 9) is MEDIUM confidence -- requires empirical validation. |

**Overall confidence:** HIGH

### Gaps to Address

- **Empirical memory calibration:** The memory budget analysis is theoretical. Actual M1 Max 64GB behavior under dual-model load with 8-16 parallel slots must be measured during Phase 1 development. The Metal GPU memory ceiling (75% default) and the `sysctl iogpu.wired_limit_mb` override need hands-on verification.
- **Prompt engineering for diversity:** The echo chamber mitigation strategies (per-archetype temperatures, contrarian biases) are based on general multi-agent LLM research, not AlphaSwarm-specific testing. Phase 2 must include systematic prompt testing with diversity metrics before scaling to 100 agents.
- **Ollama batch API:** Ollama has an open discussion about a native batch API (GitHub #10699). If released during development, it could simplify the semaphore-based batching approach. Monitor this.
- **Sequential vs dual model loading performance:** The recommended dual-load strategy (llama3.1:8b + qwen3.5:4b) trades orchestrator quality for convenience. The sequential strategy (llama3.3:70b swapped with qwen3.5:4b) adds 30-45s cold-load penalty per phase transition. The right choice depends on empirical orchestrator quality assessment -- does the 8B model produce acceptable entity extraction?
- **httpx version:** httpx 0.28.x version not directly confirmed via PyPI (search blocked during research). Verify at install time.

## Sources

### Primary (HIGH confidence)
- [Ollama Python library on PyPI (v0.6.1)](https://pypi.org/project/ollama/) -- AsyncClient API
- [Ollama model library - Llama 4](https://ollama.com/library/llama4) -- model variants and sizes
- [Ollama model library - Qwen 3.5](https://ollama.com/library/qwen3.5) -- model variants and sizes
- [Neo4j Python driver on PyPI (v6.1.0)](https://pypi.org/project/neo4j/) -- async driver
- [Neo4j concurrency documentation](https://neo4j.com/docs/python-manual/current/concurrency/) -- session safety
- [Neo4j concurrent data access](https://neo4j.com/docs/operations-manual/current/database-internals/concurrent-data-access/) -- deadlock behavior
- [Textual on PyPI (v8.1.1)](https://pypi.org/project/textual/) -- TUI framework
- [Textual Workers guide](https://textual.textualize.io/guide/workers/) -- async patterns
- [Pydantic on PyPI (v2.12.5)](https://pypi.org/project/pydantic/) -- data validation
- [psutil on PyPI (v7.2.2)](https://pypi.org/project/psutil/) -- system monitoring
- [structlog on PyPI (v25.5.0)](https://pypi.org/project/structlog/) -- structured logging
- [Ruflo GitHub (Node.js)](https://github.com/ruvnet/ruflo) -- confirms incompatibility
- [Miro API rate limiting](https://developers.miro.com/reference/rate-limiting) -- credit tiers
- [Ollama FAQ](https://docs.ollama.com/faq) -- parallel config, memory
- [TradingAgents (GitHub)](https://github.com/TauricResearch/TradingAgents) -- comparable system
- [TwinMarket (arXiv)](https://arxiv.org/abs/2502.01506) -- comparable system, ICLR 2025
- [MiroFish-Offline (GitHub)](https://github.com/nikmcfly/MiroFish-Offline) -- comparable system with Neo4j + Ollama
- [StockSim (GitHub)](https://github.com/harrypapa2002/StockSim) -- comparable system
- [Ollama parallel request handling](https://www.glukhov.org/post/2025/05/how-ollama-handles-parallel-requests/) -- batching internals

### Secondary (MEDIUM confidence)
- [ScaleSim (arXiv)](https://arxiv.org/html/2601.21473) -- memory management for multi-agent LLM serving
- [OASIS (GitHub)](https://github.com/camel-ai/oasis) -- 1M agent simulation architecture (social media focused)
- [Apple Silicon LLM benchmarks](https://github.com/ggml-org/llama.cpp/discussions/4167) -- M1/M3 performance data
- [psutil macOS issues (GitHub #1908)](https://github.com/giampaolo/psutil/issues/1908) -- VMS reporting
- [Multi-agent LLM failure modes (arXiv:2503.13657)](https://arxiv.org/html/2503.13657v1) -- echo chamber research
- [AlphaAgents (arXiv)](https://arxiv.org/abs/2508.11152) -- BlackRock multi-agent portfolio construction
- [FCLAgent (arXiv)](https://arxiv.org/abs/2510.12189) -- Fundamental-Chartist-LLM agent simulation

### Tertiary (LOW confidence)
- httpx 0.28.x version -- not directly confirmed, verify at install
- Ollama batch API (GitHub #10699) -- feature discussion, not yet released

---
*Research completed: 2026-03-24*
*Ready for roadmap: yes*
