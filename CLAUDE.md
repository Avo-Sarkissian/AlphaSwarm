# AlphaSwarm: Core Directives

**Identity:** Senior Quantitative AI Engineer.
**Mission:** Build a local-first, multi-agent financial simulation engine. Ingest a "Seed Rumor," run a multi-round consensus cascade (default 3 rounds, `ALPHASWARM_NUM_ROUNDS=2|3`) across 100 distinct AI personas, and visualize real-time state through a web UI.
**Hardware Target:** Apple M1 Max 64GB. Memory pressure is the primary bottleneck.

## Hard Constraints

1. **Concurrency:** 100% async (`asyncio`). No blocking I/O on the main event loop.
2. **Local First:** Inference runs on the local Ollama server by default, with zero configuration. Cloud providers (OpenAI-compatible, Anthropic) are strictly opt-in through the Settings UI / `.secrets/inference.json`. Never make cloud the default; never commit or log API keys. Max 2 Ollama models loaded simultaneously.
3. **Memory Safety:** Monitor RAM via `psutil` plus macOS kernel memory pressure. Dynamically throttle `asyncio` semaphores; pause the task queue at 90% utilization. (In cloud mode the rate-limit controller replaces the memory governor.)
4. **WebSocket Cadence:** Broadcaster emits snapshots at ~5Hz. Drop-oldest backpressure on per-client queues. Never block the simulation loop on slow clients.
5. **Holdings Isolation:** Portfolio data never enters swarm prompts, Neo4j, WebSocket frames, or logs. Only `alphaswarm.advisory` and `alphaswarm.web.routes.{holdings,advisory}` may import `alphaswarm.holdings`. Enforced by import-linter (pre-commit hook, and via `tests/invariants/`) plus a sentinel canary test. `Schwab/` holds the owner's real brokerage CSVs: never commit, quote, or copy values from it into code, tests, or docs. Use fictional fixtures.

## Technology Stack

- **Runtime:** Python 3.11+ (strict typing), `uv` (package manager), `pytest-asyncio`.
- **Inference:** `ollama-python` (>=0.6.1) against local Ollama with the MLX backend (`OLLAMA_USE_MLX=1`). Code calls the aliases `alphaswarm-orchestrator` (qwen3.6:27b-nvfp4) and `alphaswarm-worker` (qwen3.6:35b-a3b-nvfp4), built from `modelfiles/`. Optional cloud adapters sit behind the `InferenceProvider` protocol in `src/alphaswarm/inference/`.
- **State / Memory:** Neo4j Community 5.26 (Docker, loopback only) via the async `neo4j` driver (<6.0).
- **Market data:** `yfinance` and RSS (`feedparser` + `httpx`) providers in `src/alphaswarm/ingestion/`. They never raise; failures become `fetch_failed` slices.
- **Web Backend:** FastAPI + `uvicorn`, native WebSocket support, `httpx` for outbound calls.
- **Web Frontend:** React + TypeScript, Vite build, D3 (d3-scale/selection/transition) for visualization primitives; deterministic SVG layout for the 100-agent "mirofish" graph (`docs/DECISIONS.md#kr-41-1-01` explains why d3-force was dropped).
- **Validation / Config:** `pydantic`, `pydantic-settings`.
- **Logging:** `structlog`, with a fail-closed PII redaction processor.
- **Testing:** pytest with `pytest-socket` (network off by default; `tests/integration/` opts in by path, the `neo4j` marker opts in), `pytest-timeout` (60 s per test) and `hypothesis`; golden files under `tests/golden/`; vitest in `frontend/src/__tests__/` (node for pure tests; happy-dom + React Testing Library for hooks and components) and ESLint (`npm run lint`); golden WebSocket frames written by `tests/test_wire_contract.py` into `frontend/src/__tests__/fixtures/`.

## Swarm Composition (v2, 2026-06-10)

The 100-agent swarm models the **active price-setting margin of the narrative
ecosystem** — who forms and propagates opinions about a rumor — NOT raw AUM or
dollar volume. Two exclusions are deliberate; do not "fix" them:

