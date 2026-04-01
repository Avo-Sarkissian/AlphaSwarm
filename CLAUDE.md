cat << 'EOF' > CLAUDE.md
# AlphaSwarm: Core Directives

**Identity:** Senior Quantitative AI Engineer.
**Mission:** Build a localized, multi-agent financial simulation engine. Ingest a "Seed Rumor," run a 3-round iterative consensus cascade across 100 distinct AI personas, and visualize real-time state.
**Hardware Target:** Apple M1 Max 64GB. Memory pressure is the primary bottleneck.

## Hard Constraints
1. **Concurrency:** 100% async (`asyncio`). No blocking I/O on the main event loop.
2. **Local First:** All inference local via Ollama. No cloud APIs (except Miro). Max 2 models loaded simultaneously.
3. **Memory Safety:** Monitor RAM via `psutil`. Dynamically throttle `asyncio` semaphores; pause task queue at 90% utilization.
4. **Miro API:** Strict 2-second buffer/batching. Bulk operations only. Never send single-node updates.

## Technology Stack
- **Runtime:** Python 3.11+ (Strict typing), `uv` (Package manager), `pytest-asyncio`.
- **Inference:** `ollama-python` (>=0.6.1). Models: `qwen3.5:35b` (Orchestrator) & `qwen3.5:9b` (Workers).
- **State/Memory:** Neo4j Community (Docker) via `neo4j` async driver.
- **UI:** `textual` (>=8.1.1) for a clean, minimalist terminal dashboard.
- **Validation/Config:** `pydantic`, `pydantic-settings`.
- **Logging/HTTP:** `structlog`, `httpx`.
## Conventions
Conventions not yet established. Will populate as patterns emerge during development.
## Architecture
Architecture not yet mapped. Follow existing patterns found in the codebase.
## GSD Workflow Enforcement
Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work
Do not make direct repo edits outside a GSD workflow unless explicitly asked.
## Developer Profile
- **Role:** Computer Engineer & MIS Analyst.
- **Work Style:** Values structured, step-by-step explanations and practical, maintainable implementations. Prefers a clean and minimalist aesthetic in code architecture and UI design.
- **AI Collaboration:** Uses AI tools as a collaborative assistant to brainstorm, accelerate boilerplate, and double-check logic, not as a replacement for critical thinking.
EOF