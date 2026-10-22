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
  - `inference/provider.py`, `factory.py`, `rate_limit.py`, `budget.py`.
  - Config lives in the gitignored `.secrets/inference.json`. It is edited through
    the Settings UI or `GET/PUT /api/settings`.
  - `AuthError` and `BudgetExceededError` are never swallowed. One deliberate limit: in an advisory job they are logged with their traceback and recorded for GET, but they do not stop the post-run report ([adr-advisory-pipeline](#adr-advisory-pipeline)).
  - The inference config's load error (ValueError/OSError) can quote the file path and raw values, API keys included. The run (`SimulationManager._run`), the report and advisory jobs (`web/guards.py:job_config_error`) and the advisory gate (`web/guards.py:load_inference_config_or_422`) log only its type and fail with a fixed message: an `InferenceConfigError` raised `from None`, or 422 `inference_config_invalid` (2026-10).
- **Note:** CLAUDE.md's old "No cloud APIs" rule predates this. The correct reading is "local by default".

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
- **Where:** `config.py:31-41` (`OllamaSettings` defaults), plus the header comments in `modelfiles/Modelfile.worker` and `modelfiles/Modelfile.orchestrator`.
- **Rollback:**
  - First fallback: qwen3.5:35b GGUF MoE.
  - Second fallback: qwen3:8b plus qwen3.6:27b-q4_K_M, the stack from the 2026-05-06 decision ([adr-think-off](#adr-think-off)).
- **Revisit when:** a new MoE beats 2361 t/s prefill on 64 GB. Gemma 4 26B MoE is untested.

### <a id="adr-model-aliases"></a>Code calls Modelfile aliases; `num_ctx` lives only in Modelfiles
- **Decision:** All inference uses the aliases `alphaswarm-worker` and `alphaswarm-orchestrator` (`config.py:48-49`), built with `ollama create ... -f modelfiles/Modelfile.*`. `OllamaClient` strips any per-request `num_ctx` (`ollama_client.py:25-30`).
- **Rationale:** A per-request `num_ctx` makes Ollama silently reload the model.
- **Caveats:**
  - `OllamaSettings.worker_model` and `orchestrator_model` are only displayed in the CLI banner (`cli.py:64-65`). Changing them does not change the model; edit the Modelfile and re-run `ollama create`.
  - `OllamaSettings.num_parallel` and `max_loaded_models` are never read, so they are dead config. The real values are Ollama server environment variables (see RUNBOOK).

### <a id="adr-think-off"></a>Orchestrator reasoning ("think") is off everywhere
- **Decision:** Every local inference call passes `think=False`. It is hardcoded in `OllamaProvider.chat` (`inference/ollama_provider.py:153`), so it covers worker and orchestrator alike: seed, modifiers, rounds, narratives, advisory, report, and interview. No call site sets it individually.
- **Rationale:** The 2026-05-06 probe on qwen3.6:27b measured 274.6 s per call with thinking against 9.5 s without. Both produced valid JSON, and neither output was clearly better. With 11.3 t/s MLX decode, thinking also pushed advisory past the 600 s timeout (quick task 260611-rlx).
- **Where:**
  - Enforced: `inference/ollama_provider.py:153` (documented at `:12` and `:118`).
  - Rationale comments only: `seed.py:68-70`, `tests/test_seed_pipeline.py:89-94`, `modelfiles/Modelfile.orchestrator:16-17`.
- **Revisit:**
  - Triggers: complaints about consensus quality, or missed divergence flags.
  - How to test: `InferenceProvider.chat` has no `think` parameter today (`inference/provider.py:60`), so an A/B run needs a small change first, for example an optional `think` argument on `OllamaProvider.chat` used by one call site. No model reload is needed.
  - Hybrid option: keep `think=False` as the default and enable it only for one high-stakes call.

### <a id="adr-sequential-model-lifecycle"></a>At most two models loaded; orchestrator users are serialized
- **Decision:**
  - `OllamaModelManager` enforces sequential loading: orchestrator for seed, then worker for the rounds and narratives, then orchestrator for advisory and report (`ollama_models.py:3`, INFRA-03).
  - Report and advisory never overlap: both POST routes and the post-run pipeline check the orchestrator slot (`web/guards.py:require_orchestrator_free` and `orchestrator_job_running`, backed by `StateStore.job_statuses()`).
  - After a completed run, `PostRunPipeline` (`web/post_run.py`) runs the advisory when a portfolio is loaded (and, with a cloud orchestrator, only with the opt-in), then always the report, by direct calls; the former in-process `httpx.ASGITransport` chain is gone. `SimulationManager.start()` refuses a new run with 409 `post_run_jobs_in_progress` while the pipeline task is pending or an orchestrator job runs, and `POST /api/settings/test` is refused during a run.
  - The report and advisory POST routes check for a running simulation again after their last await, right before the job starts (`web/guards.py:require_no_simulation`): a run started while they awaited Neo4j, the config or the holdings passed `start()`'s probe, because no job was marked running yet (2026-10).
- **Rationale:** On 64 GB the worker and orchestrator cannot both stay warm, and either task unloading the orchestrator under the other corrupts the run.

### <a id="adr-swarm-composition-v2"></a>Swarm composition v2 (2026-06-10)
- **Decision:** Ten brackets that model the price-setting margin of the narrative ecosystem. Counts and weights live in `config.py:DEFAULT_BRACKETS`; the rationale is in the `types.py:BracketType` docstring.

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

### <a id="adr-influence-weight-reach"></a>`influence_weight_base` means narrative reach, not capital
- **Decision:** Weights span 0.45-0.75, and Sell-Side and Narrators rank highest on purpose.
- **Rationale:** Peer visibility, not assets under management, determines whose rationale others read.
- **In the peer sampler:** Sell-Side and Narrators are the brackets seen most often per agent. Below them, the bracket floor and the per-bracket cap make weight a rough order only ([adr-diverse-peer-context](#adr-diverse-peer-context)).

### <a id="adr-diverse-peer-context"></a>Peer context is built in memory per reader, by seeded stratified sampling
- **Decision:** `_build_diverse_peer_contexts` (`simulation.py`) builds each reader's peer context in memory and returns the ids of the peers it rendered (the reader's *exposure*). It is the production path since the June 2026 overhaul; seeded sampling replaced the deterministic fill in October 2026.
  - Per-reader weight = base reach + global citation share + `SimulationSettings.personal_boost` (default 0.3) if the reader cited that author last round. The boost raises a cited author's odds; it no longer guarantees a slot. Only an ablation (0 / 0.05 / 0.3) may change the default.
  - `select_diverse_peers` samples without replacement, weighted by that score (Efraimidis–Spirakis keys `u ** (1/w)`, computed as `log(u)/w`): first `min_brackets` brackets (default 4), each weighted by the summed weight of its candidates, with one peer each (a weighted draw over agents that skips brackets already chosen); then the remaining slots, with at most `bracket_cap` peers (default 3) from any one bracket. The cap is hard, so a reader gets fewer than `peer_limit` (default 10) peers when few brackets are eligible. The reader and previous-round PARSE_ERROR agents are never shown. Non-finite or non-positive weights have no reach: whatever their draw, they sort behind every positive weight (in random order among themselves) instead of raising.
  - The final list is shuffled, so no bracket owns position 1.
  - Randomness comes only from `peer_rng(run_seed, reader, round)` (blake2b, never the process-salted `hash()`); `run_seed` is the cycle id (`peer_seed_source = "cycle_id"`).
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
  - `read_ranked_posts`, `_dispatch_round`, and `read_peer_decisions` are dead code.
  - READ_POST edges are no longer written, which empties the report's `social_post_reach` section. See BACKLOG.
- **Control holdout (decided 2026-10 under the owner's delegation):** `control_fraction` defaults to 0.0, so product runs keep every reader's peer context; experiment and eval runs set `ALPHASWARM_SIMULATION__CONTROL_FRACTION=0.2` (20 seeded readers, round-half-up per bracket, never see peers).
- **Own prior (2026-10):** from Round 2 on, each reader's user message starts with its own previous decision (`Your Round N position: SIGNAL (conf X): rationale`, sanitized to one line and left out after a PARSE_ERROR; `ALPHASWARM_SIMULATION__OWN_PRIOR_MEMORY`, default true). Holdout readers keep it, so their flips measure everything except peers. Holdout decisions carry `d.control = true` in Rounds 2-3 (Round 1 decisions carry false), and the cycle metrics add `r{n}_control_agents`, `r{n}_flips_control` and `r{n}_flips_treated`.

### <a id="adr-num-rounds"></a>Configurable cascade depth (2 or 3 rounds)
- **Decision:** `ALPHASWARM_NUM_ROUNDS` accepts 2 or 3 and defaults to 3 (`AppSettings.num_rounds`).
  - Round 1 is the uninfluenced prior and should not be touched.
  - `num_rounds` is stamped on the Cycle when it is created (`create_cycle_with_seed_event`), so running and failed cycles carry it too. The completion metrics write the same value.
  - Report and advisory reads resolve the final round inside Cypher with `coalesce(c.num_rounds, 3)`, because cycles from before 2026-10 that lack the property were all 3-round. The replay cycle list reports the same value as `round_count`.
  - Prompts describe the rounds that ran: the ReAct report prompt says "final round", and the eager narrative prompt names the agent's round count. The CLI summary uses the last round that ran and reports convergence only for 3-round runs, since it compares R1→R2 flips with R2→R3 flips.
  - With 2 rounds, the round-3 result fields are empty, and completed-cycle listing relies on `Cycle.metrics_recorded_at`.
- **Rationale:** Most flips happen in Round 2, and 2 rounds save about a third of wall time. Keep the default at 3 until the A/B comparison is done and the frontend stops hardcoding "/3" (see BACKLOG).

### <a id="adr-structured-output"></a>Structured outputs plus a 3-tier parser
- **Decision:** Workers request JSON (the JSON schema `DECISION_JSON_SCHEMA` in `worker.py`) and still go through a 3-tier parser: JSON, then extraction, then PARSE_ERROR (`parsing.py`, INFRA-08). The brace scanner is string-aware since F-09.
- **Rationale:** The MLX runner relies on prompt adherence rather than hard grammar enforcement, so the prompt must spell out the keys. Never trust format=schema alone.

### <a id="adr-governor"></a>Memory-aware ResourceGovernor
- **Decision:**
  - A queue-based TokenPool with a 5-state machine: RUNNING, THROTTLED, PAUSED, CRISIS, RECOVERING (`governor.py`).
  - Baseline 8 slots, maximum 16.
  - Throttle at 80% memory, pause at 90%.
  - macOS sysctl kernel pressure is the master signal. Read failures are fail-stale (F-17).
  - `grow()` pays down crisis debt before adding tokens (F-04).
  - Monitor-loop failures turn into a crisis rather than silently stopping (F-21).
- **Rationale:** Memory pressure is the main way the M1 Max fails. See [Phase 3 entries](#phase-3-resource-governance-governor-memory-monitor).
- **Cloud mode:** `RateLimitController` replaces the governor through the `ConcurrencyController` protocol.

### <a id="adr-taskgroup-dispatch"></a>All agent fan-out uses `asyncio.TaskGroup`, with jitter
- **Decision:**
  - `dispatch_wave` creates one task per persona inside a TaskGroup, with no bare `create_task` (INFRA-07). Narrative generation fans out the same way.
  - Random 0.5-1.5 s jitter runs before acquiring a slot ([p3-d-14](#p3-d-14)).
  - A failed agent becomes a PARSE_ERROR decision with `error_kind` `"inference"` (the call raised) or `"parse"` (tier-3 parse fallback), and the round continues. Cycle metrics count `r{n}_inference_errors` separately from `r{n}_parse_errors`.
  - Hard stops (`HARD_STOP_ERRORS` in `batch_dispatcher.py`: `BudgetExceededError`, `AuthError`, `GovernorCrisisError`) are never converted. `dispatch_wave` and `_generate_decision_narratives` unwrap the TaskGroup's `ExceptionGroup` with `except*` and re-raise the first one bare, chained `from` the group.
  - Round abort: after `dispatch_wave` and before the round's first Neo4j write, a round in which `failed * 100 > GovernorSettings.round_abort_failure_percent * total` (default 50; `failed` = PARSE_ERROR of any kind) raises `RoundFailedError`; an empty round always fails. Failed agents are not re-dispatched.
  - `SimulationManager._run` turns any non-cancel failure into a `RunError` on `StateStore.last_error` (code, fixed-template message, round, timestamp) and logs it once with `exc_info`; `start()` clears it and cancellation never sets it. Messages never quote exception text, so they cannot leak a path or a key. A failure raised outside that handler (a provider `aclose` in `_run`'s `finally`) sets no `RunError`; the task's done-callback logs it with `exc_info`.
  - New domain errors derive from `AlphaSwarmError`; the `GraphError` family (`Neo4jUnavailableError`, `Neo4jQueryError`, `Neo4jWriteError`) carries an `op` that names the failed operation. `InferenceError`, `BudgetExceededError` and `GovernorCrisisError` keep their parents, so existing `except` clauses behave as before.
- **Rationale:** A spend-cap or auth failure surfaced as "unhandled errors in a TaskGroup (1 sub-exception)" and the UI silently dropped to IDLE, and a dead model server persisted a round of PARSE_ERRORs that later rounds read as peer context (2026-10 audit, T1.2/T1.3).

### <a id="adr-agent-worker"></a>Every worker LLM call goes through the `agent_worker` context manager (Phase 2 rule)
- **Decision:**
  - `agent_worker(persona, governor, provider)` is an `@asynccontextmanager`. It acquires one governor or rate-limit slot, yields an `AgentWorker`, and releases the slot in `finally` (`worker.py:1-9, 226-232`).
  - No raw client calls outside it, except interviews, which bypass the governor ([p14-d-13](#p14-d-13)).
  - The runtime persona is a lightweight `WorkerPersonaConfig` TypedDict derived from the frozen `AgentPersona`, which stays the source of truth (`worker.py:95`).
  - Transient Ollama errors retry with exponential backoff (`ollama_client.py:122-127`).
- **Rationale:** One choke point for concurrency accounting and failure handling. The comments in `worker.py` that cite "CONTEXT.md locked decision" mean this entry.

### <a id="adr-streaming-state"></a>Live state streams per agent; frames are never empty mid-round
- **Decision:**
  - At SEEDING, `run_simulation` calls `StateStore.begin_run(agent_ids)`: the run's roster in config order, every agent pending (`signal=None`). Every frame from then on carries that roster in that order, and `agent_count` is its size (`state.py`).
  - `_safe_agent_inference` writes `update_agent_state` for every resolved agent the moment it finishes, PARSE_ERROR included, and pushes a rationale entry only for real decisions (`batch_dispatcher.py`).
  - On round entry, `StateStore.set_phase` keeps agent keys and resets signals to `None`. The UI renders `None` as pending ("thinking"), never as HOLD; every tally counts decided agents only (`frontend/src/lib/tally.ts`).
  - Rationales live in a persistent `deque(maxlen=50)` and are not drained.
- **Rationale:** Rounds take minutes. The TUI-era "clear and batch-write after the round" contract made the 5 Hz UI look frozen (debug session `ws-agent-states-not-emitted-mid-sim`, fixed in fe366ce, 1da741e, and 0003375). Counting pending agents as HOLD made every round open at "HOLD 100%", and unwritten failures pulsed "thinking" forever (fixed Oct 2026).

### <a id="adr-ws-broadcaster"></a>WebSocket broadcaster: versioned StateFrame at 5 Hz, drop-oldest per client
- **Decision:**
  - An always-on lifespan task builds one `StateFrame` every 200 ms. `web/wire.py:build_frame` maps the live `StateSnapshot` (or the active replay's) field by field onto frozen pydantic models with `extra="forbid"`; internal dataclasses are never serialized directly. The replay manager's immediate broadcasts use the same path.
  - The frame carries `schema_version` (1), `mode` (`live`/`replay`/`idle`, derived from the phase), `cycle_id` (set right after `inject_seed`, reset on SEEDING), `num_rounds` (the configured depth from process start, so idle frames carry it too), `edges_version` (influence-edge steps finished for the cycle; in replay, round − 1), `jobs` (advisory/report status from the live store, also during replay), `last_error`, the shock fields, and a monotonic `seq` plus wall-clock `ts` on each rationale entry.
  - Adding a field keeps `schema_version`; renaming, removing or changing the meaning of a field bumps it together with the frontend adapter's `SUPPORTED_SCHEMA_VERSION`.
  - `tests/test_wire_contract.py` writes golden frames into `frontend/src/__tests__/fixtures/`; the frontend tests read them, and `tsc` checks their keys against the TypeScript mirror in `frontend/src/types.ts`.
  - Each client gets an `asyncio.Queue(maxsize=100)` with drop-oldest and its own writer task, which cleans up its registry entry in `finally` (B7).
  - Host RAM% is overlaid on every frame ([p999-3-d-01](#p999-3-d-01)).
  - `/ws/state` is unauthenticated, but the handshake Origin is validated (Aug 2026).
- **Rationale:** The simulation must never block on a slow client (CLAUDE.md hard constraint 4). An explicit, versioned frame turns a renamed internal field into a failing test instead of a silently broken UI, and gives the UI the cycle identity it needs to fetch the right cycle's edges.

### <a id="adr-replaystore-separate"></a>ReplayStore is separate from StateStore
- **Decision:** Replay builds its own `ReplayStore` (`state.py:323`) inside `ReplayManager`. While replay is active, the broadcaster reads it instead of live state. Replay and live simulation exclude each other (B4). Replay never writes the live StateStore phase: start and stop leave IDLE or COMPLETE as they were, so a replay cannot block a report or a new run ([p34-d-10](#p34-d-10), 2026-10).
- **Rationale:** Reusing StateStore would corrupt the live run. The rationale drain was destructive at the time, and the elapsed timer would restart.
- **Read model (2026-10):** Replay shows every configured bracket in config order, with its display name. Bracket rows count BUY/SELL/HOLD only: `total` and the averages exclude PARSE_ERROR, so a replayed round matches the live frame's `compute_bracket_summaries`. The report's consensus summary, by contrast, gives PARSE_ERROR its own row ([adr-report-react](#adr-report-react)). Rationales come from `Decision.rationale` ([adr-neo4j-schema](#adr-neo4j-schema)).

### <a id="adr-neo4j-schema"></a>Neo4j graph model
- **Decision:**
  - Decisions are nodes ([p4-d-01](#p4-d-01)).
  - Citations are `(Decision)-[:CITED]->(Agent)`.
  - INFLUENCED_BY is **Agent→Agent** with `{weight, cycle_id, round}`, created per round with CREATE, so readers must filter by round (`graph.py:1074-1100`).
  - This supersedes Phase 4's planned Decision→Decision INFLUENCED_BY edge.
  - Writes are UNWIND batches. Sessions are opened per method. 100 shared Agent nodes.
  - The `neo4j` driver is pinned below 6.0.
  - The Cycle stores `num_rounds` from creation ([adr-num-rounds](#adr-num-rounds)).
  - Readers take rationale text from `Decision.rationale`. `RationaleEpisode.rationale` duplicates it and is still written, but replay no longer reads it (2026-10).
- **Rationale:** Cycle-scoped edges keep reads fast without pruning history.

### <a id="adr-cycle-metrics"></a>Per-cycle run metrics on the Cycle node
- **Decision:** At the end of a run, `write_cycle_metrics` stamps durations, flips, parse errors, `r{n}_inference_errors` (the subset of `r{n}_parse_errors` whose `error_kind` is `"inference"`, for the rounds actually run), `final_round` and the final distribution onto the Cycle node (`graph.py`). `metrics_recorded_at` marks a cycle as complete for listing (`graph.py`, `read_completed_cycles`) and for the report, advisory and interview gates (`read_cycle_status`, which also accepts a round-3 decision until cycles store a status). Compare runs with `scripts/compare_cycles.py` against `scripts/benchmark_seeds.json`.
- **Provenance and peer keys:** each cycle also records `orchestrator_provider` / `worker_provider` (`ollama` for local providers, `cloud` otherwise; the model id identifies the cloud provider), `orchestrator_model`, `worker_model`, `inference_mode` (`local` / `cloud` / `mixed`), `git_sha` (empty when unknown) and `git_dirty` (omitted when unknown, because a Neo4j property cannot be null), the effective peer parameters (`peer_selection_version`, `peer_limit`, `peer_min_brackets`, `peer_bracket_cap`, `peer_budget_chars`, `peer_personal_boost`, `peer_seed_source`), the experiment knobs `own_prior_memory` and `control_fraction`, and the per-round exposure and holdout keys from [adr-diverse-peer-context](#adr-diverse-peer-context). Older cycles lack these keys, so every reader must tolerate missing keys. `git_revision` lives in `alphaswarm/manifest.py`; `current_git_revision` reads it once per process, and the web lifespan makes that read at startup, so a server stamps the revision whose code it runs even after a later commit.
- **Rationale:** A/B experiments (rounds, peers, models) need durable numbers. All history before June 2026 was lost (see [adr-tests-scoped-cleanup](#adr-tests-scoped-cleanup)).

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
- **Status (2026-10):** Only the point-in-time groundwork is built: the records, outcome labels and scoring statistics in `alphaswarm.evaluation`, the fixtures in `alphaswarm.ingestion.fixture`, `alphaswarm run --context-fixture` and `--no-market-context`, the `eval/build_fixtures.py` and `eval/label_outcomes.py` scripts, and `eval/pilot.py`, a preliminary pilot that runs three unseeded, untagged two-round repeats of about five events and finds them again by rumor text and start time. Not built yet: the curated event set with its fixtures and labels; `sim_seed`, experiment tags and run manifests; `eval/registered_simulation.json`; the worker-sampled and self-consistency baselines; separate Narrators scoring; and `docs/methodology.md`, so for now the scoring constants are fixed only in `alphaswarm.evaluation`. Until those land, the Decision bullets above describe the target design, not current behaviour.

### <a id="adr-holdings-isolation"></a>Holdings isolation: the swarm never sees the portfolio
- **Decision:** Portfolio data never enters swarm prompts, Neo4j, WebSocket frames, or logs. It reaches only the post-simulation advisory call. Enforcement:
  1. An import-linter `forbidden` contract allows only `alphaswarm.advisory` and `alphaswarm.web.routes.holdings` to import `alphaswarm.holdings` (`pyproject.toml [tool.importlinter]`; [p37-d-04](#p37-d-04)).
  2. A four-surface sentinel canary runs the real `synthesize()` (`tests/invariants/test_holdings_isolation.py`).
  3. A fail-closed structlog PII redactor ([p37-d-05](#p37-d-05)..[p37-d-07](#p37-d-07)). Tracebacks are rendered without local variables in both modes (JSON: `ExceptionDictTransformer(show_locals=False)` before the redactor; console: `plain_traceback`), so frames never leak keys or portfolio objects (2026-10).
  4. Holdings are loaded into memory at lifespan startup (`PortfolioCache`, re-read when the CSV changes) and never persisted ([p39-d-07](#p39-d-07)).
- **Rationale:** Uncontaminated consensus, plus privacy for real brokerage data.
- **Gate:** `uv run lint-imports` runs in the CI `lint` job (next to strict mypy) and as a pre-commit hook, and `tests/invariants/test_importlinter_contract.py` runs it inside pytest. Ruff is not gated yet.

### <a id="adr-provider-never-raise"></a>Market/news providers never raise
- **Decision:** `MarketDataProvider` and `NewsProvider` use batch-first signatures. Failures become `staleness="fetch_failed"` slices. Fakes live next to the protocols ([p37-d-17](#p37-d-17)..[p37-d-20](#p37-d-20)).
- **Implementations:**
  - yfinance per ticker via `to_thread` + gather.
  - RSS: Yahoo Finance for tickers, Google News otherwise.
  - No caching. Both feed a `DataSourceAuditBuffer` that the Signal Wire shows.

### <a id="adr-market-context"></a>Grounded market context: Round 1 only, fenced
- **Decision:**
  - One formatted block per run: price, fundamentals, and 5 headlines per entity.
  - It is its own system message, after the persona and before the user message, sent in Round 1 only ([Phase 40](#phase-40-simulation-context-wiring)).
  - RSS headlines are fenced as untrusted data (Aug 2026, F3) and sanitized.
- **Rationale:** Treat third-party text as untrusted. *(Inferred, not recorded: the Phase 40 CONTEXT doc gives no reason for limiting the block to Round 1. The likely intent was to ground the prior without letting market data drown out peer dynamics. Treat this as a hypothesis to test, not a settled decision.)*

### <a id="adr-advisory-pipeline"></a>Advisory synthesis
- **Decision:**
  - Prefetch swarm data in parallel, then make one orchestrator call ([p41-d-04](#p41-d-04), [p41-d-05](#p41-d-05)).
  - Relevance scoring uses a curated ticker→sector map plus an entity-impact join (F-07, F-28).
  - The LLM receives only the top 15 holdings by relevance (`advisory/engine.py:173`). Every other holding is padded server-side as HOLD@0.30 (SWEEP B-7), so items[] has exactly one entry per holding.
  - Unknown tickers default to `macro_beta` 0.5 (SWEEP B-8).
  - Ranking: confidence × exposure / total basis.
  - Output goes to `advisory/{cycle_id}_advisory.json`, served by a 202 + polling + done-callback API.
  - Runs from PostRunPipeline after every completed run when holdings are loaded (cloud orchestrator: only with the opt-in); the report runs afterwards in every case, including no holdings and advisory failure. Holdings come from PortfolioCache, which re-reads the CSV when its mtime changes.
  - Advisory failures, `AuthError` and `BudgetExceededError` included, are logged with their traceback (`advisory_task_exception_recorded`), recorded for GET (500 `advisory_generation_failed`), and do not stop the report. This is deliberate: the report needs no holdings and must not be lost to an advisory failure (2026-10).
  - Runs only when the orchestrator is local or `allow_cloud_advisory` is true in the inference config. Local means all three of: provider Ollama; not an Ollama cloud model (any dash- or colon-separated part of the name or tag that is exactly `cloud`, e.g. `gpt-oss:120b-cloud`, `glm-4.6:cloud`, `foo-cloud:latest`; this over-blocks a few odd local names on purpose); and a loopback Ollama server (`localhost`, 127.0.0.0/8 or `::1`). The server checked is read from the shared `OllamaClient` itself (`OllamaClient.base_url`, the httpx host after ollama resolved `AppSettings.ollama.base_url` or `OLLAMA_HOST`), so the check and the connection read the same value. A non-loopback `base_url` on the orchestrator role also counts as remote, even though `OllamaProvider` ignores it today. Anything unparseable, and host spellings such as 0.0.0.0, `127.1` or `0x7f000001`, fail closed (`inference/factory.py:advisory_block_reason`, 2026-10-21); the refusal log carries `reason` (`cloud_provider`, `role_base_url_remote`, `cloud_model`, `remote_host`, `remote_model`). A name cannot reveal an alias whose Modelfile is `FROM` a cloud model, and the default `alphaswarm-orchestrator` is such an alias, so before synthesis the job also asks the server (`OllamaClient.is_remote_model`, raw `/api/show`; newer servers set `remote_host`/`remote_model` for cloud models) and refuses when it reports a remote model or the request fails. The `OllamaClient` httpx client sets `trust_env=False` (an `HTTP_PROXY`/`ALL_PROXY` or macOS system proxy gets no localhost bypass in httpx and would receive the prompt) and `follow_redirects=False`. The opt-in is edited in `.secrets/inference.json`; the Settings UI preserves it but has no toggle yet. Otherwise the POST returns 409 `cloud_advisory_disabled` before the holdings are read, the job refuses as well, and the post-run pipeline skips the advisory and logs `auto_advisory_skipped_cloud` (T7.2, 2026-10). The POST route and the pipeline share `web/routes/advisory.py:advisory_refusal`, which records the refusal, so GET returns `cloud_advisory_disabled` instead of a pending 404. An unreadable inference config fails closed with 422 `inference_config_invalid`; the post-run pipeline then skips the advisory the same way (recorded, so GET returns `inference_config_invalid`) and still runs the report.

### <a id="adr-report-react"></a>Report: prompt-based ReAct producing markdown
- **Decision:**
  - The loop uses literal `ACTION:`/`INPUT:` lines, a hard iteration cap, and duplicate-call detection.
  - Tools are Cypher reads.
  - Output is Jinja2 → markdown at `reports/{cycle_id}_report.md`.
  - An invariant test asserts that every tool named in the prompt exists in the dispatch registry (F-06, `tests/test_report.py:28`).
- **Rationale:** Ollama's native tool calling was unreliable for Qwen models (2026-03 research). Markdown replaced the HTML export that was lost (see [§2](#2-historical-decisions-no-longer-in-code)).
- **Update (2026-10):** Report reads return typed rows (the row TypedDicts in `graph.py`, such as `ConsensusSummaryRow` and `ShockImpactRow`), and templates render under Jinja `StrictUndefined`. A template that reads a key its query does not return now fails the report instead of rendering a blank column. Free text goes through the `md_cell` filter (pipes escaped, whitespace collapsed) and numbers through `num` (fixed digits, "—" for a missing value).
  - Reads describe the final round ([adr-num-rounds](#adr-num-rounds)), and the timeline covers every round that ran. PARSE_ERROR has its own row in the consensus summary and its own column in the timeline, so the shares add up to 100%.
  - Failed (PARSE_ERROR) agents are excluded from dissenters, bracket stances and averages, entity impact, and shock pivots. A bracket where every agent failed has no majority ("—").
  - "Influence Weight" became `influence_share` = citations / active final-round agents, which is the [p8-d-01](#p8-d-01) edge weight.
  - Signals in the typed report rows are upper-case (`BUY`, `SELL`, `HOLD`). Replay rows stay lower-case because they map onto `SignalType`.
  - The shock section analyses only the earliest shock of a cycle. A second shock queued before Round 3 is not analysed.
  - Entity impact counts only the cycle's own `MENTIONS` entities, once per (entity, decision) pair ([p11-d-08](#p11-d-08)).
  - `social_post_reach` remains until the section is removed. It returns rows only for cycles with READ_POST edges (written before June 2026), and its template reads the query's `author_name`.

### <a id="adr-background-tasks"></a>Long LLM jobs: 202 + background task + polling
- **Decision:** Report and advisory POSTs return 202 and run `asyncio` tasks.
  - POST gates on durable state: 409 `simulation_running` during a run, 404 `cycle_not_found` for an unknown cycle, 422 `cycle_not_ready` unless the cycle reads as complete (`GraphStateManager.read_cycle_status`: a stored `Cycle.status` when there is one, else metrics stamped or a round-3 decision), 409 `*_generation_in_progress` while the orchestrator slot is taken. The in-memory phase is not consulted, so historical cycles work after a restart or a replay.
  - Job status lives in StateStore (`JobStatus` idle/running/failed per job kind); done-callbacks record failures per cycle with the exception class only, refusals with their fixed message (T-36-15).
  - GET returns 200 with the file, 409 `*_generation_in_progress` while that cycle's job runs, 500 after a recorded failure, 404 otherwise. File probes are async (T-36-14); writes are atomic (`fsutil.atomic_write_text`).
  - Cycle ids are validated by the `CycleId` uuid4 path type (`web/params.py`); malformed ids return 422 `validation_error` (T-36-01). Every error uses the envelope from `web/errors.py`.
  - The report modal polls only on 409 `report_generation_in_progress`; `usePolling` keeps at most one request in flight (F-16) and surfaces timeouts ([p41-6-d-19](#p41-6-d-19)).

### <a id="adr-web-lifespan"></a>Web process shape
- **Decision:**
  - Uvicorn owns the event loop. Every stateful object is built in the FastAPI lifespan ([p29-d-04](#p29-d-04)).
  - `create_app(settings=None)` stores the settings on `app.state.settings`, and the lifespan reads them instead of building `AppSettings()` itself, so tests and launchers choose the configuration explicitly. `None` reads the environment and `.env`, as before. The module-level `app` behind `uvicorn alphaswarm.web.app:app` is built on first access, not at import: every `alphaswarm.web` import loads the module, and pytest imports it before its hermetic fixture runs, so an import-time app would keep the operator's settings, holdings path included (2026-10).
  - Each domain has a sub-router.
  - Startup verifies Neo4j and runs `ensure_schema()` (constraints, indexes, and the 100 Agent nodes every write matches). Driver or auth errors log `neo4j_unavailable_at_startup`, set `app.state.neo4j_ready = False`, and the server keeps serving (2026-10).
  - FastAPI serves `frontend/dist` at `/` when it has been built ([p31-d-02](#p31-d-02)). In development, Vite on :5173 proxies `/api` and `/ws`, with `changeOrigin: true` on both. When the backend is down, the `/api` proxy answers 502 `backend_unreachable` (`frontend/src/lib/backendUnreachable.ts`) instead of an empty 500, so the UI shows the same "Cannot reach the backend" hint as a failed fetch.
  - `./start` (cds to the repo root, then runs `python -m alphaswarm web`) and `uv run start` (`cli:main_web`, no cd) both run uvicorn on 127.0.0.1:8000. Runtime paths (`.env`, the holdings CSV, `.secrets/inference.json`, `advisory/`, `reports/`) resolve against the repository root (`config.PROJECT_ROOT`, `AppSettings.resolve_path`), so the server may start from any directory.

### <a id="adr-frontend-quant-terminal"></a>Frontend: React + TS "Quant Terminal"
- **Decision:**
  - React 19 + Vite 6 + TypeScript, ported from the AlphaSwarm-2 design export (Phase 41.6).
  - Split React contexts (Connection, Telemetry, Agents, Rationales, Edges, FrameMeta) so 5 Hz frames do not re-render everything. Influence edges load once per (cycle, round, edges_version) through `EdgesContext`, keyed on the frame's cycle id, and every panel reads that one copy.
  - The lifecycle (idle, seeding, live, complete, replay) comes from the frame, so the shell, Run/Stop and the replay bar look the same after a reload; idle and seeding are overlays inside the canvas.
  - While the post-run advisory/report jobs hold the orchestrator (frame `jobs`), Run is disabled and reads "Report generating…" / "Advisory generating…": a new run would evict the orchestrator mid-report. The backend refuses the start with 409 `post_run_jobs_in_progress` anyway (decided Oct 2026 under the owner's delegation).
  - Deterministic SVG agent layout instead of d3-force ([KR-41.1-01](#kr-41-1-01)).
  - Design mocks are loaded only through DEV-only dynamic imports, and a production grep gate keeps them out of `dist` ([KR-41.6-14](#kr-41-6-14)).
  - Tests and lint (`frontend/TESTING.md`): vitest runs pure tests in node and hook/component tests on happy-dom with React Testing Library; backend-written golden frames pin the wire contract ([adr-ws-broadcaster](#adr-ws-broadcaster)); ESLint (typescript-eslint, react-hooks; jsx-a11y at `warn` until the accessibility pass) runs in CI. ESLint stays on 9.x while eslint-plugin-jsx-a11y supports nothing newer.
- **History:** Textual TUI, then Vue 3 + D3 force graph, then a React port of the Claude Design UI, then the AlphaSwarm-2 Quant Terminal. See HISTORY.md.

### <a id="adr-test-network-gate"></a>Tests are offline by default
- **Decision:** `pytest-socket --disable-socket --allow-unix-socket` applies globally (`pyproject.toml` addopts). `tests/integration/` auto-enables sockets ([p37-d-12](#p37-d-12)). Tests marked `neo4j` get sockets (and, when async, the session event loop shared with the session-scoped driver) from a collection hook in `tests/conftest.py`, and skip unless the throwaway `neo4j-test` database answers on 127.0.0.1:7688 (`--require-neo4j` turns the skip into a failure).
- **Note:** Phase 41.2 D-08 planned to make integration tests opt-in through an `integration` marker. That was never done; see BACKLOG.
- **CI (2026-10):** `backend` runs `-m "not neo4j"`; `backend-neo4j` runs `-m neo4j --require-neo4j` against a `neo4j:5.26-community` service container on 7688. Every test has a 60 s timeout (`pytest-timeout`) and every job a 15-minute one. The `tests/integration/` path hook still opens sockets in `backend`, so live Yahoo and Google News calls remain in CI (BACKLOG 1.8).

### <a id="adr-tests-scoped-cleanup"></a>Neo4j tests run only against a throwaway database
- **Decision (2026-10):** Neo4j tests use the `neo4j-test` Compose service (profile `test`, `127.0.0.1:7688`, tmpfs, throwaway credential), started with `scripts/neo4j_test.sh up`. The URI is hard-coded in `tests/conftest.py`, never read from the environment. The session fixture `neo4j_test_driver` exits with code 3 on port 7687 or on a database that already holds `Cycle` nodes. `graph_manager_test` deletes only the cycles created during the test (never ids in `NEO4J_PROTECTED_CYCLES`). An autouse `hermetic_env` fixture clears `ALPHASWARM_*`, ignores `.env`, and points the inference config and holdings CSV at temp paths.
- **Rationale:** Until 2026-06-10, unscoped `DETACH DELETE` ran against the live `neo4j` database after every test and destroyed all real cycle history. Community Edition has no second database, so the isolation is a second container.
- **Rule:** The only unscoped `DETACH DELETE` allowed anywhere is the `neo4j_test_driver` session teardown, after both guards pass. Never point a test at 7687. Start and stop `neo4j-test` only with `scripts/neo4j_test.sh`, which uses `compose rm` for the test container: a bare `docker compose --profile test down` also removes the dev container, and any `compose down`, even with a service name, deletes the project network a stopped dev container needs. `/data` and `/logs` are both on tmpfs, so no volume outlives the container.

### <a id="adr-engine-scenario-harness"></a>Engine scenarios run the real `run_simulation` on scripted fakes
- **Decision (2026-10):** `tests/engine/` drives the real `run_simulation` end to end with no Ollama, Neo4j or memory governor. The worker and orchestrator are `ScriptedProvider`s (`tests/inference/fakes.py`), which classify each call (decision, narrative, interview chat, orchestrator). Decision calls are answered by a deterministic `DecisionFn`, orchestrator calls from a fixed script, and narrative and interview calls with canned text. The graph is an autospecced `GraphStateManager` mock, so a call with the wrong signature raises `TypeError`. Concurrency goes through `ImmediateController` (`tests/support/controllers.py`), which never waits and counts acquires, releases, failures and monitoring sessions. `scenario_settings` sets both dispatch jitter bounds to 0.0, and the autouse `forbid_real_sleep` fixture fails any engine test that asks `asyncio.sleep` for wall-clock time.
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
- **Commits:** 53e5954, 72d55a9, 45c7827, 1e7a8ee, e353716, 820b8fe.

---

## 2. Historical decisions no longer in code

| Decision (when) | Rationale | What happened |
|---|---|---|
| <a id="hist-pygal-html-report"></a>pygal SVG charts over Plotly; HTML report with portfolio overlay (Phase 24, 2026-04-09) | Kept HTML reports under 1 MB versus over 15 MB with Plotly | **Lost.** Commit `f5330a6` (2026-04-11, mislabelled `test(27-01)`) deleted `charts.py`, `portfolio.py`, `report.html.j2`, and their tests during a worktree merge. Reports are markdown only; SWEEP B-1 later rewrote the orphaned tests. |
| <a id="hist-governor-suspend"></a>Governor `suspend()`/`resume()` around the shock window, with the memory-pressure guard at the callee (governor) to avoid a TOCTOU race; nested try/finally in `_collect_inter_round_shock` (Phase 26) | Prevented false THROTTLED states while the TUI waited for shock text | **Lost/obsolete.** The same `f5330a6` removed suspend/resume. The web shock path (Phase 35.1) never pauses: a queued shock is consumed by `consume_shock()` before Rounds 2 and 3 (`simulation.py:1144-1160, 1301-1318`). |
| <a id="hist-shock-max-len"></a>`SHOCK_TEXT_MAX_LEN = 4096` caps shock text (STATE.md) | Bounds prompt growth across 100 agents | **Replaced:** ShockText (web/params.py) bounds shock text to 10-1000 characters; shocks posted after the last gated round has started get 409 shock_window_closed, and applied shocks are carried into every later round. |
| <a id="hist-v3-ticker-pipeline"></a>v3.0 SEC-validated ticker extraction, yfinance + Alpha Vantage pipeline with a disk cache, bracket-tailored enrichment, TickerDecision output (Phases 16-23, 2026-04-05..08) | First attempt at grounding in real data | **Lost.** Commit `7226d2e` (2026-04-09, mislabelled `feat(24-01)`) deleted `enrichment.py`, `market_data.py`, `ticker_validator.py`, and their tests: about 4.4k lines of source and tests. Most of the commit's 25.6k deleted lines (about 20.6k) were v3.0 planning docs. v6.0 Phases 37-40 rebuilt grounding as `alphaswarm.ingestion`. |
| <a id="hist-miro"></a>Miro API v2 live visualization; batcher stubbed (Phase 8 D-09/D-10) | Planned spatial visualization | **Dropped** for the web graph. `miro.py` was deleted in `76b7537` (2026-06-11). |
| <a id="hist-tui"></a>Textual TUI as the primary UI (Phases 9-10, 14, 26-28) | First interface | **Retired** in favor of the web UI. `tui.py` was deleted in `76b7537`. The StateStore contracts it introduced survive. |
| <a id="hist-read-post"></a>Posts ranked by INFLUENCED_BY weight via `read_ranked_posts`; READ_POST edges from every agent to every prior post (Phase 12 D-07..D-11) | Social-influence layer | **Superseded** by [adr-diverse-peer-context](#adr-diverse-peer-context). Post nodes are still written, but READ_POST edges are not, so `read_social_post_reach` returns nothing for new cycles. |
| <a id="hist-schwab-report-only"></a>Schwab CSV loaded in memory only during the report step | Privacy | **Changed:** now loaded at web lifespan startup into `PortfolioCache` and re-read when the CSV changes ([p39-d-07](#p39-d-07)). Still memory-only and never persisted. |

---

## 3. Phase-scoped D-xx index

Every legacy `D-xx` reference found in live code (`src/`, `tests/`,
`frontend/src/`, `pyproject.toml`, `.pre-commit-config.yaml`, `CLAUDE.md`) is
listed under its originating phase. Paths drop the `src/alphaswarm/` prefix, and
`fe/` stands for `frontend/src/`. Three hits are agent IDs, not decisions, and are
excluded: `README.md:105` and `frontend/src/mocks/wire.ts:16,24`.
Phase 26/29/30/31 CONTEXT docs were deleted from `.planning/` by the accidental
commits `f5330a6` and `343669f`. Their decisions were recovered from git history.

### Phase 3: Resource governance (governor, memory monitor)

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p3-d-01"></a>`D-01` | After a pressure crisis clears, restore slots gradually (+2 per check) instead of snapping back; avoids re-triggering pressure. | active | config.py:94; governor.py:545,557 |
| <a id="p3-d-02"></a>`D-02` | Scale above baseline (up to max_parallel) only after consecutive calm memory checks. | active | config.py:94; tests/test_governor.py:377,382 |
| <a id="p3-d-03"></a>`D-03` | After crisis recovery reset to baseline, not the pre-incident slot count. | active | governor.py:503,524,528; tests/test_governor.py:278 |
| <a id="p3-d-04"></a>`D-04` | If >=20% of a dispatch wave fails, shrink the governor (per-wave failure scope). | active | config.py:94; governor.py:278; tests/test_governor.py:497,505 |
| <a id="p3-d-05"></a>`D-05` | Shrink by a fixed step (2) per trigger, never below 1 slot; gradual degradation, not halving. | active | config.py:94; governor.py:278,290; tests/test_governor.py:497,519 |
| <a id="p3-d-07"></a>`D-07` | Abort with GovernorCrisisError after a sustained crisis (default 5 min) with no successful inference. | active | config.py:94; governor.py:503,507; tests/test_governor.py:445,453 |
| <a id="p3-d-08"></a>`D-08` | Any successful inference resets the crisis timeout clock, even at 1 slot. | active | governor.py:227; tests/test_governor.py:445,476 |
| <a id="p3-d-09"></a>`D-09` | Governor reports via structlog AND StateStore metrics (GovernorMetrics) so the UI can show telemetry. | active | governor.py:408; state.py:22 |
| <a id="p3-d-11"></a>`D-11` | Metrics emitted to StateStore on state change. Later (8521e91, Jun 2026) also emitted every check for the live UI. | partial | governor.py:408; state.py:22 |
| <a id="p3-d-12"></a>`D-12` | Dual-signal memory sensing: psutil percent plus macOS kernel pressure. Implemented with sysctl kern.memorystatus_vm_pressure_level (not the memory_pressure CLI); unknown values map to GREEN, read failures are fail-stale since F-17. | partial | memory_monitor.py:39 |
| <a id="p3-d-13"></a>`D-13` | Kernel pressure YELLOW/RED is the master signal: halt the queue and drop to 1 slot. | active | governor.py:433; tests/test_governor.py:269 |
| <a id="p3-d-14"></a>`D-14` | Random jitter (0.5-1.5s) before each agent dispatch, applied in batch_dispatcher, not inside the worker; spreads load spikes. Both bounds accept 0.0 (2026-10) so deterministic tests can turn jitter off ([adr-engine-scenario-harness](#adr-engine-scenario-harness)); the defaults are unchanged. | active | batch_dispatcher.py:52; config.py:94,102 |

### Phase 4: Neo4j graph state

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p4-d-01"></a>`D-01` | A Decision is a node (Agent-[:MADE]->Decision-[:FOR]->Cycle) holding signal/confidence/sentiment/rationale, not a relationship. | active | graph.py:389 |
| <a id="p4-d-03"></a>`D-03` | cited_agents stored as explicit (Decision)-[:CITED]->(Agent) edges (raw LLM output), separate from computed INFLUENCED_BY. | active | graph.py:389 |
| <a id="p4-d-05"></a>`D-05` | Schema applied idempotently at startup via ensure_schema() (CREATE ... IF NOT EXISTS). Since 2026-10 a web server whose Neo4j was down or rejected the password at startup still starts; once the database answers, the first `/api/health` probe applies the schema (no restart for a database that was only stopped). | active | graph.py:99; web/app.py (`_prepare_neo4j`); web/routes/health.py; readiness.py |
| <a id="p4-d-06"></a>`D-06` | All 100 Agent nodes seeded eagerly in ensure_schema() from persona config. | active | graph.py:112 |
| <a id="p4-d-07"></a>`D-07` | Session-per-method: each GraphStateManager method opens its own short-lived async session; callers never manage sessions. | active | graph.py:82 |
| <a id="p4-d-08"></a>`D-08` | Keep the GraphStateManager API minimal and batch writes via UNWIND (one transaction per round, not per agent). | active | graph.py:82,389 |
| <a id="p4-d-09"></a>`D-09` | Pre-dynamic-topology peer ranking by static influence_weight_base (read_peer_decisions). Now only used by the dead _dispatch_round path. | superseded | graph.py:734 |
| <a id="p4-d-10"></a>`D-10` | cycle_id is a uuid4. | active | graph.py:188 |

### Phase 5: Seed injection and agent personas

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p5-d-06"></a>`D-06` | Seed parsing uses parse_seed_event() with the same 3-tier fallback as agent decisions (JSON -> extraction -> error). | active | seed.py:80 |
| <a id="p5-d-07"></a>`D-07` | Seed injection owns its orchestrator lifecycle (prepare -> extract -> always tear down in finally). | active | seed.py:5,65,116 |

### Phase 7: Rounds 2-3: peer influence and consensus

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p7-d-03"></a>`D-03` | Peer context carries a header naming the source round. | active | simulation.py:376 |
| <a id="p7-d-04"></a>`D-04` | Single run_simulation() orchestrates all rounds, reusing run_round1() for Round 1. | active | simulation.py:933 |
| <a id="p7-d-05"></a>`D-05` | Worker reloaded once after run_round1() (which unloads in its finally) and kept warm for later rounds. | active | simulation.py:957,1129 |
| <a id="p7-d-06"></a>`D-06` | run_round1 owns its governor monitoring session; run_simulation starts a fresh one for Rounds 2-3. | active | simulation.py:951,958,1132 |
| <a id="p7-d-07"></a>`D-07` | Phase machine IDLE -> SEEDING -> ROUND_1..N -> FINALIZING -> COMPLETE. FINALIZING covers narratives (while eager) and metrics. StateStore.set_phase drives the UI. | active | simulation.py (run_simulation); types.py (SimulationPhase) |
| <a id="p7-d-08"></a>`D-08` | SimulationResult is one frozen container for all rounds plus shift metrics. | active | simulation.py:292 |
| <a id="p7-d-09"></a>`D-09` | Round N reads peer context from round N-1, personalised per agent (self excluded). | active | simulation.py:758,1135,1293 |
| <a id="p7-d-10"></a>`D-10` | Peer contexts are built per agent BEFORE dispatch and passed into dispatch_wave. | active | simulation.py:758,846 |
| <a id="p7-d-11"></a>`D-11` | Track signal flips between rounds with a transition breakdown. | active | simulation.py:509,531 |
| <a id="p7-d-12"></a>`D-12` | Track per-bracket average confidence delta between rounds. | active | simulation.py:509,537 |
| <a id="p7-d-13"></a>`D-13` | Shift metrics computed in memory from round results; no Neo4j query. | active | simulation.py:509,511,1261,1421 |
| <a id="p7-d-14"></a>`D-14` | CLI prints each round's report as it completes via an on_round_complete callback. | active | cli.py:491; tests/test_cli.py:882 |
| <a id="p7-d-17"></a>`D-17` | The `run` CLI subcommand runs the full multi-round simulation. | active | cli.py:490; tests/test_cli.py:882 |

### Phase 8: Dynamic influence topology

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p8-d-01"></a>`D-01` | INFLUENCED_BY weight = citations received / active agents (simple, interpretable). | active | graph.py:980,1013 |
| <a id="p8-d-02"></a>`D-02` | Compute influence edges after each round so topology shapes the next round. R1 computation since removed (SWEEP B-5); R3 computation added (260512-jqn ITEM 2). | partial | graph.py:980,1059; simulation.py:954 |
| <a id="p8-d-03"></a>`D-03` | Every citation pair produces an edge; no threshold. Edge weight is the target's citation share. | active | graph.py:980 |
| <a id="p8-d-04"></a>`D-04` | Weights are cumulative across rounds (round <= up_to_round). | active | graph.py:980,984,1058; simulation.py:961,1242,1400 |
| <a id="p8-d-05"></a>`D-05` | Cold start: when no citations exist, fall back to static influence_weight_base. The explicit fallback (sequential `read_peer_decisions` reads) survives only inside the dead `_dispatch_round`. The production path (`_build_diverse_peer_contexts`) always adds base reach to citation share, so with zero citations it samples by base reach alone ([adr-diverse-peer-context](#adr-diverse-peer-context)); no static ordering remains. | superseded | simulation.py (`_dispatch_round`, `_build_diverse_peer_contexts`) |
| <a id="p8-d-06"></a>`D-06` | Bracket-diverse peer selection: top-1 from the top N brackets, then fill by weight. Superseded by seeded stratified sampling with a per-bracket cap ([adr-diverse-peer-context](#adr-diverse-peer-context)). | superseded | simulation.py (select_diverse_peers) |
| <a id="p8-d-07"></a>`D-07` | Bracket aggregation computed in memory from the round's decisions. | active | simulation.py:107; state.py:35 |
| <a id="p8-d-08"></a>`D-08` | BracketSummary frozen dataclass promoted into the simulation layer and carried on SimulationResult; CLI and UI share it. | active | cli.py:240,294,417; simulation.py:107,287,304,305,306,955,963,1105,1253,1410; state.py:35 |

### Phase 9: TUI core dashboard (retired UI; StateStore contracts survive)

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p9-d-02"></a>`D-02` | Per-agent StateStore writes as each agent resolves. Restored in May 2026 by streaming from batch_dispatcher._safe_agent_inference. | active | state.py:97,139 |
| <a id="p9-d-05"></a>`D-05` | Clear agent states at each round start for a clean visual slate. Superseded: keys now persist with signal=None ('thinking') so 5Hz frames are never empty. | superseded | state.py:150; tests/test_state.py:63 |

### Phase 10: TUI panels and telemetry (retired UI; StateStore contracts survive)

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p10-d-02"></a>`D-02` | Rationale feed fed by top-influence agents after each round. Superseded by per-agent streaming push_rationale + 50-entry sliding window (260512-jqn ITEM 4). The end-of-round calls were removed, but the `_push_top_rationales` function itself survives at simulation.py:317 as dead code that only `tests/test_state.py:375` calls. | superseded | simulation.py:324 |
| <a id="p10-d-03"></a>`D-03` | Rationale feed entries truncated to ~50 chars by the producer (sanitize_rationale(max_len=50)). | active | simulation.py:327; state.py:53,57 |
| <a id="p10-d-04"></a>`D-04` | Feed shows newest first. | active | state.py:53 |
| <a id="p10-d-05"></a>`D-05` | TPS computed from Ollama eval_count/eval_duration and accumulated in StateStore.update_tps. | active | state.py:216; worker.py:200 |
| <a id="p10-d-08"></a>`D-08` | StateStore.set_bracket_summaries after each round; all 10 brackets always shown. | active | state.py:229 |

### Phase 11: Live graph memory

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p11-d-01"></a>`D-01` | WriteBuffer queues per-agent episodes and flushes in one UNWIND batch per round. | active | simulation.py:1068; write_buffer.py:1 |
| <a id="p11-d-02"></a>`D-02` | WriteBuffer is separate from GraphStateManager (queueing vs Cypher). | active | write_buffer.py:1 |
| <a id="p11-d-04"></a>`D-04` | RationaleEpisode linked 1:1 via (Decision)-[:HAS_EPISODE]->(RationaleEpisode). | active | graph.py:803 |
| <a id="p11-d-06"></a>`D-06` | flip_type enum stored on each episode (NONE for round 1). | active | types.py:75 |
| <a id="p11-d-07"></a>`D-07` | Episode properties: rationale, timestamp, peer_context_received, flip_type, round, cycle_id. | active | graph.py:803 |
| <a id="p11-d-08"></a>`D-08` | Decision-[:REFERENCES]->Entity via case-insensitive substring match; no NLP dependency. The match is on the name only, so a REFERENCES edge can also reach a same-name entity of another type or cycle, and a seed that lists an entity twice writes duplicate MENTIONS and REFERENCES edges. Report entity impact therefore joins through the cycle's own `MENTIONS` and counts each (entity, decision) pair once (2026-10). | active | graph.py:872; tests/neo4j/test_graph_integration.py (test_references_edges_case_insensitive); tests/neo4j/test_report_reads.py (test_entity_impact_counts_each_decision_once_for_the_cycles_own_entities) |
| <a id="p11-d-09"></a>`D-09` | REFERENCES written in the same post-round flush; entity names loaded once per cycle. | active | graph.py:872,919; simulation.py:1068 |
| <a id="p11-d-10"></a>`D-10` | Post-simulation decision_narrative per agent written to Agent nodes (used by interviews/advisory). | active | graph.py:938; simulation.py:1441,1531,1544; tests/neo4j/test_graph_integration.py (test_complete_reasoning_arc, test_write_decision_narratives_integration) |
| <a id="p11-d-11"></a>`D-11` | Narratives generated eagerly as 100 worker calls after the last round. Lazy generation is an open backlog idea. | active | simulation.py:1441,1531,1544 |

### Phase 12: Richer agent interactions (posts)

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p12-d-04"></a>`D-04` | Peer context budget: 4000 chars, K posts, greedy fill, last post truncated at a word boundary. | active | simulation.py:372 |
| <a id="p12-d-05"></a>`D-05` | Unified peer-context block format (now `[agent_id|bracket] SIGNAL (conf)` lines so agents can cite IDs). | active | simulation.py:372 |
| <a id="p12-d-06"></a>`D-06` | _format_peer_context accepts post objects and applies the budget. | active | simulation.py:372 |
| <a id="p12-d-12"></a>`D-12` | Per-round write order: decisions -> posts -> (formerly READ_POST edges) -> next dispatch. READ_POST edges no longer written since Jun 2026. | partial | simulation.py:1212 |
| <a id="p12-d-13"></a>`D-13` | Round 1 has no peer context; posts written after R1 so R2 can read them. | active | simulation.py:1090 |

### Phase 13: Dynamic persona generation (modifiers)

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p13-d-01"></a>`D-01` | Orchestrator generates one entity-aware modifier per bracket from the seed. | active | simulation.py:997 |
| <a id="p13-d-02"></a>`D-02` | Generated modifier replaced the static one for all agents in a bracket. Superseded: static round-robin modifier always applies; generated text is layered on as a 'this cycle' focus line (config.py:1102-1109). | superseded | config.py:1090,1109; simulation.py:997 |
| <a id="p13-d-04"></a>`D-04` | Modifier prompt inputs: all extracted entities plus the raw rumor. | active | config.py:578,613,638 |
| <a id="p13-d-05"></a>`D-05` | Output is a flat JSON dict keyed by bracket value; exactly 10 keys for a full parse. | active | config.py:578,638; parsing.py:269 |
| <a id="p13-d-06"></a>`D-06` | Modifier generation runs in the same orchestrator session as seed parsing (no reload). | active | config.py:578,638; seed.py:58,97; simulation.py:986 |
| <a id="p13-d-07"></a>`D-07` | Total parse failure falls back to static modifiers with a warning. | active | parsing.py:269,336 |
| <a id="p13-d-08"></a>`D-08` | Partial failure falls back per bracket. | active | parsing.py:269,278,295 |
| <a id="p13-d-09"></a>`D-09` | ParsedModifiersResult carries parse_tier for observability. | active | types.py:131 |
| <a id="p13-d-10"></a>`D-10` | Sanitise entity names at injection time; stored SeedEntity names stay untouched. | active | config.py:617 |
| <a id="p13-d-11"></a>`D-11` | Sanitisation: truncate to 100 chars, strip control/format characters, keep normal punctuation. | active | config.py:490,495 |
| <a id="p13-d-12"></a>`D-12` | sanitize_entity_name() helper; raw rumor goes in a clearly labelled block. | active | config.py:490,495,617 |

### Phase 14: Agent interviews

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p14-d-04"></a>`D-04` | Interview system prompt = persona + decision narrative + per-round decisions (hybrid context). | active | graph.py:1160 |
| <a id="p14-d-05"></a>`D-05` | Strip JSON output instructions from the persona for conversational answers. | active | interview.py:59 |
| <a id="p14-d-06"></a>`D-06` | Context reconstructed from Neo4j at session start (read_agent_interview_context); persona from memory. | active | graph.py:1160,1186 |
| <a id="p14-d-08"></a>`D-08` | 10-turn sliding window. | active | interview.py:72 |
| <a id="p14-d-09"></a>`D-09` | Dropped turns summarised into a prepended system message. | active | interview.py:73 |
| <a id="p14-d-10"></a>`D-10` | Summary produced by the same worker model. | active | interview.py:74 |
| <a id="p14-d-13"></a>`D-13` | Interviews bypass the governor. Originally OllamaClient.chat directly; now the worker InferenceProvider. | partial | interview.py:75 |

### Phase 15: Post-simulation report (ReAct)

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p15-d-01"></a>`D-01` | ReAct uses literal ACTION:/INPUT: lines parsed by regex, not native tool calling (Ollama tool calling was unreliable for Qwen). | active | report.py:56,83,163 |
| <a id="p15-d-02"></a>`D-02` | FINAL_ANSWER is a reserved tool that ends the loop. | active | report.py:116,169 |
| <a id="p15-d-03"></a>`D-03` | Hard iteration cap plus duplicate (tool, input) detection. | active | report.py:117,118,174 |
| <a id="p15-d-04"></a>`D-04` | CLI `report` subcommand. The web route and auto-chain after advisory were added later. | partial | cli.py:662 |
| <a id="p15-d-05"></a>`D-05` | Sentinel file .alphaswarm/last_report.json for TUI polling. Still written, but no reader since the TUI was retired. | superseded | cli.py:794; report.py:352 |
| <a id="p15-d-07"></a>`D-07` | Fixed report section order. | active | report.py:244 |
| <a id="p15-d-10"></a>`D-10` | Reports written to ./reports/{cycle_id}_report.md. | active | cli.py:662,794; report.py:335 |
| <a id="p15-d-11"></a>`D-11` | Async file write via aiofiles. | active | report.py:333 |
| <a id="p15-d-12"></a>`D-12` | Report engine does not manage model lifecycle; the caller does. | active | cli.py:662,700,752; report.py:120 |

### Phase 26: Shock injection core

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p26-d-12"></a>`D-12` | Shock stored as (Cycle)-[:HAS_SHOCK]->(ShockEvent). The web path, the only shock source, enforces the length cap: ShockText (web/params.py) takes 10-1000 characters after stripping. Revised 2026-10: replaces the never-enforced SHOCK_TEXT_MAX_LEN=4096 from STATE.md ([hist-shock-max-len](#hist-shock-max-len)). | revised | graph.py (`write_shock_event`); web/params.py; web/routes/simulation.py |

### Phase 28: Simulation replay (data layer)

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p28-d-07"></a>`D-07` | Per-round replay data (brackets, rationales) loaded on demand. | active | graph.py:2102,2155 |
| <a id="p28-d-08"></a>`D-08` | read_full_cycle_signals() loads all rounds' signals in one query up front. | active | graph.py:1988 |

### Phase 29: FastAPI skeleton and event-loop foundation

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p29-d-04"></a>`D-04` | Uvicorn owns the event loop; all stateful objects are built inside the FastAPI lifespan, never at import. | active | cli.py:819 |
| <a id="p29-d-13"></a>`D-13` | CLI `web` calls uvicorn.run() directly (no asyncio.run wrapper). | active | cli.py:817 |

### Phase 30: WebSocket state stream

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p30-d-04"></a>`D-04` | Broadcaster includes rationale entries in each frame (now the persistent sliding window, not a drain), each stamped with `seq` and `ts`. | partial | web/wire.py (`build_frame`); state.py (`push_rationale`) |
| <a id="p30-d-05"></a>`D-05` | Wire format was json.dumps(dataclasses.asdict(snapshot)) with no separate pydantic wire model. Superseded by the versioned `StateFrame` built by `web/wire.py:build_frame` ([adr-ws-broadcaster](#adr-ws-broadcaster)). | superseded | web/wire.py; web/broadcaster.py |
| <a id="p30-d-06"></a>`D-06` | snapshot_to_json() helper encapsulates the frame pipeline (snapshot → `build_frame` → JSON). | active | web/broadcaster.py (`snapshot_to_json`) |
| <a id="p30-d-07"></a>`D-07` | Broadcaster is an always-on lifespan task ticking at 200 ms (5 Hz). | active | web/broadcaster.py:66,96 |
| <a id="p30-d-08"></a>`D-08` | /ws/state registered without a prefix. | active | web/app.py:217 |
| <a id="p30-d-10"></a>`D-10` | WebSocket is unauthenticated (local only). Since Aug 2026 the handshake Origin is validated against an allow-list. | partial | web/routes/websocket.py:7 |

### Phase 31: SPA + agent graph + edges endpoint

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p31-d-02"></a>`D-02` | FastAPI serves frontend/dist at / when it exists (single server in production). dist/ is gitignored, so it must be built locally. | active | web/app.py:219 |
| <a id="p31-d-11"></a>`D-11` | GET /api/edges/{cycle_id}?round=N returns INFLUENCED_BY edges for that round. | active | web/routes/edges.py:1 |
| <a id="p31-d-13"></a>`D-13` | Edges response: {edges: [{source_id, target_id, weight}]}. | active | web/routes/edges.py:26 |

### Phase 32: REST controls and control bar

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p32-d-12"></a>`D-12` | GET /api/replay/cycles is a real Neo4j query (completion now keyed on Cycle.metrics_recorded_at). | active | web/routes/replay.py:63 |

### Phase 34: Replay mode (web)

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p34-d-07"></a>`D-07` | ReplayManager holds the ReplayStore, cycle_id and round; created in the lifespan. | active | web/replay_manager.py:1; tests/test_web.py:1265 |
| <a id="p34-d-08"></a>`D-08` | replay_start loads all signals, builds ReplayStore, sets round 1, broadcasts. | active | web/replay_manager.py:115; web/routes/replay.py:38,103 |
| <a id="p34-d-09"></a>`D-09` | replay_advance increments the round (capped at the cycle's real depth since F-12) and broadcasts. | active | web/replay_manager.py:185; web/routes/replay.py:46,175 |
| <a id="p34-d-10"></a>`D-10` | POST /api/replay/stop ends the replay (ReplayManager inactive again) and never writes the live StateStore phase, which stays IDLE or COMPLETE. Revised 2026-10 (start set the live phase to REPLAY and stop set it to IDLE). | revised | web/replay_manager.py:249; web/routes/replay.py:54,130 |
| <a id="p34-d-11"></a>`D-11` | Broadcaster reads the replay snapshot instead of live state while replay is active. | active | web/broadcaster.py (`snapshot_to_json`); tests/test_broadcaster_frames.py |

### Phase 35: Agent interviews (web)

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p35-d-06"></a>`D-06` | One InterviewEngine per (cycle_id, agent_id) in app.state.interview_sessions; cleared on sim start (no TTL). Revised 2026-10 (was per agent_id). | revised | web/app.py:178; web/routes/interview.py:5 |
| <a id="p35-d-08"></a>`D-08` | Single POST /api/interview/{agent_id} endpoint; engine created lazily on first call. | active | web/routes/interview.py:39 |

### Phase 36: Report viewer (web)

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p36-d-01"></a>`D-01` | POST /api/report/{cycle_id}/generate returns 202 and runs a background task for any complete cycle while no simulation runs. Revised 2026-10: the phase == COMPLETE gate is gone. | revised | web/routes/report.py:58,110; tests/test_report_routes.py |
| <a id="p36-d-02"></a>`D-02` | 409 if a report task is already running (single orchestrator user). | active | web/app.py:180; web/guards.py:require_orchestrator_free; tests/test_report_routes.py |
| <a id="p36-d-03"></a>`D-03` | Web report path mirrors the CLI sequence and file locations. | active | web/routes/report.py:187,227; tests/test_web_report.py:40 |
| <a id="p36-d-05"></a>`D-05` | GET /api/report/{cycle_id} reads the markdown file; the filesystem is the source of truth: 404 = no report, 409 report_generation_in_progress while that cycle's job runs, 500 after a recorded failure. Revised 2026-10 (404 also meant "still generating"). | revised | web/routes/report.py:50,70 |

### Phase 37: Isolation foundation + provider scaffolding

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p37-d-02"></a>`D-02` | Holdings-isolation import contract enforced by a pre-commit hook and (via the pytest invariant test) CI. | active | .pre-commit-config.yaml:5 |
| <a id="p37-d-03"></a>`D-03` | Permanent test runs lint-imports against a synthetic violation to prove the contract bites. | active | tests/invariants/test_importlinter_contract.py:1 |
| <a id="p37-d-04"></a>`D-04` | Whitelist-only: only alphaswarm.advisory and alphaswarm.web.routes.holdings may import alphaswarm.holdings. | active | pyproject.toml:130,141; web/routes/holdings.py:13,120; tests/integration/test_holdings_route.py:322,334; tests/invariants/test_importlinter_contract.py:109,112; tests/invariants/test_importlinter_coverage.py:10,11,27,107,110,117,121 |
| <a id="p37-d-05"></a>`D-05` | PII redaction: key-first detection plus value-pattern backstop. | active | logging.py:48,206,208; tests/test_pii_redaction.py:3,31 |
| <a id="p37-d-06"></a>`D-06` | account_* values become sha256 first-8 hashes; other sensitive values become [REDACTED]. | active | logging.py:48,206,210; security/hashing.py:4; tests/test_pii_redaction.py:3,31 |
| <a id="p37-d-07"></a>`D-07` | Redaction fails closed: on processor error, drop the event and emit a marker with no user data. | active | logging.py:5,191,206,212; tests/test_pii_redaction.py:3,206 |
| <a id="p37-d-08"></a>`D-08` | Redaction verified by Hypothesis property tests plus tabular cases. | active | tests/test_pii_redaction.py:3,294,373 |
| <a id="p37-d-09"></a>`D-09` | pytest-socket --disable-socket globally. | active | tests/test_network_gate.py:21 |
| <a id="p37-d-10"></a>`D-10` | No loopback exemption; integration tests opt in explicitly. | active | tests/test_network_gate.py:28 |
| <a id="p37-d-12"></a>`D-12` | tests/integration/ auto-applies enable_socket; one-off opt-in via marker. | active | pyproject.toml:56; tests/integration/__init__.py:4; tests/integration/conftest.py:1; tests/test_network_gate.py:43 |
| <a id="p37-d-13"></a>`D-13` | ASCII sentinel holdings (SNTL_CANARY_*) make leaks greppable. | active | tests/invariants/conftest.py:3,29,60 |
| <a id="p37-d-14"></a>`D-14` | Canary runs a pipeline with a sentinel portfolio and asserts no sentinel appears anywhere. | active | tests/invariants/conftest.py:60; tests/invariants/test_holdings_isolation.py:1 |
| <a id="p37-d-15"></a>`D-15` | Leak detection across four surfaces: logs, Neo4j, WebSocket frames, worker prompts. | active | tests/invariants/conftest.py:4; tests/invariants/test_holdings_isolation.py:1,101 |
| <a id="p37-d-16"></a>`D-16` | tests/invariants/ holds architectural invariant tests. | active | tests/invariants/__init__.py:3; tests/invariants/test_holdings_isolation.py:1,65 |
| <a id="p37-d-17"></a>`D-17` | Exactly two provider protocols: MarketDataProvider and NewsProvider. | active | ingestion/providers.py:3 |
| <a id="p37-d-18"></a>`D-18` | Batch-first async signatures (list[str] -> dict[str, Slice]). | active | ingestion/providers.py:4 |
| <a id="p37-d-19"></a>`D-19` | Providers never raise for fetch failures; they return slices with staleness='fetch_failed'. | active | ingestion/providers.py:5,15,39,91,95,116; ingestion/rss_provider.py:9,30,129,165,178; ingestion/yfinance_provider.py:8,122; tests/integration/test_yfinance_provider_live.py:56,63,69,74; tests/test_providers.py:118,126,145; tests/test_rss_provider.py:234,403,442,607,624; tests/test_yfinance_provider.py:273,295 |
| <a id="p37-d-20"></a>`D-20` | Fake providers ship next to the protocols so consumers are test-first. | active | ingestion/providers.py:6 |

### Phase 38: Market data + news providers

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p38-d-01"></a>`D-01` | News via RSS only (no API key, no rate limits). | active | ingestion/rss_provider.py:3,56 |
| <a id="p38-d-02"></a>`D-02` | Ticker-shaped entities -> Yahoo Finance RSS; everything else -> Google News RSS (quoted). | active | ingestion/rss_provider.py:4,56; tests/test_rss_provider.py:142 |
| <a id="p38-d-03"></a>`D-03` | Headline filter: case-insensitive substring match on the entity. | active | ingestion/rss_provider.py:5; tests/test_rss_provider.py:256,315 |
| <a id="p38-d-04"></a>`D-04` | feedparser + httpx. | active | ingestion/rss_provider.py:6 |
| <a id="p38-d-05"></a>`D-05` | yfinance per ticker via asyncio.to_thread + gather for error isolation. | active | ingestion/yfinance_provider.py:3; tests/integration/test_yfinance_provider_live.py:95 |
| <a id="p38-d-06"></a>`D-06` | fast_info for price/volume; info for fundamentals. | active | ingestion/yfinance_provider.py:4; tests/integration/test_yfinance_provider_live.py:111 |
| <a id="p38-d-07"></a>`D-07` | No semaphore: providers run once per simulation, not per agent. | active | ingestion/yfinance_provider.py:5 |
| <a id="p38-d-09"></a>`D-09` | staleness='fresh' on success, 'fetch_failed' on any exception; no time-window logic. | active | ingestion/rss_provider.py:7; ingestion/yfinance_provider.py:6 |
| <a id="p38-d-10"></a>`D-10` | No caching; every call fetches fresh. | active | ingestion/rss_provider.py:8,174; ingestion/yfinance_provider.py:7 |

### Phase 39: Holdings loader

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p39-d-01"></a>`D-01` | Holdings source is a 4-column CSV (account, symbol, shares, cost_basis_per_share). | active | holdings/loader.py:9 |
| <a id="p39-d-02"></a>`D-02` | Holding.cost_basis is total position cost (shares x per-share basis). | active | holdings/loader.py:10,141; tests/test_holdings_loader.py:72 |
| <a id="p39-d-03"></a>`D-03` | Multiple accounts merge into one PortfolioSnapshot. | active | holdings/loader.py:11; tests/test_holdings_loader.py:125,145,164 |
| <a id="p39-d-04"></a>`D-04` | All positions included (no money-market filtering). | active | holdings/loader.py:12; tests/test_holdings_loader.py:125,129,134 |
| <a id="p39-d-05"></a>`D-05` | Path from ALPHASWARM_HOLDINGS_CSV_PATH, default Schwab/holdings.csv, resolved against the repo root. | active | config.py:478; web/app.py:220 |
| <a id="p39-d-06"></a>`D-06` | GET /api/holdings returns account hash, as_of, holdings with Decimals as strings. | active | web/routes/holdings.py:17,54,67; tests/integration/test_holdings_route.py:13,85,90,137 |
| <a id="p39-d-07"></a>`D-07` | Holdings load at lifespan startup into PortfolioCache on app.state and reload when the CSV's mtime changes; never assigned onto AppState. Revised 2026-10 (was loaded once, with a lazy reload in the advisory route). | revised | web/app.py:218; web/routes/holdings.py:18,120 |
| <a id="p39-d-08"></a>`D-08` | Missing/malformed CSV -> snapshot None -> structured 503; never crashes the WS loop. | active | holdings/loader.py:52; web/app.py:131,138; web/routes/holdings.py:21,82,136,146; tests/integration/test_holdings_route.py:14,215,220; tests/test_holdings_loader.py:261 |

### Phase 40: Simulation context wiring

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p40-d-01"></a>`D-01` | ContextPacket assembled inside run_simulation after seed extraction when both providers are present. | active | simulation.py:941,953,1002 |
| <a id="p40-d-02"></a>`D-02` | No providers -> log context_assembly_skipped and continue rumor-only. | active | simulation.py:941,1002 |
| <a id="p40-d-03"></a>`D-03` | Partial fetch failures kept in the packet; formatter silently skips fetch_failed slices. | active | context_formatter.py:6; simulation.py:941,1002; tests/test_context_formatter.py:6 |
| <a id="p40-d-04"></a>`D-04` | Market context is its own system message after the persona and before peer context/user message. | active | simulation.py:603; worker.py:153; tests/test_worker.py:223,252 |
| <a id="p40-d-06"></a>`D-06` | Market context goes to Round 1 only. | active | simulation.py:603,941,948,1004; tests/test_simulation.py:2966,2981 |
| <a id="p40-d-07"></a>`D-07` | One formatted block shared by all 100 agents (no per-bracket filtering). | active | batch_dispatcher.py:174; tests/test_batch_dispatcher.py:673,681,715 |
| <a id="p40-d-08"></a>`D-08` | Per entity: price, fundamentals, top headlines; fetch_failed entities omitted. | active | context_formatter.py:6,106; tests/test_context_formatter.py:4,75,103 |
| <a id="p40-d-09"></a>`D-09` | Cap headlines at 5 per entity (`HEADLINES_PER_ENTITY`, which also caps point-in-time fixtures). | active | context_formatter.py:6,41; eval/build_fixtures.py:44; tests/test_context_formatter.py:5,112 |
| <a id="p40-d-10"></a>`D-10` | yfinance + RSS providers built once in the FastAPI lifespan and stored on app/AppState. | active | app.py:43,44,127,128; web/app.py:141; tests/test_web.py:72,238 |
| <a id="p40-d-11"></a>`D-11` | CLI `run` builds the same providers inline so CLI and web runs get identical context. | active | cli.py:519; tests/test_cli.py:1015,1021 |

### Phase 41: Advisory pipeline

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p41-d-03"></a>`D-03` | Original: the orchestrator decides which holdings are affected and omits the rest. Superseded by one item per holding with server-side HOLD padding (260512-jqn ITEM 6, SWEEP B-7). | superseded | tests/unit/test_advisory.py:227 |
| <a id="p41-d-04"></a>`D-04` | Prefetch all swarm data from Neo4j in parallel (asyncio.gather) before the single LLM call. | active | advisory/engine.py:111 |
| <a id="p41-d-05"></a>`D-05` | One orchestrator call with swarm data plus holdings (ticker, qty, cost basis); this is the sanctioned place holdings enter a prompt. | active | tests/invariants/test_holdings_isolation.py:21,163,172,193,200 |
| <a id="p41-d-06"></a>`D-06` | AdvisoryItem schema (ticker, consensus_signal, confidence, rationale_summary, position_exposure). | active | advisory/prompt.py:84; advisory/types.py:17 |
| <a id="p41-d-07"></a>`D-07` | Rank by confidence x (exposure / total cost basis); denominator must be positive (F-29). | active | advisory/engine.py:142,262 |
| <a id="p41-d-08"></a>`D-08` | Route owns orchestrator load/unload in try/finally; advisory never runs concurrently with report generation (bidirectional 409). | active | advisory/engine.py:6; web/app.py:105; web/routes/advisory.py:106,323 |
| <a id="p41-d-09"></a>`D-09` | POST /api/advisory/{cycle_id} returns 202 and spawns a background task. | active | web/routes/advisory.py:87,99 |
| <a id="p41-d-10"></a>`D-10` | GET reads advisory/{cycle_id}_advisory.json: 200 ready, 409 advisory_generation_in_progress while generating, 500 recorded failure or refusal, 404 absent. Revised 2026-10 (404 meant "still generating"). | revised | web/routes/advisory.py:193 |
| <a id="p41-d-12"></a>`D-12` | Cycle ids use the shared CycleId uuid4 type (web/params.py); malformed ids return 422 validation_error. Revised 2026-10 (was a regex guard shared with the report route, 400 invalid_cycle_id). | revised | web/params.py; web/routes/advisory.py:162,193 |
| <a id="p41-d-13"></a>`D-13` | Done-callback records failures in app.state.advisory_generation_error so polling can stop. | active | web/app.py:105; web/routes/advisory.py:191,260 |
| <a id="p41-d-20"></a>`D-20` | The isolation canary calls the real synthesize() (load-bearing since Phase 41). | active | pyproject.toml:137; tests/invariants/conftest.py:162; tests/invariants/test_holdings_isolation.py:7,74 |

### Phase 41.2: Audit fix: report/advisory data plane and UI contracts

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p41-2-d-03"></a>`D-03` | OllamaClient.generate() accepts system= so narrative generation stops failing silently. Narratives have since moved to `provider.chat` with a system message (simulation.py:1613-1626), so `generate()` now has no production caller. | partial | ollama_client.py:149; tests/test_ollama_client.py:139,148; tests/test_simulation.py:3698,3706,3777 |
| <a id="p41-2-d-04"></a>`D-04` | Replace the mock ReportModalV2 with the real backend-wired ReportModal. | active | fe/components/ReportModal.tsx:2; fe/components/modals.jsx:8 |
| <a id="p41-2-d-05"></a>`D-05` | Render portfolio_outlook + items[] in the advisory surface (now AdvisoryV2). | active | fe/lib/markdown.ts:2 |

### Phase 41.6: UI revamp: AlphaSwarm-2 Quant Terminal port

| ID | Decision and rationale | Status | Referenced from |
|---|---|---|---|
| <a id="p41-6-d-03"></a>`D-03` | Convert the CDN-globals JSX design export to native ES modules. | active | fe/components/app_v2.tsx:4; fe/components/history.tsx:4; fe/components/icons.jsx:3; fe/components/panels.jsx:3; fe/components/settings.tsx:3; fe/components/states.jsx:8; fe/components/tweaks.jsx:3; fe/components/v2.tsx:5; fe/components/viz.jsx:3 |
| <a id="p41-6-d-07"></a>`D-07` | App shell = split context providers (Connection, Telemetry, Agents, Rationales, Edges, FrameMeta); bracket bars derive from agents, BracketContext removed (Oct 2026). | revised | fe/App.tsx:1; fe/components/app_v2.tsx:4 |
| <a id="p41-6-d-08"></a>`D-08` | AdvisoryV2: derive what the backend supports, stub the rest (stubs tracked as KRs). | active | fe/components/modals.jsx:9; fe/components/v2.tsx:17,745,816,844,1055; fe/lib/advisoryParse.ts:2,24,51 |
| <a id="p41-6-d-09"></a>`D-09` | Render portfolio_outlook markdown via renderMarkdown(). | active | fe/components/v2.tsx:18,745,985; fe/lib/advisoryParse.ts:2,11; fe/lib/markdown.ts:3 |
| <a id="p41-6-d-10"></a>`D-10` | AdvisoryV2 keeps four tabs; Holdings and Overview share items[]. | active | fe/components/v2.tsx:18,745,1023 |
| <a id="p41-6-d-11"></a>`D-11` | interview_v2 is the canonical interview surface (real /api/interview). | active | fe/components/interview_v2.tsx:2; fe/components/modals.jsx:7 |
| <a id="p41-6-d-12"></a>`D-12` | Onboarding first-run flow gated by a localStorage flag and /api/health components (lists what is down with its fix; Re-check; Skip to dashboard). | active | fe/App.tsx:2,22; fe/components/onboarding.tsx:1,137 |
| <a id="p41-6-d-13"></a>`D-13` | bracket_deep full-screen view filtered from AgentsContext. | active | fe/components/bracket_deep.tsx:2,10,60 |
| <a id="p41-6-d-14"></a>`D-14` | Design data file is reference only; keep just the BRACKETS constant. | active | fe/components/app_v2.tsx:4; fe/components/states.jsx:9; fe/data.ts:1 |
| <a id="p41-6-d-19"></a>`D-19` | usePolling surfaces timeout as an Error so modals can show it. | active | fe/components/v2.tsx:798; fe/hooks/usePolling.ts:92 |
| <a id="p41-6-d-20"></a>`D-20` | ReportModal: canonical markdown first; rich subsections only when a matching H2 heading parses. | active | fe/components/ReportModal.tsx:3,266; fe/components/modals.jsx:8; fe/components/v2.tsx:24,1240; fe/lib/advisoryParse.ts:3; fe/lib/markdown.ts:3 |
| <a id="p41-6-d-21"></a>`D-21` | CycleHistory Compare button renders only when comparison data exists (currently never). | active | fe/components/history.tsx:1,12,103,168,177,290,318 |
| <a id="p41-6-d-22"></a>`D-22` | Advisory stat relabelled HOLDINGS AFFECTED, read from affected/total counts. | active | fe/components/modals.jsx:9; fe/components/v2.tsx:18,746,870,997 |
| <a id="p41-6-d-23"></a>`D-23` | UI tweaks persist to localStorage; backend-owned settings (model, provider, keys) live on the backend only. | active | fe/api/settings.ts:4; fe/components/settings.tsx:6; fe/components/settings_inference.tsx:3; fe/lib/settingsState.ts:5 |

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
| <a id="kr-41-1-01"></a>KR-41.1-01 | Agent graph uses the design's deterministic SVG layout, with no d3-force physics | active (deliberate design) | CLAUDE.md:20; fe/components/viz.jsx:4 |
| <a id="kr-41-1-02"></a>KR-41.1-02 | Signal Wire and Data Sources render static mocks (no backend) | partial: Signal Wire is live via `data_source_audit` (260512-jqn ITEM 5) with a DEV-only mock fallback; Data Sources is still mock in DEV and a placeholder in prod | fe/components/states.jsx:19; fe/mocks/index.ts:5; fe/mocks/sources.ts:1; fe/mocks/wire.ts:1 |
| <a id="kr-41-1-03"></a>KR-41.1-03 | Per-agent `flipped`, `roundLastSpoke`, `thinking` stubbed | partial: `thinking` is derived from `signal===null`; `flipped` and `roundLastSpoke` are still 0/null (frame.ts:180-181) | fe/adapter/frame.ts:180,181; fe/types.ts:25,26 |
| <a id="kr-41-1-04"></a>KR-41.1-04 | Memory shown as percent, not MB; GB literals in MemoryPaused are design copy | active | fe/adapter/frame.ts:154; fe/components/states.jsx:114,140; fe/types.ts:44 |
| <a id="kr-41-1-05"></a>KR-41.1-05 | Slot counts stubbed | **closed** (260512-jqn ITEM 3: `active_count`/`current_slots` on the wire) | fe/adapter/frame.ts:140; fe/types.ts:45,46; tests/test_state.py:126 |
| <a id="kr-41-1-06"></a>KR-41.1-06 | Replay Rewind disabled (no endpoint) | open | fe/components/modals.jsx:122,148 |
| <a id="kr-41-1-07"></a>KR-41.1-07 | CycleHistory consensus/flips/duration/shocks show "—" (`/api/replay/cycles` is minimal) | open; now cheap, because the Cycle node carries these metrics ([adr-cycle-metrics](#adr-cycle-metrics)) but `CycleItem` (`web/routes/replay.py:22-28`) does not expose them | fe/api/replay.ts:3; fe/components/history.tsx:9,158,269 |
| <a id="kr-41-1-08"></a>KR-41.1-08 | Error log lines are design copy (no structured error stream) | open | fe/components/history.tsx:56; fe/components/modals.jsx:192,267; fe/components/states.jsx:156,178 |
| <a id="kr-41-1-09"></a>KR-41.1-09 | Top Influencers ranked by confidence during live view | **closed** (2026-10): ranked by citations received (CITED BY, `rankInfluencers`) for the round on screen from round 2's edges on; an empty-state line before that, no confidence fallback | fe/lib/influence.ts; fe/components/app_v2.tsx |
| <a id="kr-41-1-10"></a>KR-41.1-10 | Rationale `citations`/`sources` stubbed `[]` (RationaleEntry has no `cited_agents`) | open | fe/adapter/frame.ts:234,235; fe/components/app_v2.tsx:314; fe/types.ts:59,60 |
| <a id="kr-41-1-11"></a>KR-41.1-11 | Interview is non-streaming (single POST) | open | fe/api/interview.ts:2; fe/components/interview_v2.tsx:2,9 |
| <a id="kr-41-6-01"></a>KR-41.6-01 | AdvisoryV2 shares/basis/last/sentiment shown as "—" (not on AdvisoryItem) | open (holdings API has qty/cost_basis, so a client-side join could fill two of them) | fe/components/v2.tsx:844,1055,1065,1217; fe/lib/advisoryParse.ts:9 |
| <a id="kr-41-6-02"></a>KR-41.6-02 | `new_features.jsx` (What-If Compare, Watch Mode, Multi-seed, Seed Suggestions) deferred; overflow items say "Coming in v6.x" | open (no code reference) | — |
| <a id="kr-41-6-03"></a>KR-41.6-03 | InterviewV2 PERSONA filler removed; live response is canonical | closed (by design) | fe/components/interview_v2.tsx:2,6,173,230,333 |
| <a id="kr-41-6-04"></a>KR-41.6-04 | Onboarding Ollama check is coarse (`/api/health` aggregate) | closed (Oct 2026: onboarding lists each /api/health component that is down with its fix) | fe/components/onboarding.tsx:1; fe/lib/health.ts |
| <a id="kr-41-6-05"></a>KR-41.6-05 | AdvisoryV2 Risk tab is placeholder copy | open | fe/components/v2.tsx:1118 |
| <a id="kr-41-6-06"></a>KR-41.6-06 | Backend-touching settings read-only ("Coming in v6.x") | partial: inference provider/model/key/limits are now editable (`settings_inference.tsx` → `/api/settings`); memory threshold, slots, and agent count are still read-only | fe/components/settings.tsx:12,177,183,189,301 |
| <a id="kr-41-6-07"></a>KR-41.6-07 | CycleHistory Compare hidden (no comparison endpoint) | open | fe/components/history.tsx:14,104,168 |
| <a id="kr-41-6-08"></a>KR-41.6-08 | ModelStatus chip hardcoded `qwen3:8b` | **closed**: the chip shows live inference mode and spend from `/api/health` (v2.tsx:347-387). The comments at v2.tsx:14-16 and app_v2.tsx:4 are stale | fe/components/app_v2.tsx:4; fe/components/v2.tsx:15 |
| <a id="kr-41-6-09"></a>KR-41.6-09 | InterviewV2 stats panel partial (peer reads, shock impact, data sources have no source) | open | fe/components/interview_v2.tsx:2,16,280 |
| <a id="kr-41-6-10"></a>KR-41.6-10 | AdvisoryV2 "agents" count is a regex heuristic over rationale text, strictly intersected with live IDs | active (heuristic) | fe/components/v2.tsx:19,842; fe/lib/advisoryParse.ts:51,66 |
| <a id="kr-41-6-11"></a>KR-41.6-11 | IdleState SystemCheck rows are static copy | open | fe/components/states.jsx:18 |
| <a id="kr-41-6-12"></a>KR-41.6-12 | ReportModal rich sections render only when an explicit `## Section` heading parses; otherwise omitted | active (policy) | fe/components/ReportModal.tsx:6,275; fe/components/v2.tsx:849; fe/lib/advisoryParse.ts:9 |
| <a id="kr-41-6-13"></a>KR-41.6-13 | BracketDeepDive influence counts only after the cycle ("—" live) | **closed** (2026-10): counts come from the shared EdgesContext for the round on screen, live from round 2's edges on; "—" only before they exist | fe/hooks/useCycleEdges.ts; fe/components/bracket_deep.tsx |
| <a id="kr-41-6-14"></a>KR-41.6-14 | Mocks loaded only through DEV-only dynamic import; production grep gate keeps them out of `dist` | active (policy) | fe/components/app_v2.tsx:504; fe/components/v2.tsx:11,44,84,114,185,402,411,454; fe/hooks/useDataSourceAudit.ts:8 |

---

## 5. June 2026 deep-audit findings

From audit branch `fix/deep-audit-260621` (PR #2, merged 2026-06-26). All are
fixed; the code comments explain the guard. Fix commits are listed for `git show`.

| ID | Finding (fixed) | Fix commit | Referenced from |
|---|---|---|---|
| <a id="f-01"></a>F-01 | `read_key_dissenters` compared lowercase signals to uppercase majority, so every agent was flagged a dissenter | 6ced8a8 | (Cypher fix, no comment) |
| <a id="f-02"></a>F-02 | `read_signal_flips` filtered `'NONE'` instead of `'none'` and read a non-existent `round_num` | 6ced8a8 | — |
| <a id="f-03"></a>F-03 | Shock-impact aggregation used uppercase keys, so every value was zero and HOLD | 6ced8a8 | — |
| <a id="f-04"></a>F-04 | `TokenPool.grow()` ignored crisis debt, so concurrency exceeded the limit right after recovery | 78744f6 | governor.py:90; tests/test_governor.py:74 |
| <a id="f-05"></a>F-05 | Anthropic provider defaulted to max_tokens=1024, truncating orchestrator output (now 8192 orchestrator / 2048 worker) | c99d00b | inference/factory.py:130 |
| <a id="f-06"></a>F-06 | ReAct prompt tool names did not match the registry, so the consensus and flip sections were always missing | 90dd0f9 | tests/test_report.py:28 |
| <a id="f-07"></a>F-07 | Advisory read the wrong entity-impact keys, so relevance ranking was dead; added `resolve_ticker` | 3d65f99 | advisory/engine.py:151; advisory/sector_map.py:86; tests/unit/test_advisory.py:615,619,632 |
| <a id="f-08"></a>F-08 | Round 2 equal weights meant every reader got the same peers; fixed with a stable per-reader jitter. The jitter is gone: seeded per-reader sampling ([adr-diverse-peer-context](#adr-diverse-peer-context)) disperses readers by construction | 7ae6a69 | simulation.py (peer_rng); tests/test_peer_selection.py (test_equal_weights_disperse_across_readers) |
| <a id="f-09"></a>F-09 | JSON brace scanner ignored strings, so `}` in a rationale dropped the vote | 9748dd5 | parsing.py:49; tests/test_parsing.py:96 |
| <a id="f-10"></a>F-10 | OpenAI strict schema kept min/max, got a 400, and silently fell back to json_object | c99d00b | inference/schema.py:25; tests/inference/test_schema.py:150 |
| <a id="f-11"></a>F-11 | Failed cloud calls leaked TPM reservation (follow-up in 9312419: refund only on failure) | c99d00b, 9312419 | inference/rate_limit.py:299; tests/inference/test_rate_limit.py:276 |
| <a id="f-12"></a>F-12 | Replay advanced 2-round cycles to an empty round 3 | 66d680f | web/replay_manager.py:167 |
| <a id="f-13"></a>F-13 | Settings PUT carried the old vendor's API key to a new provider | 66d680f, 9312419 | web/routes/settings.py:250; tests/test_web_settings.py:103 |
| <a id="f-14"></a>F-14 | Blank account cells crashed the holdings loader outside the 503 path | 902d7b5 | holdings/loader.py:150 |
| <a id="f-15"></a>F-15 | Interview window trim lost a turn when summarization failed | 902d7b5 | interview.py:157 |
| <a id="f-16"></a>F-16 | `usePolling` stacked overlapping requests | df2f26a | fe/hooks/usePolling.ts:58 |
| <a id="f-17"></a>F-17 | A sysctl read failure returned GREEN and cleared a crisis; now fail-stale with a timeout | c567a2f | memory_monitor.py:121; tests/test_memory_monitor.py:273,286 |
| <a id="f-18"></a>F-18 | An unpriced model cost $0 under a spend cap; now priced at a conservative ceiling | f11aeee, cd5d35d | inference/budget.py:96,153,177; tests/inference/test_budget.py:89,96 |
| <a id="f-19"></a>F-19 | Empty peer set still injected a "peers exist" block | 7ae6a69 | simulation.py:420; tests/test_simulation.py:155 |
| <a id="f-20"></a>F-20 | Influence weights normalized by a count that included PARSE_ERROR agents | 7ae6a69 | simulation.py:1245 |
| <a id="f-21"></a>F-21 | Any monitor-loop exception silently killed throttling | 78744f6 | governor.py:346,360 |
| <a id="f-22"></a>F-22 | Anthropic missing-tool ValueError escaped the provider error contract | c99d00b | inference/anthropic_provider.py:242 |
| <a id="f-23"></a>F-23 | Retry-After HTTP-date ignored; now a shared clamped parser | c99d00b, 9312419 | inference/anthropic_provider.py:273; inference/openai_provider.py:317 |
| <a id="f-24"></a>F-24 | Broadcaster crashed every tick during replay start-up (`has_store` gate) | 66d680f | web/broadcaster.py:44,46; web/replay_manager.py:134 |
| <a id="f-25"></a>F-25 | Inference config save was not atomic (now temp file + `os.replace`) | 902d7b5 | config.py:335 |
| <a id="f-26"></a>F-26 | `/replay/start` skipped the cycle_id guard | 66d680f | web/routes/replay.py:114 |
| <a id="f-27"></a>F-27 | A binary WS frame dropped the connection | 66d680f | web/routes/websocket.py:133 |
| <a id="f-28"></a>F-28 | Sector seed-match used bare substrings (false positives) | 35471d4 | advisory/engine.py:64 |
| <a id="f-29"></a>F-29 | A negative aggregate cost basis inverted the ranking | 35471d4 | advisory/engine.py:145 |
| <a id="f-30"></a>F-30 | Inconsistent ticker casing across items | 35471d4 | advisory/engine.py:225 |
| <a id="f-31"></a>F-31 | Inverted governor thresholds passed validation | 902d7b5 | config.py:105 |
| <a id="f-32"></a>F-32 | A failed unload aborted `ensure_clean_state`, risking the two-model invariant | 66d680f | ollama_models.py:118,171 |
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
| <a id="b1"></a>B1 | Shock injection was dead in the web UI: `consume_shock()` had no caller and there was no `write_shock_event`. Fixed in Phase 35.1: shock consumed before Rounds 2 and 3 and persisted as ShockEvent. Since 2026-10 shocks carry forward: every applied shock is appended to all later rounds' user message, oldest first (a Round 2 shock is still in Round 3), and recorded on the StateStore (`applied_shocks`). A shock posted once the last gated round has started gets 409 `shock_window_closed` instead of being accepted and never read | graph.py:2140; simulation.py:1411 (`run_simulation` shock gates); web/simulation_manager.py (`inject_shock`); tests/test_graph.py:1547; tests/test_simulation.py:129,2602,2666; tests/test_shock_window.py; tests/engine/test_scenarios.py:138 |
| <a id="b4"></a>B4 | Replay could run on top of a live sim. Fixed with mutual exclusion: route returns 409 and `SimulationManager.start` raises `ReplayActiveError` | web/app.py:111; web/routes/replay.py:109,124; web/simulation_manager.py:123,130; tests/test_web.py:57,1427,1433,1454 |
| <a id="b7"></a>B7 | ConnectionManager leaked dead clients. The writer `finally` now removes its own entries | web/connection_manager.py:54,73; tests/test_web.py:1427,1473 |
| <a id="b8"></a>B8 | `_on_task_done` race with `start()`. Phase reset now happens synchronously inside `_run` before the lock is released | web/simulation_manager.py:151,215,241; tests/test_web.py:1159,1427,1495,1560 |
| <a id="b9"></a>B9 | ReplayManager `advance`/`stop` mutated state without the lock. Both are now serialized | web/replay_manager.py:187,236; tests/test_web.py:1427,1567,1600,1603 |
| <a id="b10"></a>B10 | Duplicate `set_phase(COMPLETE)`. Only `simulation.py` sets it now. The comments cite `simulation.py:1109`; the real line is ~1507 | web/simulation_manager.py:157,212; tests/test_web.py:1427,1607,1649 |

The other BUGFIX-CONTEXT items (B2, B3, B5, B6, B11-B20) are not referenced in
code. Their status is in BACKLOG.md.

### SWEEP-260528 (2026-05-28 full sweep; "B-n" with a hyphen, plus §3.3)

| ID | Item and resolution | Referenced from |
|---|---|---|
| <a id="sweep-b-1"></a>SWEEP B-1 | 19 `test_report.py` failures against the removed `assemble_html()`. Tests rewritten against `ReportAssembler.assemble()` (markdown) | tests/test_report.py:385 |
| <a id="sweep-b-5"></a>SWEEP B-5 | Round 1 can never produce citations, so its influence-edge computation was dead work. Removed. The comment at simulation.py:1100-1103 still says Round 2 reads `read_ranked_posts`, which is stale | simulation.py:1103 |
| <a id="sweep-b-7"></a>SWEEP B-7 | Advisory prompt over-emitted boilerplate HOLD items. Non-top holdings are no longer sent to the LLM and are padded server-side as HOLD@0.30 | advisory/engine.py:174; advisory/prompt.py:90; tests/test_advisory_synthesize.py:145,163; tests/unit/test_advisory.py:260 |
| <a id="sweep-b-8"></a>SWEEP B-8 | Unknown tickers had `macro_beta=0`, so they could never rank. Default raised to 0.5 | advisory/sector_map.py:74; tests/test_advisory_synthesize.py:47,130 |
| <a id="sweep-3-3"></a>SWEEP §3.3 | Structural peer-context bias: every agent saw the same authority top-10. Fixed by [adr-diverse-peer-context](#adr-diverse-peer-context) | simulation.py:166,188,438,763,1162 |

---

## 7. Threat-model IDs

| ID | Threat and mitigation | Referenced from |
|---|---|---|
| <a id="t-35-1-01"></a>T-35.1-01 | Cypher injection through shock text. All user input goes through parameters, never f-strings | graph.py:1964 |
| <a id="t-36-01"></a>T-36-01 | Path traversal through cycle_id. Since 2026-10 the `CycleId` path type and `CYCLE_ID_PATTERN` (`web/params.py`) validate it for report, advisory, replay, edges and interview, and malformed ids get 422 `validation_error` (was the `_CYCLE_ID_RE` regex guard) | web/params.py; tests/test_web_params.py |
| <a id="t-36-14"></a>T-36-14 | Blocking `Path.exists/stat` on the event loop. Uses `aiofiles.os` | web/routes/advisory.py:4; web/routes/report.py:4,95,101,131; tests/test_web_report.py:11,175 |
| <a id="t-36-15"></a>T-36-15 | Background task errors lost, leaving the UI polling forever. A done-callback records per-cycle errors and GET returns 500 | web/app.py:101; web/routes/advisory.py:5,260; web/routes/report.py:7,90,106,159,161,220,233,247; tests/test_web.py:69; tests/test_web_report.py:5,43,64,157,438 |
| <a id="t-36-16"></a>T-36-16 | Non-atomic report/advisory file write, partial read possible. Fixed 2026-10: both writes go through `fsutil.atomic_write_text` (temp file, fsync, `os.replace`, owner-only) | fsutil.py; report.py:write_report; web/routes/advisory.py:8 |
| <a id="t-38-01"></a>T-38-01 | URL injection through entity strings into RSS URLs. Ticker whitelist `^[A-Z]{1,5}$`; Google News query percent-encoded | ingestion/rss_provider.py:43,89; simulation.py:56; tests/test_rss_provider.py:142,164,549 |
| <a id="t-39-06"></a>T-39-06 | Holdings 503 leaking filesystem path or exception text. Generic body only | web/routes/holdings.py:25,87,93,141; tests/integration/test_holdings_route.py:14,215,259 |
| <a id="t-41-6-13"></a>T-41.6-13 | XSS through interview responses. Rendered as plain text, not markdown | fe/components/interview_v2.tsx:20 |
| <a id="t-260512-jqn-03"></a>T-260512-jqn-03 | Data-source audit buffer leaking raw bodies or env vars. Only bounded summary fields are recorded | data_audit.py:14,83; tests/test_data_audit.py:68 |
| <a id="t-260512-jqn-09"></a>T-260512-jqn-09 | Audit buffer mistaken for a compliance trail. It is a bounded in-memory UX ring buffer only | data_audit.py:10 |

---

## 8. Requirement IDs

Requirement IDs come from the old REQUIREMENTS files. All referenced ones are
implemented. MEM-01 is also cited in the superpowers spec.

| ID | Requirement | Referenced from |
|---|---|---|
| <a id="req-infra-03"></a>INFRA-03 | Sequential model loading (orchestrator unloads before worker loads) | ollama_models.py:3; tests/test_models.py:1 |
| <a id="req-infra-04"></a>INFRA-04 | Async Ollama wrapper; `num_ctx` only in Modelfiles | tests/test_ollama_client.py:1 |
| <a id="req-infra-05"></a>INFRA-05 | Cycle-scoped indexes for fast peer reads | tests/neo4j/test_graph_integration.py (test_ensure_schema_idempotent) |
| <a id="req-infra-07"></a>INFRA-07 | TaskGroup for all batch processing; no bare create_task | batch_dispatcher.py:4,155 |
| <a id="req-infra-08"></a>INFRA-08 | Pydantic parsing with multi-tier fallback | parsing.py:3; tests/test_parsing.py:1 |
| <a id="req-tui-03"></a>TUI-03 / TUI-04 / TUI-05 | Rationale stream / telemetry (RAM, TPS, slots) / bracket panel. The contracts survive in StateStore after the TUI was removed | TUI-03: simulation.py:313,324; state.py:53,101. TUI-04: batch_dispatcher.py:176; simulation.py:313; state.py:101,127,216; worker.py:200,237. TUI-05: simulation.py:313,1110; state.py:101,130,229 |
| <a id="req-graph-03"></a>GRAPH-03 | Decision→Entity REFERENCES edges | tests/neo4j/test_graph_integration.py (test_complete_reasoning_arc) |
| <a id="req-int-01"></a>INT-01 | Interview context reconstructed from Neo4j | graph.py:1160 |
| <a id="req-report-02"></a>REPORT-02 | Cypher report tools (bracket, influence, entity, flips, posts) | graph.py:1260,1300,1339,1379,1434,1483,1529,1576 |
| <a id="req-social-01"></a>SOCIAL-01 / SOCIAL-02 | Rationale posts as Post nodes / top-K posts in peer context (SOCIAL-02 ranking superseded, see [§2](#hist-read-post)) | SOCIAL-01: graph.py:504. SOCIAL-02: graph.py:592,678 |
| <a id="req-replay-01"></a>REPLAY-01 | Replay from Neo4j without re-inference | graph.py:1988,2102,2155; tests/test_graph.py:1555,1580,1602,1625 |
| <a id="req-vis-03"></a>VIS-03 | Edges endpoint for the web graph (Phase 31 ID) | tests/test_web.py:841 |
| <a id="req-shock"></a>SHOCK-04 / SHOCK-05 | Phase 27-internal IDs (never added to REQUIREMENTS.md). SHOCK-04: `read_shock_event` / `read_shock_impact` (bracket deltas, pivot count, comparable agents) plus the old TUI bracket-panel delta mode. SHOCK-05: shock-impact report section (`11_shock_impact.j2`, `TOOL_TO_TEMPLATE['shock_impact']`, CLI pre-seeding of the `shock_impact` observation) | SHOCK-04: graph.py:1655; tests/test_graph.py:1438,1459,1473,1514. SHOCK-05: tests/test_cli.py:957,994; tests/test_report.py:498,505,514,542,586,600 |
| <a id="req-be"></a>BE-01 / 03 / 04 / 08 / 09 / 10 | v5.0 web-backend IDs (definitions recovered from `git show 343669f^:.planning/...`). BE-01: FastAPI app whose lifespan owns the event loop, plus `/api/health`. BE-03: per-client WebSocket queue with drop-oldest and writer-task cleanup (ConnectionManager). BE-04: `/ws/state` 5 Hz snapshot stream (Phase 30). BE-08: `GET /api/replay/cycles` (real Neo4j query). BE-09: `POST /api/replay/start/{cycle_id}`. BE-10: `POST /api/replay/advance` (BE-09/10 began as Phase 32 stubs and were filled in by Phase 34) | BE-01: tests/test_web.py:99,223. BE-03: tests/test_web.py:281,310,341. BE-04: tests/test_web.py:438,821. BE-08..10: tests/test_web.py:1207 |
| <a id="req-isol"></a>ISOL-01..07 | v6.0 isolation: stdlib holdings types (01), frozen ingestion models (02), import contract (03), PII redaction (04), provider protocols (05), socket gate (06), four-surface canary (07) | see the `ISOL-` lines in `holdings/`, `ingestion/`, `logging.py`, `tests/invariants/`, `tests/test_network_gate.py` |
| <a id="req-ingest"></a>INGEST-01 / 02 | yfinance provider / RSS provider | ingestion/__init__.py:9; ingestion/yfinance_provider.py:1; ingestion/rss_provider.py:1; tests/... |
| <a id="req-hold"></a>HOLD-01..04 | CSV loader (01), account number hashed with `sha256_first8` (02/04), `GET /api/holdings` (03) | config.py:452; holdings/loader.py:1,13,73,145; holdings/types.py:33; security/hashing.py:5; web/routes/holdings.py:1; tests/... |
| <a id="req-advis"></a>ADVIS-01 / 02 | `synthesize()` ranked items / `POST /api/advisory` with serialization | advisory/__init__.py:1; advisory/engine.py:1; advisory/types.py:1; web/routes/advisory.py:1,99; tests/unit/... |
| <a id="req-sim-04"></a>SIM-04 | `run_simulation` takes optional providers; backward compatible without them | tests/test_simulation.py:3269 |
| <a id="req-mem"></a>MEM-01..03 | Live RAM% on every WS frame, 5 Hz, governor fields preserved | web/broadcaster.py:27,53; web/wire.py:167; tests/test_web.py:464,471,496,527,556; docs/design/inference-providers.md:142 |
| <a id="req-auto"></a>AUTO-01..05 | Run the post-run jobs on completion (capture cycle_id, schedule from the done-callback). Revised 2026-10: PostRunPipeline calls the advisory and report jobs directly instead of an in-process POST, and the report runs in every case | tests/unit/test_simulation_manager_auto_advisory.py; tests/test_post_run_pipeline.py; tests/test_web_post_run_wiring.py |

---

## 9. Quick-task IDs

| ID | What it did | Referenced from |
|---|---|---|
| <a id="quick-260416-m8x"></a>260416-m8x | Tier-1 web fixes B4, B7, B8, B9, B10 | tests/test_web.py:1426 |
| <a id="quick-260507-19f"></a>260507-19f | Removed the UI POST trigger for advisory. Synthesis is auto-fired by the backend on completion; the frontend only polls GET | fe/api/advisory.ts:2; fe/components/v2.tsx:22,797 |
| <a id="quick-260512-jqn"></a>260512-jqn | Six post-run follow-ups. ITEM 1: CSS for InterviewV2/Onboarding/BracketDeepDive takeovers. ITEM 2: Round 3 INFLUENCED_BY edges, so `/api/edges?round=3` works. ITEM 3: governor slots on the wire (closes KR-41.1-05). ITEM 4: rationale sliding window + per-agent streaming `push_rationale`. ITEM 5: live data-source audit feeding the Signal Wire. ITEM 6: advisory one-item-per-holding + sector enrichment | 48 refs across frame.ts, v2.tsx, RationalesContext.tsx, useDataSourceAudit.ts, styles.css, types.ts, advisory/engine.py, advisory/sector_map.py, batch_dispatcher.py, data_audit.py, ingestion/*_provider.py, simulation.py, state.py, web/app.py, web/broadcaster.py, and tests |
| <a id="quick-260611-rlx"></a>260611-rlx | `think=False` in advisory synthesis; report auto-chained after advisory succeeds | tests/unit/test_advisory_route.py:219 |

---

## 10. Phase-number lookup

"Phase N" in comments means the roadmap phase that introduced the code. Counts
are the live references.

| Phase | Topic | Refs | Main locations |
|---|---|---|---|
| 1 | Project foundation (config, types, logging) | 5 | simulation.py, governor.py |
| 2 | Ollama integration (client, model manager, worker context manager, parsing) | 11 | app.py, governor.py, simulation.py |
| 3 | Resource governance | 7 | config.py, governor.py, memory_monitor.py, state.py |
| 4 | Neo4j graph state | 2 | app.py, tests/conftest.py |
| 5 | Seed injection + personas | 5 | parsing.py, tests |
| 6 | Round 1 standalone | 3 | simulation.py |
| 7 | Rounds 2-3 peer influence | 13 | cli.py, simulation.py |
| 8 | Dynamic influence topology + bracket summaries | 10 | cli.py, graph.py |
| 10 | TUI panels/telemetry (StateStore contracts) | 9 | state.py, simulation.py, worker.py |
| 11 | Live graph memory | 23 | simulation.py, graph.py, interview.py |
| 12 | Posts / social layer | 10 | simulation.py, graph.py |
| 13 | Dynamic persona modifiers | 14 | config.py, simulation.py, seed.py, parsing.py |
| 14 | Agent interviews | 1 | graph.py |
| 15 | ReAct report | 4 | cli.py, graph.py, web/routes/report.py |
| 24 | HTML report export ([lost](#hist-pygal-html-report)) | 1 | tests/test_report.py |
| 27 | Shock analysis + reporting (`read_shock_impact`, shock template) | 19 | tests/test_report.py, tests/test_graph.py, graph.py, cli.py |
| 28 | Replay data layer | 3 | graph.py |
| 30 / 31 / 32 / 34 / 35 / 36 | Web: WS stream / SPA + edges / controls / replay / interviews / report viewer | 3/2/4/1/1/8 | web/*, tests/test_web*.py |
| 35.1 | Shock injection wiring (B1) | 8 | simulation.py, graph.py, fe/components/app_v2.tsx |
| 37 | Isolation foundation | 10 | logging.py, tests/invariants/ |
| 38 | yfinance + RSS providers | 6 | ingestion/ |
| 39 | Holdings loader | 5 | config.py, holdings/loader.py, security/hashing.py, web/app.py |
| 40 | Simulation context wiring | 38 | simulation.py, app.py, context_formatter.py, ingestion/, tests |
| 41 | Advisory pipeline | 11 | web/routes/advisory.py, tests/invariants/ |
| 41.1 | First React port (Claude Design UI) | 1 | fe/components/modals.jsx |
| 41.2 | Audit fix: Cypher case, tool names, `generate(system=)`, modal wiring | 5 | fe/components/ReportModal.tsx, fe/lib/markdown.ts, tests |
| 41.4 | R3 stall: Ollama parallelism + model swap + `think=False` | 5 | seed.py, scripts/start_ollama.sh, tests |
| 41.6 | Quant Terminal UI port | 1 | fe/components/ReportModal.tsx |
| 999.3 | Live memory telemetry | 2 | web/broadcaster.py |

---

## 11. Review tags

About 190 comment lines cite cross-AI plan reviews ("Codex HIGH-2", "codex
MEDIUM-7", "gemini #G2", "REVIEW HIGH", "REVIEWS #1", "REVISION-1"). These were
findings from reviewing the GSD plans. The reasoning is already in each comment,
and the source review files under `.planning/phases/*/*-REVIEWS.md` are being
deleted. **Recommendation:** leave them, and strip the tag prefix when the
comment is next edited. Do not invent anchors for them. The heaviest files are
`tests/test_pii_redaction.py` (16), `fe/components/v2.tsx` (16), `logging.py` (14),
and `tests/test_ingestion_types.py` (11). Mentions of "Gemini" in
`tests/inference/test_openai_provider_real_providers.py` refer to the Google
provider, not a review.

Other GSD bookkeeping tags carry no decision content and get no anchors. Treat
them the same way (leave them, and strip them when the comment is next edited):

| Tag family | Live lines | Example | Note |
|---|---|---|---|
| `Pitfall N` / `Research Pitfall N` | ~111 | `advisory/engine.py:8` "Pitfall 1: NEVER pass the PortfolioSnapshot… into a structlog" | Numbered per phase `*-RESEARCH.md`, so "Pitfall 1" means different things in different files. Almost every hit restates the pitfall inline; the few that only cited the file were rewritten to DECISIONS anchors when `.planning/` was removed |
| `Plan NN-NN` / `Plan NN-NN task N` | ~70 | `fe/components/app_v2.tsx:50` "Plan 41.6-04 task 2 (W4)" | GSD plan and task numbers |
| `W1`..`W4` / `Wave N` | ~44 | `fe/App.tsx:3` "lands in Plan 41.6-04 (W4)" | GSD execution waves |
| `ITEM n` | ~50 | `state.py:115` "ITEM 4 of quick task 260512-jqn" | Items of quick task 260512-jqn; see [§9](#quick-260512-jqn) |
| `(Rule N)` deviation | 1 | `fe/api/simulation.ts:20` "Plan 41.1-03 deviation (Rule 1)" | GSD executor deviation rule |
