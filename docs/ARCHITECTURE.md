# AlphaSwarm Architecture

A map of the system as of commit `820b8fe` (2026-10-03). For *why* things are
built this way, see [DECISIONS.md](DECISIONS.md). For how to run it, see
[RUNBOOK.md](RUNBOOK.md).

## Runtime components

| Component | Where | Role |
|---|---|---|
| FastAPI + uvicorn | `alphaswarm.web.app:create_app`, bound to 127.0.0.1:8000 (`start` script → `cli.main_web`) | REST `/api/*`, WebSocket `/ws/state`, and the built `frontend/dist` when present |
| Simulation task | `web/simulation_manager.py` → `simulation.run_simulation` | One background asyncio task per run, held under an `asyncio.Lock` for its whole lifetime |
| Broadcaster | `web/broadcaster.py` + `web/wire.py` + `web/connection_manager.py` | ~5 Hz task: `StateStore.snapshot()` (or the replay store's) → `build_frame` → versioned `StateFrame` JSON → one `Queue(maxsize=100)` per client, dropping the oldest frame when full |
| Ollama (MLX) | `localhost:11434`, `modelfiles/` | Aliases `alphaswarm-orchestrator` (qwen3.6:27b-nvfp4) and `alphaswarm-worker` (qwen3.6:35b-a3b-nvfp4); `OllamaModelManager` loads and unloads them one at a time |
| Optional cloud LLMs | `.secrets/inference.json` (Settings UI) | OpenAI-compatible or Anthropic, chosen per role, wrapped in `BudgetTrackingProvider` and throttled by `RateLimitController` |
| Neo4j 5.26 | `docker-compose.yml`, bolt on `127.0.0.1:7687` | Durable graph of cycles, decisions, episodes, and influence |
| External data | yfinance, Google/Yahoo RSS | Round 1 market context (prices and headlines) |
| Files | `reports/`, `advisory/`, `Schwab/holdings.csv` | Report markdown, advisory JSON, holdings input (gitignored). Paths resolve against the repo root. |
| React SPA | `frontend/` (Vite, TypeScript, React-rendered SVG, d3-scale) | Live dashboard, deterministic SVG agent graph, replay, interview, report and advisory modals, settings |

## Modules (`src/alphaswarm/`)

- **Entry points and composition**
  - `__main__.py`, `cli.py`: subcommands `inject | run | report | web`. `run` takes `--context-fixture PATH` (a point-in-time ContextPacket replaces the live fetch) or `--no-market-context` (no market block); either way no yfinance or RSS provider is built.
  - `app.py`: `AppState`, a container for the settings, StateStore, ResourceGovernor, Ollama client and model manager, GraphStateManager, and the market and news providers, plus `create_app_state()`.
  - `web/app.py`: the lifespan. It builds AppState, the Simulation, Replay, and Connection managers and the `PostRunPipeline`, loads the holdings into `PortfolioCache`, and starts the broadcaster.
- **Domain and config**
  - `types.py`: enums, BracketConfig, AgentPersona, SeedEvent, AgentDecision.
  - `config.py`: settings, inference-config persistence, origin constants, prompt templates, sanitizers, `DEFAULT_BRACKETS`, `generate_personas`, `generate_modifiers`.
  - `errors.py`: exception types.
- **Engine**
  - `seed.py`: `inject_seed`. The orchestrator parses the seed, then one atomic write creates the Cycle and its Entities, then persona modifiers are generated.
  - `simulation.py`: `run_simulation`, `run_round1`, peer selection, the control holdout and own-prior lines, shifts, bracket summaries, narratives.
  - `metrics.py`: pure measurement functions; `split_flips` splits a round's flips between the control holdout and the treated readers.
  - `batch_dispatcher.py`: `dispatch_wave`, a TaskGroup of 100 jittered inferences.
  - `worker.py`: `AgentWorker`, the decision JSON schema, and the fence for untrusted market data.
  - `parsing.py`: 3-tier parsers.
  - `write_buffer.py`: `EpisodeRecord`, `compute_flip_type`.
  - `context_formatter.py`, `utils.py`.
- **Concurrency**
  - `governor.py`: ResourceGovernor / TokenPool state machine.
  - `memory_monitor.py`: psutil plus macOS sysctl memory pressure.
  - `inference/concurrency.py`: ConcurrencyController protocol.
  - `inference/rate_limit.py`: the cloud controller.
- **Inference**
  - `ollama_client.py`: backoff, plus the rule that `num_ctx` is never sent per request.
  - `ollama_models.py`: model load and unload.
  - `inference/`: provider protocol and types; the `ollama_provider`, `openai_provider`, and `anthropic_provider` adapters; `schema` (structured-output translation per vendor); `budget`; `factory` (`build_providers`, `build_controller`, `inference_mode`).
- **Persistence**
  - `graph.py`: GraphStateManager. It covers schema, writes, influence edges, cycle status, and the report, replay, and interview queries.
  - `fsutil.py`: `atomic_write_text`, the all-or-nothing writer for report and advisory files.
- **Ingestion**
  - `ingestion/`: MarketDataProvider and NewsProvider protocols with fakes, the yfinance and RSS providers, and frozen pydantic slices. Providers never raise.
- **Post-run features**
  - `report.py` + `templates/report/*.j2`: the ReAct engine and the Jinja assembler.
  - `interview.py`: a multi-turn engine with a 10-turn window plus a summary.
  - `advisory/`: synthesis, prompt, sector map, types.
  - `holdings/`: CSV loader and types. Only `advisory` and `web.routes.{holdings,advisory}` may import it; import-linter enforces this.
- **State and observability**
  - `state.py`: StateStore, ReplayStore, snapshot dataclasses.
  - `data_audit.py`.
  - `readiness.py`: bounded Neo4j, Ollama and model-alias probes (1 s timeouts, never raising) shared by `/api/health`; each returns a `ComponentStatus` that names the fix for a failure (a password error is told apart from a stopped database).
  - `logging.py`: structlog plus the fail-closed PII redaction processor.
  - `security/hashing.py`.
- **Web**
  - `web/`: `simulation_manager`, `replay_manager`, `post_run` (PostRunPipeline), `guards` (shared route guards), `errors` (the error envelope and handlers), `params` (validated input types), `broadcaster`, `wire` (the versioned `StateFrame` and its mapper), `connection_manager`, and `origin_guard` (a CSRF Origin guard).
  - `web/routes/`: health (component readiness, cached 5 s, plus `/api/health/live`), simulation (start/stop/shock), edges, replay, interview, holdings, report, advisory, settings, websocket, agents (per-agent decision history).
- **Evaluation**
  - `evaluation.py`: eval records, outcome labels and forecast scoring (pure; `docs/DECISIONS.md#adr-eval-harness`).
  - `ingestion/fixture.py`: point-in-time `ContextPacket` fixtures for `alphaswarm run --context-fixture`.
  - Repo-root `eval/`: the `build_fixtures`, `label_outcomes` and preliminary `pilot` scripts. They read `eval/events.jsonl` and `eval/headlines/`, and write the committed `eval/fixtures/` and the gitignored `eval/results/` (labels, pilot state).

## Data flow: seed → rounds → graph → web → UI

1. **Start.** `POST /api/simulate/start {seed}` reaches `SimulationManager.start`, which refuses with 409 while a replay is active or post-run jobs hold the orchestrator (`post_run_jobs_in_progress`), then takes the lock, clears interview sessions and the previous run's `StateStore.last_error`, and calls `_run`. `_run` loads the InferenceConfig (or the local defaults) and builds:
   - providers with `build_providers`: Ollama, or budget-wrapped cloud providers;
   - a controller with `build_controller`: ResourceGovernor locally, RateLimitController for cloud.

   Then it calls `run_simulation`.
2. **Seed.** `inject_seed` runs these steps:
   - `orchestrator.prepare`, then a JSON-mode chat;
   - `parse_seed_event`;
   - `create_cycle_with_seed_event`, which writes Cycle, Entity, and MENTIONS;
   - `generate_modifiers`.

   Then `generate_personas` builds 100 prompts. Each one is a bracket template plus a round-robin modifier, a per-cycle focus line, and the JSON instructions.
3. **Market context (Round 1 only).** Ticker-shaped entities go to `asyncio.gather(yfinance.get_prices, rss.get_headlines)`. The results become a ContextPacket, which `format_market_context` turns into one block, fenced as untrusted data inside the user message. A point-in-time run (`run --context-fixture`) skips the fetch: its fixture packet goes straight to `format_market_context`, and supplied providers are never called.
4. **Round 1.** `dispatch_wave` runs 100 tasks. Each one waits out its jitter, calls `controller.acquire`, then `AgentWorker.infer` (schema-constrained decode, per-bracket temperature), then `parse_agent_decision`. Results stream into the StateStore as they finish. Then:
   - the round-abort check (`RoundFailedError` when more than `round_abort_failure_percent` of agents failed);
   - `write_decisions` (plus CITED edges);
   - RationaleEpisode and REFERENCES records;
   - bracket summaries.
5. **Rounds 2..N.** Before each later round, a shock queued while the shock window was open is consumed; every applied shock is appended to all later rounds' user message (oldest first) and recorded on the StateStore. Peer contexts are built in memory, per reader, by `_build_diverse_peer_contexts`:
   - each candidate's weight is base reach plus global citation share, plus `SimulationSettings.personal_boost` (0.3) if the reader cited that agent last round;
   - `select_diverse_peers` samples peers by weight with a per-reader `peer_rng(cycle_id, reader, round)`: at least 4 brackets, at most 3 peers per bracket, shuffled display order;
   - the builder returns each reader's rendered peer ids, which `run_simulation` stamps on the Cycle as `r{n}_exposure_*` metrics next to the run provenance (models, provider mode, git SHA).

   Each reader's user message then starts with its own previous decision (`own_prior_memory`, default on), and the seeded control holdout (`control_fraction`, default 0.0, so nobody) loses its peer context before the exposure metrics are counted; holdout decisions are stored with `d.control = true`, and the cycle metrics split the round's flips into control and treated.

   The round is then dispatched, checked against the same round-abort rule, and persisted, and `compute_influence_edges` writes `INFLUENCED_BY {round, weight}`.
6. **Finalize.**
   - The phase becomes FINALIZING.
   - `_generate_decision_narratives`: 100 worker calls.
   - `write_cycle_metrics`.
   - The phase becomes COMPLETE.

   If anything in steps 1-6 fails instead (an invalid inference config, a hard stop, `RoundFailedError`, a Neo4j error), `SimulationManager._run` publishes a UI-safe `RunError` as `StateStore.last_error`, logs the exception once with its traceback, and resets the phase to IDLE. A cancelled run sets no error.
7. **Post-run pipeline.** `PostRunPipeline` runs the advisory when holdings are loaded (`PortfolioCache`) and allowed, writing `advisory/{id}_advisory.json`, then always the report (`reports/{id}_report.md`: the ReAct loop, up to 10 orchestrator calls over 8 graph tools, rendered through Jinja). Both write atomically; job status is in the StateStore.
8. **Live UI.**
   - The broadcaster sends a versioned `StateFrame` over `/ws/state`: `schema_version`, `mode`, `cycle_id`, `num_rounds`, `edges_version`, `jobs`, `last_error`, the shock fields, agent states, rationale entries with `seq`/`ts`, bracket summaries, the data-source audit, and governor metrics with the live host memory.
   - On the frontend, `useWebSocket` feeds `adapter/frame.ts`, which updates the React contexts (`FrameProviders`: Connection, FrameMeta, Telemetry, Agents, Rationales; plus Edges), which render the SVG graph.
   - Edges come over REST through one cached loader keyed by the frame's cycle_id, round and edges_version (EdgesContext). Report, advisory, replay and settings also come over REST.
9. **Replay.** ReplayManager loads a cycle's signals from Neo4j into a ReplayStore, and the broadcaster switches its snapshot source. No inference runs, and the live phase is left alone.
10. **Interview.** `POST /api/interview/{agent_id}` takes the request's `cycle_id` or the latest complete cycle, reads the agent's context with `read_agent_interview_context`, and runs InterviewEngine on the worker provider.

## Neo4j graph model

```
(:Agent {id, name, bracket, risk_profile, temperature, influence_weight_base, decision_narrative})
(:Cycle {cycle_id, seed_rumor, overall_sentiment, created_at, num_rounds, <metrics>, metrics_recorded_at})
    -[:MENTIONS {relevance, sentiment}]->(:Entity {name, type})
(:Agent)-[:MADE]->(:Decision {decision_id, cycle_id, round, signal, confidence, sentiment, rationale, control})-[:FOR]->(:Cycle)
(:Decision)-[:CITED]->(:Agent)
(:Decision)-[:HAS_EPISODE]->(:RationaleEpisode {rationale, peer_context_received, flip_type, round, cycle_id})
(:Decision)-[:REFERENCES]->(:Entity)
(:Agent)-[:AUTHORED]->(:Post)<-[:HAS_POST]-(:Decision)      # legacy: written, never read (BACKLOG 1.1)
(:Agent)-[:INFLUENCED_BY {weight, cycle_id, round}]->(:Agent)
(:Cycle)-[:HAS_SHOCK]->(:ShockEvent)
```

Signals are stored lowercase (`SignalType.value`). Schema statements (constraints
and indexes) live in `graph.py` `SCHEMA_STATEMENTS` and are applied by
`ensure_schema()`. That function also seeds the Agent nodes.