- **Passive/index capital** is excluded: it never reacts to rumors by definition.
- **Market makers / vol desks** are excluded: their honest reaction ("vol up,
  quote both sides") doesn't fit the buy/sell/hold ontology.

The 10 brackets (counts/weights in `config.py:DEFAULT_BRACKETS`, rationale in
`types.py:BracketType` docstring): Institutions 18, Sell-Side 10, Event-Driven
10, Quants 12, Degens 15, Narrators 8, Algos 8, Macro 7, Shorts 7, Allocators 5.
`influence_weight_base` represents narrative REACH (peer visibility), not
capital — Sell-Side and Narrators rank highest by design. Action-bias mix is
deliberate: 4 hold-biased, 4 act-biased, 1 sell-biased, 1 second-order.

## Architecture

Full map: `docs/ARCHITECTURE.md`. In short:

- **Composition roots:** `cli.py` (`inject | run | report | web`), `app.py` (`AppState`), `web/app.py` (FastAPI lifespan: builds AppState and the managers, starts the 5 Hz broadcaster).
- **Engine:** `seed.py` (orchestrator parses the rumor → Cycle + Entities) → `simulation.py` (`run_simulation`: rounds, in-memory diverse peer selection, influence edges, narratives, metrics) → `batch_dispatcher.py` (TaskGroup of 100 jittered agent calls) → `worker.py` (schema-constrained decision) → `parsing.py` (3-tier fallback).
- **Concurrency:** `governor.py` + `memory_monitor.py` locally; `inference/rate_limit.py` for cloud. Both implement `inference/concurrency.py:ConcurrencyController`.
- **Inference:** `inference/` (provider protocol, Ollama/OpenAI-compatible/Anthropic adapters, budget, factory) on top of `ollama_client.py` / `ollama_models.py`.
- **Persistence:** `graph.py` (GraphStateManager: schema, writes, report/replay/interview queries). Graph model is in `docs/ARCHITECTURE.md`.
- **Post-run:** `advisory/` (portfolio synthesis), `report.py` + `templates/report/` (ReAct → markdown), `interview.py`.
- **Live state:** `state.py` (StateStore/ReplayStore) → `web/wire.py` (`build_frame` → versioned `StateFrame`) → `web/broadcaster.py` → `/ws/state` → `frontend/src/hooks/useWebSocket.ts` → `adapter/frame.ts` → React contexts (`FrameProviders`, including `FrameMetaContext`) → SVG graph.

## Conventions

- **Python:** `from __future__ import annotations`; heavy or cyclic imports under `if TYPE_CHECKING:`. Ruff line length 100.
- **Data models:** frozen pydantic models at LLM/ingestion boundaries (AgentDecision, SeedEvent, ingestion slices); frozen dataclasses for internal value objects; TypedDict for chat messages. Settings via pydantic-settings, prefix `ALPHASWARM_`, `__` for nesting.
- **Async:** fan-out with `asyncio.TaskGroup` (no bare `create_task` in the engine). Long-running jobs use `create_task` with a strong-reference set and a done-callback. Blocking I/O goes through `asyncio.to_thread` or aiofiles. Loop-bound objects are created inside the FastAPI lifespan. Seams are Protocols.
- **Logging:** `log = structlog.get_logger(component="<area>")`. Event names are snake_case past tense (`decisions_written`) with scalar key/value context. Never log holdings objects; log counts or hashes.
- **Errors:** domain exceptions live in `errors.py`. Routes raise `HTTPException(status, detail={"error": "<snake_code>", "message": ...})`: 409 for state conflicts, 503 for unavailable services, 400 for bad ids. `AuthError` and `BudgetExceededError` are never swallowed.
- **Neo4j:** a public `async def read_*/write_*` method plus a `@staticmethod async def _<verb>_tx(tx, ...)`. Batch writes use `UNWIND $rows`, schema statements use `IF NOT EXISTS`, and signals are stored lowercase.
- **LLM calls:** prompts are lists of `InferenceMessage` dicts. The worker decodes against a JSON schema; orchestrator calls use `json_mode=True` plus tiered parse fallbacks. Untrusted text (RSS headlines, peer rationales) is sanitized and fenced, and never placed in the system role.
- **Comments:** cite `docs/DECISIONS.md#<anchor>` for design rationale. Legacy bare IDs (`D-xx`, `KR-…`, `F-xx`) are indexed there by file and line. Replace them with anchors when you next touch the comment.
- **Tests:** `asyncio_mode=auto`; sockets are disabled globally (`@pytest.mark.enable_socket` opts in). An autouse `hermetic_env` fixture clears `ALPHASWARM_*`, ignores `.env`, and points the inference config and holdings CSV at temp paths; env-clearing helpers must use `clear_alphaswarm_env`. Neo4j tests live in `tests/neo4j/` with `pytestmark = pytest.mark.neo4j` and read one deterministic, fictional 100-agent cycle (`seeded_cycle`). Shared helpers live in `tests/support/` (`golden.py`, `seed_builder.py`, `aio.py`, `controllers.py`); fakes, including the deterministic `ScriptedProvider`, are in `tests/inference/fakes.py`; `tests/engine/` runs the real `run_simulation` on scripted fakes with zero real sleeps; architectural invariants are in `tests/invariants/`. Known bugs are pinned with `xfail(strict=True, reason="<item id>: …")` (`docs/DECISIONS.md#adr-engine-scenario-harness`).
- **Commits:** Conventional Commits with a scope (`fix(security): …`, `feat(inference): …`), an imperative summary, and an explanatory body.

## Gotchas

- Start the backend from the repo root: `.env`, `Schwab/holdings.csv`, `.secrets/`, `advisory/`, and `reports/` are all resolved relative to the working directory.
- Ollama must run with `OLLAMA_USE_MLX=1`, or the nvfp4 models silently fall back to slow llama.cpp. When a simulation is suddenly slow, check the server env first (`docs/RUNBOOK.md` §1).
- Orchestrator calls pass `think=False`. Output caps (`num_predict`) and `num_ctx` live in the Modelfiles, not in per-request options.
- Tests never touch the dev database. Neo4j tests run against the throwaway `neo4j-test` container on 127.0.0.1:7688 (`scripts/neo4j_test.sh up`); its session fixture refuses port 7687 and non-empty databases, and its teardown is the only unscoped `DETACH DELETE` allowed (`docs/DECISIONS.md#adr-tests-scoped-cleanup`). Start and stop it only with `scripts/neo4j_test.sh`: a bare `docker compose --profile test down` also removes the dev container, and any `compose down` deletes the project network a stopped dev container needs.
- The repo lives at `~/dev/AlphaSwarm`, outside iCloud Drive (moved 2026-10). If `* 2.py`-style conflict copies ever appear, they are gitignored and skipped by pytest; delete them, don't "fix" tests they break.

## Project Docs

- `docs/ARCHITECTURE.md`: components, modules, data flow, and the graph model.
- `docs/DECISIONS.md`: why things are the way they are, with stable anchors for code comments.
- `docs/BACKLOG.md`: open defects, cleanup items, experiments, and unsigned UAT, each with evidence. Update it when an item closes.
- `docs/RUNBOOK.md`: Ollama env and LaunchAgent, MLX check, model builds, Neo4j backup/restore, the smoke checklist, troubleshooting.
- `docs/HISTORY.md`: milestones, pivots, and lessons.

## Workflow

- Plain git: branch off `master`, make small Conventional Commits, open PRs. Don't recreate a `.planning/` directory or any planning-framework scaffolding.
- Write a short markdown plan in `docs/` only when a change is big enough to need one.
- Before calling work done (CI's `lint`, `backend`, `backend-neo4j` and `frontend` jobs run the gated checks):
  - `uv run pytest -q -m "not neo4j"` is green (run from the repo root; same selection as CI `backend`);
  - after touching `graph.py`, report templates or read models: `scripts/neo4j_test.sh up && uv run pytest -q -m neo4j --require-neo4j`, then `scripts/neo4j_test.sh down`;
  - `uv run mypy src` reports no errors (gated in CI; modules under `[[tool.mypy.overrides]]` stay exempt until cleaned up, the list only shrinks, never add one);
  - `uv run lint-imports` reports the contract kept;
  - `uv run vulture src vulture_whitelist.py --min-confidence 80` is clean (gated in CI; whitelist only names an interface requires, never dead code);
  - `uv run ruff check <changed files>` is clean on the lines you changed (ruff is not yet gated in CI);
  - for frontend changes, run `npx tsc -b --noEmit && npx vitest run && npm run lint && npm run build` in `frontend/`.
- Golden files in `tests/golden/` change only in a commit whose purpose explains the diff: `UPDATE_GOLDEN=1 uv run pytest -q -m neo4j --require-neo4j tests/neo4j/` (scenario goldens in `tests/golden/scenarios/`: `UPDATE_GOLDEN=1 uv run pytest -q tests/engine/`, no services), then review `git diff tests/golden` line by line.

## Developer Profile

- **Role:** Computer Engineer & MIS Analyst.
- **Work Style:** Values structured, step-by-step explanations and practical, maintainable implementations. Prefers a clean and minimalist aesthetic in code architecture and UI design.
- **AI Collaboration:** Uses AI tools as a collaborative assistant to brainstorm, accelerate boilerplate, and double-check logic, not as a replacement for critical thinking.
