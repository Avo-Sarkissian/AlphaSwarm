# AlphaSwarm Decision Log

Ported from the retired `.planning/` (GSD) system on 2026-10-03 and checked
against the code at commit `820b8fe`. Planning docs were often stale. Where the
code disagrees with the original decision, the entry says so. The original
`.planning/` text stays in git history: `git show 820b8fe:.planning/<path>`.

## How to cite this file

- Code comments should point here: `# see docs/DECISIONS.md#adr-holdings-isolation`.
- Anchors are lower-case and stable. Every table row carries an explicit
  `<a id>` so links survive edits to the wording.
- **Legacy `D-xx` IDs are phase-scoped.** "D-04" in `graph.py` (Phase 4) and
  "D-04" in `rss_provider.py` (Phase 38) are different decisions. The anchor
  format is `p<phase>-d-<nn>`, with dots in the phase number replaced by hyphens.
  Examples: `#p37-d-19`, `#p41-6-d-08`, `#p999-3-d-01`.
- Status values: **active** (true in code today), **partial** (true with
  changes, which the entry notes), **revised** (changed on purpose; the entry
  describes the current code and says what it replaced), **superseded**
  (replaced by a later decision), **lost** (the code no longer exists).

Contents

1. [Core architectural decisions](#1-core-architectural-decisions)
2. [Historical decisions no longer in code](#2-historical-decisions-no-longer-in-code)
3. [Phase-scoped D-xx index](#3-phase-scoped-d-xx-index)
4. [Known-regression register (KR-41.1 / KR-41.6)](#4-known-regression-register)
5. [June 2026 deep-audit findings (F-01..F-35)](#5-june-2026-deep-audit-findings)
6. [Bug IDs (BUGFIX-CONTEXT B-n, SWEEP-260528)](#6-bug-ids)
7. [Threat-model IDs (T-...)](#7-threat-model-ids)
8. [Requirement IDs](#8-requirement-ids)
9. [Quick-task IDs](#9-quick-task-ids)
10. [Phase-number lookup](#10-phase-number-lookup)
11. [Review tags (codex / gemini / REVIEW)](#11-review-tags)

---

## 1. Core architectural decisions

### <a id="adr-local-first-inference"></a>Local-first inference with optional cloud providers
- **Decision:** Ollama on the M1 Max is the default and needs no configuration.
  An opt-in cloud path (OpenAI-compatible endpoints and native Anthropic) exists
  behind the `InferenceProvider` protocol in `src/alphaswarm/inference/`. The
  orchestrator and worker roles are set independently and can be mixed.
- **Rationale:** The product is a local simulation, but local throughput is the
  bottleneck. The cloud path removes it without changing simulation logic. The
  design came from the superpowers spec (`docs/design/inference-providers.md`, decisions D1-D6):
  - D1: OpenAI-compatible plus Anthropic.
  - D2: adaptive token-bucket pacing with Retry-After handling and a max-in-flight cap.
  - D3: backend-owned key file; the browser never sees the raw key.
  - D4: pre-run estimate plus a hard spend cap.
  - D5: local is the default and roles can be mixed.
  - D6: a provider protocol plus adapters, mirroring the Phase 37 provider pattern.
- **Where:**
  - `inference/provider.py`, `factory.py`, `rate_limit.py`, `budget.py`, `retry.py`. Retries, configuration errors (`ProviderConfigError`), the preflight and pricing follow [adr-cloud-retry](#adr-cloud-retry).
  - Config lives in the gitignored `.secrets/inference.json`. It is edited through
    the Settings UI or `GET/PUT /api/settings`.
  - `AuthError`, `BudgetExceededError` and `ProviderConfigError` are never swallowed ([adr-cloud-retry](#adr-cloud-retry)). One deliberate limit: in an advisory job they are logged with their traceback and recorded for GET, but they do not stop the post-run report ([adr-advisory-pipeline](#adr-advisory-pipeline)).
  - The inference config's load error (ValueError/OSError) can quote the file path; a strict-model rejection (`errors.InferenceConfigFileError`) names key paths and error types, never a value, since the file holds API keys. The run and the report and advisory jobs (`services/runtime.py:InferenceRuntime.config`), the advisory gate and the interview route (both through `InferenceRuntime`), and Settings (`web/guards.py:load_inference_config_or_422`) log only its type and fail with a fixed message: an `InferenceConfigError` raised `from None`, or 422 `inference_config_invalid` (2026-10). A config that loads but that `build_providers` rejects (a cloud role without its API key, an OpenAI-compatible role without its base URL) fails the run with `InferenceConfigIncompleteError`, and an interview with 422 `inference_config_invalid`, with a second fixed message that points at Settings, not at the file: the health check reports such a file ok, and it may hold the other role's working settings.
  - The stored config is strict (unknown keys, zero limits, negative cap are rejected); an invalid file is never rewritten; `/api/health`'s `inference_config` component names the rejected keys (no values). Until the file is fixed or moved aside, `POST /api/simulate/start` still answers 202 but the run fails at once with `last_error` `inference_config_invalid`; only the onboarding Run button refuses up front, because `/api/health` is degraded. Settings and interviews answer 422 `inference_config_invalid`, the advisory is refused with the same code, and a report job fails with `report_generation_failed` (2026-10).
- **Note:** CLAUDE.md's old "No cloud APIs" rule predates this. The correct reading is "local by default".

### <a id="adr-cloud-retry"></a>One retry policy for every inference backend; configuration errors stop the run
- **Decision (2026-10):**
  - `inference/retry.py` classifies every HTTP failure. 408, 409, 429, 5xx and 529 and connection errors are retried; 400, 401, 403, 404 and 422 never are. 401/403 raise `AuthError`. A 400/404/422 that is not about the request's schema, the prompt's size or a content filter raises `ProviderConfigError`, a hard stop like `AuthError` (`batch_dispatcher.HARD_STOP_ERRORS`), so a typo in a model id costs one call instead of a cycle of PARSE_ERRORs. Context-length and content-filter 400s stay per-call `InferenceError`s; the round breaker (`round_abort_failure_percent`) is the backstop.
  - Backoff is capped full jitter: each wait is drawn from [0, min(30 s, 1 s × 2^attempt)]. `Retry-After` (seconds or HTTP-date, clamped to 60 s) replaces it when present. Timeouts are never retried, on any backend: a call that used its whole timeout points at an overloaded endpoint.
  - The Ollama client follows the same status classes (`errors.is_permanent_http_status`). The Anthropic path gets `ProviderLimits.max_retries` like the OpenAI-compatible path.
  - In cloud mode `RateLimitController` is also the retry gate: a 429 seen by any agent sets one shared cooldown (concurrent 429s take the maximum, never the sum), and every retry takes a fresh RPM token. The TPM reservation per call is `ProviderLimits.avg_tokens_per_call` (default 1,500).
  - Cloud `prepare()` runs a preflight once per provider, and `services.runtime.open_simulation` runs it for both roles before seeding (`factory.preflight_cloud_roles`). `GET /models` is only a fast positive (ids may carry a namespace prefix such as `models/`); a miss or an error falls back to a 1-token completion whose answer is definitive. Transient preflight failures are logged (`cloud_preflight_inconclusive`) and never block a run. The preflight is not metered (at most one output token).
  - Pricing: model ids are normalized (`-YYYYMMDD` and `-YYYY-MM-DD` stripped), then the longest table key that the id extends only by a version suffix (`-6`, `:free`, `@2025`) is used; another product such as `o1-pro` is never priced as `o1`. `PRICING_VERIFIED_AT` records the last check against the vendor pages and a test fails once it is 180 days old. Premium `-pro` variants are not in the table: add a `pricing_overrides` entry before using one. The run estimate prices through the meter's own logic and lists `unpriced_models`. A response that was billed and then failed (a malformed body, a missing tool call) is still recorded.
- **Rejected:** a full AIMD controller; a persistent spend ledger or daily cap (the per-operation cap is the intent); retrying timeouts.
- **Where:** `inference/retry.py`, `inference/openai_provider.py`, `inference/anthropic_provider.py`, `inference/rate_limit.py`, `inference/factory.py`, `inference/budget.py`, `ollama_client.py`, `errors.py`, `services/runtime.py`.

### <a id="adr-model-stack"></a>Model stack: MLX Qwen 3.6 pair (decided 2026-06-11)
- **Decision:**
  - Worker: `qwen3.6:35b-a3b-nvfp4` (36B MoE, about 3B active).
  - Orchestrator: `qwen3.6:27b-nvfp4`.
  - Both are MLX-format tags run with `OLLAMA_USE_MLX=1`.
- **Rationale:** Persona prompts are about 2.5k tokens against about 150 output tokens, so prefill dominates. Measured on this machine:

  | Role | Before | MLX tag | Prefill gain |
  |---|---|---|---|
  | Worker | qwen3:8b GGUF, 422 t/s | 2361 t/s | about 5.6x |
  | Orchestrator | 27b GGUF, 111 t/s | 3395 t/s | about 30x |

  Dense-model parallel decode is capped by memory bandwidth on the M1 Max, so a fast MoE stream beats parallel dense 8B.
- **Where:** `settings.py:OllamaSettings` (defaults), plus the header comments in `modelfiles/Modelfile.worker` and `modelfiles/Modelfile.orchestrator`.
- **Rollback:**
  - First fallback: qwen3.5:35b GGUF MoE.
  - Second fallback: qwen3:8b plus qwen3.6:27b-q4_K_M, the stack from the 2026-05-06 decision ([adr-think-off](#adr-think-off)).
- **Revisit when:** a new MoE beats 2361 t/s prefill on 64 GB. Gemma 4 26B MoE is untested.

### <a id="adr-model-aliases"></a>Code calls Modelfile aliases; `num_ctx` lives only in Modelfiles
- **Decision:** All inference uses the aliases `alphaswarm-worker` and `alphaswarm-orchestrator` (`settings.py:OllamaSettings`), built with `ollama create ... -f modelfiles/Modelfile.*`. `OllamaClient` strips any per-request `num_ctx` (`ollama_client.py:25-30`). Output caps are sent per request: OllamaProvider forwards max_tokens as options["num_predict"], a sampling option that does not reload the model; the Modelfile num_predict is only the fallback, so a base tag chosen in Settings is capped too (2026-10). See [adr-output-caps](#adr-output-caps).
- **Rationale:** A per-request `num_ctx` makes Ollama silently reload the model.
- **Caveats:**
  - `OllamaSettings.worker_model` and `orchestrator_model` are not read by any code path: the banner that `alphaswarm web` and `alphaswarm doctor` print (2026-10) shows the model each role calls, from the inference config. Changing them does not change the model; edit the Modelfile and re-run `ollama create`.
  - `OllamaSettings.num_parallel` and `max_loaded_models` were removed in 2026-10: they were never read. Old `.env` files that still set them load with one `ollama_retired_settings_ignored` warning. The real values are the Ollama server variables (RUNBOOK §1), checked by `alphaswarm doctor`.

### <a id="adr-output-caps"></a>Explicit output caps at every call site
- **Decision:** Every `chat`/`chat_structured` call passes `max_tokens`. The values live in `inference/caps.py` (worker decision 400, decision narrative 400, interview reply 600 and summary 300, seed 1024, modifiers 1024), except the report narrative (1200, `report.py`) and the advisory (3000, `advisory/engine.py`), which sit next to their prompts. Ollama receives the cap as `num_predict` on each request; the Modelfiles keep `num_predict` 400 (worker) and 4096 (orchestrator) as fallbacks. Anthropic defaults: 512 for the worker role, 8192 for the orchestrator.
- **Rationale:** On MLX the worker prefills at about 2,361 t/s but decodes at about 56 t/s, so output length drives call time. The caps lived only in the worker Modelfile, so a base tag chosen in Settings, the orchestrator and every cloud worker ran uncapped (Anthropic defaulted to 2048).
- **Where:** `inference/caps.py`, `inference/ollama_provider.py`, `inference/factory.py`, `worker.py`, `seed.py`, `interview.py`, `report.py`, `advisory/engine.py`, `modelfiles/`.
- **Guard:** `tests/invariants/test_output_caps.py` fails for a call without a cap.
- **Rationale and citations:** the decode schema caps rationale at 280 characters and cited_agents at 5 items, and the instructions ask for one or two sentences of at most 40 words. AgentDecision is not capped, so a backend that ignores maxLength/maxItems still parses. Long rationales also pushed peers out of the 4,000-character peer budget. Kept or reverted by gate G-24 (docs/experiments.md, arm A1).

### <a id="adr-prefix-reuse"></a>Prompt layout for KV-prefix reuse (experiment, gate G-22)
- **Decision (pending G-22):** persona prompts put shared text first and agent text last: the JSON rules (every agent), the bracket template and this cycle's bracket focus (one bracket), then the agent's static modifier and the header `[<Name> | <Display> bracket]`. `AgentPersona.shared_prompt_chars` marks the end of the shared part. Arm A2 also includes: the worker sends the fixed guards first and the persona as two system messages (shared, then agent), local dispatch has no jitter so prompts reach Ollama in bracket order, and Anthropic gets a cache breakpoint after the shared block.
- **Rationale:** every prompt opened with a unique header, so two agents of a bracket shared about 14 characters of prefix. The realistic gain is the 400-600 tokens of rules and template per call, and only if the MLX runner reuses a KV prefix, which is unverified.
- **Constraints:** untrusted text never moves into the system role (F3; the market and peer blocks stay fenced in the user message), and `AGENT_HEADER_RE` keeps matching the header.
- **Kept only if** mean R2-R3 `prefill_ms` drops by at least 10% with unchanged final distributions (docs/experiments.md, arm A2).
- **Where:** `personas.py`, `types.py`, `interview.py`, `worker.py`, `batch_dispatcher.py`, `inference/anthropic_provider.py`.
- **Anthropic:** several system messages are sent as text blocks with cache_control on the second-to-last one (the persona's shared block for the worker). Anthropic only caches prefixes above the model's minimum (1,024 tokens or more), so the about 600-token worker prefix is usually not cached; cache hits show up as cached_prompt_tokens in inference_call. Cache writes cost 1.25x and reads 0.1x the input price while BudgetMeter prices all prompt tokens at 1x (pricing belongs to the cloud-pricing work).

### <a id="adr-think-off"></a>Orchestrator reasoning ("think") is off everywhere
- **Decision:** Every local inference call passes `think=False`. It is hardcoded in `OllamaProvider.chat` (`inference/ollama_provider.py:162`), so it covers worker and orchestrator alike: seed, modifiers, rounds, narratives, advisory, report, and interview. No call site sets it individually.
- **Rationale:** The 2026-05-06 probe on qwen3.6:27b measured 274.6 s per call with thinking against 9.5 s without. Both produced valid JSON, and neither output was clearly better. With 11.3 t/s MLX decode, thinking also pushed advisory past the 600 s timeout (quick task 260611-rlx).
- **Where:**
  - Enforced: `inference/ollama_provider.py:162` (documented at `:12` and `:129`); the load warm-up in ollama_models.py passes it too (2026-10).
  - Rationale comments only: `seed.py:inject_seed`, `tests/test_seed_pipeline.py:test_inject_seed_calls_chat_with_seed_schema`, `modelfiles/Modelfile.orchestrator:16-17`.
- **Revisit:**
  - Triggers: complaints about consensus quality, or missed divergence flags.
  - How to test: `InferenceProvider.chat` has no `think` parameter today (`inference/provider.py:60`), so an A/B run needs a small change first, for example an optional `think` argument on `OllamaProvider.chat` used by one call site. No model reload is needed.
  - Hybrid option: keep `think=False` as the default and enable it only for one high-stakes call.

### <a id="adr-inference-timeouts"></a>Per-role Ollama timeouts
- **Decision:** `OllamaClient` holds two HTTP pools built from `OllamaTimeouts`. Worker inference uses `httpx.Timeout(connect=5, read=120, write=30, pool=30)`; everything else (orchestrator calls, model loads, unloads and warm-ups) uses read=600. Settings: `ALPHASWARM_OLLAMA__CONNECT_TIMEOUT_S`, `__WORKER_READ_TIMEOUT_S`, `__ORCHESTRATOR_READ_TIMEOUT_S`. The retired `__REQUEST_TIMEOUT_SECONDS` maps onto the orchestrator value with a `FutureWarning`.
- **Rationale:** One 600 s scalar let a stalled worker call hold its slot for ten minutes and made an unreachable host take 600 s to fail. Worker calls take seconds on MLX. `ollama.AsyncClient` fixes its timeout per client, hence two pools rather than a per-call value.
- **Where:** `ollama_client.py` (`OllamaTimeouts`, `chat(timeout_role=)`), `inference/ollama_provider.py`, `app.py`, `settings.py`.
- **Revisit when:** a cold worker load inside a worker call (keep-alive expired, for example a late interview) needs more than 120 s: raise `ALPHASWARM_OLLAMA__WORKER_READ_TIMEOUT_S`.
- **Warm-up:** every load sends a short fixed prompt with think=False and num_predict 1 on the orchestrator read timeout, and logs model_warmed (warmup_ms, load_ms, prompt_tokens, prefill_tps). A prefill rate under 200 t/s logs model_warmup_slow, which usually means OLLAMA_USE_MLX is not set. Before this, the "ping" ran with qwen3.6 reasoning on and no output cap.

### <a id="adr-sequential-model-lifecycle"></a>At most two models loaded; orchestrator users are serialized
- **Decision:**
  - The callers set the load order; `OllamaModelManager` only serializes load and unload transitions under one lock (`ollama_models.py:OllamaModelManager`, INFRA-03). A run loads the orchestrator for the seed and unloads it (`seed.py:inject_seed`), then loads the worker once for all rounds ([adr-round-runner](#adr-round-runner)). Advisory and report load the orchestrator after the run, and decision narratives are generated on the first interview ([p11-d-11](#p11-d-11)).
  - Report and advisory never overlap: both POST routes and the post-run pipeline start their jobs through `services.jobs.JobRunner`, which refuses a second job with `JobInProgressError` (409 `{kind}_generation_in_progress`) and reads the running state from `StateStore.job_statuses()`; `SimulationManager.start` asks the same runner (`JobRunner.is_busy`).
  - After a completed run, `PostRunPipeline` (`services/post_run.py`) runs the advisory when a portfolio is loaded (and, with a cloud orchestrator, only with the opt-in), then always the report, by direct calls; the former in-process `httpx.ASGITransport` chain is gone. `SimulationManager.start()` refuses a new run with 409 `post_run_jobs_in_progress` while the pipeline task is pending or an orchestrator job runs, and `POST /api/settings/test` is refused during a run.
  - The report and advisory POST routes check for a running simulation again after their last await, right before the job starts (`web/guards.py:require_no_simulation`): a run started while they awaited Neo4j, the config or the holdings passed `start()`'s probe, because no job was marked running yet (2026-10).
- **Rationale:** On 64 GB the worker and orchestrator cannot both stay warm, and either task unloading the orchestrator under the other corrupts the run.

### <a id="adr-round-runner"></a>One round implementation and one worker session for all rounds (revises D-05 and D-06, 2026-10)
- **Decision:**
  - `rounds.run_round(ctx, round_num, prev, shocks)` is the only implementation of a round: shock-gate side effects, per-reader peer context, dispatch, the round-abort check, `persist_round`, influence edges, bracket summaries, the round's metrics and the `on_round_complete` callback (`rounds.py`).
  - `simulation.run_simulation(rumor, deps, personas, brackets, *, on_round_complete, consume_shock)` seeds the cycle, builds the market context, writes the run manifest ([adr-run-manifest](#adr-run-manifest)), sets each round's phase and number, consumes a pending shock after the round has started, loops over `settings.num_rounds`, and writes the cycle metrics and status.
  - Dependencies arrive in a frozen `SimulationDeps` (settings, graph, controller, orchestrator and worker providers, state sink, the optional market and news providers, and an optional point-in-time `context_fixture`). Providers are required and built by `inference.factory`; `simulation`, `rounds` and `peers` never import `ollama_provider`, `ollama_client` or `ollama_models` (import-linter contract).
  - The worker is prepared once before Round 1 and torn down once after the last round, inside one governor monitoring session ([p7-d-05](#p7-d-05) and [p7-d-06](#p7-d-06) revised). `inject_seed` tears the orchestrator down before the worker loads, so the two are never co-resident during rounds.
  - Only the Ollama worker provider unloads resident AlphaSwarm models before it loads (`OllamaProvider(clean_state_on_prepare=True)`, set by `build_providers`); orchestrator jobs (report, advisory) never evict a worker that an interview is using.
- **Rationale:** The Round 2 and Round 3 blocks were copy-pasted and had drifted (T9.1). Nothing used Ollama between Round 1 and Round 2, so tearing down the ~20 GB MLX worker and reloading it cost a cold load (MLX kernel compilation plus a warm-up call) for nothing. D-05 accepted that cost when the worker was a 5 GB GGUF. Letting the caller own the lifecycle keeps the modularity D-05 wanted without the reload.
- **Consequences:** The UI stays on `seeding` while the worker loads (it used to show `round_1`); `r{n}_seconds` measure the round alone, without model loads; the governor's pool is no longer reset between Round 1 and Round 2; a cloud worker no longer triggers a local `ensure_clean_state()`.

### <a id="adr-swarm-composition-v2"></a>Swarm composition v2 (2026-06-10)
- **Decision:** Ten brackets that model the price-setting margin of the narrative ecosystem. Counts and weights live in `personas.py:DEFAULT_BRACKETS`; the rationale is in the `types.py:BracketType` docstring.

  | Bracket | Count | Weight |
  |---|---|---|
  | Institutions | 18 | 0.65 |
  | Sell-Side | 10 | 0.75 |
  | Event-Driven | 10 | 0.60 |
  | Quants | 12 | 0.55 |
  | Degens | 15 | 0.50 |
  | Narrators | 8 | 0.70 |
  | Algos | 8 | 0.45 |
  | Macro | 7 | 0.55 |
  | Shorts | 7 | 0.60 |
  | Allocators | 5 | 0.60 |

- **Deliberate exclusions (do not "fix"):**
  - Passive/index capital never reacts to rumors.
  - Market makers' honest reaction ("vol up, quote both sides") does not fit buy/sell/hold.
- **Rationale:** v1 had Sovereigns, Whales, Suits, Insiders, Policy Wonks, and Doom-Posters. Combined with static-authority peer ranking, it manufactured convergence toward a HOLD-heavy bloc (SWEEP-260528 §3).
- **Action-bias mix:** 4 hold-biased, 4 act-biased, 1 sell-biased, 1 second-order.

### <a id="adr-persona-traits"></a>Seeded per-agent traits break the prompt twins (Phase 7)
- **Decision:** With `simulation.persona_traits` (default on) each agent's persona gains one sentence (horizon from a bracket-appropriate pool, current position, coverage focus), placed after its round-robin modifier and before the header, so the shared prefix stays shared ([adr-prefix-reuse](#adr-prefix-reuse)). Draws use `random.Random(blake2b("{sim_seed}:traits:{bracket}:{modifier group}"))` (`personas.trait_for`); agents that share a static modifier always get distinct combinations, so every header-stripped prompt is unique (`personas.prompt_twin_groups`). `ALPHASWARM_SIMULATION__PERSONA_TRAITS=false` reproduces the trait-less prompts. Interviews rebuild the same traits: `read_persona_trait_seed` returns the cycle's `sim_seed` when its run manifest had traits on, and cycles without a manifest keep the trait-less persona. Bracket composition, counts and reach are unchanged ([adr-swarm-composition-v2](#adr-swarm-composition-v2)).
- **Rationale:** Round-robin modifiers gave 43 distinct prompt bodies for 100 agents; prompt twins at low temperature answer alike, so measured agreement partly reflected duplication rather than opinion formation. The effect is measured as Round 1 agreement among former twins (`scripts/persona_agreement.py`, `docs/experiments.md`).

### <a id="adr-influence-weight-reach"></a>`influence_weight_base` means narrative reach, not capital
- **Decision:** Weights span 0.45-0.75, and Sell-Side and Narrators rank highest on purpose.
- **Rationale:** Peer visibility, not assets under management, determines whose rationale others read.
- **In the peer sampler:** Sell-Side and Narrators are the brackets seen most often per agent. Below them, the bracket floor and the per-bracket cap make weight a rough order only ([adr-diverse-peer-context](#adr-diverse-peer-context)).

### <a id="adr-diverse-peer-context"></a>Peer context is built in memory per reader, by seeded stratified sampling
- **Decision:** `build_peer_contexts` (`peers.py`) builds each reader's peer context in memory and returns the ids of the peers it rendered (the reader's *exposure*). It is the production path since the June 2026 overhaul; seeded sampling replaced the deterministic fill in October 2026.
  - Per-reader weight = base reach + global citation share + `SimulationSettings.personal_boost` (default 0.3) if the reader cited that author last round. The boost raises a cited author's odds; it no longer guarantees a slot. Only an ablation (0 / 0.05 / 0.3) may change the default.
  - `select_diverse_peers` samples without replacement, weighted by that score (Efraimidis–Spirakis keys `u ** (1/w)`, computed as `log(u)/w`): first `min_brackets` brackets (default 4), each weighted by the summed weight of its candidates, with one peer each (a weighted draw over agents that skips brackets already chosen); then the remaining slots, with at most `bracket_cap` peers (default 3) from any one bracket. The cap is hard, so a reader gets fewer than `peer_limit` (default 10) peers when few brackets are eligible. The reader and previous-round PARSE_ERROR agents are never shown. Non-finite or non-positive weights have no reach: whatever their draw, they sort behind every positive weight (in random order among themselves) instead of raising.
  - The final list is shuffled, so no bracket owns position 1.
  - Randomness comes only from `peer_rng(run_seed, reader, round)` (blake2b, never the process-salted `hash()`); `run_seed` is `str(sim_seed)` (`peer_seed_source = "sim_seed"`; cycles recorded before the run manifest used the cycle id, [adr-run-manifest](#adr-run-manifest)).
  - Knobs: `ALPHASWARM_SIMULATION__PEER_LIMIT`, `__MIN_BRACKETS`, `__BRACKET_CAP`, `__PERSONAL_BOOST`, `__PEER_BUDGET_CHARS` (defaults 10 / 4 / 3 / 0.3 / 4000).
  - The format is `[agent_id|bracket] SIGNAL (conf)`, so agents can cite IDs. Peers cut by the character budget do not count as exposure.
  - Each peer round's exposure is summarized in the cycle metrics (`r{n}_exposure_<bracket>`, `r{n}_readers_seeing_<bracket>`, `r{n}_distinct_peers_shown`) with `peer_selection_version = 2`; `scripts/peer_exposure.py` prints them, with slots per agent and the cycle's peer knobs, and checks them.
- **Rationale:** "Reach" means the probability of being seen, not a monopoly.
  - *Legacy fill:* base weights are constant per bracket, so the top-weight fill was deterministic. It selected 7 Sell-Side, 1 Narrator, 1 Institution and 1 Event-Driven peer for every reader, put Sell-Side at position 1, and never showed six brackets. The character budget then cut the feeds short: in the *before* cycle below, readers saw about 5.6 peers each in R2 (2.6 of them Sell-Side), and only 46 (R2) and 45 (R3) agents were ever visible.
  - *Per-agent reach:* sampling hears every bracket and keeps the top of the reach order. Phase 1 weights a bracket by its members' summed weight, so Sell-Side and Narrators (the two highest weights) are still the brackets seen most often per agent. Below them, the bracket floor lifts small brackets and the per-bracket cap trims large ones, so weight orders the rest only roughly. Offline R2 selections on the production roster over 300 run seeds, in readers who saw an average member: Sell-Side 12.2, Narrators 12.1, Allocators 11.6, Shorts 11.0, Event-Driven 10.3, Macro 10.2, Institutions 9.4, Quants 9.3, Algos 8.5, Degens 8.2. `test_highest_reach_brackets_are_seen_most_per_agent` pins the top two. The gaps are small next to one cycle's noise. Replaying the *after* cycle's own Round 1 rationales over 200 run seeds gives rendered R2 means of Sell-Side 7.4, Narrators 7.3 and Allocators 7.1 per agent, with a per-cycle standard deviation of 0.7-1.2. That cycle's own column (Allocators 8.2, Sell-Side 7.2, Narrators 6.9) is within that noise.
  - Weighting Phase 1 by each bracket's best member instead, as a never-merged draft did, put Allocators first per agent (13.7, against Narrators 12.3 and Sell-Side 12.0). Its after cycle `c446284f-a40e-4527-b55e-2f9030d348a5` also passed the invariant.
  - Building in memory also replaced the `read_ranked_posts` path, which showed all 100 agents the same authority top-10 (SWEEP-260528 §3.3) and cost 100 sequential Neo4j reads per round.
- **Invariant (tested in `tests/test_peer_selection.py`):** on `generate_personas(DEFAULT_BRACKETS)`, no bracket takes more than 35% of a round's slots and every bracket is visible to at least 15% of readers, in R2 and in an R3 worst case where everyone cited the same two Sell-Side agents.
- **Superseded:** the deterministic fill ([p8-d-06](#p8-d-06)) and the `_stable_peer_jitter` tie-break ([f-08](#f-08)); per-reader seeded sampling disperses equal-weight readers by construction.
- **Evidence (benchmark seed `apple-anthropic`, 3 rounds, one inference configuration for both cycles):**
  - *Before* (legacy selector, `peer_selection_version` 1): cycle `5c59c533-e841-40fb-91ca-071ac239c1ab`, git `8ae04cac`, mode `local`, worker `alphaswarm-worker`, parse errors R2 `0` / R3 `0`; `peers: limit=10 min_brackets=4 bracket_cap=- personal_boost=0.3 budget_chars=4000 seed_source=-` (the cycle predates the `peer_bracket_cap` and `peer_seed_source` keys).

    | bracket | slots | per agent | slot % | readers % | citations % |
    |---|---|---|---|---|---|
    | institutions | 100 | 5.6 | 18.0% | 100% | 20.5% |
    | sell_side | 256 | 25.6 | 46.0% | 100% | 46.7% |
    | event_driven | 100 | 10.0 | 18.0% | 100% | 23.5% |
    | quants | 0 | 0.0 | 0.0% | 0% | 0.0% |
    | degens | 0 | 0.0 | 0.0% | 0% | 0.0% |
    | narrators | 100 | 12.5 | 18.0% | 100% | 9.3% |
    | algos | 0 | 0.0 | 0.0% | 0% | 0.0% |
    | macro | 0 | 0.0 | 0.0% | 0% | 0.0% |
    | shorts | 0 | 0.0 | 0.0% | 0% | 0.0% |
    | allocators | 0 | 0.0 | 0.0% | 0% | 0.0% |

    R2: distinct peers shown 46/100; max slot share 46.0% (limit 35%); min readers 0% (limit 15%) -> FAIL

    | bracket | slots | per agent | slot % | readers % | citations % |
    |---|---|---|---|---|---|
    | institutions | 100 | 5.6 | 16.9% | 100% | 24.9% |
    | sell_side | 290 | 29.0 | 49.2% | 100% | 44.4% |
    | event_driven | 100 | 10.0 | 16.9% | 100% | 23.9% |
    | quants | 0 | 0.0 | 0.0% | 0% | 0.0% |
    | degens | 0 | 0.0 | 0.0% | 0% | 0.0% |
    | narrators | 100 | 12.5 | 16.9% | 100% | 6.8% |
    | algos | 0 | 0.0 | 0.0% | 0% | 0.0% |
    | macro | 0 | 0.0 | 0.0% | 0% | 0.0% |
    | shorts | 0 | 0.0 | 0.0% | 0% | 0.0% |
    | allocators | 0 | 0.0 | 0.0% | 0% | 0.0% |

    R3: distinct peers shown 45/100; max slot share 49.2% (limit 35%); min readers 0% (limit 15%) -> FAIL

  - *After* (seeded stratified sampling, `peer_selection_version` 2): cycle `10d9419f-9ed6-4d2a-9842-e6e208a65d62`, git `032d3982`, mode `local`, worker `alphaswarm-worker`, parse errors R2 `0` / R3 `0`; `peers: limit=10 min_brackets=4 bracket_cap=3 personal_boost=0.3 budget_chars=4000 seed_source=cycle_id`.

    | bracket | slots | per agent | slot % | readers % | citations % |
    |---|---|---|---|---|---|
    | institutions | 93 | 5.2 | 15.2% | 72% | 25.0% |
    | sell_side | 72 | 7.2 | 11.8% | 59% | 4.0% |
    | event_driven | 67 | 6.7 | 11.0% | 56% | 13.4% |
    | quants | 60 | 5.0 | 9.8% | 51% | 13.4% |
    | degens | 80 | 5.3 | 13.1% | 66% | 4.9% |
    | narrators | 55 | 6.9 | 9.0% | 49% | 8.0% |
    | algos | 50 | 6.2 | 8.2% | 41% | 3.6% |
    | macro | 52 | 7.4 | 8.5% | 49% | 10.3% |
    | shorts | 41 | 5.9 | 6.7% | 40% | 11.2% |
    | allocators | 41 | 8.2 | 6.7% | 37% | 6.2% |

    R2: distinct peers shown 100/100; max slot share 15.2% (limit 35%); min readers 37% (limit 15%) -> PASS

    | bracket | slots | per agent | slot % | readers % | citations % |
    |---|---|---|---|---|---|
    | institutions | 113 | 6.3 | 17.9% | 77% | 26.3% |
    | sell_side | 79 | 7.9 | 12.5% | 62% | 7.5% |
    | event_driven | 69 | 6.9 | 11.0% | 60% | 16.5% |
    | quants | 70 | 5.8 | 11.1% | 54% | 14.3% |
    | degens | 75 | 5.0 | 11.9% | 60% | 1.9% |
    | narrators | 67 | 8.4 | 10.6% | 58% | 7.9% |
    | algos | 44 | 5.5 | 7.0% | 40% | 3.4% |
    | macro | 41 | 5.9 | 6.5% | 40% | 7.5% |
    | shorts | 55 | 7.9 | 8.7% | 49% | 11.7% |
    | allocators | 17 | 3.4 | 2.7% | 16% | 3.0% |

    R3: distinct peers shown 100/100; max slot share 17.9% (limit 35%); min readers 16% (limit 15%) -> PASS

  - *R3 margin:* Allocators were seen by 16% of R3 readers, just above the 15% floor. This cycle drew badly; it is not the typical outcome. Rebuilding R3 from the cycle's stored R2 decisions reproduces the recorded exposure exactly. Of the 45 Allocators selected, 31 fell in display positions 6-9 (18 expected), which the character budget cuts. Replaying the same decisions over 1,000 other run seeds gives a mean R3 minimum of 32.7% (worst 17%, never below 15%).
  - *Summary:* R2 max slot share `46.0%` → `15.2%`; R2 min readers `0%` → `37%`; R3 `49.2%` → `17.9%` and `0%` → `16%`; distinct peers shown R2 `46` → `100`, R3 `45` → `100`; Sell-Side share of R2 citations `46.7%` → `4.0%`. Flips and final distribution (context, not a gate) are in `scripts/compare_cycles.py` for both cycles.

- **Leftovers:**
  - `read_ranked_posts`, `_dispatch_round`, and `read_peer_decisions` were dead code and were deleted in 2026-10.
  - The report's `social_post_reach` section and the Post writes were removed (2026-10).
- **Control holdout (decided 2026-10 under the owner's delegation):** `control_fraction` defaults to 0.0, so product runs keep every reader's peer context; experiment and eval runs set `ALPHASWARM_SIMULATION__CONTROL_FRACTION=0.2` (20 seeded readers, round-half-up per bracket, never see peers).
- **Own prior (2026-10):** from Round 2 on, each reader's user message carries its own previous decision after the fenced peer block (if any) and before the rumor (`Your Round N position: SIGNAL (conf X): rationale`, sanitized to one line and left out after a PARSE_ERROR; `ALPHASWARM_SIMULATION__OWN_PRIOR_MEMORY`, default true). Holdout readers keep it, so their flips measure everything except peers. Holdout decisions carry `d.control = true` in every round, Round 1 included, and the cycle metrics add `r{n}_control_agents`, `r{n}_flips_control` and `r{n}_flips_treated`.
- **Seeding and validity (2026-10, [adr-run-manifest](#adr-run-manifest)):** sampling, the holdout and the display shuffle use `run_seed = str(sim_seed)`, so two cycles with the same manifest and seed show the same Round 2 peers; only citations of peers a reader was shown count toward influence and the next round's personal boost. `peer_strategy`, `show_bracket_labels` and `show_confidence` exist for ablations; the defaults keep the stratified feed with labels and confidence.

### <a id="adr-num-rounds"></a>Configurable cascade depth (2 or 3 rounds)
- **Decision:** `ALPHASWARM_NUM_ROUNDS` accepts 2 or 3 and defaults to 3 (`AppSettings.num_rounds`).
  - Round 1 is the uninfluenced prior and should not be touched.
  - `num_rounds` is stamped on the Cycle when it is created (`create_cycle_with_seed_event`), so running and failed cycles carry it too. The completion metrics write the same value.
  - Report and advisory reads resolve the final round inside Cypher with `coalesce(c.num_rounds, 3)`, because cycles from before 2026-10 that lack the property were all 3-round. The replay cycle list reports the same value as `round_count`.
  - Prompts describe the rounds that ran: the report's narrative data carries `final_round` (and the report header the round count), and the lazy narrative prompt (generated on first interview) names the agent's round count. The CLI summary uses the last round that ran and reports convergence only for 3-round runs, since it compares R1→R2 flips with R2→R3 flips.
  - With 2 rounds, the round-3 result fields are empty, and completed-cycle listing relies on `Cycle.status` ([adr-cycle-metrics](#adr-cycle-metrics)).
- **Rationale:** Most flips happen in Round 2, and 2 rounds save about a third of wall time. Keep the default at 3 until the 2-vs-3-round ablation is done. The UI reads `num_rounds` from the frame (`useRounds()`), so a 2-round run renders correctly end to end.

### <a id="adr-structured-output"></a>Structured outputs plus a 3-tier parser
- **Decision:** Workers request JSON (the JSON schema `DECISION_JSON_SCHEMA` in `worker.py`) and still go through a 3-tier parser: JSON, then extraction, then PARSE_ERROR (`parsing.py`, INFRA-08). The brace scanner is string-aware since F-09.
- **Rationale:** The MLX runner relies on prompt adherence rather than hard grammar enforcement, so the prompt must spell out the keys. Never trust format=schema alone.
- **Orchestrator replies** (seed, modifiers, report narrative, advisory) go through inference.structured.chat_structured: the output model's portable JSON schema as response_schema, tier-2 candidate extraction, one retry carrying field errors but never input values, then StructuredOutputError. Boundary validators normalise "BUY" and percentage confidences. Worker decisions keep DECISION_JSON_SCHEMA and parse_agent_decision, now recording parse_tier (r{n}_parse_tier1..3). Clamping cannot fix NaN, so every number on an LLM-facing model keeps its range: a NaN then fails inside chat_structured, where it is retried, instead of later in a domain model (`SeedLLMOutput.overall_sentiment`, 2026-10).

### <a id="adr-decision-prompt"></a>The worker reasons before it votes, about a named instrument (Phase 7)
- **Decision:** `DECISION_JSON_SCHEMA` and `JSON_OUTPUT_INSTRUCTIONS` put `rationale` first, so under constrained decoding the reasoning tokens precede the signal. When the seed has a resolved company ticker, every decision message ends with `Instrument in focus: <TICKER> (<name>). …` taken from the highest-relevance resolved company ([adr-ticker-resolution](#adr-ticker-resolution)); the line sits in the user message after the rumor and shocks, never in the system role, and tells each agent to read buy/sell/hold the way its own role defines them, so the Narrators' "which way the STORY pushes the crowd" framing stands. The full probabilistic decision schema is a separate decision, taken after the Phase 7 evaluation.
- **Rationale:** With the signal first and `think=False`, the vote was emitted before any reasoning, and a bare rumor left BUY ambiguous between the acquirer, its peers or nothing tradeable.

### <a id="adr-inference-telemetry"></a>Inference telemetry: one normalized result, one log line, per-round aggregates
- **Decision:** Every provider returns `InferenceResult` with `input_tokens` ("prompt_tokens"), `output_tokens` ("completion_tokens"), `cached_prompt_tokens`, `prefill_ms`, `decode_ms`, `load_ms` and `finish_reason` (`stop | length | content_filter | tool_use | error | other`). Unknown values stay `None`; they are never written as 0.
- **Normalization:**
  - Ollama: `prompt_eval_count` / `eval_count` / `prompt_eval_duration` / `eval_duration` / `load_duration`; `done_reason` `stop`/`length`, anything else `other`. `prompt_eval_count` counts only tokens actually prefilled, so a reused KV prefix lowers it.
  - OpenAI-compatible: `usage.prompt_tokens` (cache included), `prompt_tokens_details.cached_tokens`, `finish_reason` (`tool_calls` → `tool_use`). No timings.
  - Anthropic: prompt tokens = `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` (the API's `input_tokens` is the uncached remainder); `stop_reason` `end_turn`/`stop_sequence` → `stop`, `max_tokens` → `length`, `refusal` → `content_filter`. No timings. The budget meter therefore prices cache reads at the full input rate (an overestimate, the safe direction for a spend cap).
- **Per call:** every provider's `chat` goes through `inference/call_log.py:logged_call`, which logs one `inference_call` line with role, model, prompt/completion/cached tokens, prefill/decode/load ms, finish reason and latency; a failure logs `finish_reason=error` with the exception class only. `cycle_id`, `round` and `agent_id` come from structlog contextvars. Prompt and reply text are never logged, which keeps advisory calls free of holdings.
- **Per round:** `RoundTelemetry` writes `r{n}_latency_p50_ms`/`p95_ms`, mean prompt/completion tokens, mean prefill/decode ms, total load ms, cold loads (load ≥ 500 ms), truncations (`finish_reason` `length`; such a parse failure is `error_kind="truncated"`) and context warnings (prompt ≥ 90% of `OllamaSettings.worker_num_ctx`, local workers only). The governor adds time-in-state and peak memory; `seed_seconds` and `total_seconds` share one run clock (`metrics_version` 2).
- **Where:** `inference/types.py`, the three adapters in `inference/`, `inference/call_log.py`, `telemetry.py`, `governor.py`.

### <a id="adr-governor"></a>Memory-aware ResourceGovernor
- **Decision:**
  - One slot limiter (`_limit`, `_in_use`, `_paused`, `_fatal`) whose predicate every waiter re-checks after each notify, so pause, resize and a fatal monitor error reach agents already queued. It replaced the queue-based TokenPool in 2026-10. An `asyncio.Condition` was the first design; a generation `asyncio.Event` gives the same semantics because the synchronous `release()` and the task done-callback cannot take a Condition's lock.
  - A 5-state machine: RUNNING, THROTTLED, PAUSED, CRISIS, RECOVERING. PAUSED escalates to CRISIS after `crisis_timeout_seconds` without a successful inference ([p3-d-07](#p3-d-07)); crisis recovery ramps toward the baseline ([p3-d-01](#p3-d-01), [p3-d-03](#p3-d-03)).
  - Baseline 8 slots, maximum 16; throttle at 80% used, pause at 90% (thresholds as calibrated in docs/experiments.md "Governor threshold calibration").
  - The memory signal is the macOS kernel's, read through ctypes ([p3-d-12](#p3-d-12)); kernel pressure is the master signal ([p3-d-13](#p3-d-13)). Read failures are fail-stale (F-17).
  - A dead monitor or a D-07 abort is a fatal error raised in every waiter; `stop_monitoring()` re-raises one no waiter saw, unless another exception is propagating. Monitor-loop failures turn into a crisis rather than silently stopping (F-21).
  - Failures are counted per call over a rolling window ([p3-d-04](#p3-d-04)).
  - Note: shrinking slots frees almost no memory with these hybrid-attention models; the governor's job is to prevent stalls under memory pressure, not to reduce footprint.
- **Rationale:** Memory pressure is the main way the M1 Max fails. See [Phase 3 entries](#phase-3-resource-governance-governor-memory-monitor).
- **Cloud mode:** `RateLimitController` replaces the governor through the `ConcurrencyController` protocol.
- **Testing seam (2026-10):** `ResourceGovernor(settings, *, state_store=None, monitor=None)` reads memory through `monitor`, any `MemoryReader` (`memory_monitor.py`, a protocol with one method, `read_combined()`); production leaves it out and gets `MemoryMonitor(settings)`. Tests run the real monitor loop and state machine on scripted readings with `ScriptedMonitor`, `reading()` and `fast_governor_settings()` (`tests/support/monitor.py`: no psutil or sysctl, a zero check interval). The behavioral tests are in `tests/test_governor_concurrency.py`, and `tests/engine/test_scenarios_governor.py` runs one full scenario on the real governor.
- **Fixed defects (2026-10):** the five strict xfails in `tests/test_governor_concurrency.py` (a queued waiter starting while PAUSED, a crisis abort missing queued waiters, `stop_monitoring()` swallowing a fatal error, PAUSED never escalating, crisis exit snapping to baseline) now pass as ordinary tests.

### <a id="adr-taskgroup-dispatch"></a>All agent fan-out uses `asyncio.TaskGroup`, with jitter
- **Decision:**
  - `dispatch_wave` creates one task per persona inside a TaskGroup, with no bare `create_task` (INFRA-07). Narratives are no longer a fan-out: one worker call on an agent's first interview ([p11-d-11](#p11-d-11)).
  - Random 0.5-1.5 s jitter runs before acquiring a slot for cloud providers; local dispatch has none since 2026-10, so prompts reach Ollama in bracket order ([p3-d-14](#p3-d-14), [adr-prefix-reuse](#adr-prefix-reuse)).
  - A failed agent becomes a PARSE_ERROR decision with `error_kind` `"inference"` (the call raised) or `"parse"` (tier-3 parse fallback), and the round continues. Cycle metrics count `r{n}_inference_errors` separately from `r{n}_parse_errors`.
  - Hard stops (`HARD_STOP_ERRORS` in `batch_dispatcher.py`: `BudgetExceededError`, `AuthError`, `GovernorCrisisError`, `ProviderConfigError`) are never converted. `dispatch_wave` unwraps the TaskGroup's `ExceptionGroup` with `except*` and re-raises the first one bare, chained `from` the group; `ensure_decision_narrative` lets them propagate and turns any other inference failure into an interview without a narrative; a failure to store the narrative fails that first interview.
  - Round abort: after `dispatch_wave` and before the round's first Neo4j write, a round in which `failed * 100 > GovernorSettings.round_abort_failure_percent * total` (default 50; `failed` = PARSE_ERROR of any kind) raises `RoundFailedError`; an empty round always fails. Failed agents are not re-dispatched.
  - `SimulationManager._run` turns any non-cancel failure into a `RunError` on `StateStore.last_error` (code, fixed-template message, round, timestamp) and logs it once with `exc_info`; `start()` clears it and cancellation never sets it. Messages never quote exception text, so they cannot leak a path or a key. A failure raised outside that handler (a provider `aclose` in `_run`'s `finally`) sets no `RunError`; the task's done-callback logs it with `exc_info`.
  - New domain errors derive from `AlphaSwarmError`; the `GraphError` family (`Neo4jUnavailableError`, `Neo4jQueryError`, `Neo4jWriteError`) carries an `op` that names the failed operation. `InferenceError`, `BudgetExceededError` and `GovernorCrisisError` keep their parents, so existing `except` clauses behave as before.
- **Rationale:** A spend-cap or auth failure surfaced as "unhandled errors in a TaskGroup (1 sub-exception)" and the UI silently dropped to IDLE, and a dead model server persisted a round of PARSE_ERRORs that later rounds read as peer context (2026-10 audit, T1.2/T1.3).

### <a id="adr-agent-worker"></a>Every worker LLM call goes through the `agent_worker` context manager (Phase 2 rule)
- **Decision:**
  - `agent_worker(persona, governor, provider)` is an `@asynccontextmanager`. It acquires one governor or rate-limit slot, yields an `AgentWorker`, and releases the slot in `finally` (`worker.py:1-9, 226-232`).
  - No raw client calls outside it, except interviews, which bypass the governor ([p14-d-13](#p14-d-13)).
  - The runtime persona is a lightweight `WorkerPersonaConfig` TypedDict derived from the frozen `AgentPersona`, which stays the source of truth (`types.py:WorkerPersonaConfig`).
  - Transient Ollama errors retry with exponential backoff (`ollama_client.py:OllamaClient._chat_with_backoff`); permanent 4xx (400/401/403/404/422) and timeouts are not retried ([adr-cloud-retry](#adr-cloud-retry)).
- **Rationale:** One choke point for concurrency accounting and failure handling. The comments in `worker.py` that cite "CONTEXT.md locked decision" mean this entry.

### <a id="adr-streaming-state"></a>Live state streams per agent; frames are never empty mid-round
- **Decision:**
  - At SEEDING, `run_simulation` calls `StateStore.begin_run(agent_ids)`: the run's roster in config order, every agent pending (`signal=None`). Every frame from then on carries that roster in that order, and `agent_count` is its size (`state.py`).
  - `_safe_agent_inference` writes `update_agent_state` for every resolved agent the moment it finishes, PARSE_ERROR included, and pushes a rationale entry only for real decisions (`batch_dispatcher.py`).
  - On round entry, `StateStore.set_phase` keeps agent keys and resets signals to `None`. The UI renders `None` as pending ("thinking"), never as HOLD; every tally counts decided agents only (`frontend/src/lib/tally.ts`).
  - Rationales live in a persistent `deque(maxlen=50)` and are not drained.
- **Rationale:** Rounds take minutes. The TUI-era "clear and batch-write after the round" contract made the 5 Hz UI look frozen (debug session `ws-agent-states-not-emitted-mid-sim`, fixed in fe366ce, 1da741e, and 0003375). Counting pending agents as HOLD made every round open at "HOLD 100%", and unwritten failures pulsed "thinking" forever (fixed Oct 2026).

### <a id="adr-ws-broadcaster"></a>WebSocket broadcaster: 5 Hz ticks, sent on change, latest-wins per client
- **Decision:**
  - An always-on lifespan task ticks every 200 ms. With no client connected it serializes nothing. With clients it builds a `StateFrame` only when the state version changed (`StateStore.version`, or the replay store's), a client connected, or one second passed since the last frame; that keepalive carries the live memory percent, elapsed time and TPS, which move without a mutation. `broadcast_stats` logs ticks, serializations and skips once a minute (2026-10).
  - `web/wire.py:build_frame` maps the live `StateSnapshot` (or the active replay's) field by field onto frozen pydantic models with `extra="forbid"`; internal dataclasses are never serialized directly. The replay manager's immediate broadcasts use the same path.
  - The frame carries `schema_version` (1), `mode` (`live`/`replay`/`idle`, derived from the phase), `cycle_id` (set right after `inject_seed`, reset on SEEDING), `num_rounds` (the configured depth from process start, so idle frames carry it too), `edges_version` (influence-edge steps finished for the cycle; in replay, round − 1), `jobs` (advisory/report status from the live store, also during replay), `last_error`, the shock fields, and a monotonic `seq` plus wall-clock `ts` on each rationale entry.
  - Adding a field keeps `schema_version`; renaming, removing or changing the meaning of a field bumps it together with the frontend adapter's `SUPPORTED_SCHEMA_VERSION`.
  - `tests/test_wire_contract.py` writes golden frames into `frontend/src/__tests__/fixtures/`; the frontend tests read them, and `tsc` checks their keys against the TypeScript mirror in `frontend/src/types.ts`.
  - Each client gets an `asyncio.Queue(maxsize=1)`: latest-wins, which is still drop-oldest, so a slow client sees the newest frame instead of up to 20 s of backlog (2026-10). Its own writer task cleans up its registry entry in `finally` (B7).
  - Host RAM% is overlaid on every frame ([p999-3-d-01](#p999-3-d-01)).
  - `/ws/state` is unauthenticated, but the handshake Origin is validated (Aug 2026).
- **Rationale:** The simulation must never block on a slow client (CLAUDE.md hard constraint 4). An explicit, versioned frame turns a renamed internal field into a failing test instead of a silently broken UI, and gives the UI the cycle identity it needs to fetch the right cycle's edges. Serializing the ~26 KB frame cost about 1 ms of loop time per tick even with nobody connected (2026-10). Delta frames and orjson were considered and not adopted.

### <a id="adr-replaystore-separate"></a>ReplayStore is separate from StateStore
- **Decision:** Replay builds its own `ReplayStore` (`state.py:474`) inside `ReplayManager`. While replay is active, the broadcaster reads it instead of live state. Replay and live simulation exclude each other (B4). Replay never writes the live StateStore phase: start and stop leave IDLE or COMPLETE as they were, so a replay cannot block a report or a new run ([p34-d-10](#p34-d-10), 2026-10).
- **Rationale:** Reusing StateStore would corrupt the live run. The rationale drain was destructive at the time, and the elapsed timer would restart.
- **Read model (2026-10):** Replay shows every configured bracket in config order, with its display name. Bracket rows count BUY/SELL/HOLD only: `total` and the averages exclude PARSE_ERROR, so a replayed round matches the live frame's `compute_bracket_summaries`. The report's consensus summary, by contrast, gives PARSE_ERROR its own row ([adr-report-react](#adr-report-react)). Rationales come from `Decision.rationale` ([adr-neo4j-schema](#adr-neo4j-schema)).

### <a id="adr-neo4j-schema"></a>Neo4j graph model
- **Decision:**
  - Decisions are nodes ([p4-d-01](#p4-d-01)).
  - Citations are `(Decision)-[:CITED]->(Agent)`.
  - INFLUENCED_BY is **Agent→Agent** with `{weight, cycle_id, round}`, created per round with CREATE, so readers must filter by round (`graph/schema_writes.py`, `_write_influence_edges_tx`).
  - This supersedes Phase 4's planned Decision→Decision INFLUENCED_BY edge.
  - Writes are UNWIND batches. Sessions are opened per operation, only inside `GraphStateManager._read`/`_write` (and `ensure_schema`'s DDL). 100 shared Agent nodes.
  - The `neo4j` driver is pinned below 6.0.
  - Since 2026-10, Post nodes, `AUTHORED`/`HAS_POST` and `(:Decision)-[:FOR]->(:Cycle)` are no longer written; existing ones remain as history and no reader uses them. `RationaleEpisode.rationale` is no longer written (readers use `d.rationale`).
  - The Cycle stores `num_rounds` ([adr-num-rounds](#adr-num-rounds)), `modifiers_json` (the per-cycle persona focus lines) and `prompt_template_hash` (sha256 of the static persona prompt pieces, `compute_prompt_template_hash`) at creation; interviews rebuild the persona from config plus `modifiers_json`.
  - A final-round Decision may carry `narrative`, generated on the first interview of that agent in that cycle ([p11-d-11](#p11-d-11)).
  - REFERENCES link a decision to the cycle's own `(:Entity {name, type})` through `MENTIONS`, matched on whole tokens (`episodes.match_entities`, `match_type: "token"`); a name the cycle lists under two types is skipped. A seed that lists an entity twice still yields one REFERENCES edge per decision.
  - Schema: `decision_id_unique`; indexes `decision_cycle_round`, `decision_cycle`, `influenced_by_cycle_round`, `cycle_created`, `cycle_status`. `ensure_schema` drops `agent_id_idx`, `decision_id_idx`, `post_cycle_round`, `post_id_idx`, `episode_cycle_round` first (the constraint cannot coexist with the old plain index). It deletes no data: the retired `Agent.decision_narrative` property is removed only by `remove_legacy_properties()`, which the owner runs after a backup (`docs/RUNBOOK.md` §3).
  - While `decision_id_unique` does not exist yet, `ensure_schema` first counts duplicate decision ids (read-only). If there are any, it keeps `decision_id_idx` in place of the constraint, logs `decision_id_duplicates_found` with the count (never the ids) and continues; no data is deleted, and the constraint is created on the first start after the duplicates are resolved.
  - **Module layout (Phase 5c).** `alphaswarm.graph` is a package. `manager.py` holds `GraphStateManager`, a facade that owns the driver, the `_read`/`_write` helpers and error mapping and delegates every other method in one line; `schema_writes.py` (schema and all writes), `analytics.py` (report, shock and influence-edge reads) and `replay_interview.py` (replay reads, cycle lookups, interview rows) own the Cypher; `rows.py` holds the TypedDict rows callers read. Influence weights and shock aggregation are pure functions in `alphaswarm/influence.py`; interview context is assembled in `alphaswarm/interview.py` from `AgentInterviewRows`; display glyphs live in `templates/report/_macros.j2`. An import-linter layers contract keeps the graph below interview, report, the engine, services and web.
- **Rationale:** Cycle-scoped edges keep reads fast without pruning history.

### <a id="adr-cycle-metrics"></a>Cycle status lifecycle and per-cycle run metrics
- **Decision:**
  - `Cycle.status` ∈ {`running`, `complete`, `failed`, `cancelled`}. `running` is set in the transaction that creates the Cycle. That write is the last step of seeding, after the persona modifiers are generated and the orchestrator is released, so a seeding failure (teardown included) leaves no Cycle, and nothing runs between that write and `run_simulation` recording the id of the Cycle it must mark. `run_simulation` writes `complete` after the last round is persisted and metrics were attempted, `failed` plus `Cycle.error_code` (a `RunErrorCode`) on any exception, and `cancelled` on cancellation. A status-write failure is logged and never masks the original error. The `failed`/`cancelled` write is bounded to 5 s (`_TERMINAL_STATUS_TIMEOUT_S`): a managed write retries an unreachable database for the driver's 30 s, which would hold Stop or a failed run that long, so on timeout the cycle stays `running` instead. Indexed (`cycle_status`).
  - Listings and defaults filter on status: `read_completed_cycles` and `read_latest_cycle_id()` return `complete` cycles only, and the report, advisory and interview gates read the same status (`read_cycle_status`). Cycles written before the status existed are back-filled idempotently by `ensure_schema()` (`complete` if `metrics_recorded_at` is set or a round-3 decision exists, otherwise `failed`), and every reader applies the same rule to a cycle that has not been back-filled yet.
  - A process killed outright (`kill -9`, OOM), or a terminal write that times out, leaves its cycle `running`; it is never listed as complete ([BACKLOG 1.15](BACKLOG.md)).
  - A Stop or a hard stop during FINALIZING (now only the metrics write, since narratives are lazy) marks a cycle whose rounds are all persisted `cancelled` or `failed`, so it is not listed ([BACKLOG 1.16](BACKLOG.md)).
  - `alphaswarm inject` stores a seed-only cycle that no run will ever finish, so it marks it `failed`, the status the back-fill gives a legacy seed-only cycle.
  - Each round's Decisions, CITED edges, RationaleEpisodes and REFERENCES are persisted by one `GraphStateManager.persist_round` transaction ([p4-d-08](#p4-d-08)).
  - At the end of a run, `write_cycle_metrics` stamps durations, flips, parse errors, `r{n}_inference_errors` (the subset of `r{n}_parse_errors` whose `error_kind` is `"inference"`, for the rounds actually run), `r{n}_citations_dropped`, `final_round` and the final distribution onto the Cycle node. A metrics-write failure is logged and does not block `complete`. Compare runs with `scripts/compare_cycles.py` against `scripts/benchmark_seeds.json`.
- **metrics_version 2 (2026-10):** the run clock starts at the top of `run_simulation`, so `total_seconds` includes seeding; `seed_seconds` is the time from that start until Round 1 begins (seed and modifier calls, market context, worker load). Version 2 also adds the per-round inference telemetry keys of [adr-inference-telemetry](#adr-inference-telemetry). Readers key off the presence of a key, never off the version alone.
- **metrics_version 3 (2026-10):** every round also carries the consensus and dispersion estimators of [adr-consensus-estimators](#adr-consensus-estimators) (`r{n}_net_score_*`, `r{n}_entropy`, `r{n}_polarization`, `r{n}_stdev`, `r{n}_trans_*`, `r{n}_conformity_rate`, `r{n}_mean_abs_conf_delta`, `r{n}_citation_gini`). Undefined estimators are omitted, so readers key off the presence of a key. A failure in these derived numbers is logged and never blocks the other metrics.
- **Provenance and peer keys:** each cycle also records `orchestrator_provider` / `worker_provider` (`ollama` for local providers, `cloud` otherwise; the model id identifies the cloud provider), `orchestrator_model`, `worker_model`, `inference_mode` (`local` / `cloud` / `mixed`), `git_sha` (empty when unknown) and `git_dirty` (omitted when unknown, because a Neo4j property cannot be null), the effective peer parameters (`peer_selection_version`, `peer_limit`, `peer_min_brackets`, `peer_bracket_cap`, `peer_budget_chars`, `peer_personal_boost`, `peer_seed_source`), the experiment knobs `own_prior_memory` and `control_fraction`, and the per-round exposure and holdout keys from [adr-diverse-peer-context](#adr-diverse-peer-context). Older cycles lack these keys, so every reader must tolerate missing keys. `git_revision` lives in `alphaswarm/manifest.py`; `current_git_revision` reads it once per process, and the web lifespan makes that read at startup, so a server stamps the revision whose code it runs even after a later commit.
- **Rationale:** Completion used to be inferred from `metrics_recorded_at` or a round-3 decision, so finished 2-round cycles could vanish, crashed cycles lingered, and `alphaswarm report` could default to a running cycle. A/B experiments (rounds, peers, models) need durable numbers; all history before June 2026 was lost (see [adr-tests-scoped-cleanup](#adr-tests-scoped-cleanup)).

### <a id="adr-consensus-estimators"></a>Consensus and dispersion estimators (Phase 7)
- **Decision:** "Consensus" is a net score `S = Σ w·s·c / Σ w` over decided agents (`s` = +1 buy, 0 hold, −1 sell; `c` = confidence; PARSE_ERROR excluded), reported under three weightings: headcount (`w = 1`), reach (`w = influence_weight_base`, see [adr-influence-weight-reach](#adr-influence-weight-reach)) and bracket-equal (`w = 1 / decided agents in the bracket`). A score above `+0.15` leans BUY, below `−0.15` SELL, otherwise HOLD. Uncertainty is a 1,000-draw percentile bootstrap over agents (95%; stored for headcount only). Dispersion is the Shannon entropy of the decided shares normalized by `ln 3` and the population standard deviation of `s·c`; polarization is `4·p_buy·p_sell`. Code: `alphaswarm/consensus.py`, `alphaswarm/metrics.py`; the TypeScript mirror `frontend/src/lib/consensus.ts` is pinned to the Python numbers by `frontend/src/__tests__/fixtures/consensus_cases.json`.
- **Rationale:** The UI ring was a raw plurality, the adapter's `consensus` was an unread mean, and the metrics stored only final counts, so neither confidence nor reach entered any aggregate. One documented estimator shared by metrics, advisory and UI makes runs comparable and lets the evaluation harness ([adr-eval-harness](#adr-eval-harness)) score a single number.

### <a id="adr-run-manifest"></a>Run manifest, run seed and experiment controls (2026-10)
- **Decision:**
  - Every experiment knob is a bounded `ALPHASWARM_SIMULATION__*` setting (`peer_strategy`, `own_prior_memory`, `market_context_rounds`, `show_bracket_labels`, `show_confidence`, `uniform_temperature`, `control_fraction`, `shock_treatment_split`, `sim_seed`, `experiment_tag`, `retest_round1`), so a bad value fails at startup, before any model loads or any Cycle is written.
  - Every cycle stores a `RunManifest` as JSON on the Cycle (`run_manifest_json`, schema `alphaswarm.run-manifest/1`, plus `sim_seed` and an indexed `experiment_tag`), written after seeding and before Round 1 so a run that fails later is still described; a failed manifest write fails the run. It holds the git SHA and dirty flag, the provider type, model and Ollama digest of each role (from `InferenceRuntime.run_provenance`; the provider protocol's labels when no composition root supplies them), the inference mode, a hash of the bracket table and of each prompt text, the generated modifiers, the exact market block, `num_rounds`, every `SimulationSettings` knob, `sim_seed` and `experiment_tag`. Unknown fields are rejected and nothing secret is recorded: no keys, base URLs, file paths or holdings. Digest lookups are best effort: an unreachable Ollama leaves the digest unknown.
  - `sim_seed` (the setting, else a blake2b derivation of the cycle id, in `[1, 2^31-1]`; never `hash()` or wall-clock time) seeds peer sampling (`run_seed = str(sim_seed)`; metric `peer_seed_source = "sim_seed"`, older cycles say `"cycle_id"`), the control holdout, the shock arm and every worker call (`derive_call_seed(sim_seed, agent_id, round)`, sent as Ollama `options.seed` or the OpenAI-compatible `seed` field; Anthropic has no seed). A server that rejects `seed` gets one retry without it and stays unseeded for the provider's lifetime (`seed_parameter_unsupported`).
  - Seeds narrow run-to-run variation but do not remove it: Ollama's NUM_PARALLEL batching is not bit-exact, and the orchestrator's seed-parsing and modifier calls are not seeded (their outputs are in the manifest). Results are therefore reported over several seeds with bootstrap intervals (`docs/experiments.md`); `scripts/compare_cycles.py --group-by experiment_tag` groups the cycles.
  - From Round 2 on, each agent sees its own previous decision ([adr-diverse-peer-context](#adr-diverse-peer-context), "Own prior"). The market block reaches rounds 1..`market_context_rounds` ([adr-market-context](#adr-market-context)).
  - A seeded share of every bracket (`control_fraction`, round-half-up, never a whole bracket) is held out from peer context for the whole run and stored as `d.control` in every round. Peer-attributable flips are the treated flip rate minus the control flip rate, as the mean of per-cycle differences with a bootstrap interval over cycles (`scripts/peer_effect.py effect`); a PARSE_ERROR on either side of a round pair is not a flip. `retest_round1` draws Round 1 a second time with the same prompts and different call seeds (never persisted or streamed); `r1_retest_flip_rate` is the noise floor. `shock_treatment_split` shows active shocks to a seeded half of each bracket only (`d.shock_treated`; `r{n}_pivots_shock_treated` / `_untreated`).
  - Exposure is persisted per decision (`d.peer_ids`, in display order; `[]` in Round 1 and for control readers). A citation is kept only when it names a peer the reader was shown (case and whitespace ignored, no self-citations, no duplicates); dropped ones are counted (`d.citations_invalid`, `r{n}_citations_invalid`, `r{n}_citation_validity_rate`), and only the kept ones reach the CITED edges, the influence edges and the next round's personal boost. For analysis, influence is the citation rate given exposure with a Beta(1, 1) prior (`alphaswarm.metrics`; per bracket as `r{n}_cite_rate_<bracket>`). The INFLUENCED_BY weight ([p8-d-01](#p8-d-01)) is unchanged.
  - Ablation knobs: `peer_strategy` (`stratified`, `random`, `none`), `show_bracket_labels`, `show_confidence`, `uniform_temperature`.
- **Rationale:** A flip between rounds used to mix peer influence with information loss, missing memory and sampling noise, and nothing recorded which models, prompts or settings produced a cycle. With a manifest, a control arm and a noise floor, the headline claim (peers move opinions) becomes a measured, re-runnable effect.
- **Evidence:** docs/experiments.md, sections P7.1 and P7.3 (not run yet).

### <a id="adr-eval-harness"></a>Point-in-time evaluation harness (P7.7, P7.8)
- **Decision:**
  - Accuracy is measured on 15-20 historical public events (`eval/events.jsonl`) against 1- and 5-day abnormal returns with a volatility-scaled flat zone (`eval/label_outcomes.py`, `alphaswarm.evaluation.compute_outcome`).
  - Runs are point-in-time: `alphaswarm run --context-fixture` replaces the live yfinance/RSS fetch with a committed `ContextPacket` holding only the last close at or before the event and curated headlines published before it. Fundamentals are refused because the providers only expose current values.
  - The fixture packet goes straight to the shared formatter instead of through the Fake market and news providers, so the block an event's agents see does not depend on which entities the orchestrator happens to extract or resolve: every run of an event sees byte-identical context.
  - Every evaluation and ablation cycle is seeded (`sim_seed` 2101-2103), tagged (`p77.*`, `p78.*`) and run without the control holdout (`control_fraction = 0.0`); scoring reads stored decisions and run manifests, never logs, and compares settings against the defaults frozen at registration (`eval/registered_simulation.json`).
  - Baselines in cost order: the orchestrator's `overall_sentiment`, the Round 1 aggregate of the same cycles, one worker call sampled 5 times, and compute-matched self-consistency. The Narrators bracket is scored separately as well as inside the swarm.
  - Metrics, thresholds and gate rules are pre-registered in `docs/methodology.md` before any run.
- **Rationale:** Without ground truth nothing shows that 100 interacting personas beat one model, and live data providers would leak post-event prices and headlines into a historical replay.
- **Sessions (2026-10):** An event's base close, for its label and its fixture, is the last session close at or before the event. Sessions close at 16:00 New York time, or at 13:00 on the NYSE's regular early-close days: the day after Thanksgiving, and July 3 and December 24 from Monday to Thursday (`alphaswarm.evaluation.session_close_utc`). Without the early close, an event between 13:00 and 16:00 on such a day would take the previous session as its base, so the 1-day label would measure a move that ended before the event. Decided 2026-10 under the owner's delegation.
- **Status (2026-10):** The harness code is built: records, labels, scoring statistics and gate rules in `alphaswarm.evaluation`, fixtures in `alphaswarm.ingestion.fixture`, `alphaswarm run --context-fixture` and `--no-market-context`, and the `eval/` scripts `build_fixtures.py`, `label_outcomes.py`, `run_eval.py` and `baselines.py`. The fast-track `eval/pilot.py` was removed; its unseeded, untagged cycles stay in Neo4j and are never scored. Not done yet: the curated event set with its fixtures and labels, `eval/registered_simulation.json` and the evaluation runs, which are the owner's (docs/RUNBOOK.md).

### <a id="adr-holdings-isolation"></a>Holdings isolation: the swarm never sees the portfolio
- **Decision:** Portfolio data never enters swarm prompts, Neo4j, WebSocket frames, or logs. It reaches only the post-simulation advisory call. Enforcement:
  1. An import-linter `forbidden` contract allows only `alphaswarm.advisory`, `alphaswarm.web.routes.holdings` and `alphaswarm.services.advisory` to reach `alphaswarm.holdings` (`pyproject.toml [tool.importlinter]`; [p37-d-04](#p37-d-04)). The service may import only `alphaswarm.holdings.types`, never the loader; the portfolio reaches it through an injected `PortfolioCache.get`. The advisory route reaches holdings only through AdvisoryService (2026-10).
  2. A four-surface sentinel canary runs the real `synthesize()` (`tests/invariants/test_holdings_isolation.py`). A second canary runs AdvisoryService.generate() and checks its logs (tests/invariants/test_holdings_isolation.py).
  3. A fail-closed structlog PII redactor ([p37-d-05](#p37-d-05)..[p37-d-07](#p37-d-07)). Tracebacks are rendered without local variables in both modes (JSON: `ExceptionDictTransformer(show_locals=False)`; console: structlog's plain-text `format_exc_info`), so frames never leak keys or portfolio objects, and both render before the redactor, so it also scrubs the traceback text (2026-10). Since 2026-10 the redactor also replaces API-key shapes (`sk-…`, `nvapi-…`, `Bearer …`) in every logged string at any depth, whatever its key, because free-text error fields, exception text and bridged stdlib messages can carry a key past the key-name rules.
  4. Holdings are loaded into memory at lifespan startup (`PortfolioCache`, re-read when the CSV changes) and never persisted ([p39-d-07](#p39-d-07)).
  5. The owner's curated sector map lives in the gitignored `data/sector_map.local.json`; the repository ships only the fictional `examples/sector_map.example.json`. `scripts/ticker_scan.py` (count-only) checks that `src/`, `tests/` and `frontend/src/` name none of the owner's tickers (2026-10).
  6. Validation errors (2026-10): `str()` and `repr()` of a pydantic `ValidationError`, and so its rendered traceback, echo the input values, which on the advisory path can be tickers or a cost basis. Wherever the advisory logs a failure with a `ValidationError` on its cause or context chain (the service's failure line, the JobRunner's `job_failed` line, the post-run pipeline), it logs `alphaswarm.logging.validation_error_summary` instead: the error count, up to ten dotted locations (an extra key's own name masked) and the sorted error types, never `exc_info`. `chat_structured` logs only a problem count per invalid reply, and its correction turn names locations and pydantic's messages, never the values or the rejected reply. A reply that never validates raises `StructuredOutputError`, whose message names only the output model and the attempt count and whose chain holds no `ValidationError`. HTTP bodies carry fixed text only.
- **Rationale:** Uncontaminated consensus, plus privacy for real brokerage data.
- **Gate:** `uv run lint-imports` runs in the CI `lint` job and as a pre-commit hook, and `tests/invariants/test_importlinter_contract.py` runs it inside pytest. Ruff, mypy and vulture are gated in the same job.

### <a id="adr-provider-never-raise"></a>Market/news providers never raise
- **Decision:** `MarketDataProvider` and `NewsProvider` use batch-first signatures. Failures become `staleness="fetch_failed"` slices. Fakes live next to the protocols ([p37-d-17](#p37-d-17)..[p37-d-20](#p37-d-20)).
- **Implementations:**
  - yfinance per ticker via `to_thread` + gather.
  - RSS: Yahoo Finance for tickers, Google News otherwise.
  - No caching. Both feed a `DataSourceAuditBuffer` that the Signal Wire shows.

### <a id="adr-market-context"></a>Grounded market context: every round by default, fenced
- **Decision:**
  - One formatted block per run: price, fundamentals, and 5 headlines per entity.
  - Sent in rounds 1..`market_context_rounds` (default 3, i.e. every round; revised 2026-10 under the owner's delegation), announced by the fixed MARKET_CONTEXT_GUARD system message and fenced as untrusted data in the user message (since F3, Aug 2026), ahead of the fenced peer block. RSS headlines are sanitized.
  - Phase 7: entities are ordered by relevance and a block that would overflow the budget is skipped, not the rest; only swarm-resolved tickers ([adr-ticker-resolution](#adr-ticker-resolution)) are priced and get the Yahoo feed; prices join their company by ticker and show the quote time and a stale marker. Code: alphaswarm/market_context.py, context_formatter.py.
- **Rationale:** Treat third-party text as untrusted. Dropping the block after Round 1 ([Phase 40](#phase-40-simulation-context-wiring)) confounded every Round 2 flip with information loss ([adr-run-manifest](#adr-run-manifest)); the original reason for the Round 1 limit was never recorded. Keeping it costs the block's prompt tokens on every call of Rounds 2..N; that cost is not measured yet (the A0 baseline in docs/experiments.md records `r{n}_mean_prompt_tokens`). `market_context_rounds=1` restores the Round 1-only behaviour for ablations.

### <a id="adr-ticker-resolution"></a>Seed-entity tickers are resolved on the swarm side (Phase 7)
- **Decision:** The seed schema carries an optional `ticker` per entity (normalised to 1-5 capital letters; anything else becomes `null`). `alphaswarm.ingestion.tickers.TickerResolver` decides which symbols the swarm may use: only `company` entities get one; with the cached SEC map (`data/sec_tickers.json`, fetched once with `scripts/fetch_ticker_map.py`, gitignored) a proposed symbol is kept only when its SEC title agrees with the entity name, and names resolve through the map; without the map a symbol is trusted unless it is a known non-company acronym (FED, OPEC, …). A missing or unreadable map degrades to that no-map rule and never fails a run. The resolved ticker is stored on the cycle's `MENTIONS` edge and is the key of the advisory's entity→holding join; price fetches, news routing and the decision prompt are meant to use the same resolved value.
- **Rationale:** The orchestrator emits company names, so prices almost never reached agents and acronyms were routed to the per-ticker news feed. The swarm side must never use portfolio-derived aliases (holdings isolation, [adr-holdings-isolation](#adr-holdings-isolation)); `tests/invariants/test_swarm_ticker_resolution.py` keeps `alphaswarm.advisory` out of these modules.

### <a id="adr-advisory-pipeline"></a>Advisory synthesis
- **Decision:**
  - Prefetch swarm data in parallel, then make one orchestrator call, decoded through `chat_structured` into `AdvisoryLLMOutput` with the tickers restricted to the prompt's ([p41-d-04](#p41-d-04), [p41-d-05](#p41-d-05), [p41-d-06](#p41-d-06)).
  - Relevance scoring uses a curated ticker→sector map read per run from `data/sector_map.local.json` (fallback: the fictional example; invalid file: empty map) plus an entity-impact join. Entity names resolve only to held tickers, and the `unknown` sector never earns a seed bonus (F-07, F-28; 2026-10).
  - The LLM receives only the top 15 held tickers by relevance, one entry per ticker with sector tags; quantities and cost basis stay server-side (2026-10, [p41-d-05](#p41-d-05)).
  - Every holding without a conviction item is padded server-side as HOLD@0.30 and marked source=placeholder; overview stats exclude placeholders (SWEEP B-7). items[] has exactly one entry per holding.
  - Unknown tickers default to `macro_beta` 0.5 (SWEEP B-8).
  - Ranking: confidence × cost basis / total cost basis; the displayed signal comes from swarm evidence when at least 3 agents referenced the company ([adr-grounded-advisory](#adr-grounded-advisory)).
  - Output goes to `advisory/{cycle_id}_advisory.json`, served by a 202 + polling API over JobRunner jobs. Files are written atomically as owner-only (0600) and only the newest `ALPHASWARM_ADVISORY_KEEP_LAST` (default 20) are kept, because they hold cost-basis exposure (2026-10, SPEC T7.4).
  - Runs from PostRunPipeline after every completed run when holdings are loaded (cloud orchestrator: only with the opt-in); the report runs afterwards in every case, including no holdings and advisory failure. Holdings come from PortfolioCache, which re-reads the CSV when its mtime changes.
  - Advisory failures, `AuthError` and `BudgetExceededError` included, are recorded for GET (500 `advisory_generation_failed`, with a message that names only the exception class) and do not stop the report. This is deliberate: the report needs no holdings and must not be lost to an advisory failure (2026-10).
  - Failure logging (2026-10): the job's own line (`advisory_generation_failed`) carries the exception class (and, for a validation error, the `validation_error_summary` fields), never a traceback. JobRunner's done-callback (`job_failed`) logs an advisory job's exception class and validation summary only, never a traceback. The post-run pipeline (`auto_advisory_failed`) logs the traceback, except when a pydantic `ValidationError` is anywhere on the exception's cause or context chain: then they log `exc_type` plus `validation_error_summary` fields and no `exc_info` ([adr-holdings-isolation](#adr-holdings-isolation), item 6). Other exceptions keep their traceback, message included, for diagnosis; the redactor scrubs key shapes and holdings-named fields from it, not arbitrary text.
  - Runs only when the orchestrator is local or `allow_cloud_advisory` is true in the inference config. Local means all three of: provider Ollama; not an Ollama cloud model (any dash- or colon-separated part of the name or tag that is exactly `cloud`, e.g. `gpt-oss:120b-cloud`, `glm-4.6:cloud`, `foo-cloud:latest`; this over-blocks a few odd local names on purpose); and a loopback Ollama server (`localhost`, 127.0.0.0/8 or `::1`). The server checked is read from the shared `OllamaClient` itself (`OllamaClient.base_url`, the httpx host after ollama resolved `AppSettings.ollama.base_url` or `OLLAMA_HOST`), so the check and the connection read the same value. A non-loopback `base_url` on the orchestrator role also counts as remote, even though `OllamaProvider` ignores it today. Anything unparseable, and host spellings such as 0.0.0.0, `127.1` or `0x7f000001`, fail closed (`inference/factory.py:advisory_block_reason`, 2026-10-21); the refusal log carries `reason` (`cloud_provider`, `role_base_url_remote`, `cloud_model`, `remote_host`, `remote_model`). A name cannot reveal an alias whose Modelfile is `FROM` a cloud model, and the default `alphaswarm-orchestrator` is such an alias, so before synthesis the job also asks the server (`OllamaClient.is_remote_model`, raw `/api/show`; newer servers set `remote_host`/`remote_model` for cloud models) and refuses when it reports a remote model or the request fails. The `OllamaClient` httpx client sets `trust_env=False` (an `HTTP_PROXY`/`ALL_PROXY` or macOS system proxy gets no localhost bypass in httpx and would receive the prompt) and `follow_redirects=False`. The opt-in is the **Allow cloud advisory** checkbox in Settings → Model (`PUT /api/settings` `allow_cloud_advisory`; omitted or null keeps the stored value), saved in the inference config. The checkbox is shown when the orchestrator looks off this machine from its settings, or when the opt-in is already on so it can be cleared; for what the settings cannot show (an alias of a cloud model, a remote `OLLAMA_HOST`) the key is set in `.secrets/inference.json`. With the opt-in on, the UI never says the holdings stay on this machine, because the opt-in also skips the host and `/api/show` checks. Otherwise the POST returns 409 `cloud_advisory_disabled` before the holdings are read, the job refuses as well, and the post-run pipeline skips the advisory and logs `auto_advisory_skipped_cloud` (T7.2, 2026-10). The POST route and the pipeline share `services/advisory.py:AdvisoryService.gate`, and both record a refusal on the JobRunner (`JobRunner.record_refusal`), so GET returns `cloud_advisory_disabled` with the fixed message instead of a pending 404; a job refused under the lock records the same code. An unreadable inference config fails closed with 422 `inference_config_invalid`; the post-run pipeline records it the same way (GET returns `inference_config_invalid`), counts the advisory as `failed` and still runs the report.

### <a id="adr-grounded-advisory"></a>Advisory signals come from the agents, not from the orchestrator's reading (Phase 7)
- **Decision:** For each holding the advisory reads the final-round decisions whose rationale referenced the company (`read_final_round_decisions`; the swarm-resolved `MENTIONS.ticker` first, the advisory sector map only for unresolved company names). With at least 3 supporting agents the displayed signal is the lean of their headcount net score ([adr-consensus-estimators](#adr-consensus-estimators)) and the confidence is agreement-weighted (Σ confidence of agreeing agents ÷ support). The orchestrator still writes the outlook and rationales; its own per-holding signal is stored as `llm_signal` and a disagreement sets `divergent`. Items carry `swarm_support`, `swarm_sentiment` and `evidence_agent_ids`. `position_exposure` is renamed `cost_basis_exposure` (files written before keep validating). The swarm evidence and the cost-basis labels are computed in Python and appear only in the advisory file and the advisory route response, never in a prompt, the graph, a WebSocket frame or a log; the advisory prompt keeps its minimised input ([adr-holdings-isolation](#adr-holdings-isolation)).
- **Holdings are not priced (decided 2026-10 under the owner's delegation):** the advisory does not fetch market prices for held tickers, because that would send the portfolio's tickers to Yahoo; exposure stays cost basis and is labelled as such.
- **Rationale:** The per-holding signal was the LLM's opinion of bracket aggregates, so recommendations could not be traced to agents or reproduced, the UI's agent count was a regex over prose, and "value" was cost basis.

### <a id="adr-report-react"></a>Report: deterministic data plus one grounded narrative call
- **Decision:**
  - `report.collect_report_data` runs every report read concurrently with the cycle id bound server-side; the model never chooses a query or a cycle.
  - One orchestrator call through `chat_structured` writes the executive summary, key moments, dissent and follow-ups (`ReportNarrativeLLMOutput`); list items naming agents absent from the data are dropped. A reply that never validates yields a tables-only report.
  - `render_report` renders the Jinja section templates under `StrictUndefined`; `build_sections` returns the convergence and influence rows the UI charts. Files: `reports/{cycle_id}_report.json` (sections) then `reports/{cycle_id}_report.md`, both atomic.
  - `services.report.ReportService` wraps `report.generate_report` in the orchestrator lock and the provider lifecycle; the web report job runs through it (`JobRunner`), and `GET /api/report/{id}` returns the sections next to the markdown (`sections: null` for a report without a readable sidecar). The CLI `report` command runs the same service inside `open_runtime`.
- **Rationale:** the ReAct loop spent up to ten orchestrator calls choosing among eight fixed queries and its text never reached the report (T5.1). **Superseded** the prompt-based ReAct loop (2026-10): one call now, measured with `ScriptedProvider` in `tests/test_report_pipeline.py`.
- **Update (2026-10):** Report reads return typed rows (the row TypedDicts in `graph/rows.py`, such as `ConsensusSummaryRow` and `ShockImpactRow`), and templates render under Jinja `StrictUndefined`. A template that reads a key its query does not return now fails the report instead of rendering a blank column. Free text goes through the `md_cell` filter (pipes escaped, whitespace collapsed) and numbers through `num` (fixed digits, "—" for a missing value).
  - Reads describe the final round ([adr-num-rounds](#adr-num-rounds)), and the timeline covers every round that ran. PARSE_ERROR has its own row in the consensus summary and its own column in the timeline, so the shares add up to 100%.
  - Failed (PARSE_ERROR) agents are excluded from dissenters, bracket stances and averages, entity impact, and shock pivots. A bracket where every agent failed has no majority ("—").
  - "Influence Weight" became `influence_share` = citations / active final-round agents, which is the [p8-d-01](#p8-d-01) edge weight.
  - Signals in the typed report rows are upper-case (`BUY`, `SELL`, `HOLD`). Replay rows stay lower-case because they map onto `SignalType`.
  - The shock section analyses only the earliest shock of a cycle. A second shock queued before Round 3 is not analysed.
  - Entity impact counts only the cycle's own `MENTIONS` entities, once per (entity, decision) pair ([p11-d-08](#p11-d-08)).
  - The `social_post_reach` section (its tool, template `08_social_post_reach.j2`, prompt line and registry entries) was removed: READ_POST edges have not been written since June 2026, so the section was always empty.

### <a id="adr-background-tasks"></a>Long LLM jobs: 202 + background task + polling
- **Decision:** Report and advisory POSTs return 202 and run `asyncio` tasks.
  - POST gates on durable state: 409 `simulation_running` during a run, 404 `cycle_not_found` for an unknown cycle, 422 `cycle_not_ready` unless the cycle reads as complete (`GraphStateManager.read_cycle_status`: a stored `Cycle.status` when there is one, else metrics stamped or a round-3 decision), 409 `*_generation_in_progress` while the orchestrator slot is taken. The in-memory phase is not consulted, so historical cycles work after a restart or a replay.
  - `services.jobs.JobRunner` runs the report and advisory jobs one at a time and records idle/running/failed in the StateStore (`JobStatus` per job kind) and a failure code per cycle, which GET answers with 500 and a fixed message ([T-36-15](#t-36-15) successor).
  - GET returns 200 with the file, 409 `*_generation_in_progress` while that cycle's job runs, 500 after a recorded failure, 404 otherwise. File probes are async (T-36-14); writes are atomic (`fsutil.atomic_write_text`).
  - Cycle ids are validated by the `CycleId` uuid4 path type (`web/params.py`); malformed ids return 422 `validation_error` (T-36-01). Every error uses the envelope from `web/errors.py`.
  - The report modal polls only on 409 `report_generation_in_progress`; `usePolling` keeps at most one request in flight (F-16) and surfaces timeouts ([p41-6-d-19](#p41-6-d-19)).

### <a id="adr-cli-ux"></a>CLI: stdout for output, stderr for logs, fixed exit codes
- **Decision:**
  - structlog writes to the `sys.stderr` current at each write; stdout carries only command output (tables, report paths, help).
  - Every subcommand runs through `cli._run_command`. Exit codes: `0` success, `1` runtime failure, `2` usage or configuration error (argparse errors, `pydantic.ValidationError` from settings, `InferenceConfigError`), `130` interrupted (Ctrl-C). Tracebacks print only with `-v/--verbose`, accepted before or after the subcommand. Bare `alphaswarm` prints help and exits 0. A handler that raises `SystemExit` on purpose (after printing its own message) keeps its exit code.
  - Exit code 75 when another AlphaSwarm process holds the instance lock; the message names it ([adr-instance-lock](#adr-instance-lock)).
  - `alphaswarm report` takes the cycle id positionally (as the README documents) or with `--cycle`; two different ids are a usage error.
- **Rationale:** JSON log lines interleaved with the CLI's tables on stdout, so piping a command captured both. Every failure, Ctrl-C included, exited 1 without a traceback, and bare `alphaswarm` printed a banner. The documented `report <cycle_id>` did not parse.
- **Not chosen:** logging from the runner. It would run before logging is configured for configuration errors and land on stdout; the code that failed logs its own error.

### <a id="adr-web-lifespan"></a>Web process shape
- **Decision:**
  - Uvicorn owns the event loop. `services.runtime.open_runtime` is the one composition root for the CLI and the lifespan: it configures logging, builds AppState, the InferenceRuntime and the JobRunner, applies the Neo4j schema and tears everything down through one `AsyncExitStack` ([p29-d-04](#p29-d-04)).
  - `create_app(settings=None, *, runtime_factory=None)` stores the settings on `app.state.settings`; nothing is constructed at import time, and the module has no module-level `app` (pytest imports it before its hermetic fixture runs, so an import-time app would keep the operator's settings, holdings path included). `None` reads the environment and `.env`. The single documented launcher is `alphaswarm web` (`uvicorn.run("alphaswarm.web.app:create_app", factory=True, workers=1)` on 127.0.0.1:8000); `./start` (cds to the repo root, then runs `python -m alphaswarm web`) and `uv run start` (`cli:main_web`) call it. Both hold the instance lock ([adr-instance-lock](#adr-instance-lock)).
  - The lifespan enters `runtime_factory` (default `open_runtime`) and `wire_web_state` builds the services, the post-run pipeline, the managers and the broadcaster on top of it, registering every teardown on the same stack: a startup failure still closes the runtime. Route tests build their apps through the same `wire_web_state`.
  - Shutdown order: broadcaster, simulation and post-run task, interview providers, jobs, the Ollama HTTP pool, the Neo4j driver.
  - Each domain has a sub-router.
  - Startup verifies Neo4j and runs `ensure_schema()` (constraints, indexes, and the 100 Agent nodes every write matches). Driver or auth errors log `neo4j_unavailable_at_startup`, set `neo4j_ready = False`, and the server keeps serving (2026-10).
  - FastAPI serves `frontend/dist` at `/` when it has been built ([p31-d-02](#p31-d-02)); without a build, `/` serves a short HTML page with the build command (2026-10). In development, Vite on :5173 proxies `/api` and `/ws`, with `changeOrigin: true` on both. When the backend is down, the `/api` proxy answers 502 `backend_unreachable` (`frontend/src/lib/backendUnreachable.ts`) instead of an empty 500, so the UI shows the same "Cannot reach the backend" hint as a failed fetch.
  - Runtime paths (`.env`, the holdings CSV, `.secrets/inference.json`, `advisory/`, `reports/`) resolve against the repository root (`config.PROJECT_ROOT`, `AppSettings.resolve_path`), so the server may start from any directory.

### <a id="adr-instance-lock"></a>One AlphaSwarm process at a time (per-user `flock`)
- **Decision (2026-10):** `alphaswarm web` (and `start`) and the CLI's `run`, `inject` and `report` take one `fcntl.flock` on `~/.alphaswarm/instance.lock` (override: `ALPHASWARM_INSTANCE_LOCK`) without blocking and hold it for their whole run. A second one exits with code 75 and names the holder (command, pid, start time, URL). `doctor` takes no lock. The server starts only through `alphaswarm web` / `start` (`workers=1`); a hand-written `uvicorn` command skips the lock.
- **Rationale:** each process unloads the shared aliases at its own idle gaps, so a CLI report during a web run evicted the web job's model. The kernel releases a `flock` when the holder exits, even after SIGKILL, so there is no stale state to clean up.
- **Rejected (2026-10 audit):** a cross-process ModelLease with pidfiles and `expires_at` heuristics; a lock inside the FastAPI lifespan (every in-process test app would contend for it).
- **Where:** `instance_lock.py`; `cli.py` (`LOCKED_COMMANDS`, `EXIT_LOCKED`); `scripts/backup_neo4j.sh` refuses to stop Neo4j while a CLI command holds the lock.

### <a id="adr-frontend-quant-terminal"></a>Frontend: React + TS "Quant Terminal"
- **Decision:**
  - React 19 + Vite 6 + TypeScript, ported from the AlphaSwarm-2 design export (Phase 41.6).
  - Split React contexts (Connection, Telemetry, Agents, Rationales, Edges, FrameMeta) so 5 Hz frames do not re-render everything. Influence edges load once per (cycle, round, edges_version) through `EdgesContext`, keyed on the frame's cycle id, and every panel reads that one copy.
  - The lifecycle (idle, seeding, live, complete, replay) comes from the frame, so the shell, Run/Stop and the replay bar look the same after a reload; idle and seeding are overlays inside the canvas.
  - While the post-run advisory/report jobs hold the orchestrator (frame `jobs`), Run is disabled and reads "Report generating…" / "Advisory generating…": a new run would evict the orchestrator mid-report. The backend refuses the start with 409 `post_run_jobs_in_progress` anyway (decided Oct 2026 under the owner's delegation).
  - React-rendered SVG with a deterministic layout instead of d3-force ([KR-41.1-01](#kr-41-1-01)); `d3-scale` is the only D3 module. `d3-selection` and `d3-transition` were never imported and were removed (2026-10).
  - The agent graph lives in `frontend/src/viz/` ([adr-hero-graph](#adr-hero-graph)).
  - One overlay slot: the shell holds a single `ActiveModal` discriminated union rendered by `ModalHost` (`frontend/src/app/ModalHost.tsx`), so takeovers never stack; the interview is addressed by agent id and opens only while that agent is in the live roster.
  - Feature folders (`frontend/src/features/<name>/`) composed by `frontend/src/app/`; features never import each other. TypeScript only with `noUncheckedIndexedAccess`; enforced by `frontend/src/__tests__/invariants/structure.test.ts`.
  - No design mocks or placebo controls ship: the mock data, the dev Tweaks panel and handler-less buttons were deleted (2026-10). Every on-screen value comes from the frame, REST or config; an ESLint rule rejects a `<button>` without a handler and knip gates dead code in CI ([KR-41.6-14](#kr-41-6-14)).
  - Fonts (IBM Plex Sans, JetBrains Mono) are self-hosted through `@fontsource`, which fits local-first.
  - Tests and lint (`frontend/TESTING.md`): vitest runs pure tests in node and hook/component tests on happy-dom with React Testing Library; backend-written golden frames pin the wire contract ([adr-ws-broadcaster](#adr-ws-broadcaster)); ESLint (typescript-eslint, react-hooks; jsx-a11y at `warn` until the accessibility pass) runs in CI. ESLint stays on 9.x while eslint-plugin-jsx-a11y supports nothing newer.
- **History:** Textual TUI, then Vue 3 + D3 force graph, then a React port of the Claude Design UI, then the AlphaSwarm-2 Quant Terminal. See HISTORY.md.

### <a id="adr-hero-graph"></a>Hero influence graph: overview first, details on demand
- **Decision (2026-10):**
  - Positions are a pure function of the static roster (registry order, ids sorted), the canvas size, the layout and the reserved corners (`frontend/src/viz/layout.ts`): Clusters (phyllotaxis-packed bracket clusters on a ring), Radial (one labelled ring per bracket) and Grid. Frame order never moves a node, so live and replay draw identical positions. Still no physics ([KR-41.1-01](#kr-41-1-01)). Unknown agent ids get an "Unknown" cluster.
  - Default view (owner's small-decisions delegation, 2026-10-23): bracket-to-bracket ribbons (`aggregateByBracket`; width ∝ √count; colour of the cited bracket), `DEFAULT_ALL_EDGES = false`. Hovering or clicking an agent draws its ego network: peers it cited and peers citing it in two colours, everyone else dimmed. "All edges" draws every citation coloured by the citer's signal. Arrows run from the cited agent to the citing agent. Clicking pins an agent; its card offers the interview.
  - Node size = √ of the distinct peers citing the agent in the round on screen (uniform while nobody is cited); failed agents carry a cross. The legend lists only the encodings on screen; an empty graph explains itself ("Round 1: agents decide independently…").
  - Every edge colour keeps ≥ 3:1 contrast against the canvas at the drawn opacity (`frontend/src/__tests__/lib/contrast.test.ts`).
  - The graph is pointer-only; keyboard users reach every agent through Top Influencers, the rationale feed and the bracket deep dive. Focusable SVG nodes were considered and not adopted.
- **Rationale:** citations concentrate on few agents; 200-500 agent edges at readable contrast form a hairball, so the overview aggregates and details appear on demand.

### <a id="adr-test-network-gate"></a>Tests are offline by default
- **Decision:** `pytest-socket --disable-socket --allow-unix-socket` applies globally (`pyproject.toml` addopts). Tests opt in by marker, never by directory (`tests/support/markers.py`, applied from `tests/conftest.py`): `neo4j` (the throwaway neo4j-test database on 127.0.0.1:7688, see [adr-tests-scoped-cleanup](#adr-tests-scoped-cleanup)), `live_network` (public internet) and `ollama` (local Ollama) get sockets, and async `neo4j` tests share the session event loop with the session-scoped driver. `live_network` and `ollama` tests are skipped unless `--run-live` is given. `neo4j` tests skip when neo4j-test is unreachable unless `--require-neo4j` is given.
- **CI:** `backend-unit` runs `-m "not neo4j and not live_network and not ollama"` with an 85% branch-coverage gate; `backend-neo4j` runs `-m neo4j --require-neo4j` against a `neo4j:5.26-community` service; `.github/workflows/nightly.yml` runs `--run-live -m live_network` daily. Every test has a 60 s timeout (`pytest-timeout`) and every job a 15-minute one.
- **History:** a path hook used to enable sockets for everything under `tests/integration/` ([p37-d-12](#p37-d-12)), which put Yahoo and Google News calls into every CI run; Phase 41.2 D-08's planned `integration` marker was never built. The markers above replaced both in October 2026.

### <a id="adr-tests-scoped-cleanup"></a>Neo4j tests run only against a throwaway database
- **Decision (2026-10):** Neo4j tests use the `neo4j-test` Compose service (profile `test`, `127.0.0.1:7688`, tmpfs, throwaway credential), started with `scripts/neo4j_test.sh up`. The URI is hard-coded in `tests/conftest.py`, never read from the environment. The session fixture `neo4j_test_driver` exits with code 3 on port 7687 or on a database that already holds `Cycle` nodes. `graph_manager_test` deletes only the cycles created during the test (never ids in `NEO4J_PROTECTED_CYCLES`). An autouse `hermetic_env` fixture clears `ALPHASWARM_*`, ignores `.env`, and points the inference config and holdings CSV at temp paths.
- **Rationale:** Until 2026-06-10, unscoped `DETACH DELETE` ran against the live `neo4j` database after every test and destroyed all real cycle history. Community Edition has no second database, so the isolation is a second container.
- **Rule:** The only unscoped `DETACH DELETE` allowed anywhere is the `neo4j_test_driver` session teardown, after both guards pass. Never point a test at 7687. Start and stop `neo4j-test` only with `scripts/neo4j_test.sh`, which uses `compose rm` for the test container: a bare `docker compose --profile test down` also removes the dev container, and any `compose down`, even with a service name, deletes the project network a stopped dev container needs. `/data` and `/logs` are both on tmpfs, so no volume outlives the container.

### <a id="adr-engine-scenario-harness"></a>Engine scenarios run the real `run_simulation` on scripted fakes
- **Decision (2026-10):** `tests/engine/` drives the real `run_simulation` end to end with no Ollama or Neo4j, and all but one scenario run without the memory governor. The worker and orchestrator are `ScriptedProvider`s (`tests/inference/fakes.py`), which classify each call (decision, narrative, interview chat, orchestrator). Decision calls are answered by a deterministic `DecisionFn`, orchestrator calls from a fixed script, and narrative and interview calls with canned text. The graph is an autospecced `GraphStateManager` mock, so a call with the wrong signature raises `TypeError`. Concurrency goes through `ImmediateController` (`tests/support/controllers.py`), which never waits and counts acquires, releases, failures and monitoring sessions. The exception is `tests/engine/test_scenarios_governor.py`, which runs the real `ResourceGovernor` on a `ScriptedMonitor` ([adr-governor](#adr-governor)) to check that zero jitter cannot push concurrency past the slot limit. `scenario_settings` sets both dispatch jitter bounds to 0.0, and the autouse `forbid_real_sleep` fixture fails any engine test that asks `asyncio.sleep` for wall-clock time.
- **Rationale:** Before this, engine tests patched internals (including the dead `_dispatch_round`, which made three lifecycle tests no-ops) and never ran a full cascade. A scripted run of 100 agents over 3 rounds takes about 0.1 s, so behavior such as phase order, shock carry-over, failure accounting and peer exposure can be pinned cheaply.
- **Rule:** Known engine bugs are pinned with `xfail(strict=True)` and a reason of the form `<item ID>: <the bug in words> (fix: plan NN)`; the fix removes the marker. Item IDs such as `T8.1` and the plan numbers refer to the owner's improvement plan (`docs/IMPROVEMENT_PLAN.md` and `docs/plans/`), which is not tracked in git yet, so the reason must describe the bug on its own. Changes to persona headers or peer-context lines must keep the `AGENT_HEADER_RE` and `PEER_LINE_RE` regexes in `tests/inference/fakes.py` matching. The narrative prompt must keep its `Agent: <name> (<bracket>)` user line, which is where `ScriptedProvider` reads the agent's identity, and its system prompt must not carry a persona header, or the call is classified as an interview chat. `test_narrative_prompts_identify_every_agent` fails on either drift.

### <a id="adr-security-2026-08"></a>Security hardening (Claude Security scans, 2026-08-01/02)
- **Decision:**
  - No default Neo4j password. Compose requires `ALPHASWARM_NEO4J__PASSWORD`, and the app raises when it is unset.
  - Neo4j ports are bound to 127.0.0.1.
  - RSS headlines are fenced out of the system prompt.
  - The `/ws/state` Origin is checked against an allow-list (close code 1008).
  - Every state-changing HTTP route has an Origin guard (`web/origin_guard.py`, CWE-352).
  - The API-key file and its directory are created owner-only (CWE-276).
  - One origin list, `AppSettings.allowed_origins` (`ALPHASWARM_ALLOWED_ORIGINS`), serves the HTTP CSRF guard and the WebSocket handshake through `origin_guard.is_allowed`; the WebSocket no longer accepts an Origin derived from the request's own Host. `ALPHASWARM_WS_ALLOWED_ORIGINS` and `ALPHASWARM_HTTP_ALLOWED_ORIGINS` are no longer read; startup logs `legacy_origin_settings_ignored` when they are set (2026-10, SPEC T7.3, T11.8).
  - `TrustedHostMiddleware` answers only `AppSettings.trusted_hosts` (default `localhost`, `127.0.0.1`, `[::1]`; `ALPHASWARM_TRUSTED_HOSTS`), so a DNS-rebinding page can no longer read `GET /api/holdings`, the advisories or the live stream. It is the outermost middleware; it became possible once the in-process `testserver` calls were removed (2026-10, SPEC T7.3). Entries are lower-cased and checked when the app is built: a port, a scheme or path, a bare `*` or a wildcard anywhere but a leading `*.` fails startup, instead of answering every request with 400 or failing the first request with 500 (2026-10). Starlette compares only the text before the first `:` of the Host, so the `[::1]` entry never matches today and an IPv6-loopback Host is refused (fail-closed; the server binds 127.0.0.1 by default).
  - Peer rationales are sanitized (`security/sanitize.py:sanitize_peer_rationale`: every Unicode Cc, Cf, Zl and Zp character becomes a space, the headline rule, so zero-width, bidi and invisible tag characters go too) and fenced in `<peer_observations>` in the user message behind the fixed `PEER_CONTEXT_GUARD`; no model-generated or third-party text reaches the system role (2026-10, SPEC T7.6).
  - Logging bridge (2026-10): `configure_logging` routes stdlib logging through structlog's `ProcessorFormatter`, so uvicorn, httpx and provider-SDK records get the same processors as structlog events, redaction included, and the same format; `httpx`, `httpcore` and `neo4j` stay at WARNING, and the four inference modules log through structlog. `alphaswarm web` and `./start` configure logging before uvicorn starts and pass `log_config=None`. On a direct `uvicorn --factory alphaswarm.web.app:create_app` launch, uvicorn's default config gives its loggers their own handlers with propagation off; the `configure_logging` call in `open_runtime`, which the lifespan enters, removes those handlers and turns propagation on (a logger without handlers, such as an access log turned off with `--no-access-log`, is left alone), so only uvicorn's first two startup lines keep its own format.
  - Run context (2026-10): `run_simulation` binds `cycle_id`, every agent call binds `round` and `agent_id`, and the report and advisory jobs bind `cycle_id` and `job`, all with `structlog.contextvars`. Each binding is task-local, so concurrent work never mixes context, and every log line of a run carries it.
  - Threat model, mitigations with file pointers and known limitations: [SECURITY.md](SECURITY.md) (2026-10).
- **Commits:** 53e5954, 72d55a9, 45c7827, 1e7a8ee, e353716, 820b8fe.

### <a id="adr-docs-sync"></a>Measured numbers have one home; the docs copy them by script
- **Decision:** Every measured number the README, the CHANGELOG and the résumé bullets show lives once, in the headline table of [docs/experiments.md](experiments.md#headline-numbers-v60). `scripts/docs_sync.py` renders the README's results, quality and run-time tables, the bracket table from `DEFAULT_BRACKETS`, the demo link, the screenshot gallery (from `docs/media/captures.json`), the CHANGELOG results and the résumé bullets in `docs/HISTORY.md`. `docs_sync.py check`, and a repository test once the blocks exist, fail when any copy is stale.
- **Rationale:** The October 2026 audit found a README that contradicted the code in a dozen places, and screenshots that showed mock data. Generated copies turn drift into a test failure instead of a reviewer's job.
- **Rule:** A generated sentence names a feature only when `repo_facts` finds it in the repository: the static demo build (the frontend reads `VITE_DEMO`), run manifests (`alphaswarm.manifest` defines `RunManifest`), pre-registered metrics (`docs/methodology.md` exists), per-call inference telemetry (`alphaswarm/inference/call_log.py` exists) and the ruff gate (a CI step runs `ruff check`). Until then the demo line is empty and the résumé bullets leave the feature out, so `write` cannot publish a claim ahead of the code. A claim that a result reproduces also needs run manifests. Wording changes go into the renderer and its test, never into a generated block.
- **Status (2026-10-22):** The script, its unit tests and the headline table exist; the generated blocks do not. README.md and docs/HISTORY.md carry no `<!-- NAME:start -->` markers, and CHANGELOG.md and `docs/media/captures.json` are absent, so `docs_sync.py check` and `write` exit 2 and change nothing, and no test compares a copy with the table yet. The README rewrite adds the markers and that test.

---

## 2. Historical decisions no longer in code

| Decision (when) | Rationale | What happened |
|---|---|---|
| <a id="hist-pygal-html-report"></a>pygal SVG charts over Plotly; HTML report with portfolio overlay (Phase 24, 2026-04-09) | Kept HTML reports under 1 MB versus over 15 MB with Plotly | **Lost.** Commit `f5330a6` (2026-04-11, mislabelled `test(27-01)`) deleted `charts.py`, `portfolio.py`, `report.html.j2`, and their tests during a worktree merge. Reports are markdown only; SWEEP B-1 later rewrote the orphaned tests. |
| <a id="hist-governor-suspend"></a>Governor `suspend()`/`resume()` around the shock window, with the memory-pressure guard at the callee (governor) to avoid a TOCTOU race; nested try/finally in `_collect_inter_round_shock` (Phase 26) | Prevented false THROTTLED states while the TUI waited for shock text | **Lost/obsolete.** The same `f5330a6` removed suspend/resume. The web shock path (Phase 35.1) never pauses: a queued shock is consumed by `consume_shock()` at the start of each later round (`simulation.py:_run_simulation`). |
| <a id="hist-shock-max-len"></a>`SHOCK_TEXT_MAX_LEN = 4096` caps shock text (STATE.md) | Bounds prompt growth across 100 agents | **Replaced:** ShockText (web/params.py) bounds shock text to 10-1000 characters; shocks posted after the last gated round has started get 409 shock_window_closed, and applied shocks are carried into every later round. |
| <a id="hist-v3-ticker-pipeline"></a>v3.0 SEC-validated ticker extraction, yfinance + Alpha Vantage pipeline with a disk cache, bracket-tailored enrichment, TickerDecision output (Phases 16-23, 2026-04-05..08) | First attempt at grounding in real data | **Lost.** Commit `7226d2e` (2026-04-09, mislabelled `feat(24-01)`) deleted `enrichment.py`, `market_data.py`, `ticker_validator.py`, and their tests: about 4.4k lines of source and tests. Most of the commit's 25.6k deleted lines (about 20.6k) were v3.0 planning docs. v6.0 Phases 37-40 rebuilt grounding as `alphaswarm.ingestion`. |
| <a id="hist-miro"></a>Miro API v2 live visualization; batcher stubbed (Phase 8 D-09/D-10) | Planned spatial visualization | **Dropped** for the web graph. `miro.py` was deleted in `76b7537` (2026-06-11). |
| <a id="hist-tui"></a>Textual TUI as the primary UI (Phases 9-10, 14, 26-28) | First interface | **Retired** in favor of the web UI. `tui.py` was deleted in `76b7537`. The StateStore contracts it introduced survive. |
| <a id="hist-read-post"></a>Posts ranked by INFLUENCED_BY weight via `read_ranked_posts`; READ_POST edges from every agent to every prior post (Phase 12 D-07..D-11) | Social-influence layer | **Superseded** by [adr-diverse-peer-context](#adr-diverse-peer-context). READ_POST edges stopped in June 2026; Post writes and the report's social-reach section were removed in October 2026. |
| <a id="hist-schwab-report-only"></a>Schwab CSV loaded in memory only during the report step | Privacy | **Changed:** now loaded at web lifespan startup into `PortfolioCache` and re-read when the CSV changes ([p39-d-07](#p39-d-07)). Still memory-only and never persisted. |

---

## 3. Phase-scoped D-xx index

Every legacy `D-xx` reference found in live code (`src/`, `tests/`,
`frontend/src/`, `pyproject.toml`, `.pre-commit-config.yaml`, `CLAUDE.md`) is
listed under its originating phase. Paths drop the `src/alphaswarm/` prefix, and
`fe/` stands for `frontend/src/`. Three agent IDs shaped like `D-xx` (one in an
older `README.md`, two in the mock wire data deleted in 2026-10) are not decisions
and are not listed.
Phase 26/29/30/31 CONTEXT docs were deleted from `.planning/` by the accidental
commits `f5330a6` and `343669f`. Their decisions were recovered from git history.

### Phase 3: Resource governance (governor, memory monitor)

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p3-d-01"></a>`D-01` | After a pressure crisis clears, restore slots gradually (+`slot_adjustment_step` per check) toward the D-03 baseline instead of snapping back; avoids re-triggering pressure. Before 2026-10 crisis exit snapped to baseline and this ramp never ran after a crisis. | active | governor.py `_handle_crisis`, `_handle_recovering` |
| <a id="p3-d-02"></a>`D-02` | Scale above baseline (up to max_parallel) only after consecutive calm memory checks. | active | settings.py:GovernorSettings; tests/test_governor.py:360,365 |
| <a id="p3-d-03"></a>`D-03` | Crisis recovery targets the baseline, not the pre-incident slot count; D-01's ramp is how it gets there. | active | governor.py `_handle_crisis`; tests/test_governor.py `test_recovery_ramps_by_step_until_baseline` |
| <a id="p3-d-04"></a>`D-04` | Inference failures shrink the governor. Since 2026-10 they are counted per call in `release(success=...)` over the last `failure_window_size` (20) outcomes: a failure share ≥ `batch_failure_threshold_percent` (20%) shrinks one step and clears the window; `failure_regrow_successes` (10) consecutive successes grow one step back, never above the pre-shrink level. Parse fallbacks release with success=True and do not count. Before: once per wave, reset by stop_monitoring, parse errors included. | active | governor.py `_record_outcome`, `_maybe_regrow`; batch_dispatcher.py `dispatch_wave` |
| <a id="p3-d-05"></a>`D-05` | Shrink by a fixed step (2) per trigger, never below 1 slot; gradual degradation, not halving. | active | settings.py:GovernorSettings; governor.py:292,304; tests/test_governor.py:480,502 |
| <a id="p3-d-07"></a>`D-07` | Abort with GovernorCrisisError after a sustained crisis (default 5 min) with no successful inference. Since 2026-10 a PAUSED that lasts `crisis_timeout_seconds` with no successful inference escalates to CRISIS with the crisis clock backdated to when the pause began, so the abort follows on the next check; CRISIS is left only when kernel pressure is GREEN and used % is below the pause threshold. | active | governor.py `_handle_paused`, `_handle_crisis`; tests/test_governor.py `TestPauseEscalation` |
| <a id="p3-d-08"></a>`D-08` | Any successful inference resets the crisis timeout clock, even at 1 slot. | active | governor.py:241; tests/test_governor.py:428,459 |
| <a id="p3-d-09"></a>`D-09` | Governor reports via structlog AND StateStore metrics (GovernorMetrics) so the UI can show telemetry. | active | governor.py:419; state.py:25 |
| <a id="p3-d-11"></a>`D-11` | Metrics emitted to StateStore on state change. Later (8521e91, Jun 2026) also emitted every check for the live UI. | partial | governor.py:419; state.py:25 |
| <a id="p3-d-12"></a>`D-12` | Dual-signal memory sensing. Since 2026-10 both signals come from the macOS kernel through ctypes `sysctlbyname` with no subprocess: used % = 100 − `kern.memorystatus_level`, pressure = `kern.memorystatus_vm_pressure_level`. psutil is the fallback off macOS or for one reading when the kernel call fails (it over-reports: 61.7% used vs 77% available at idle). Unknown pressure values map to GREEN; failed pressure reads are fail-stale (F-17); a degraded read is logged once per monitor. | active | memory_monitor.py `MemoryMonitor`, `memory_used_percent` |
| <a id="p3-d-13"></a>`D-13` | Kernel pressure YELLOW/RED is the master signal: halt the queue and drop to 1 slot. | active | governor.py:444; tests/test_governor.py:268 |
| <a id="p3-d-14"></a>`D-14` | Random jitter (0.5-1.5s) before each agent dispatch, applied in batch_dispatcher, not inside the worker; spreads load spikes. Both bounds accept 0.0 (2026-10) so deterministic tests can turn jitter off ([adr-engine-scenario-harness](#adr-engine-scenario-harness)); the defaults are unchanged. Since 2026-10 for cloud providers only (adr-prefix-reuse). | partial | batch_dispatcher.py:dispatch_wave; settings.py:GovernorSettings |

### Phase 4: Neo4j graph state

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p4-d-01"></a>`D-01` | A Decision is a node (Agent-[:MADE]->Decision-[:FOR]->Cycle) holding signal/confidence/sentiment/rationale, not a relationship. The `FOR` edge is no longer written (2026-10); decisions carry `cycle_id`. | active | graph/schema_writes.py (`persist_round`) |
| <a id="p4-d-03"></a>`D-03` | cited_agents stored as explicit (Decision)-[:CITED]->(Agent) edges (raw LLM output), separate from computed INFLUENCED_BY. | active | graph/schema_writes.py (`persist_round`) |
| <a id="p4-d-05"></a>`D-05` | Schema applied idempotently at startup via ensure_schema() (CREATE ... IF NOT EXISTS). Since 2026-10 a web server whose Neo4j was down or rejected the password at startup still starts; once the database answers, the first `/api/health` probe applies the schema (no restart for a database that was only stopped). | active | graph/manager.py (`ensure_schema`); services/runtime.py (`_prepare_graph`); web/routes/health.py; readiness.py |
| <a id="p4-d-06"></a>`D-06` | All 100 Agent nodes seeded eagerly in ensure_schema() from persona config. | active | graph/schema_writes.py (`seed_agents`) |
| <a id="p4-d-07"></a>`D-07` | Session-per-method: each GraphStateManager method opens its own short-lived async session; callers never manage sessions. Sessions are opened only by the `_read`/`_write` helpers (plus `ensure_schema`'s DDL), which apply `Neo4jSettings.query_timeout_s` through `unit_of_work` and map driver/server errors to the `GraphError` family (`Neo4jUnavailableError`, `Neo4jQueryError`, `Neo4jWriteError`). | active | graph/manager.py (`_read`, `_write`, `_map_graph_error`) |
| <a id="p4-d-08"></a>`D-08` | Keep the GraphStateManager API minimal and batch writes via UNWIND (one transaction per round, not per agent). `persist_round` writes a round's Decisions, CITED, RationaleEpisodes and REFERENCES in one transaction; the round's influence edges (`compute_influence_edges`) still follow in their own transaction. Posts are no longer written (2026-10). | active | graph/schema_writes.py (`persist_round`) |
| <a id="p4-d-09"></a>`D-09` | Pre-dynamic-topology peer ranking by static influence_weight_base (read_peer_decisions). Deleted with the dead _dispatch_round path in 2026-10. | superseded | — |
| <a id="p4-d-10"></a>`D-10` | cycle_id is a uuid4. | active | graph/schema_writes.py (`create_cycle_with_seed_event`) |

### Phase 5: Seed injection and agent personas

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p5-d-06"></a>`D-06` | Seed parsing goes through chat_structured(SeedLLMOutput); invalid entities are dropped and values clamped; tier 3 = empty SeedEvent. Revised 2026-10 (was parse_seed_event() with the agent decisions' 3-tier fallback). | revised | seed.py:SeedLLMOutput,inject_seed |
| <a id="p5-d-07"></a>`D-07` | Seed injection owns its orchestrator lifecycle (prepare -> extract -> always tear down in finally). | active | seed.py:inject_seed |

### Phase 7: Rounds 2-3: peer influence and consensus

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p7-d-03"></a>`D-03` | Peer context carries a header naming the source round. | active | peers.py:format_peer_context |
| <a id="p7-d-04"></a>`D-04` | Single run_simulation() orchestrates all rounds. **Revised 2026-10:** every round runs through rounds.run_round(); run_round1() is gone ([adr-round-runner](#adr-round-runner)). | revised | simulation.py:run_simulation; rounds.py:run_round |
| <a id="p7-d-05"></a>`D-05` | Worker reloaded once after run_round1() (which unloads in its finally) and kept warm for later rounds. **Superseded 2026-10** by [adr-round-runner](#adr-round-runner): the worker is prepared once before Round 1 and torn down once after the last round. | superseded | simulation.py:_run_simulation |
| <a id="p7-d-06"></a>`D-06` | run_round1 owned its governor monitoring session and run_simulation started a fresh one for Rounds 2-3. **Superseded 2026-10** by [adr-round-runner](#adr-round-runner): one monitoring session covers every round. | superseded | simulation.py:_run_simulation |
| <a id="p7-d-07"></a>`D-07` | Phase machine IDLE -> SEEDING -> ROUND_1..N -> FINALIZING -> COMPLETE. FINALIZING covers the metrics and the status write (narratives are lazy since 2026-10). StateStore.set_phase drives the UI. | active | simulation.py (`run_simulation`); types.py (`SimulationPhase`) |
| <a id="p7-d-08"></a>`D-08` | SimulationResult is one frozen container for all rounds plus shift metrics. **Revised 2026-10:** `rounds: tuple[RoundOutcome, ...]` with roundN_* compatibility properties. | revised | simulation.py:SimulationResult; rounds.py:RoundOutcome |
| <a id="p7-d-09"></a>`D-09` | Round N reads peer context from round N-1, personalised per agent (self excluded). | active | rounds.py:run_round; peers.py:build_peer_contexts |
| <a id="p7-d-10"></a>`D-10` | Peer contexts are built per agent BEFORE dispatch and passed into dispatch_wave. | active | peers.py:build_peer_contexts; rounds.py:run_round |
| <a id="p7-d-11"></a>`D-11` | Track signal flips between rounds with a transition breakdown. | active | rounds.py:compute_shifts |
| <a id="p7-d-12"></a>`D-12` | Track per-bracket average confidence delta between rounds. | active | rounds.py:compute_shifts |
| <a id="p7-d-13"></a>`D-13` | Shift metrics computed in memory from round results; no Neo4j query. | active | rounds.py:compute_shifts,run_round |
| <a id="p7-d-14"></a>`D-14` | CLI prints each round's report as it completes via an on_round_complete callback. | active | cli.py:_run_pipeline,_make_round_complete_handler; tests/test_cli_runtime.py:test_run_command_runs_through_the_runtime; tests/test_cli.py:test_round_complete_handler_prints_report_and_shift |
| <a id="p7-d-17"></a>`D-17` | The `run` CLI subcommand runs the full multi-round simulation. | active | cli.py:_handle_run,_run_pipeline; tests/test_cli_runtime.py:test_run_command_runs_through_the_runtime |

### Phase 8: Dynamic influence topology

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p8-d-01"></a>`D-01` | INFLUENCED_BY weight = citations received / active agents (simple, interpretable). | active | influence.py (`citation_weights`); graph/schema_writes.py (`compute_influence_edges`) |
| <a id="p8-d-02"></a>`D-02` | Compute influence edges after each round so topology shapes the next round. R1 computation since removed (SWEEP B-5); R3 computation added (260512-jqn ITEM 2). | partial | graph/schema_writes.py (`compute_influence_edges`, `_read_citation_pairs_tx`); rounds.py:run_round |
| <a id="p8-d-03"></a>`D-03` | Every citation pair produces an edge; no threshold. Edge weight is the target's citation share. | active | influence.py (`citation_weights`); graph/schema_writes.py (`compute_influence_edges`) |
| <a id="p8-d-04"></a>`D-04` | Weights are cumulative across rounds (round <= up_to_round). | active | graph/schema_writes.py (`compute_influence_edges`, `_read_citation_pairs_tx`); rounds.py:run_round |
| <a id="p8-d-05"></a>`D-05` | Cold start: when no citations exist, fall back to static influence_weight_base. The explicit fallback (sequential `read_peer_decisions` reads) was deleted with `_dispatch_round` in 2026-10. The production path (`build_peer_contexts`) always adds base reach to citation share, so with zero citations it samples by base reach alone ([adr-diverse-peer-context](#adr-diverse-peer-context)); no static ordering remains. | superseded | peers.py (`build_peer_contexts`) |
| <a id="p8-d-06"></a>`D-06` | Bracket-diverse peer selection: top-1 from the top N brackets, then fill by weight. Superseded by seeded stratified sampling with a per-bracket cap ([adr-diverse-peer-context](#adr-diverse-peer-context)). | superseded | peers.py (select_diverse_peers) |
| <a id="p8-d-07"></a>`D-07` | Bracket aggregation computed in memory from the round's decisions. | active | rounds.py:compute_bracket_summaries; state.py:38 |
| <a id="p8-d-08"></a>`D-08` | BracketSummary frozen dataclass promoted into the simulation layer and carried on SimulationResult; CLI and UI share it. | active | cli.py:_print_bracket_table_from_summaries,_print_round_report,_print_simulation_summary; rounds.py:compute_bracket_summaries,RoundOutcome; simulation.py:SimulationResult; state.py:38 |

### Phase 9: TUI core dashboard (retired UI; StateStore contracts survive)

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p9-d-02"></a>`D-02` | Per-agent StateStore writes as each agent resolves. Restored in May 2026 by streaming from batch_dispatcher._safe_agent_inference. | active | state.py:97,139 |
| <a id="p9-d-05"></a>`D-05` | Clear agent states at each round start for a clean visual slate. Superseded: keys now persist with signal=None ('thinking') so 5Hz frames are never empty. | superseded | state.py:150; tests/test_state.py:63 |

### Phase 10: TUI panels and telemetry (retired UI; StateStore contracts survive)

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p10-d-02"></a>`D-02` | Rationale feed fed by top-influence agents after each round. Superseded by per-agent streaming push_rationale + 50-entry sliding window (260512-jqn ITEM 4). The end-of-round calls were removed then, and `_push_top_rationales` itself was deleted in 2026-10. | superseded | batch_dispatcher.py (`_safe_agent_inference`) |
| <a id="p10-d-03"></a>`D-03` | Rationale feed entries truncated to ~50 chars by the producer (sanitize_rationale(max_len=50)). | active | batch_dispatcher.py (`_safe_agent_inference`, the producer); state.py (`RationaleEntry`) |
| <a id="p10-d-04"></a>`D-04` | Feed shows newest first. Restored in the web UI (2026-10): the frontend sorts by the wire `seq` and keys rows by it. | active | fe/lib/rationaleFeed.ts; state.py:72 |
| <a id="p10-d-05"></a>`D-05` | Live TPS = completion tokens finished in the last 10 s of wall-clock time, summed over every parallel call, divided by 10 (StateStore.record_tokens; SEEDING empties the window). Replaced the per-stream eval_count/eval_duration mean, which understated throughput by about NUM_PARALLEL. | revised 2026-10 | state.py (record_tokens); worker.py (infer) |
| <a id="p10-d-08"></a>`D-08` | StateStore.set_bracket_summaries after each round; all 10 brackets always shown. | active | state.py:229 |

### Phase 11: Live graph memory

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p11-d-01"></a>`D-01` | WriteBuffer queued per-agent episodes and flushed them after the decisions. Superseded: `persist_round` writes each round in one transaction and `write_buffer.py` is deleted. | superseded | graph/schema_writes.py (`persist_round`); episodes.py |
| <a id="p11-d-02"></a>`D-02` | WriteBuffer was separate from GraphStateManager (queueing vs Cypher). Superseded with p11-d-01; the pure value objects live in `episodes.py`. | superseded | episodes.py |
| <a id="p11-d-04"></a>`D-04` | RationaleEpisode linked 1:1 via (Decision)-[:HAS_EPISODE]->(RationaleEpisode). | active | graph/schema_writes.py (`persist_round`); episodes.py |
| <a id="p11-d-06"></a>`D-06` | flip_type enum stored on each episode (NONE for round 1). | active | types.py:75 |
| <a id="p11-d-07"></a>`D-07` | Episode properties: rationale, timestamp, peer_context_received, flip_type, round, cycle_id. `rationale` is no longer written (2026-10); readers use `Decision.rationale`. | active | graph/schema_writes.py (`persist_round`); episodes.py |
| <a id="p11-d-08"></a>`D-08` | Decision-[:REFERENCES]->Entity, matched in Python. Superseded 2026-10: whole-token, case-insensitive matching on the cycle's typed entities; ambiguous names skipped (`episodes.match_entities`). | superseded | graph.py:875; tests/neo4j/test_graph_integration.py (test_references_edges_case_insensitive); tests/neo4j/test_report_reads.py (test_entity_impact_counts_each_decision_once_for_the_cycles_own_entities) |
| <a id="p11-d-09"></a>`D-09` | REFERENCES are written in the same transaction as the round's decisions (`persist_round`); the cycle's entities are read once before Round 1. | active | graph/schema_writes.py (`persist_round`); simulation.py (`run_simulation`) |
| <a id="p11-d-10"></a>`D-10` | Post-simulation decision narrative per agent. Superseded 2026-10: stored on the agent's final-round Decision (`d.narrative`), never on the shared Agent node. | superseded | graph/schema_writes.py (`LEGACY_PROPERTY_CLEANUP`, `write_decision_narrative`); tests/neo4j/test_interview_context.py |
| <a id="p11-d-11"></a>`D-11` | Narratives generated eagerly as 100 worker calls after the last round. Superseded 2026-10: generated lazily on the first interview of (cycle, agent). | superseded | interview.py (`ensure_decision_narrative`); web/routes/interview.py; web/routes/settings.py (`get_estimate`); inference/budget.py (`estimate_run`) |

### Phase 12: Richer agent interactions (posts)

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p12-d-04"></a>`D-04` | Peer context budget: 4000 chars, K posts, greedy fill, last post truncated at a word boundary. | active | peers.py:format_peer_context |
| <a id="p12-d-05"></a>`D-05` | Unified peer-context block format (now `[agent_id|bracket] SIGNAL (conf)` lines so agents can cite IDs). Since 2026-10 each rationale is sanitized and capped near 300 characters, and the block is fenced in the user message. | partial | peers.py:format_peer_context |
| <a id="p12-d-06"></a>`D-06` | format_peer_context accepts post objects and applies the budget. | active | peers.py:format_peer_context |
| <a id="p12-d-12"></a>`D-12` | Per-round write order: decisions -> posts -> (formerly READ_POST edges) -> next dispatch. READ_POST edges no longer written since Jun 2026. Post writes removed 2026-10. | superseded | rounds.py:run_round |
| <a id="p12-d-13"></a>`D-13` | Round 1 has no peer context. Posts are no longer written (2026-10); Round 2 peers come from in-memory decisions. | superseded | rounds.py:run_round |

### Phase 13: Dynamic persona generation (modifiers)

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p13-d-01"></a>`D-01` | Orchestrator generates one entity-aware modifier per bracket from the seed. | active | seed.py:generate_modifiers; simulation.py:_run_simulation |
| <a id="p13-d-02"></a>`D-02` | Generated modifier replaced the static one for all agents in a bracket. Superseded: static round-robin modifier always applies; generated text is layered on as a 'this cycle' focus line (personas.py:generate_personas). | superseded | personas.py:generate_personas; simulation.py:_run_simulation |
| <a id="p13-d-04"></a>`D-04` | Modifier prompt inputs: the raw rumor plus each entity's name and type. **Revised (Phase 7):** relevance and sentiment are no longer sent, and the prompt asks for role and expertise only, no directional view, so the orchestrator's reading of the rumor cannot prime a whole bracket before Round 1. | revised | prompts/modifiers.py:render_modifier_generation_prompt,build_modifier_user_message; seed.py:generate_modifiers |
| <a id="p13-d-05"></a>`D-05` | Output is a flat JSON dict keyed by bracket value, decoded as ModifiersLLMOutput: one field per bracket key, keys case-insensitive. Revised 2026-10 (a full parse needed exactly 10 keys; a missing key now leaves that bracket without a focus line, [p13-d-08](#p13-d-08)). | revised | prompts/modifiers.py:MODIFIER_GENERATION_PROMPT; seed.py:ModifiersLLMOutput,generate_modifiers |
| <a id="p13-d-06"></a>`D-06` | Modifier generation runs in the same orchestrator session as seed parsing (no reload). | active | seed.py:inject_seed,generate_modifiers; simulation.py:_run_simulation |
| <a id="p13-d-07"></a>`D-07` | Total parse failure falls back to static modifiers with a warning. **Revised (Phase 7):** no modifiers are applied and personas are not regenerated with modifiers; the cycle metric `modifier_parse_tier` is 3. Static fallbacks told every agent it was the bracket's first static persona. | revised | seed.py:generate_modifiers; simulation.py:_run_roster,_derived_cycle_metrics |
| <a id="p13-d-08"></a>`D-08` | Partial failure falls back per bracket. **Revised (Phase 7):** only the brackets the orchestrator filled get a focus line; missing brackets get none. | revised | seed.py:ModifiersLLMOutput.to_modifiers |
| <a id="p13-d-09"></a>`D-09` | ParsedModifiersResult carries parse_tier for observability. | active | types.py:ParsedModifiersResult |
| <a id="p13-d-10"></a>`D-10` | Sanitise entity names at injection time; stored SeedEntity names stay untouched. | active | prompts/modifiers.py:build_modifier_user_message |
| <a id="p13-d-11"></a>`D-11` | Sanitisation: truncate to 100 chars, strip control/format characters, keep normal punctuation. | active | security/sanitize.py:sanitize_entity_name |
| <a id="p13-d-12"></a>`D-12` | sanitize_entity_name() helper; raw rumor goes in a clearly labelled block. | active | security/sanitize.py:sanitize_entity_name; prompts/modifiers.py:build_modifier_user_message |

### Phase 14: Agent interviews

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p14-d-04"></a>`D-04` | Interview system prompt = persona + decision narrative + per-round decisions (hybrid context). The persona is rebuilt with the cycle's stored modifiers (2026-10). | active | interview.py (`load_interview_context`, `interview_persona`); graph/replay_interview.py (`read_agent_interview_rows`) |
| <a id="p14-d-05"></a>`D-05` | Strip JSON output instructions from the persona for conversational answers (wherever they sit, since [adr-prefix-reuse](#adr-prefix-reuse)). | active | interview.py:_strip_json_instructions |
| <a id="p14-d-06"></a>`D-06` | Context reconstructed from Neo4j at session start: the graph returns the agent's rows (read_agent_interview_rows) and `interview.load_interview_context` rebuilds the persona from config plus Cycle.modifiers_json; unknown or off-roster agents raise AgentNotFoundError (404). | active | graph/replay_interview.py (`read_agent_interview_rows`); interview.py (`load_interview_context`) |
| <a id="p14-d-08"></a>`D-08` | Interview history keeps up to 12 user/assistant pairs; past that the oldest 6 are summarized in one call. A turn is committed only after the provider answers. Revised 2026-10 (was a 10-pair window trimmed one pair per turn). | revised | interview.py:172,230 |
| <a id="p14-d-09"></a>`D-09` | Dropped turns summarised into a prepended system message. | active | interview.py:216 |
| <a id="p14-d-10"></a>`D-10` | Summary produced by the same worker model. | active | interview.py:259 |
| <a id="p14-d-13"></a>`D-13` | Interviews bypass the governor and use only the worker provider (`InferenceRuntime.open_role`); no orchestrator client is built. Revised 2026-10 (was OllamaClient.chat directly, then a full provider pair of which only the worker was used). | revised | web/routes/interview.py:interview_agent; services/runtime.py:InferenceRuntime.open_role |

### Phase 15: Post-simulation report (ReAct)

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p15-d-01"></a>`D-01` | ReAct with literal ACTION:/INPUT: lines. Superseded by deterministic reads plus one chat_structured narrative call (adr-report-react). | superseded | report.py (history) |
| <a id="p15-d-02"></a>`D-02` | FINAL_ANSWER ended the ReAct loop. Superseded: there is no loop (adr-report-react). | superseded | report.py (history) |
| <a id="p15-d-03"></a>`D-03` | Hard iteration cap plus duplicate-call detection. Superseded: one call, at most one validated retry (adr-structured-output). | superseded | report.py (history) |
| <a id="p15-d-04"></a>`D-04` | CLI `report` subcommand. The web route and auto-chain after advisory were added later. | partial | cli.py:_handle_report |
| <a id="p15-d-05"></a>`D-05` | Sentinel file .alphaswarm/last_report.json for TUI polling. Had no reader once the TUI was retired; the `write_sentinel` writer was deleted in 2026-10. | superseded | — |
| <a id="p15-d-07"></a>`D-07` | Fixed report section order. | active | report.py:SECTION_TEMPLATES |
| <a id="p15-d-10"></a>`D-10` | Reports written to ./reports/{cycle_id}_report.md, next to a `{cycle_id}_report.json` sections sidecar (2026-10). | active | report.py:generate_report; cli.py:_handle_report; services/report.py:ReportService.generate |
| <a id="p15-d-11"></a>`D-11` | Async file write via aiofiles. Revised: `write_report_files` writes the sections sidecar, then the markdown, atomically off the event loop (`generate_report` runs it through `asyncio.to_thread`; temp file + fsync + os.replace, BACKLOG 1.11), and report.py no longer uses aiofiles. | revised | report.py:write_report_files,generate_report |
| <a id="p15-d-12"></a>`D-12` | Report code does not manage the model lifecycle; the caller (`ReportService`, which the CLI `report` command and the web report job both use) prepares, tears down and closes the provider around `generate_report`. | active | report.py:generate_report; services/report.py:ReportService.generate; cli.py:_handle_report |

### Phase 26: Shock injection core

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p26-d-12"></a>`D-12` | Shock stored as (Cycle)-[:HAS_SHOCK]->(ShockEvent). The web path, the only shock source, enforces the length cap: ShockText (web/params.py) takes 10-1000 characters after stripping. Revised 2026-10: replaces the never-enforced SHOCK_TEXT_MAX_LEN=4096 from STATE.md ([hist-shock-max-len](#hist-shock-max-len)). | revised | graph/schema_writes.py (`write_shock_event`); web/params.py; web/routes/simulation.py |

### Phase 28: Simulation replay (data layer)

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p28-d-07"></a>`D-07` | Per-round replay data (brackets, rationales) loaded on demand. | active | graph/replay_interview.py (`read_bracket_narratives_for_round`, `read_rationale_entries_for_round`) |
| <a id="p28-d-08"></a>`D-08` | read_full_cycle_signals() loads all rounds' signals in one query up front. | active | graph/replay_interview.py (`read_full_cycle_signals`) |

### Phase 29: FastAPI skeleton and event-loop foundation

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p29-d-04"></a>`D-04` | Uvicorn owns the event loop; `open_runtime` builds every stateful object inside the lifespan; there is no module-level app. | active | cli.py:_handle_web; web/app.py:create_app; services/runtime.py:open_runtime |
| <a id="p29-d-13"></a>`D-13` | CLI `web` calls uvicorn.run() directly (no asyncio.run wrapper). | active | cli.py:817 |

### Phase 30: WebSocket state stream

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p30-d-04"></a>`D-04` | Broadcaster includes rationale entries in each frame (now the persistent sliding window, not a drain), each stamped with `seq` and `ts`. | partial | web/wire.py (`build_frame`); state.py (`push_rationale`) |
| <a id="p30-d-05"></a>`D-05` | Wire format was json.dumps(dataclasses.asdict(snapshot)) with no separate pydantic wire model. Superseded by the versioned `StateFrame` built by `web/wire.py:build_frame` ([adr-ws-broadcaster](#adr-ws-broadcaster)). | superseded | web/wire.py; web/broadcaster.py |
| <a id="p30-d-06"></a>`D-06` | snapshot_to_json() helper encapsulates the frame pipeline (snapshot → `build_frame` → JSON). | active | web/broadcaster.py (`snapshot_to_json`) |
| <a id="p30-d-07"></a>`D-07` | Broadcaster is an always-on lifespan task ticking at 200 ms (5 Hz). | active | web/broadcaster.py:66,96 |
| <a id="p30-d-08"></a>`D-08` | /ws/state registered without a prefix. | active | web/app.py:216 |
| <a id="p30-d-10"></a>`D-10` | WebSocket is unauthenticated (local only). Since Aug 2026 the handshake Origin is validated against an allow-list. | partial | web/routes/websocket.py:7 |

### Phase 31: SPA + agent graph + edges endpoint

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p31-d-02"></a>`D-02` | FastAPI serves frontend/dist at / when it exists (single server in production). dist/ is gitignored, so it must be built locally. | active | web/app.py:218 |
| <a id="p31-d-11"></a>`D-11` | GET /api/edges/{cycle_id}?round=N returns INFLUENCED_BY edges for that round. | active | web/routes/edges.py:1 |
| <a id="p31-d-13"></a>`D-13` | Edges response: {edges: [{source_id, target_id, weight}]}. | active | web/routes/edges.py:26 |

### Phase 32: REST controls and control bar

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p32-d-12"></a>`D-12` | GET /api/replay/cycles is a real Neo4j query (completion keyed on `Cycle.status`, [adr-cycle-metrics](#adr-cycle-metrics)). | active | web/routes/replay.py (`replay_cycles`) |

### Phase 34: Replay mode (web)

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p34-d-07"></a>`D-07` | ReplayManager holds the ReplayStore, cycle_id and round; created in the lifespan. | active | web/replay_manager.py:1; tests/test_web.py:1209 |
| <a id="p34-d-08"></a>`D-08` | replay_start loads all signals, reads round 1 and only then commits the ReplayStore; the 5 Hz broadcaster shows it on its next tick; the immediate broadcast was removed. | partial | web/replay_manager.py; web/routes/replay.py |
| <a id="p34-d-09"></a>`D-09` | replay_advance reads the next round first and commits it in one synchronous step (capped at the cycle's real depth since F-12); no immediate broadcast. | partial | web/replay_manager.py; web/routes/replay.py |
| <a id="p34-d-10"></a>`D-10` | POST /api/replay/stop ends the replay (ReplayManager inactive again) and never writes the live StateStore phase, which stays IDLE or COMPLETE. Revised 2026-10 (start set the live phase to REPLAY and stop set it to IDLE). | revised | web/replay_manager.py:249; web/routes/replay.py:66,136 |
| <a id="p34-d-11"></a>`D-11` | Broadcaster reads the replay snapshot instead of live state while replay is active. | active | web/broadcaster.py (`snapshot_to_json`); tests/test_broadcaster_frames.py |

### Phase 35: Agent interviews (web)

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p35-d-06"></a>`D-06` | One InterviewEngine per (cycle_id, agent_id) in app.state.interview_sessions; cleared on sim start (no TTL). Sessions are closed and their close tasks awaited at shutdown (`web/app.py:close_interview_sessions`). Revised 2026-10 (was per agent_id). | revised | web/app.py:176; web/routes/interview.py:5 |
| <a id="p35-d-08"></a>`D-08` | Single POST /api/interview/{agent_id} endpoint; engine created lazily on first call. | active | web/routes/interview.py:39 |

### Phase 36: Report viewer (web)

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p36-d-01"></a>`D-01` | POST /api/report/{cycle_id}/generate returns 202 and runs a background task for any complete cycle while no simulation runs. Revised 2026-10: the phase == COMPLETE gate is gone. | revised | web/routes/report.py:generate_report; services/report.py:ReportService.start; tests/test_report_routes.py |
| <a id="p36-d-02"></a>`D-02` | 409 if a report task is already running (single orchestrator user). | active | services/jobs.py:JobRunner; web/deps.py:job_conflict; tests/test_report_routes.py |
| <a id="p36-d-03"></a>`D-03` | Web report path mirrors the CLI sequence and file locations. | active | services/report.py:ReportService.generate; tests/test_report_service.py |
| <a id="p36-d-05"></a>`D-05` | GET /api/report/{cycle_id} reads the markdown file; the filesystem is the source of truth: 404 = no report, 409 report_generation_in_progress while that cycle's job runs, 500 after a recorded failure. Revised 2026-10 (404 also meant "still generating"). | revised | web/routes/report.py:get_report |

### Phase 37: Isolation foundation + provider scaffolding

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p37-d-02"></a>`D-02` | Holdings-isolation import contract enforced by a pre-commit hook and (via the pytest invariant test) CI. | active | .pre-commit-config.yaml:17 |
| <a id="p37-d-03"></a>`D-03` | Permanent test runs lint-imports against a synthetic violation to prove the contract bites. | active | tests/invariants/test_importlinter_contract.py:1 |
| <a id="p37-d-04"></a>`D-04` | Whitelist-only: only alphaswarm.advisory and alphaswarm.web.routes.holdings may import alphaswarm.holdings. | active | pyproject.toml:206,217; web/routes/holdings.py:13,120; tests/unit/test_holdings_route.py:324,337; tests/invariants/test_importlinter_contract.py:105,108; tests/invariants/test_importlinter_coverage.py:10,11,24,108,111,118,122 |
| <a id="p37-d-05"></a>`D-05` | PII redaction: key-first detection plus value-pattern backstop. | active | logging.py:49,197,199; tests/test_pii_redaction.py:3,31 |
| <a id="p37-d-06"></a>`D-06` | account_* values become sha256 first-8 hashes; other sensitive values become [REDACTED]. | active | logging.py:49,197,201; security/hashing.py:4; tests/test_pii_redaction.py:3,31 |
| <a id="p37-d-07"></a>`D-07` | Redaction fails closed: on processor error, drop the event and emit a marker with no user data. | active | logging.py:5,184,197,203; tests/test_pii_redaction.py:3,196 |
| <a id="p37-d-08"></a>`D-08` | Redaction verified by Hypothesis property tests plus tabular cases. | active | tests/test_pii_redaction.py:3,284,363 |
| <a id="p37-d-09"></a>`D-09` | pytest-socket --disable-socket globally. | active | tests/test_network_gate.py:17 |
| <a id="p37-d-10"></a>`D-10` | No loopback exemption; integration tests opt in explicitly. | active | tests/test_network_gate.py:23 |
| <a id="p37-d-12"></a>`D-12` | tests/integration/ auto-applied enable_socket; one-off opt-in via marker. | superseded (2026-10: marker-based gating, [adr-test-network-gate](#adr-test-network-gate); the path hook is deleted) | — |
| <a id="p37-d-13"></a>`D-13` | ASCII sentinel holdings (SNTL_CANARY_*) make leaks greppable. | active | tests/invariants/conftest.py:3,29,60 |
| <a id="p37-d-14"></a>`D-14` | Canary runs a pipeline with a sentinel portfolio and asserts no sentinel appears anywhere. | active | tests/invariants/conftest.py:60; tests/invariants/test_holdings_isolation.py:1 |
| <a id="p37-d-15"></a>`D-15` | Leak detection across four surfaces: logs, Neo4j, WebSocket frames, worker prompts. | active | tests/invariants/conftest.py:4; tests/invariants/test_holdings_isolation.py:1,100 |
| <a id="p37-d-16"></a>`D-16` | tests/invariants/ holds architectural invariant tests. | active | tests/invariants/__init__.py:3; tests/invariants/test_holdings_isolation.py:1,64 |
| <a id="p37-d-17"></a>`D-17` | Exactly two provider protocols: MarketDataProvider and NewsProvider. | active | ingestion/providers.py:3 |
| <a id="p37-d-18"></a>`D-18` | Batch-first async signatures (list[str] -> dict[str, Slice]). | active | ingestion/providers.py:4 |
| <a id="p37-d-19"></a>`D-19` | Providers never raise for fetch failures; they return slices with staleness='fetch_failed'. | active | ingestion/providers.py:5,15,39,85,89,110; ingestion/rss_provider.py:9,30,125,161,174; ingestion/yfinance_provider.py:8,120; tests/integration/test_yfinance_provider_live.py:50,57,63,68; tests/test_providers.py:109,117,136; tests/test_rss_provider.py:214,361,396,549,566; tests/test_yfinance_provider.py:265,285 |
| <a id="p37-d-20"></a>`D-20` | Fake providers ship next to the protocols so consumers are test-first. | active | ingestion/providers.py:6 |

### Phase 38: Market data + news providers

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p38-d-01"></a>`D-01` | News via RSS only (no API key, no rate limits). | active | ingestion/rss_provider.py:3,56 |
| <a id="p38-d-02"></a>`D-02` | Ticker-shaped entities -> Yahoo Finance RSS; everything else -> Google News RSS (quoted). **Revised (Phase 7):** only swarm-resolved tickers ([adr-ticker-resolution](#adr-ticker-resolution)) use the Yahoo per-ticker feed; every other entity, including acronyms such as FED, goes to Google News. | revised | ingestion/rss_provider.py (`_route_url`); tests/test_rss_provider.py |
| <a id="p38-d-03"></a>`D-03` | Headline filter: case-insensitive substring match on the entity. **Revised (Phase 7):** Google results use a case-insensitive word-boundary match; Yahoo per-ticker feeds are not filtered. | revised | ingestion/rss_provider.py (`_entity_pattern`); tests/test_rss_provider.py |
| <a id="p38-d-04"></a>`D-04` | feedparser + httpx. | active | ingestion/rss_provider.py:6 |
| <a id="p38-d-05"></a>`D-05` | yfinance per ticker via asyncio.to_thread + gather for error isolation. | active | ingestion/yfinance_provider.py:3; tests/integration/test_yfinance_provider_live.py:89 |
| <a id="p38-d-06"></a>`D-06` | fast_info for price/volume; info for fundamentals. **Revised (Phase 7):** two guarded stages under one batch deadline (`asyncio.timeout`, 20 s): a failed or late `info` keeps the `fast_info` price; whatever finished is returned. | revised | ingestion/yfinance_provider.py (`_fetch_stages`); tests/test_yfinance_provider.py |
| <a id="p38-d-07"></a>`D-07` | No semaphore: providers run once per simulation, not per agent. | active | ingestion/yfinance_provider.py:5 |
| <a id="p38-d-09"></a>`D-09` | staleness='fresh' on success, 'fetch_failed' on any exception; no time-window logic. **Revised (Phase 7):** market slices carry `as_of` (the quote's market time) and are 'stale' when older than 24 h; 'fetch_failed' only when stage 1 fails. News slices are unchanged. | revised | ingestion/yfinance_provider.py (`classify_quote`); ingestion/rss_provider.py |
| <a id="p38-d-10"></a>`D-10` | No caching; every call fetches fresh. | active | ingestion/rss_provider.py:8,170; ingestion/yfinance_provider.py:7 |

### Phase 39: Holdings loader

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p39-d-01"></a>`D-01` | Holdings source is a 4-column CSV (account, symbol, shares, cost_basis_per_share). | active | holdings/loader.py:9 |
| <a id="p39-d-02"></a>`D-02` | Holding.cost_basis is total position cost (shares x per-share basis). | active | holdings/loader.py:10,145; tests/test_holdings_loader.py:79 |
| <a id="p39-d-03"></a>`D-03` | Multiple accounts merge into one PortfolioSnapshot. | active | holdings/loader.py:11; tests/test_holdings_loader.py:132,152,171 |
| <a id="p39-d-04"></a>`D-04` | All positions included (no money-market filtering). | active | holdings/loader.py:12; tests/test_holdings_loader.py:132,136,141 |
| <a id="p39-d-05"></a>`D-05` | Path from ALPHASWARM_HOLDINGS_CSV_PATH, default Schwab/holdings.csv, resolved against the repo root. | active | settings.py:AppSettings; web/app.py:219 |
| <a id="p39-d-06"></a>`D-06` | GET /api/holdings returns account hash, as_of, holdings with Decimals as strings. | active | web/routes/holdings.py:17,54,67; tests/unit/test_holdings_route.py:17,89,94,141 |
| <a id="p39-d-07"></a>`D-07` | Holdings load at lifespan startup into PortfolioCache on app.state and reload when the CSV's mtime changes; never assigned onto AppState. Revised 2026-10 (was loaded once, with a lazy reload in the advisory route). | revised | web/app.py:221; web/routes/holdings.py:18,120 |
| <a id="p39-d-08"></a>`D-08` | Missing/malformed CSV -> snapshot None -> structured 503; never crashes the WS loop. | active | holdings/loader.py:52; web/app.py:130,137; web/routes/holdings.py:21,82,136,146; tests/unit/test_holdings_route.py:18,217,222; tests/test_holdings_loader.py:277 |

### Phase 40: Simulation context wiring

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p40-d-01"></a>`D-01` | ContextPacket assembled inside run_simulation after seed extraction when both providers are present. | active | market_context.py:build_context_packet; simulation.py:_round_1_market_context |
| <a id="p40-d-02"></a>`D-02` | No providers -> log context_assembly_skipped and continue rumor-only. | active | market_context.py:build_context_packet |
| <a id="p40-d-03"></a>`D-03` | Partial fetch failures kept in the packet; formatter silently skips fetch_failed slices. | active | context_formatter.py:6; market_context.py:build_context_packet; tests/test_context_formatter.py:6 |
| <a id="p40-d-04"></a>`D-04` | Market context is its own system message after the persona and before peer context/user message. Since F3 (Aug 2026) and SPEC T7.6 (2026-10) only fixed guard texts are system messages; the market and peer blocks are fenced in the user message, market first. | partial | rounds.py:run_round; worker.py:155; tests/test_worker.py:219,248 |
| <a id="p40-d-06"></a>`D-06` | Market context goes to Round 1 only. Superseded 2026-10: rounds 1..market_context_rounds, default every round ([adr-market-context](#adr-market-context)). | superseded | rounds.py (prepare_round_inputs); settings.py (SimulationSettings.market_context_rounds); tests/engine/test_round_inputs.py (test_market_block_reaches_the_configured_rounds) |
| <a id="p40-d-07"></a>`D-07` | One formatted block shared by all 100 agents (no per-bracket filtering). | active | batch_dispatcher.py:176; tests/test_batch_dispatcher.py:691,699,734 |
| <a id="p40-d-08"></a>`D-08` | Per entity: price, fundamentals, top headlines; fetch_failed entities omitted. | active | context_formatter.py:6,99; tests/test_context_formatter.py:4,75,103 |
| <a id="p40-d-09"></a>`D-09` | Cap headlines at 5 per entity (`HEADLINES_PER_ENTITY`, which also caps point-in-time fixtures). | active | context_formatter.py:6,40; eval/build_fixtures.py:44; tests/test_context_formatter.py:5,112 |
| <a id="p40-d-10"></a>`D-10` | yfinance + RSS providers built once per process, with the StateStore as their audit sink, and stored on AppState. Revised 2026-10 (were built in the FastAPI lifespan and also stored on app.state; now `services.runtime.build_runtime` builds them for the web app and the CLI alike). | revised | app.py; services/runtime.py:build_runtime; tests/test_runtime.py |
| <a id="p40-d-11"></a>`D-11` | CLI `run` gets the same providers from `build_runtime`, so CLI and web runs get identical context (`--no-market-context` and a context fixture drop them for that run). Revised 2026-10 (were built inline in `cli.py`). | revised | services/runtime.py:build_runtime; cli.py:_run_pipeline; tests/test_cli_runtime.py |

### Phase 41: Advisory pipeline

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p41-d-03"></a>`D-03` | Original: the orchestrator decides which holdings are affected and omits the rest. Superseded by one item per holding with server-side HOLD padding (260512-jqn ITEM 6, SWEEP B-7). | superseded | tests/unit/test_advisory.py:test_ticker_join_filters_unmatched |
| <a id="p41-d-04"></a>`D-04` | Prefetch all swarm data from Neo4j in parallel (asyncio.gather) before the single LLM call. | active | advisory/engine.py:synthesize |
| <a id="p41-d-05"></a>`D-05` | One orchestrator call with swarm data plus aggregated per-ticker holdings rows (ticker and sector enrichment; no quantity or cost basis), decoded through chat_structured with tickers restricted to the prompt's holdings at temperature 0.2. Still the only place holdings enter a prompt. | active | advisory/engine.py:_ticker_entries,advisory_llm_schema,synthesize; advisory/prompt.py:build_advisory_prompt; tests/invariants/test_holdings_isolation.py (rendered-prompt canary) |
| <a id="p41-d-06"></a>`D-06` | The orchestrator writes AdvisoryLLMOutput (portfolio_outlook + items: ticker, signal, confidence, rationale, risk, upside); the engine assembles AdvisoryItem (adds position_exposure, source = swarm \| placeholder) and AdvisoryReport (totals, stats over conviction items, holdings_as_of). Revised 2026-10 (the orchestrator wrote the AdvisoryItem fields itself). Revised in Phase 7: swarm_signal, swarm_support, swarm_sentiment, evidence_agent_ids, llm_signal, divergent; position_exposure → cost_basis_exposure ([adr-grounded-advisory](#adr-grounded-advisory)). | revised | advisory/types.py (`AdvisoryLLMOutput`); advisory/types.py (`AdvisoryItem`); advisory/engine.py (`assemble_advisory_report`) |
| <a id="p41-d-07"></a>`D-07` | Rank by confidence x (exposure / total cost basis); denominator must be positive (F-29). | active | advisory/engine.py (`assemble_advisory_report`) |
| <a id="p41-d-08"></a>`D-08` | AdvisoryService owns orchestrator prepare/teardown; JobRunner runs one orchestrator job at a time and its lock serialises direct callers. Revised 2026-10 (replaces route-owned load/unload and the two routes refusing each other with 409). | revised | advisory/engine.py (module docstring); services/advisory.py:AdvisoryService.generate; services/jobs.py:JobRunner |
| <a id="p41-d-09"></a>`D-09` | POST /api/advisory/{cycle_id} returns 202 and spawns a background task. | active | web/routes/advisory.py:86,98 |
| <a id="p41-d-10"></a>`D-10` | GET reads advisory/{cycle_id}_advisory.json: 200 ready, 409 advisory_generation_in_progress while generating, 500 recorded failure or refusal, 404 absent. Revised 2026-10 (404 meant "still generating"). | revised | web/routes/advisory.py:196 |
| <a id="p41-d-12"></a>`D-12` | Cycle ids use the shared CycleId uuid4 type (web/params.py); malformed ids return 422 validation_error. Revised 2026-10 (was a regex guard shared with the report route, 400 invalid_cycle_id). | revised | web/params.py; web/routes/advisory.py:161,196 |
| <a id="p41-d-13"></a>`D-13` | Failures are recorded per cycle so polling can stop. Revised 2026-10 (was a route done-callback writing app.state.advisory_generation_error; now the JobRunner records the code and GET answers it with fixed text). | revised | services/jobs.py:JobRunner; web/routes/advisory.py:get_advisory |
| <a id="p41-d-20"></a>`D-20` | The isolation canary calls the real synthesize() (load-bearing since Phase 41). | active | pyproject.toml:213; tests/invariants/conftest.py:162; tests/invariants/test_holdings_isolation.py:7,73 |

### Phase 41.2: Audit fix: report/advisory data plane and UI contracts

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p41-2-d-03"></a>`D-03` | OllamaClient.generate() accepts system= so narrative generation stops failing silently. Narratives have since moved to `provider.chat` with a system message, and `generate()`, left without a production caller, was deleted in 2026-10. | superseded | interview.py (`ensure_decision_narrative`) |
| <a id="p41-2-d-04"></a>`D-04` | Replace the mock ReportModalV2 with the real backend-wired ReportModal. | active | fe/features/report/ReportModal.tsx; fe/features/dashboard/{ShockDrawer,ReplayBar}.tsx |
| <a id="p41-2-d-05"></a>`D-05` | Render portfolio_outlook + items[] in the advisory surface (now AdvisoryV2). | active | fe/lib/markdown.ts:2 |

### Phase 41.6: UI revamp: AlphaSwarm-2 Quant Terminal port

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p41-6-d-03"></a>`D-03` | Convert the CDN-globals JSX design export to native ES modules. | active | fe/app/AppShell.tsx; fe/components/Icon.tsx; fe/features/dashboard/panels.tsx; fe/features/settings/Settings.tsx; fe/features/dashboard/StateOverlays.tsx; fe/features/{wire,advisory,report,dashboard}/ (split from v2.tsx); fe/viz/InfluenceGraph.tsx |
| <a id="p41-6-d-07"></a>`D-07` | App shell = split context providers (Connection, Telemetry, Agents, Rationales, Edges, FrameMeta); bracket bars derive from agents, BracketContext removed (Oct 2026). | revised | fe/app/App.tsx; fe/app/AppShell.tsx |
| <a id="p41-6-d-08"></a>`D-08` | AdvisoryV2: derive what the backend supports, stub the rest (stubs tracked as KRs). | active | fe/features/dashboard/{ShockDrawer,ReplayBar}.tsx; fe/features/{wire,advisory,report,dashboard}/ (split from v2.tsx); fe/lib/advisoryParse.ts:2,24,51 |
| <a id="p41-6-d-09"></a>`D-09` | Render portfolio_outlook markdown via renderMarkdown(). | active | fe/features/{wire,advisory,report,dashboard}/ (split from v2.tsx); fe/lib/advisoryParse.ts:2,11; fe/lib/markdown.ts:3 |
| <a id="p41-6-d-10"></a>`D-10` | AdvisoryV2 keeps four tabs; Holdings and Overview share items[]. | active | fe/features/{wire,advisory,report,dashboard}/ (split from v2.tsx) |
| <a id="p41-6-d-11"></a>`D-11` | interview_v2 is the canonical interview surface (real /api/interview). | active | fe/features/interview/InterviewPanel.tsx; fe/features/dashboard/{ShockDrawer,ReplayBar}.tsx |
| <a id="p41-6-d-12"></a>`D-12` | Onboarding first-run flow gated by a localStorage flag and /api/health components (lists what is down with its fix; Re-check; Skip to dashboard). | active | fe/app/App.tsx; fe/features/onboarding/Onboarding.tsx |
| <a id="p41-6-d-13"></a>`D-13` | bracket_deep full-screen view filtered from AgentsContext. | active | fe/features/dashboard/BracketDeepDive.tsx |
| <a id="p41-6-d-14"></a>`D-14` | Design data file is reference only; keep just the BRACKETS constant. Now the single bracket registry `{key, display, count, color}` with wire snake_case keys, checked against the backend-generated `brackets.json` (2026-10). | active | fe/data.ts; fe/__tests__/lib/data.test.ts |
| <a id="p41-6-d-19"></a>`D-19` | usePolling surfaces timeout as an Error so modals can show it. | active | fe/features/{wire,advisory,report,dashboard}/ (split from v2.tsx); fe/hooks/usePolling.ts:83 |
| <a id="p41-6-d-20"></a>`D-20` | ReportModal: canonical markdown first; rich subsections only when a matching H2 heading parses. | active | fe/features/report/ReportModal.tsx; fe/features/dashboard/{ShockDrawer,ReplayBar}.tsx; fe/features/{wire,advisory,report,dashboard}/ (split from v2.tsx); fe/lib/advisoryParse.ts:3; fe/lib/markdown.ts:3 |
| <a id="p41-6-d-21"></a>`D-21` | CycleHistory Compare button renders only when comparison data exists. Superseded 2026-10: selection, Compare and CompareModal were deleted because no comparison feature exists. | superseded | — |
| <a id="p41-6-d-22"></a>`D-22` | Advisory stat relabelled HOLDINGS AFFECTED, read from affected/total counts. | active | fe/features/dashboard/{ShockDrawer,ReplayBar}.tsx; fe/features/{wire,advisory,report,dashboard}/ (split from v2.tsx) |
| <a id="p41-6-d-23"></a>`D-23` | UI tweaks persist to localStorage; backend-owned settings (model, provider, keys) live on the backend only. Revised 2026-10: the tweaks had no effect and were removed; the only browser-stored value is the onboarding flag, written through `safeStorage`. | revised | fe/lib/safeStorage.ts; fe/app/App.tsx; fe/api/settings.ts:4 |

### Phase 999.3: Live memory telemetry

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p999-3-d-01"></a>`D-01` | Broadcaster overlays live host RAM% (psutil) on every frame, including idle and replay. | active | web/broadcaster.py (`_host_memory_percent`); web/wire.py (`_governor`); tests/test_wire_models.py |

---

## 4. Known-regression register

KRs are deliberate, accepted gaps from the two React ports (Phase 41.1, then
Phase 41.6). The rule that came with them: a surface listed here may differ
from the design in the documented way, and any other difference is a bug.
Status checked against current code.

| ID | Accepted gap | Status (2026-10) | Referenced from |
|---|---|---|---|
| <a id="kr-41-1-01"></a>KR-41.1-01 | Agent graph uses the design's deterministic SVG layout, with no d3-force physics | active (deliberate design) | CLAUDE.md:22; fe/viz/InfluenceGraph.tsx |
| <a id="kr-41-1-02"></a>KR-41.1-02 | Signal Wire and Data Sources render static mocks (no backend) | **closed** (2026-10): both read the live `data_source_audit` slice; `src/mocks/` and the DEV fallback were deleted | fe/features/{wire,advisory,report,dashboard}/ (split from v2.tsx); fe/lib/dataSources.ts |
| <a id="kr-41-1-03"></a>KR-41.1-03 | Per-agent `flipped`, `roundLastSpoke`, `thinking` stubbed | partial: `thinking` is derived from `signal===null`; `flipped` and `roundLastSpoke` are still 0/null (frame.ts:151-152) | fe/adapter/frame.ts:151,152; fe/types.ts:26,27 |
| <a id="kr-41-1-04"></a>KR-41.1-04 | Memory shown as percent, not MB; GB literals in MemoryPaused are design copy | active for the percent display; MemoryPausedState and its GB literals were deleted (2026-10) | fe/adapter/frame.ts; fe/types.ts |
| <a id="kr-41-1-05"></a>KR-41.1-05 | Slot counts stubbed | **closed** (260512-jqn ITEM 3: `active_count`/`current_slots` on the wire) | fe/adapter/frame.ts:111; fe/types.ts:43,44; tests/test_state.py:126 |
| <a id="kr-41-1-06"></a>KR-41.1-06 | Replay Rewind disabled (no endpoint) | open; the disabled Rewind button was removed (2026-10: no placebo controls) | fe/features/dashboard/{ShockDrawer,ReplayBar}.tsx (ReplayBar) |
| <a id="kr-41-1-07"></a>KR-41.1-07 | CycleHistory consensus/flips/duration/shocks show "—" (`/api/replay/cycles` is minimal) | **closed** (2026-10): the listing returns final counts, flips and duration and pages with `limit`/`before`; History renders them and dropped the shocks column | web/routes/replay.py; fe/features/cycles/CycleBrowser.tsx; fe/lib/cycles.ts |
| <a id="kr-41-1-08"></a>KR-41.1-08 | Error log lines are design copy (no structured error stream) | **closed** (2026-10): the design-copy ErrorState was deleted; connection loss shows the frame-watchdog banner | fe/hooks/useWebSocket.ts; fe/components/ConnectionBanner.tsx |
| <a id="kr-41-1-09"></a>KR-41.1-09 | Top Influencers ranked by confidence during live view | **closed** (2026-10): ranked by citations received (CITED BY, `rankInfluencers`) for the round on screen from round 2's edges on; an empty-state line before that, no confidence fallback | fe/lib/influence.ts; fe/app/AppShell.tsx |
| <a id="kr-41-1-10"></a>KR-41.1-10 | Rationale `citations`/`sources` stubbed `[]` (RationaleEntry has no `cited_agents`) | open | fe/adapter/frame.ts:197,198; fe/app/AppShell.tsx; fe/types.ts:57,58 |
| <a id="kr-41-1-11"></a>KR-41.1-11 | Interview is non-streaming (single POST) | open | fe/api/interview.ts:2; fe/features/interview/InterviewPanel.tsx |
| <a id="kr-41-6-01"></a>KR-41.6-01 | AdvisoryV2 shares/basis/last/sentiment shown as "—" (not on AdvisoryItem) | open (holdings API has qty/cost_basis, so a client-side join could fill two of them) | fe/features/{wire,advisory,report,dashboard}/ (split from v2.tsx); fe/lib/advisoryParse.ts:9 |
| <a id="kr-41-6-02"></a>KR-41.6-02 | `new_features.jsx` (What-If Compare, Watch Mode, Multi-seed, Seed Suggestions) deferred; overflow items say "Coming in v6.x" | open (no code reference) | — |
| <a id="kr-41-6-03"></a>KR-41.6-03 | InterviewV2 PERSONA filler removed; live response is canonical | closed (by design) | fe/features/interview/InterviewPanel.tsx |
| <a id="kr-41-6-04"></a>KR-41.6-04 | Onboarding Ollama check is coarse (`/api/health` aggregate) | closed (Oct 2026: onboarding lists each /api/health component that is down with its fix) | fe/features/onboarding/Onboarding.tsx; fe/lib/health.ts |
| <a id="kr-41-6-05"></a>KR-41.6-05 | AdvisoryV2 Risk tab is placeholder copy | open | fe/features/{wire,advisory,report,dashboard}/ (split from v2.tsx) |
| <a id="kr-41-6-06"></a>KR-41.6-06 | Backend-touching settings read-only ("Coming in v6.x") | partial: inference provider/model/key/limits are now editable (`settings_inference.tsx` → `/api/settings`); memory threshold, slots, and agent count are still read-only | fe/features/settings/Settings.tsx |
| <a id="kr-41-6-07"></a>KR-41.6-07 | CycleHistory Compare hidden (no comparison endpoint) | **closed** (won't do, 2026-10): selection, Compare and CompareModal were deleted | — |
| <a id="kr-41-6-08"></a>KR-41.6-08 | ModelStatus chip hardcoded `qwen3:8b` | **closed**: the chip shows live inference mode and spend from `/api/health` (v2.tsx:ModelStatus) and no model name; the v2.tsx and app_v2.tsx comments say so (2026-10) | fe/app/AppShell.tsx; fe/features/{wire,advisory,report,dashboard}/ (split from v2.tsx) |
| <a id="kr-41-6-09"></a>KR-41.6-09 | InterviewV2 stats panel partial (peer reads, shock impact, data sources have no source) | partial: the three "—" rows were removed (2026-10); out/in-degree remain; history comes from stored decisions | fe/features/interview/InterviewPanel.tsx |
| <a id="kr-41-6-10"></a>KR-41.6-10 | AdvisoryV2 "agents" count is a regex heuristic over rationale text, strictly intersected with live IDs | active (heuristic) | fe/features/{wire,advisory,report,dashboard}/ (split from v2.tsx); fe/lib/advisoryParse.ts:51,66 |
| <a id="kr-41-6-11"></a>KR-41.6-11 | IdleState SystemCheck rows are static copy | **closed** (2026-10): rows come from `/api/health` components | fe/features/dashboard/StateOverlays.tsx; fe/lib/systemChecks.ts |
| <a id="kr-41-6-12"></a>KR-41.6-12 | ReportModal rich sections render only when an explicit `## Section` heading parses; otherwise omitted | active (policy) | fe/features/report/ReportModal.tsx; fe/features/{wire,advisory,report,dashboard}/ (split from v2.tsx); fe/lib/advisoryParse.ts:9 |
| <a id="kr-41-6-13"></a>KR-41.6-13 | BracketDeepDive influence counts only after the cycle ("—" live) | **closed** (2026-10): counts come from the shared EdgesContext for the round on screen, live from round 2's edges on; "—" only before they exist | fe/hooks/useCycleEdges.ts; fe/features/dashboard/BracketDeepDive.tsx |
| <a id="kr-41-6-14"></a>KR-41.6-14 | Mocks loaded only through DEV-only dynamic import; production grep gate keeps them out of `dist` | **obsolete** (2026-10): no mocks remain, so neither the DEV-only import nor the grep gate is needed | — |

---

## 5. June 2026 deep-audit findings

From audit branch `fix/deep-audit-260621` (PR #2, merged 2026-06-26). All are
fixed; the code comments explain the guard. Fix commits are listed for `git show`.

| ID | Finding (fixed) | Fix commit | Referenced from |
|---|---|---|---|
| <a id="f-01"></a>F-01 | `read_key_dissenters` compared lowercase signals to uppercase majority, so every agent was flagged a dissenter | 6ced8a8 | (Cypher fix, no comment) |
| <a id="f-02"></a>F-02 | `read_signal_flips` filtered `'NONE'` instead of `'none'` and read a non-existent `round_num` | 6ced8a8 | — |
| <a id="f-03"></a>F-03 | Shock-impact aggregation used uppercase keys, so every value was zero and HOLD | 6ced8a8 | — |
| <a id="f-04"></a>F-04 | `TokenPool.grow()` ignored crisis debt, so concurrency exceeded the limit right after recovery | 78744f6 | governor.py:90; tests/test_governor.py:73 |
| <a id="f-05"></a>F-05 | Anthropic provider defaulted to max_tokens=1024, truncating orchestrator output (now 8192 orchestrator / 512 worker; [adr-output-caps](#adr-output-caps)) | c99d00b | inference/factory.py:130 |
| <a id="f-06"></a>F-06 | ReAct prompt tool names did not match the registry, so the consensus and flip sections were always missing | 90dd0f9 | — (the ReAct loop and its registry were deleted in 2026-10; `SECTION_TEMPLATES` renders every section, [adr-report-react](#adr-report-react)) |
| <a id="f-07"></a>F-07 | Advisory read the wrong entity-impact keys, so relevance ranking was dead; added `resolve_ticker` | 3d65f99 | advisory/engine.py:synthesize; advisory/sector_map.py:187; tests/unit/test_advisory.py:test_enrich_holdings_entity_impact_drives_ranking |
| <a id="f-08"></a>F-08 | Round 2 equal weights meant every reader got the same peers; fixed with a stable per-reader jitter. The jitter is gone: seeded per-reader sampling ([adr-diverse-peer-context](#adr-diverse-peer-context)) disperses readers by construction | 7ae6a69 | peers.py (peer_rng); tests/test_peer_selection.py (test_equal_weights_disperse_across_readers) |
| <a id="f-09"></a>F-09 | JSON brace scanner ignored strings, so `}` in a rationale dropped the vote | 9748dd5 | inference/structured.py:json_object_candidates (shared by parsing.py and chat_structured since 2026-10); tests/test_parsing.py:test_tier2_brace_in_rationale_with_trailing_brace |
| <a id="f-10"></a>F-10 | OpenAI strict schema kept min/max, got a 400, and silently fell back to json_object | c99d00b | inference/schema.py:25; tests/inference/test_schema.py:150 |
| <a id="f-11"></a>F-11 | Failed cloud calls leaked TPM reservation (follow-up in 9312419: refund only on failure) | c99d00b, 9312419 | inference/rate_limit.py:RateLimitController.release; tests/inference/test_rate_limit.py |
| <a id="f-12"></a>F-12 | Replay advanced 2-round cycles to an empty round 3 | 66d680f | web/replay_manager.py:167 |
| <a id="f-13"></a>F-13 | Settings PUT carried the old vendor's API key to a new provider | 66d680f, 9312419 | web/routes/settings.py:248; tests/test_web_settings.py:103 |
| <a id="f-14"></a>F-14 | Blank account cells crashed the holdings loader outside the 503 path | 902d7b5 | holdings/loader.py:166 |
| <a id="f-15"></a>F-15 | Interview window trim lost a turn when summarization failed | 902d7b5 | interview.py:265 |
| <a id="f-16"></a>F-16 | `usePolling` stacked overlapping requests | df2f26a | fe/hooks/usePolling.ts:51 |
| <a id="f-17"></a>F-17 | A sysctl read failure returned GREEN and cleared a crisis; now fail-stale with a timeout | c567a2f | memory_monitor.py:133; tests/test_memory_monitor.py:268,279 |
| <a id="f-18"></a>F-18 | An unpriced model cost $0 under a spend cap; now priced at a conservative ceiling | f11aeee, cd5d35d | inference/budget.py:BudgetMeter._cost_of; tests/inference/test_budget.py |
| <a id="f-19"></a>F-19 | Empty peer set still injected a "peers exist" block | 7ae6a69 | peers.py:format_peer_context; tests/simulation/test_peer_context.py (test_format_peer_context_empty_peers) |
| <a id="f-20"></a>F-20 | Influence weights normalized by a count that included PARSE_ERROR agents | 7ae6a69 | rounds.py:run_round |
| <a id="f-21"></a>F-21 | Any monitor-loop exception silently killed throttling | 78744f6 | governor.py:360,374 |
| <a id="f-22"></a>F-22 | Anthropic missing-tool ValueError escaped the provider error contract | c99d00b | inference/anthropic_provider.py:AnthropicProvider._parse_response |
| <a id="f-23"></a>F-23 | Retry-After HTTP-date ignored; now a shared clamped parser | c99d00b, 9312419 | inference/types.py:parse_retry_after; inference/retry.py:retry_after_seconds |
| <a id="f-24"></a>F-24 | Broadcaster crashed every tick during replay start-up (`has_store` gate) | 66d680f | web/broadcaster.py:44,46; web/replay_manager.py:144 |
| <a id="f-25"></a>F-25 | Inference config save was not atomic (now temp file + `os.replace`) | 902d7b5 | inference/config.py:save_inference_config |
| <a id="f-26"></a>F-26 | `/replay/start` skipped the cycle_id guard | 66d680f | web/routes/replay.py:112 |
| <a id="f-27"></a>F-27 | A binary WS frame dropped the connection | 66d680f | web/routes/websocket.py:89 |
| <a id="f-28"></a>F-28 | Sector seed-match used bare substrings (false positives) | 35471d4 | advisory/engine.py:_enrich_holdings |
| <a id="f-29"></a>F-29 | A negative aggregate cost basis inverted the ranking | 35471d4 | advisory/engine.py (`assemble_advisory_report`) |
| <a id="f-30"></a>F-30 | Inconsistent ticker casing across items | 35471d4 | advisory/engine.py (`assemble_advisory_report`) |
| <a id="f-31"></a>F-31 | Inverted governor thresholds passed validation | 902d7b5 | settings.py:GovernorSettings |
| <a id="f-32"></a>F-32 | A failed unload aborted `ensure_clean_state`, risking the two-model invariant | 66d680f | ollama_models.py:OllamaModelManager.unload_model, OllamaModelManager.ensure_clean_state |
| <a id="f-33"></a>F-33 | Double-click could start two simulations | df2f26a | fe/hooks/useRunGate.tsx:51 |
| <a id="f-34"></a>F-34 | `parseInfluences` produced duplicate React keys | df2f26a | fe/__tests__/advisoryParse.test.ts:81; fe/lib/advisoryParse.ts:175 |
| <a id="f-35"></a>F-35 | Top Influencers showed "0" filler rows | df2f26a | fe/lib/influence.ts:5 |
| <a id="u1-u4"></a>U1/U2/U4 | Uncertain findings, also fixed: per-record episode stamping (U1), sysctl child reaped on cancel (U2), convergence weight normalization (U4) | 63d70da | — |

Note: the August security fixes use a separate "F1-F4" numbering in commit
subjects, for example "remove hardcoded Neo4j password default (F1)". See
[adr-security-2026-08](#adr-security-2026-08).

---

## 6. Bug IDs

### BUGFIX-CONTEXT (2026-04-16 analysis; B-numbers without a hyphen)

| ID | Bug and fix | Referenced from |
|---|---|---|
| <a id="b1"></a>B1 | Shock injection was dead in the web UI: `consume_shock()` had no caller and there was no `write_shock_event`. Fixed in Phase 35.1: shock consumed before Rounds 2 and 3 and persisted as ShockEvent. Since 2026-10 shocks carry forward: every applied shock is appended to all later rounds' user message, oldest first (a Round 2 shock is still in Round 3), and recorded on the StateStore (`applied_shocks`). A shock posted once the last gated round has started gets 409 `shock_window_closed` instead of being accepted and never read | graph/schema_writes.py (`write_shock_event`); simulation.py:_run_simulation (shock consumption); rounds.py:run_round (shock gate); web/simulation_manager.py (`inject_shock`); tests/test_graph.py:1547; tests/engine/test_orchestration.py (test_shocks_are_written_once_and_carried_forward, test_shock_is_consumed_after_the_round_starts); tests/engine/test_round_runner.py (test_round_message_is_rumor_plus_active_shocks); tests/test_shock_window.py; tests/engine/test_scenarios.py:135 |
| <a id="b4"></a>B4 | Replay could run on top of a live sim. Fixed with mutual exclusion: route returns 409 and `SimulationManager.start` raises `ReplayActiveError` | web/app.py:110; web/routes/replay.py:107,122; web/simulation_manager.py:120,131; tests/test_web.py:59,1380,1386,1407 |
| <a id="b7"></a>B7 | ConnectionManager leaked dead clients. The writer `finally` now removes its own entries | web/connection_manager.py:56,75; tests/test_connection_manager.py |
| <a id="b8"></a>B8 | `_on_task_done` race with `start()`. Phase reset now happens synchronously inside `_run` before the lock is released | web/simulation_manager.py:SimulationManager._run,_on_task_done; tests/test_web.py:1081,1380,1426,1492 |
| <a id="b9"></a>B9 | ReplayManager `advance`/`stop` mutated state without the lock. Both are now serialized | web/replay_manager.py:195,248; tests/test_web.py:1380,1499,1532,1535 |
| <a id="b10"></a>B10 | Duplicate `set_phase(COMPLETE)`. Only `simulation.py` (`_run_simulation`) sets it now. The comments name `run_simulation`; their stale `simulation.py` line citations were fixed in 2026-10 | web/simulation_manager.py:SimulationManager._run; tests/test_web.py:1380,1539,1581 |

The other BUGFIX-CONTEXT items (B2, B3, B5, B6, B11-B20) are not referenced in
code. Their status is in BACKLOG.md.

### SWEEP-260528 (2026-05-28 full sweep; "B-n" with a hyphen, plus §3.3)

| ID | Item and resolution | Referenced from |
|---|---|---|
| <a id="sweep-b-1"></a>SWEEP B-1 | 19 `test_report.py` failures against the removed `assemble_html()`. Tests rewritten against `ReportAssembler.assemble()` (markdown) | — (`ReportAssembler.assemble()` was deleted with the ReAct loop in 2026-10, [adr-report-react](#adr-report-react)) |
| <a id="sweep-b-5"></a>SWEEP B-5 | Round 1 can never produce citations, so its influence-edge computation was dead work. Removed | rounds.py:run_round (influence edges only when a previous round exists) |
| <a id="sweep-b-7"></a>SWEEP B-7 | Advisory prompt over-emitted boilerplate HOLD items. Non-top holdings are no longer sent to the LLM; every holding without a conviction item is padded server-side as HOLD@0.30, marked source=placeholder and left out of the overview stats (2026-10) | advisory/engine.py (`synthesize`); advisory/engine.py (`assemble_advisory_report`); advisory/types.py (`AdvisoryItem`); advisory/prompt.py (`build_advisory_prompt`); tests/test_advisory_synthesize.py (`test_prompt_instructs_conviction_items_only`); tests/unit/test_advisory.py |
| <a id="sweep-b-8"></a>SWEEP B-8 | Unknown tickers had `macro_beta=0`, so they could never rank. Default raised to 0.5 | advisory/sector_map.py:175; tests/test_advisory_synthesize.py:75,164 |
| <a id="sweep-3-3"></a>SWEEP §3.3 | Structural peer-context bias: every agent saw the same authority top-10. Fixed by [adr-diverse-peer-context](#adr-diverse-peer-context) | peers.py:select_diverse_peers,build_peer_contexts; rounds.py:run_round |

---

## 7. Threat-model IDs

| ID | Threat and mitigation | Referenced from |
|---|---|---|
| <a id="t-35-1-01"></a>T-35.1-01 | Cypher injection through shock text. All user input goes through parameters, never f-strings | graph/schema_writes.py (`write_shock_event`) |
| <a id="t-36-01"></a>T-36-01 | Path traversal through cycle_id. Since 2026-10 the `CycleId` path type and `CYCLE_ID_PATTERN` (`web/params.py`) validate it for report, advisory, replay, edges and interview, and malformed ids get 422 `validation_error` (was the `_CYCLE_ID_RE` regex guard) | web/params.py; tests/test_web_params.py |
| <a id="t-36-14"></a>T-36-14 | Blocking `Path.exists/stat` on the event loop. Uses `aiofiles.os` | web/routes/advisory.py:4; web/routes/report.py:get_report; tests/test_report_routes.py:test_routes_use_async_filesystem_probes |
| <a id="t-36-15"></a>T-36-15 | Background task errors lost, leaving the UI polling forever. A done-callback records per-cycle errors and GET returns 500 | web/app.py:100; web/routes/advisory.py:5,268; services/jobs.py:JobRunner; web/routes/report.py:get_report; tests/test_report_routes.py |
| <a id="t-36-16"></a>T-36-16 | Non-atomic report/advisory file write, partial read possible. Fixed 2026-10: both writes go through `fsutil.atomic_write_text` (temp file, fsync, `os.replace`, owner-only) | fsutil.py; report.py:write_report_files; web/routes/advisory.py:8 |
| <a id="t-38-01"></a>T-38-01 | URL injection through entity strings into RSS URLs. Ticker whitelist `^[A-Z]{1,5}$`; Google News query percent-encoded | ingestion/rss_provider.py:_TICKER_RE; types.py:TICKER_PATTERN; tests/test_rss_provider.py:142,164,549 |
| <a id="t-39-06"></a>T-39-06 | Holdings 503 leaking filesystem path or exception text. Generic body only | web/routes/holdings.py:25,87,93,141; tests/unit/test_holdings_route.py:14,215,259 |
| <a id="t-41-6-13"></a>T-41.6-13 | XSS through interview responses. Rendered as plain text, not markdown | fe/features/interview/InterviewPanel.tsx |
| <a id="t-260512-jqn-03"></a>T-260512-jqn-03 | Data-source audit buffer leaking raw bodies or env vars. Only bounded summary fields are recorded | data_audit.py:14,83; tests/test_data_audit.py:68 |
| <a id="t-260512-jqn-09"></a>T-260512-jqn-09 | Audit buffer mistaken for a compliance trail. It is a bounded in-memory UX ring buffer only | data_audit.py:10 |

---

## 8. Requirement IDs

Requirement IDs come from the old REQUIREMENTS files. All referenced ones are
implemented. MEM-01 is also cited in the superpowers spec.

| ID | Requirement | Referenced from |
|---|---|---|
| <a id="req-infra-03"></a>INFRA-03 | Sequential model loading (orchestrator unloads before worker loads) | tests/test_models.py:1; the callers order the loads (`seed.py:inject_seed`, `simulation.py:_run_simulation`; [adr-sequential-model-lifecycle](#adr-sequential-model-lifecycle)) |
| <a id="req-infra-04"></a>INFRA-04 | Async Ollama wrapper; `num_ctx` only in Modelfiles | tests/test_ollama_client.py:1 |
| <a id="req-infra-05"></a>INFRA-05 | Cycle-scoped indexes for fast peer reads | tests/neo4j/test_graph_integration.py (test_ensure_schema_idempotent) |
| <a id="req-infra-07"></a>INFRA-07 | TaskGroup for all batch processing; no bare create_task | batch_dispatcher.py:4,157 |
| <a id="req-infra-08"></a>INFRA-08 | Pydantic parsing with multi-tier fallback | parsing.py:3; tests/test_parsing.py:1 |
| <a id="req-tui-03"></a>TUI-03 / TUI-04 / TUI-05 | Rationale stream / telemetry (RAM, TPS, slots) / bracket panel. The contracts survive in StateStore after the TUI was removed | No live references since 2026-10: the code cites [p10-d-02](#p10-d-02) (rationale stream), [p10-d-05](#p10-d-05) (TPS) and [p10-d-08](#p10-d-08) (bracket summaries) instead, in state.py, batch_dispatcher.py and worker.py |
| <a id="req-graph-03"></a>GRAPH-03 | Decision→Entity REFERENCES edges | tests/neo4j/test_graph_integration.py (test_complete_reasoning_arc) |
| <a id="req-int-01"></a>INT-01 | Interview context reconstructed from Neo4j | graph/replay_interview.py (`read_agent_interview_rows`); interview.py (`load_interview_context`) |
| <a id="req-report-02"></a>REPORT-02 | Cypher report tools (bracket, influence, entity, flips, posts) | graph/analytics.py:read_consensus_summary,read_round_timeline,read_bracket_narratives,read_key_dissenters,read_influence_leaders,read_signal_flips,read_entity_impact |
| <a id="req-social-01"></a>SOCIAL-01 / SOCIAL-02 | Rationale posts as Post nodes / top-K posts in peer context (SOCIAL-02 ranking superseded, see [§2](#hist-read-post)) | SOCIAL-01: `write_posts` and its Post writes were deleted in 2026-10. SOCIAL-02: its ranking read (`read_ranked_posts`) and READ_POST writer (`write_read_post_edges`) were deleted in 2026-10 |
| <a id="req-replay-01"></a>REPLAY-01 | Replay from Neo4j without re-inference | graph/replay_interview.py:read_full_cycle_signals,read_bracket_narratives_for_round,read_rationale_entries_for_round; tests/test_graph.py:1555,1580,1602,1625 |
| <a id="req-vis-03"></a>VIS-03 | Edges endpoint for the web graph (Phase 31 ID) | tests/test_web.py:754 |
| <a id="req-shock"></a>SHOCK-04 / SHOCK-05 | Phase 27-internal IDs (never added to REQUIREMENTS.md). SHOCK-04: `read_shock_event` / `read_shock_impact` (bracket deltas, pivot count, comparable agents) plus the old TUI bracket-panel delta mode. SHOCK-05: shock-impact report section (`11_shock_impact.j2`). Since 2026-10 `collect_report_data` reads the impact only when the cycle has a shock and `render_report` adds the section; this replaced `TOOL_TO_TEMPLATE['shock_impact']` and the CLI's pre-seeded `shock_impact` observation | SHOCK-04: graph/analytics.py:read_shock_event,read_shock_impact; tests/test_graph.py:1438,1459,1473,1514. SHOCK-05: report.py:SECTION_TEMPLATES,collect_report_data; tests/test_report.py:test_shock_impact_template_renders_bracket_delta_table,test_shock_impact_template_renders_pivot_list; tests/test_report_pipeline.py:test_collect_reads_shock_impact_only_when_a_shock_exists,test_render_skips_the_shock_section_without_a_shock |
| <a id="req-be"></a>BE-01 / 03 / 04 / 08 / 09 / 10 | v5.0 web-backend IDs (definitions recovered from `git show 343669f^:.planning/...`). BE-01: FastAPI app whose lifespan owns the event loop, plus `/api/health`. BE-03: per-client WebSocket queue with drop-oldest and writer-task cleanup (ConnectionManager). BE-04: `/ws/state` 5 Hz snapshot stream (Phase 30). BE-08: `GET /api/replay/cycles` (real Neo4j query). BE-09: `POST /api/replay/start/{cycle_id}`. BE-10: `POST /api/replay/advance` (BE-09/10 began as Phase 32 stubs and were filled in by Phase 34) | BE-01: tests/test_web.py:102,226. BE-03: tests/test_connection_manager.py. BE-04: tests/test_web.py:356,735. BE-08..10: tests/test_web.py:1130 |
| <a id="req-isol"></a>ISOL-01..07 | v6.0 isolation: stdlib holdings types (01), frozen ingestion models (02), import contract (03), PII redaction (04), provider protocols (05), socket gate (06), four-surface canary (07) | see the `ISOL-` lines in `holdings/`, `ingestion/`, `logging.py`, `tests/invariants/`, `tests/test_network_gate.py` |
| <a id="req-ingest"></a>INGEST-01 / 02 | yfinance provider / RSS provider | ingestion/__init__.py:9; ingestion/yfinance_provider.py:1; ingestion/rss_provider.py:1; tests/... |
| <a id="req-hold"></a>HOLD-01..04 | CSV loader (01), account number hashed with `sha256_first8` (02/04), `GET /api/holdings` (03) | settings.py:AppSettings; holdings/loader.py:1,13,73,161; holdings/types.py:33; security/hashing.py:5; web/routes/holdings.py:1; tests/... |
| <a id="req-advis"></a>ADVIS-01 / 02 | `synthesize()` ranked items / `POST /api/advisory` with serialization | advisory/__init__.py:1; advisory/engine.py:1; advisory/types.py:1; web/routes/advisory.py:1,98; tests/unit/... |
| <a id="req-sim-04"></a>SIM-04 | `run_simulation` takes optional providers; backward compatible without them. Superseded 2026-10 by [adr-round-runner](#adr-round-runner): the inference providers are required and arrive in `SimulationDeps`; only the market and news providers stay optional | simulation.py:run_simulation; rounds.py:SimulationDeps |
| <a id="req-mem"></a>MEM-01..03 | Live RAM% on every WS frame, 5 Hz, governor fields preserved | web/broadcaster.py:27,53; web/wire.py:165; tests/test_web.py:380,387,412,443,472; docs/design/inference-providers.md:142 |
| <a id="req-auto"></a>AUTO-01..05 | Run the post-run jobs on completion (capture cycle_id, schedule from the done-callback). Revised 2026-10: PostRunPipeline calls the advisory and report jobs directly instead of an in-process POST, and the report runs in every case | tests/unit/test_simulation_manager_auto_advisory.py; tests/test_post_run_pipeline.py; tests/test_web_post_run_wiring.py |

---

## 9. Quick-task IDs

| ID | What it did | Referenced from |
|---|---|---|
| <a id="quick-260416-m8x"></a>260416-m8x | Tier-1 web fixes B4, B7, B8, B9, B10 | tests/test_web.py:1379 |
| <a id="quick-260507-19f"></a>260507-19f | Removed the UI POST trigger for advisory. Synthesis is auto-fired by the backend on completion; the frontend only polls GET | fe/api/advisory.ts:2; fe/features/{wire,advisory,report,dashboard}/ (split from v2.tsx) |
| <a id="quick-260512-jqn"></a>260512-jqn | Six post-run follow-ups. ITEM 1: CSS for InterviewV2/Onboarding/BracketDeepDive takeovers. ITEM 2: Round 3 INFLUENCED_BY edges, so `/api/edges?round=3` works. ITEM 3: governor slots on the wire (closes KR-41.1-05). ITEM 4: rationale sliding window + per-agent streaming `push_rationale`. ITEM 5: live data-source audit feeding the Signal Wire. ITEM 6: advisory one-item-per-holding + sector enrichment | 33 refs (2026-10) across frame.ts, v2.tsx, RationalesContext.tsx, styles.css, types.ts, batch_dispatcher.py, data_audit.py, ingestion/*_provider.py, state.py, web/app.py, and tests. ITEM 6 is now uncited: the padding lives in advisory/engine.py (`assemble_advisory_report`, [sweep-b-7](#sweep-b-7)) |
| <a id="quick-260611-rlx"></a>260611-rlx | `think=False` in advisory synthesis; report auto-chained after advisory succeeds | tests/unit/test_advisory_route.py:224 |

---

## 10. Phase-number lookup

"Phase N" in comments means the roadmap phase that introduced the code. Counts
are the live references.

| Phase | Topic | Refs | Main locations |
|---|---|---|---|
| 1 | Project foundation (config, types, logging) | 5 | simulation.py, governor.py |
| 2 | Ollama integration (client, model manager, worker context manager, parsing) | 11 | app.py, governor.py, simulation.py |
| 3 | Resource governance | 7 | settings.py, governor.py, memory_monitor.py, state.py |
| 4 | Neo4j graph state | 2 | app.py, tests/conftest.py |
| 5 | Seed injection + personas | 5 | parsing.py, tests |
| 6 | Round 1 standalone | 3 | simulation.py |
| 7 | Rounds 2-3 peer influence | 13 | cli.py, simulation.py |
| 8 | Dynamic influence topology + bracket summaries | 10 | cli.py, graph.py |
| 10 | TUI panels/telemetry (StateStore contracts) | 9 | state.py, simulation.py, worker.py |
| 11 | Live graph memory | 23 | simulation.py, graph.py, interview.py |
| 12 | Posts / social layer | 10 | simulation.py, graph.py |
| 13 | Dynamic persona modifiers | 14 | personas.py, prompts/modifiers.py, seed.py, simulation.py, parsing.py |
| 14 | Agent interviews | 1 | graph.py |
| 15 | ReAct report | 4 | cli.py, graph.py, web/routes/report.py |
| 24 | HTML report export ([lost](#hist-pygal-html-report)) | 1 | tests/test_report.py |
| 27 | Shock analysis + reporting (`read_shock_impact`, shock template) | 19 | tests/test_report.py, tests/test_graph.py, graph.py, cli.py |
| 28 | Replay data layer | 3 | graph.py |
| 30 / 31 / 32 / 34 / 35 / 36 | Web: WS stream / SPA + edges / controls / replay / interviews / report viewer | 3/2/4/1/1/8 | web/*, tests/test_web*.py |
| 35.1 | Shock injection wiring (B1) | 8 | simulation.py, graph.py, fe/app/AppShell.tsx |
| 37 | Isolation foundation | 10 | logging.py, tests/invariants/ |
| 38 | yfinance + RSS providers | 6 | ingestion/ |
| 39 | Holdings loader | 5 | settings.py, holdings/loader.py, security/hashing.py, web/app.py |
| 40 | Simulation context wiring | 38 | simulation.py, app.py, context_formatter.py, ingestion/, tests |
| 41 | Advisory pipeline | 11 | web/routes/advisory.py, tests/invariants/ |
| 41.1 | First React port (Claude Design UI) | 1 | fe/features/dashboard/{ShockDrawer,ReplayBar}.tsx |
| 41.2 | Audit fix: Cypher case, tool names, `generate(system=)`, modal wiring | 5 | fe/features/report/ReportModal.tsx, fe/lib/markdown.ts, tests |
| 41.4 | R3 stall: Ollama parallelism + model swap + `think=False` | 5 | seed.py, scripts/start_ollama.sh, tests |
| 41.6 | Quant Terminal UI port | 1 | fe/features/report/ReportModal.tsx |
| 999.3 | Live memory telemetry | 2 | web/broadcaster.py |

---

## 11. Review tags

About 190 comment lines cite cross-AI plan reviews ("Codex HIGH-2", "codex
MEDIUM-7", "gemini #G2", "REVIEW HIGH", "REVIEWS #1", "REVISION-1"). These were
findings from reviewing the GSD plans. The reasoning is already in each comment,
and the source review files under `.planning/phases/*/*-REVIEWS.md` are being
deleted. **Recommendation:** leave them, and strip the tag prefix when the
comment is next edited. Do not invent anchors for them. The heaviest files are
`tests/test_pii_redaction.py` (16), `fe/features/{wire,advisory,report,dashboard}/ (split from v2.tsx)` (16), `logging.py` (14),
and `tests/test_ingestion_types.py` (11). Mentions of "Gemini" in
`tests/inference/test_openai_provider_real_providers.py` refer to the Google
provider, not a review.

Other GSD bookkeeping tags carry no decision content and get no anchors. Treat
them the same way (leave them, and strip them when the comment is next edited):

| Tag family | Live lines | Example | Note |
|---|---|---|---|
| `Pitfall N` / `Research Pitfall N` | ~111 | `advisory/engine.py` (module docstring) "Pitfall 1: NEVER pass the PortfolioSnapshot… into a structlog" | Numbered per phase `*-RESEARCH.md`, so "Pitfall 1" means different things in different files. Almost every hit restates the pitfall inline; the few that only cited the file were rewritten to DECISIONS anchors when `.planning/` was removed |
| `Plan NN-NN` / `Plan NN-NN task N` | ~70 | `fe/app/AppShell.tsx` "Plan 41.6-04 task 2 (W4)" | GSD plan and task numbers |
| `W1`..`W4` / `Wave N` | ~44 | `fe/app/App.tsx` "lands in Plan 41.6-04 (W4)" | GSD execution waves |
| `ITEM n` | ~50 | `state.py:115` "ITEM 4 of quick task 260512-jqn" | Items of quick task 260512-jqn; see [§9](#quick-260512-jqn) |
| `(Rule N)` deviation | 1 | `fe/api/simulation.ts:20` "Plan 41.1-03 deviation (Rule 1)" | GSD executor deviation rule |
