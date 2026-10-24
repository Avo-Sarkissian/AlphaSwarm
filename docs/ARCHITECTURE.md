# AlphaSwarm Architecture

A map of the system as of commit `820b8fe` (2026-10-03). For *why* things are
built this way, see [DECISIONS.md](DECISIONS.md). For how to run it, see
[RUNBOOK.md](RUNBOOK.md).

## Runtime components

| Component | Where | Role |
|---|---|---|
| FastAPI + uvicorn | `alphaswarm.web.app:create_app` via `alphaswarm web` (uvicorn factory mode, `workers=1`, 127.0.0.1:8000; `./start` and `uv run start` call it) | REST `/api/*`, WebSocket `/ws/state`, and the built `frontend/dist` when present |
| Simulation task | `web/simulation_manager.py` → `simulation.run_simulation` | One background asyncio task per run, held under an `asyncio.Lock` for its whole lifetime; the server process holds the per-user instance lock (`instance_lock.py`) |
| Broadcaster | `web/broadcaster.py` + `web/wire.py` + `web/connection_manager.py` | ~5 Hz ticks: when a client is connected and the state version changed (or 1 s passed), `StateStore.snapshot()` (or the replay store's) → `build_frame` → versioned `StateFrame` JSON → one latest-wins `Queue(maxsize=1)` per client; nothing is serialized with no client; `broadcast_stats` logs counts per minute |
| Ollama (MLX) | `localhost:11434`, `modelfiles/` | Aliases `alphaswarm-orchestrator` (qwen3.6:27b-nvfp4) and `alphaswarm-worker` (qwen3.6:35b-a3b-nvfp4); `OllamaModelManager` loads and unloads them one at a time |
| Optional cloud LLMs | `.secrets/inference.json` (Settings UI) | OpenAI-compatible or Anthropic, chosen per role, wrapped in `BudgetTrackingProvider` and throttled by `RateLimitController` |
| Neo4j 5.26 | `docker-compose.yml`, bolt on `127.0.0.1:7687` | Durable graph of cycles, decisions, episodes, and influence |
| External data | yfinance, Google/Yahoo RSS | Market context (prices and headlines) for rounds 1..`market_context_rounds` |
| Files | `reports/`, `advisory/`, `Schwab/holdings.csv` | Report markdown, advisory JSON, holdings input (gitignored). Paths resolve against the repo root. |
| React SPA | `frontend/` (Vite, TypeScript, React-rendered SVG, d3-scale) | Live dashboard, deterministic SVG agent graph, replay, interview, report and advisory modals, settings |

## Modules (`src/alphaswarm/`)

- **Entry points and composition**
  - `__main__.py`, `cli.py`: subcommands `inject | run | report | web | doctor | cycles`; `inject`, `run`, `report` and `web` hold the instance lock (a held lock exits 75). `run` takes `--context-fixture PATH` (a point-in-time ContextPacket replaces the live fetch) or `--no-market-context` (no market block); either way the run gets no yfinance or RSS provider, so nothing is fetched. Every subcommand enters `services.runtime.open_runtime`; `report` runs `ReportService`, and `web` starts uvicorn in factory mode (`alphaswarm.web.app:create_app`, one worker). `report` takes the cycle id positionally or with `--cycle`. `cycles list|export|delete` manage stored cycles without a model ([adr-cycle-export](DECISIONS.md#adr-cycle-export)). Every subcommand runs through `_run_command`: command output on stdout, logs on stderr, exit codes 0/1/2/130, tracebacks only with `-v`; bare `alphaswarm` prints help ([adr-cli-ux](DECISIONS.md#adr-cli-ux)).
  - `doctor.py`: `alphaswarm doctor`, one read-only readiness report (Neo4j and its container, Ollama, the aliases, MLX on the running server, the launchctl env, foreign models, the UI build, the memory signal) built on `readiness.py`.
  - `instance_lock.py`: the per-user `flock` that keeps one AlphaSwarm process at a time (a second one exits 75).
  - `app.py`: `AppState`, a container for the settings, StateStore, ResourceGovernor, Ollama client and model manager, GraphStateManager, and the market and news providers, plus `create_app_state()`.
  - `services/`: `runtime` (`InferenceRuntime`, `Runtime`, `build_runtime`, `open_runtime`, `open_simulation`), `jobs` (`JobRunner`: one orchestrator job at a time, per-cycle failure codes), `report` (`ReportService`), `advisory` (`AdvisoryService`, the only service that touches holdings) and `post_run` (`PostRunPipeline` and `ServicePostRunJobs`, which runs it over the services).
  - `web/app.py`: `create_app(settings, *, runtime_factory)` and the lifespan. The lifespan enters the runtime (`open_runtime` by default), loads the holdings into `PortfolioCache`, and `wire_web_state` builds the report and advisory services, the `PostRunPipeline` over them, the Simulation, Replay, and Connection managers and the broadcaster, with every teardown on one `AsyncExitStack`. `web/deps.py` holds typed accessors for those `app.state` slots.
- **Domain and config**
  - `types.py`: enums, BracketConfig, AgentPersona, WorkerPersonaConfig, SeedEvent, AgentDecision.
  - `settings.py`: `AppSettings` and its nested models (`OllamaSettings`, `Neo4jSettings`, `GovernorSettings`, `SimulationSettings`), `PROJECT_ROOT`, origin defaults.
  - `inference/config.py`: `InferenceConfig` persistence in `.secrets/inference.json` (owner-only files) and key masking.
  - `personas.py`: `DEFAULT_BRACKETS`, the static modifiers, `generate_personas`, the prompt-template hash, `persona_to_worker_config`. Personas get seeded per-agent traits (`generate_personas(seed=)`, `simulation.persona_traits`); `prompt_twin_groups` finds agents whose trait-less prompts are identical ([adr-persona-traits](DECISIONS.md#adr-persona-traits)).
  - `prompts/`: the decision JSON instructions and the modifier-generation prompt (rendered from the bracket registry).
  - `security/sanitize.py`: sanitizers for entity names, headlines, rationales and peer rationales.
  - `errors.py`: exception types.
- **Engine**
  - `seed.py`: `inject_seed`. The orchestrator parses the seed (`SeedLLMOutput`) and generates the persona modifiers (`ModifiersLLMOutput`), both through `chat_structured`, and is then released; only after that does one atomic write create the Cycle (status `running`) and its Entities, so a seeding failure, teardown included, leaves no Cycle. `generate_modifiers` lives here too.
  - `simulation.py`: `run_simulation`, a loop over `settings.num_rounds`: seeding, the market context, the run seed and run manifest, phase transitions, one worker load and one governor session for every round, the cycle metrics and status ([adr-round-runner](DECISIONS.md#adr-round-runner)).
  - `rounds.py`: `run_round` (shock-gate side effects, peers, dispatch, round-abort check, citation filtering, `persist_round`, influence edges, bracket summaries, experiment metrics, callback), `prepare_round_inputs` (one `RoundInputs` per round), `retest_round1`, `SimulationDeps`, `RoundContext`, `RoundOutcome`, shift metrics.
  - `peers.py`: seeded stratified (or random, or no) peer selection, peer-context rendering and exposures, the seeded control holdout and shock arm, the own-prior lines, and `build_round_context`.
  - `consensus.py`: net score (headcount, reach, bracket-equal), dispersion, bootstrap CI ([adr-consensus-estimators](DECISIONS.md#adr-consensus-estimators)).
  - `metrics.py`: pure measurement functions: citation filtering and validity, citation rate given exposure, control/treated flips (`split_flips`), the retest noise floor and bootstrap intervals, and the round estimators (entropy, polarization, transitions, conformity, citation Gini) that `methodology_metrics` composes into `metrics_version` 3.
  - `manifest.py`: git state, blake2b run and call seeds, `ModelRef`/`RunProvenance`, `RunManifest` ([adr-run-manifest](DECISIONS.md#adr-run-manifest)).
  - `batch_dispatcher.py`: `dispatch_wave`, a TaskGroup of 100 jittered inferences.
  - `worker.py`: `AgentWorker`, the decision JSON schema, and the fence for untrusted market data.
  - `parsing.py`: `parse_agent_decision`, the worker decisions' 3-tier parser; it stamps each decision's `parse_tier`.
  - `episodes.py`: `EpisodeRecord`, `compute_flip_type`, `EntityRef`/`EntityMatch`, `match_entities`, `new_decision_ids`.
  - `market_context.py`: relevance-ordered entities, resolved tickers to yfinance/Yahoo, one ContextPacket and block ([adr-market-context](DECISIONS.md#adr-market-context)).
  - `context_formatter.py`: `format_market_context`, the ticker-aware block with the quote time and stale marker.
- **Concurrency**
  - `governor.py`: ResourceGovernor, one slot limiter (`_limit`, `_in_use`, `_paused`, `_fatal`) under a 5-state machine with PAUSED→CRISIS escalation, ramped crisis recovery and rolling-window failure accounting; per-session time in THROTTLED/PAUSED/CRISIS, peak memory, and a transition probe logged on every state change.
  - `memory_monitor.py`: the macOS kernel memory signal through ctypes `sysctlbyname` (used % = 100 − `kern.memorystatus_level`, plus the pressure level); psutil only off macOS.
  - `inference/concurrency.py`: ConcurrencyController protocol.
  - `inference/rate_limit.py`: the cloud controller and the shared retry gate (one cooldown after a 429, a fresh RPM token per retry).
  - `inference/retry.py`: the retry classifier and capped full-jitter policy every backend uses ([adr-cloud-retry](DECISIONS.md#adr-cloud-retry)).
- **Telemetry**
  - `telemetry.py`: per-round inference telemetry (`RoundTelemetry`, the `r{n}_*` cycle-metric keys), governor metrics, and the transition probe (loaded models, Docker VM memory) ([adr-inference-telemetry](DECISIONS.md#adr-inference-telemetry)).
  - `inference/call_log.py`: one `inference_call` log line per provider call (tokens, timings, finish reason, latency; never prompt or reply text).
- **Inference**
  - `ollama_client.py`: backoff (never for a permanent 4xx), plus the rule that `num_ctx` is never sent per request; per-role connect/read timeouts (`OllamaTimeouts`).
  - `ollama_models.py`: model load and unload; a one-token warm-up per load that logs `model_warmed`.
  - `inference/`: provider protocol and types; the `ollama_provider`, `openai_provider`, and `anthropic_provider` adapters; `schema` (structured-output translation per vendor); `structured` (`chat_structured`: every orchestrator reply, decoded against its output model with tier-2 extraction and one validated retry); `budget` (meter, normalized pricing with `PRICING_VERIFIED_AT`, the run estimate); `factory` (`build_providers`, `build_controller`, `attach_retry_gate`, `preflight_cloud_roles`, `inference_mode`; a local role without an Ollama client fails at build time); `caps` (one output cap per call site). The package `__init__` imports only the types and the provider protocol; other names load on first access.
- **Persistence**
  - `graph/`: the GraphStateManager facade (`manager.py`: driver, `_read`/`_write`, error mapping, one-line delegations) over `schema_writes.py` (schema, writes, influence edges, cycle status), `analytics.py` (report, shock and influence-edge reads), `replay_interview.py` (replay, cycle lookups, agent decisions, interview rows) and `rows.py` (typed rows).
  - `influence.py`: pure influence weights and shock aggregation.
  - `fsutil.py`: `atomic_write_text`, the all-or-nothing writer for report and advisory files.
- **Ingestion**
  - `ingestion/`: MarketDataProvider and NewsProvider protocols with fakes, the yfinance and RSS providers, and frozen pydantic slices. Providers never raise.
  - `ingestion/tickers.py`: swarm-side `TickerResolver` over the cached SEC map; `inject_seed` runs it before the Cycle is written ([adr-ticker-resolution](DECISIONS.md#adr-ticker-resolution)).
- **Post-run features**
  - `export.py`: the portable `alphaswarm.cycle-export/1` model and `export_cycle` (endpoint, CLI `cycles export`, `scripts/export_cycle.py`); import-linter keeps it away from holdings and advisory ([adr-cycle-export](DECISIONS.md#adr-cycle-export)).
  - `report.py` + `templates/report/*.j2`: data collection, one grounded narrative call (`chat_structured`), rendering and sections.
  - `interview.py`: a multi-turn engine keeping up to 12 user/assistant pairs; older pairs are folded six at a time into a summary.
  - `advisory/`: synthesis, prompt, sector map, types, and `evidence.py` (per-holding swarm signal, support and evidence ids, joined after the LLM call; [adr-grounded-advisory](DECISIONS.md#adr-grounded-advisory)).
  - `holdings/`: CSV loader and types. Only `advisory`, `services.advisory` (types only) and `web.routes.holdings` may import it; import-linter enforces this.
- **State and observability**
  - `state.py`: StateStore, ReplayStore, snapshot dataclasses, and the `StateSink` protocol: the StateStore methods the engine (`run_simulation`, `run_round`, `dispatch_wave`, `AgentWorker`) writes through. `StateStore` satisfies it; web-only calls such as `set_last_error` stay off it ([adr-round-runner](DECISIONS.md#adr-round-runner)).
  - `data_audit.py`.
  - `readiness.py`: bounded Neo4j, Ollama and model-alias probes (1 s timeouts, never raising) shared by `/api/health`; each returns a `ComponentStatus` that names the fix for a failure (a password error is told apart from a stopped database).
  - `logging.py`: structlog plus the fail-closed PII redaction processor.
  - `security/hashing.py`.
- **Web**
  - `web/`: `simulation_manager`, `replay_manager`, `guards` (shared route guards), `errors` (the error envelope and handlers), `params` (validated input types), `broadcaster`, `wire` (the versioned `StateFrame` and its mapper), `connection_manager`, and `origin_guard` (the single Origin policy for HTTP and the WebSocket; `web/app.py` also installs `TrustedHostMiddleware`).
  - `web/routes/`: health (component readiness: the Neo4j, Ollama and alias probes are cached 5 s, the stored inference config is read on every request; plus `/api/health/live`), simulation (start/stop/shock), edges, replay, interview, holdings, report, advisory, settings, websocket, agents (per-agent decision history), cycles (per-round citations, the portable export).
- **Evaluation**
  - `evaluation.py`: eval records, outcome labels, forecast scoring and the pre-registered gate rules (pure; `docs/DECISIONS.md#adr-eval-harness`; protocol in `docs/methodology.md`).
  - `ingestion/fixture.py`: point-in-time `ContextPacket` fixtures for `alphaswarm run --context-fixture`.
  - Repo-root `eval/`: `build_fixtures` and `label_outcomes` (yfinance), `run_eval` (`check`, `budget`, `registration`, seeded `run` through `alphaswarm run`, `score`) and `baselines` (worker-only `single`, `sc` and `probe` through `open_runtime`). They read `eval/events.jsonl` and `eval/headlines/`, read Neo4j only in read transactions, and write the committed `eval/fixtures/` and the gitignored `eval/results/` (labels, baselines, probes, tables).

## Frontend layout (`frontend/src/`)

- `app/`: `App.tsx` (WebSocket, onboarding gate, providers), `AppShell.tsx` (seed and
  overlay state), `Topbar.tsx`, `ModalHost.tsx` (the one overlay slot: an `ActiveModal`
  union, so opening an overlay replaces the current one), `ComingSoonModal.tsx`,
  `RunControls.tsx`, `ConnectionBanner.tsx`.
- `features/dashboard/`: `Dashboard.tsx`, `panels.tsx`, `StateOverlays.tsx`, `ModelStatus.tsx`,
  `ShockDrawer.tsx`, `ReplayBar.tsx`, `BracketDeepDive.tsx`, `RunErrorBanner.tsx`,
  `useDashboardData.ts`.
- `features/wire/` (Signal Wire, Data Sources), `features/advisory/`, `features/report/`
  (`ReportModal`, `ReportCharts`), `features/cycles/` (`CycleBrowser`, the one cycle list:
  reports and replays), `features/interview/`, `features/settings/`, `features/onboarding/`.
- `viz/`: the hero graph, shared by features: `layout.ts` (deterministic scene from the
  roster), `edges.ts` (curves, bracket matrix, ego network), `encodings.ts`,
  `legendItems.ts`, `caption.ts`, `Legend.tsx`, `AgentTooltip.tsx`, `InfluenceGraph.tsx`.
  No physics; see `docs/DECISIONS.md#adr-hero-graph`.
- Shared: `components/` (`Modal`, the one dialog primitive every overlay goes through; `Icon`,
  `InlineError`, `RunConfirmModal`), `hooks/`, `lib/`
  (pure helpers), `context/`, `api/`, `adapter/`, `types.ts`, `data.ts`.
- Rules, enforced by `src/__tests__/invariants/structure.test.ts`: TypeScript only, no
  explicit `any`, `noUncheckedIndexedAccess`, features never import each other or `app/`,
  `viz/` never imports `app/` or `features/`,
  modules stay under 600 lines, the inline-style count never grows, and every icon-only button
  has an aria-label.

## Data flow: seed → rounds → graph → web → UI

1. **Start.** `POST /api/simulate/start {seed}` reaches `SimulationManager.start`, which refuses with 409 while a replay is active or post-run jobs hold the orchestrator (`post_run_jobs_in_progress`), then takes the lock, clears interview sessions and the previous run's `StateStore.last_error`, and calls `_run`. `_run` opens `services.runtime.open_simulation` on the shared `InferenceRuntime`, which loads the InferenceConfig (or the local defaults; cached until the file changes) and builds:
   - providers with `build_providers`: Ollama, or budget-wrapped cloud providers;
   - a controller with `build_controller`: ResourceGovernor locally, RateLimitController for cloud.

   It records the run's budget meter and inference mode on `AppState` (read by `/api/health`), then calls `run_simulation`; the providers are closed afterwards.
2. **Seed.** `inject_seed` runs these steps:
   - `orchestrator.prepare`, then one `chat_structured` call that decodes the reply as `SeedLLMOutput` (a reply that never validates leaves an empty SeedEvent, tier 3);
   - `generate_modifiers`, a second `chat_structured` call (`ModifiersLLMOutput`; the static modifiers when it never validates);
   - `orchestrator.teardown`;
   - `create_cycle_with_seed_event`, which writes Cycle (status `running`), Entity, and MENTIONS in one transaction.

   Then `generate_personas` builds 100 prompts, shared text first: the JSON instructions (rationale first), the bracket template, the cycle's focus line for brackets the orchestrator actually filled (no entity sentiment reaches the modifier request; a modifier reply that never validates adds none), then the agent's round-robin modifier, its seeded traits (seeded with `sim_seed` once the run manifest fixes it) and its header.
3. **Market context (rounds 1..`market_context_rounds`, default every round; [adr-market-context](DECISIONS.md#adr-market-context)).** Entities are ordered by relevance; swarm-resolved tickers go to `yfinance.get_prices` (two stages, 20 s deadline, `as_of`) and every entity to `rss.get_headlines` (Yahoo only for resolved tickers), then `format_market_context` builds one block from the ContextPacket, fenced as untrusted data inside the user message. With `simulation.private_headlines` (experiment flag, never the default) each agent instead receives a seeded private half of each entity's headlines (`market_context.private_market_contexts`; prices shared). A point-in-time run (`run --context-fixture`) skips the fetch: its fixture packet goes straight to `format_market_context`, and supplied providers are never called.
4. **Round 1.** `run_simulation` loads the worker once here; it stays loaded until the last round ends. `dispatch_wave` runs 100 tasks. Each one waits out its jitter, calls `controller.acquire`, then `AgentWorker.infer` (schema-constrained decode, per-bracket temperature), then `parse_agent_decision`, which records the decision's `parse_tier` (the round metrics count them as `r{n}_parse_tier1..3`). Each decision message ends with the focal-instrument line when the seed has a resolved company ticker ([adr-decision-prompt](DECISIONS.md#adr-decision-prompt)). Results stream into the StateStore as they finish. Then:
   - the round-abort check (`RoundFailedError` when more than `round_abort_failure_percent` of agents failed);
   - `persist_round`: Decisions (with `error_kind` and `parse_tier`), CITED, RationaleEpisodes and REFERENCES in one transaction;
   - bracket summaries.
5. **Rounds 2..N.** Every round, the first included, is one `run_round` call. After each later round has started, `run_simulation` consumes a shock queued while the shock window was open; `run_round` persists it, appends every applied shock to all later rounds' user message (oldest first) and records it on the StateStore. Peer contexts are built in memory from the previous round's decisions, per reader, by `build_peer_contexts` (`peers.py`):
   - each candidate's weight is base reach plus global citation share, plus `SimulationSettings.personal_boost` (0.3) if the reader cited that agent last round;
   - `select_diverse_peers` samples peers by weight with a per-reader `peer_rng(str(sim_seed), reader, round)`: at least 4 brackets, at most 3 peers per bracket, shuffled display order;
   - the builder returns each reader's rendered peer ids, which `run_round` counts into `r{n}_exposure_*` metrics; `run_simulation` stamps them on the Cycle next to the run provenance (models, provider mode, git SHA).

   Each reader's user message then carries its own previous decision (`own_prior_memory`, default on) after the fenced peer block (if any) and before the rumor, and the seeded control holdout (`control_fraction`, default 0.0, so nobody) loses its peer context before the exposure metrics are counted; holdout decisions are stored with `d.control = true`, and the cycle metrics split the round's flips into control and treated.

   The round is then dispatched, checked against the same round-abort rule, and persisted, and `compute_influence_edges` writes `INFLUENCED_BY {round, weight}`.
6. **Finalize.**
   - The phase becomes FINALIZING, and the worker is torn down once, after the last round.
   - No narrative calls (generated lazily on first interview).
   - `write_cycle_metrics`.
   - `Cycle.status = complete` (or `failed` / `cancelled` from the `run_simulation` wrapper on error; the web manager then publishes `StateStore.last_error`).
   - The phase becomes COMPLETE.

   If anything in steps 1-6 fails instead (an invalid inference config, a hard stop, `RoundFailedError`, a Neo4j error), `SimulationManager._run` publishes a UI-safe `RunError` as `StateStore.last_error`, logs the exception once with its traceback, and resets the phase to IDLE. A cancelled run sets no error.
7. **Post-run pipeline.** `PostRunPipeline` (`services.post_run`) runs the advisory when holdings are loaded (`PortfolioCache`) and allowed, writing `advisory/{id}_advisory.json`, then the report, always; both run as `JobRunner` jobs through `AdvisoryService`/`ReportService`. The report reads run concurrently, one grounded orchestrator call writes the narrative through `chat_structured`, and Jinja renders the tables into `reports/{id}_report.md` plus a `{id}_report.json` sections sidecar. Both write atomically; job status is in the StateStore.
8. **Live UI.**
   - The broadcaster sends a versioned `StateFrame` over `/ws/state` when the state changed or once a second, never with no client: `schema_version`, `mode`, `cycle_id`, `num_rounds`, `edges_version`, `jobs`, `last_error`, the shock fields, agent states, rationale entries with `seq`/`ts`, bracket summaries, the data-source audit, and governor metrics with the live host memory.
   - `useWebSocket` skips byte-identical frames and adapts the rest against the previous frame, so unchanged agents and lists keep their identity and memoized panels skip re-rendering.
   - On the frontend, `useWebSocket` feeds `adapter/frame.ts`, which updates the React contexts (`FrameProviders`: Connection, FrameMeta, Telemetry, Agents, Rationales; plus Edges), which render the SVG graph.
   - Edges come over REST through one cached loader keyed by the frame's cycle_id, round and edges_version (EdgesContext). Report, advisory, replay and settings also come over REST.
9. **Replay.** ReplayManager loads a cycle's signals from Neo4j into a ReplayStore, and the broadcaster switches its snapshot source. No inference runs, and the live phase is left alone.
10. **Interview.** `POST /api/interview/{agent_id}` takes the request's `cycle_id` or the latest complete cycle, builds the agent's context with `interview.load_interview_context` (graph rows from `read_agent_interview_rows`), and runs InterviewEngine on the worker provider, the only one an interview builds (`InferenceRuntime.open_role`). The persona is rebuilt with the cycle's stored modifiers and, when the run manifest had traits on, the same seeded traits (`read_persona_trait_seed`); on the first interview of (cycle, agent) the decision narrative is generated and stored on the final-round Decision.

## Neo4j graph model

```text
(:Agent {id, name, bracket, risk_profile, temperature, influence_weight_base})
(:Cycle {cycle_id, seed_rumor, overall_sentiment, created_at, status, error_code, num_rounds,
         modifiers_json, prompt_template_hash, run_manifest_json, sim_seed, experiment_tag,
         <metrics>, metrics_recorded_at})
    -[:MENTIONS {relevance, sentiment, ticker}]->(:Entity {name, type})
(:Agent)-[:MADE]->(:Decision {decision_id, cycle_id, round, signal, confidence, sentiment,
                              rationale, control, error_kind, parse_tier, peer_ids,
                              citations_invalid, shock_treated, narrative})
(:Decision)-[:CITED]->(:Agent)
(:Decision)-[:HAS_EPISODE]->(:RationaleEpisode {peer_context_received, flip_type, round, cycle_id})
(:Decision)-[:REFERENCES {match_type: "token"}]->(:Entity)      # cycle's own (name, type)
(:Agent)-[:INFLUENCED_BY {weight, cycle_id, round}]->(:Agent)
(:Cycle)-[:HAS_SHOCK]->(:ShockEvent)
# History only, no longer written: (:Post), [:AUTHORED], [:HAS_POST],
# (:Decision)-[:FOR]->(:Cycle), RationaleEpisode.rationale, Agent.decision_narrative
```

Signals are stored lowercase (`SignalType.value`). Schema statements (constraints
and indexes) live in `graph/schema_writes.py` `SCHEMA_STATEMENTS` and are applied by
`ensure_schema()`. That function also seeds the Agent nodes, drops the retired indexes
(it deletes no data: the old Agent narrative property stays until the owner runs
`remove_legacy_properties()` after a backup, `docs/RUNBOOK.md` §3), and skips the `decision_id_unique` constraint while
duplicate decision ids exist (`docs/DECISIONS.md#adr-neo4j-schema`).

## Run provenance and experiment controls

Rationale and limits: [adr-run-manifest](DECISIONS.md#adr-run-manifest).

- **Run manifest:** after seeding and the market fetch, `run_simulation` fixes `sim_seed` (the setting, else derived from the cycle id), writes the `RunManifest` (`write_run_manifest`) and only then starts Round 1. Exact provider types and Ollama digests come from `services.runtime.InferenceRuntime.run_provenance`, which `open_simulation` passes as `SimulationDeps.provenance`.
- **Per round:** `prepare_round_inputs` builds per-reader peer blocks, own-prior lines and exposures (`peers.build_round_context`), the worker configs (`uniform_temperature`), the market block for rounds 1..`market_context_rounds`, per-call seeds (`derive_call_seed`) and, in a shock-split round, per-reader messages. After dispatch, `run_round` keeps only citations of shown peers and persists `peer_ids`, `control`, `citations_invalid` and `shock_treated` with the decisions. With `retest_round1`, Round 1 is drawn a second time, unpersisted, for the noise floor. A Decision or Cycle property that was not recorded is absent rather than null.
- **Operator scripts:** `scripts/compare_cycles.py --group-by experiment_tag,worker_model` (means with bootstrap intervals) and `scripts/peer_effect.py` (`effect`, `shock`, `noise`, `influence`, `exposure-diff`) read stored cycles read-only; their tables go into `docs/experiments.md`.
