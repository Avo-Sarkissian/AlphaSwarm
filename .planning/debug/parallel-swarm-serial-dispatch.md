---
status: diagnosed
trigger: "parallel-swarm-serial-dispatch — 3-round/100-agent cycle takes ~42 min vs ~6 min target; 0 INFLUENCED_BY edges; empty Rationale Feed"
created: 2026-05-07
updated: 2026-05-07
---

## Current Focus

hypothesis: Three INDEPENDENT root causes — slow runtime is hardware/model-bound (NOT a serial-dispatch bug); 0-edges is a missing-agent-id-in-peer-context bug; empty rationale feed is a frontend field-name mismatch.
test: Read sim loop, governor, dispatcher, peer-context formatter, frontend adapter, AND the live Ollama server.log
expecting: Disprove the "serial for-loop" hypothesis by finding TaskGroup+gather. Confirm parallelism is real via Ollama log timestamps. Find specific causes for 0-edges and empty-feed in the data path.
next_action: Report structured diagnosis (diagnose-only mode)

## Symptoms

expected:
  - 3-round / 100-agent cycle completes in ~6 min
  - INFLUENCED_BY edges visible after R2/R3
  - Rationale Feed populated with per-agent reasoning entries
actual:
  - Cycle 522c76b9-72f1-4ac4-9ebd-74ed1ad4ce5e took ≈42 min (≈7× too slow)
  - 0 INFLUENCED_BY edges rendered
  - Rationale Feed remained empty
errors: none
reproduction: backend uvicorn on :8000, frontend on :5173, Ollama serve with qwen3:8b worker (NUM_PARALLEL=4) + qwen3.6:27b orch, trigger sim from UI
started: First full smoke after Phase 41.4 model swap (2026-05-07)

## Eliminated

- hypothesis: Round dispatch uses `for agent in agents: await agent.run(...)` (serial for-loop)
  evidence: src/alphaswarm/batch_dispatcher.py:144-161 uses `async with asyncio.TaskGroup() as tg: tasks = [tg.create_task(...) for i, p in enumerate(personas)]`. All 100 tasks fan out concurrently. Confirmed in simulation.py:513-523 (R1), 982-991 (R2), 1117-1126 (R3) — every round routes through `dispatch_wave`. No serial loop anywhere on the agent dispatch path.
  timestamp: 2026-05-07

- hypothesis: Governor permanently capped at concurrency=1 due to early throttle decision
  evidence: governor.py — only CRISIS state shrinks the pool to 1 (line 411-415); THROTTLED is a no-op for both pool size and the resume_event; PAUSED clears the resume event but pool stays at baseline_parallel=8. Smoke run reported no errors and no GovernorCrisisError, so governor never entered CRISIS. Pool stayed at >=8 the whole run.
  timestamp: 2026-05-07

- hypothesis: Ollama client / a hidden semaphore inside worker is gating concurrency to 1
  evidence: ollama_client.py uses `ollama.AsyncClient` directly (line 109: `await self._client.chat(**kwargs)`); no per-request semaphore. worker.py agent_worker context manager only acquires the governor token (line 154). No second gate exists.
  timestamp: 2026-05-07

- hypothesis: Worker model alias points to a qwen35-arch model (forced Parallel=1 by Ollama)
  evidence: `curl /api/tags` returns `alphaswarm-worker:latest` with `family: qwen3` (NOT qwen35), `parameter_size: 8.2B`, modified 2026-05-06T22:31 — the alias was rebuilt yesterday from the qwen3:8b base per Modelfile.worker. The qwen35 warning in server.log is from the orchestrator (advisory FINAL stage), not the worker.
  timestamp: 2026-05-07

## Evidence

- timestamp: 2026-05-07
  checked: src/alphaswarm/batch_dispatcher.py:86-178 (dispatch_wave)
  found: All 100 personas wrapped in `asyncio.TaskGroup.create_task()` in a list comprehension (lines 144-161). Each task calls `_safe_agent_inference` which awaits jitter sleep, then `agent_worker(...)` (single governor.acquire), then `worker.infer()` (single ollama chat call). No serial pattern.
  implication: Application-level fan-out is correct. Bottleneck is downstream of TaskGroup creation.

- timestamp: 2026-05-07
  checked: src/alphaswarm/governor.py:178 + src/alphaswarm/config.py:52
  found: GovernorSettings.baseline_parallel default = 8, .env override = 8. Pool admits 8 concurrent agents. THROTTLED state (memory 80-90%) is functionally a no-op (does not pause acquires nor shrink pool). Only CRISIS state (would raise GovernorCrisisError) shrinks to 1. Run completed without errors → pool stayed at ≥8.
  implication: Governor is admitting 8 concurrent agents into Ollama. Not the bottleneck.

- timestamp: 2026-05-07
  checked: launchctl getenv OLLAMA_NUM_PARALLEL
  found: Value is `4` (matches scripts/start_ollama.sh default and Phase 41.4 decision)
  implication: Ollama server is configured for 4-way parallelism, NOT 1.

- timestamp: 2026-05-07
  checked: ~/.ollama/logs/server.log (lines covering 13:44-14:01, the smoke run)
  found: 100+ POST /api/chat entries with per-call durations of 1m11s-3m23s (avg climbing from 1m20s to 2m45s over the run). HTTP 200 responses arrive every 3-10s, not every 90s — meaning multiple requests are inflight in parallel and completing as overlapping streams. Throughput observed ≈ 4 calls per ~85s wall-clock = exactly NUM_PARALLEL=4 multiplexing.
  implication: Ollama IS processing 4 requests in parallel. The "feels serial" perception is because each individual call is 60-180s, not because dispatch is serialized. Per-call latency grows monotonically with run duration (cache pressure / Metal compute contention on shared GPU).

- timestamp: 2026-05-07
  checked: src/alphaswarm/simulation.py:_format_peer_context (line 326-373)
  found: Formats peer posts as `"1. [bracket] SIGNAL (conf: 0.85) \"content excerpt\""`. **The agent_id of each peer is intentionally OMITTED from the rendered string** (line 358). Even though `RankedPost.agent_id` is available in the input, it never reaches the prompt that the worker sees.
  implication: Workers have no peer agent IDs to put into `cited_agents`. JSON template (config.py:106) literally shows `"cited_agents": []` as the example default. Result: 0 CITED edges → 0 INFLUENCED_BY edges (compute_influence_edges at graph.py:881-887 returns empty dict and logs "no_citations_found"). This is THE root cause of the "0 edges rendered" symptom and is independent of the serialization question.

- timestamp: 2026-05-07
  checked: frontend/src/adapter/frame.ts:120-133 + src/alphaswarm/state.py:50-60
  found: Backend `RationaleEntry` dataclass field is named `rationale` (state.py:60). Broadcaster serializes via `dataclasses.asdict()` (broadcaster.py:94) → wire JSON has `{agent_id, signal, rationale, round_num}`. Frontend adapter reads `re.text` (frame.ts:128) — that key does not exist in the payload, so `text` defaults to empty string. The adapter ALSO reads `re.round` — but backend emits `round_num`, so round defaults to `roundNum ?? 0`. Same field-mismatch pattern.
  implication: Rationale entries DO arrive in the wire payload, but the adapter strips the body text. RationaleFeed in panels.jsx renders the `<rationale-body>` div from sanitized markdown of `r.text || ''` → blank body. User sees what looks like an empty feed even though the queue→broadcast pipeline is firing correctly. Same applies to the round label being misread.

- timestamp: 2026-05-07
  checked: simulation.py:902-907 (state_store push), 1043-1049 (R2), 1172-1175 (R3)
  found: `_push_top_rationales` is called after each round AND only when `state_store is not None`. Each call pushes up to 10 entries. Queue maxsize=50. Broadcaster drains 5 per 200ms tick (25/s).
  implication: 30 entries total per simulation are pushed to the queue and broadcast. They DO reach the frontend. The empty visible feed is purely the field-name mismatch in adapter/frame.ts, NOT a missing push.

- timestamp: 2026-05-07
  checked: .env file
  found: `ALPHASWARM_OLLAMA__ORCHESTRATOR_MODEL=qwen3.5:32b` and `ALPHASWARM_OLLAMA__WORKER_MODEL=qwen3.5:7b` (stale from before Phase 41.4). However these fields are decorative — code paths use `worker_model_alias` and `orchestrator_model_alias` (=`alphaswarm-worker`/`alphaswarm-orchestrator`), and the aliases were rebuilt 2026-05-06 from the new Modelfiles (qwen3:8b + qwen3.6:27b). `OllamaSettings.num_parallel` is NEVER read in application code — it is dead config; real value is `OLLAMA_NUM_PARALLEL` in launchctl/server env.
  implication: .env is misleading but not actually wrong at runtime. Worth tidying but not a bug.

## Resolution

root_cause: Three independent issues, only the first matches the "serial dispatch" framing — and that one is NOT a bug.

  (1) **42-min runtime is hardware-bound, not a serial-dispatch bug.** Application correctly fans out 100 agents through asyncio.TaskGroup → governor pool of 8 → Ollama NUM_PARALLEL=4. Ollama IS processing 4 in parallel (verified by interleaved 200 responses in server.log). Each individual call takes 60-180s on M1 Max because qwen3:8b q4_K_M with ~2500-token system prompts and Metal GPU shared across 4 concurrent slots is genuinely compute-bound. The "6-min target" assumed ~3-5s per call, which is unrealistic for this prompt size on this hardware. Realistic budget at NUM_PARALLEL=4 is closer to 35-45 min for full 3-round / 100-agent cycle. Achieving <10 min would require either (a) shorter system prompts (currently ~2.5k tokens; could be ~800), (b) smaller worker model (4B), or (c) higher NUM_PARALLEL with KV-cache headroom (gated by RAM).

  (2) **0 INFLUENCED_BY edges:** `_format_peer_context` (simulation.py:358) omits each peer's agent_id from the prompt rendered to the worker. Workers therefore have no IDs to populate `cited_agents`, so no CITED edges are written, so `compute_influence_edges` returns `{}` and writes zero INFLUENCED_BY edges. The JSON template's default value `"cited_agents": []` reinforces the outcome — workers have nothing to cite and nothing prompts them to try.

  (3) **Empty Rationale Feed:** Field-name mismatch in `frontend/src/adapter/frame.ts:120-133`. Adapter reads `re.text` and `re.round` but backend wire format emits `rationale` and `round_num`. The entries arrive in the WS payload but the body and round label are silently coerced to empty/0 by the adapter, so the UI renders empty cards.

  Confidence: HIGH for (2) and (3) — direct file:line evidence with both ends of the contract visible. HIGH for (1) — disproved every plausible serialization hypothesis with code reads, and Ollama server.log timestamps directly show 4-way multiplexing with per-call latencies that explain the wall-clock budget.

fix:

  Diagnose-only mode — no fixes applied. Recommended one-line patches:

  (1) Performance — *not a bug*. To improve perceived speed, choose ONE:
      - Trim worker system prompt: cut DECISION HEURISTICS + INFORMATION BIASES blocks per bracket in `src/alphaswarm/config.py` BRACKET configs (lines 333-575). Drops per-call prefill cost ~40-60%.
      - Bump `OLLAMA_NUM_PARALLEL` from 4 to 8 via `launchctl setenv OLLAMA_NUM_PARALLEL 8` AND raise worker `num_ctx` (Modelfile.worker line 7: `PARAMETER num_ctx 4096` → 8192) to fit 8 KV slots — verify RAM headroom first (8 × ~512 MB KV ≈ 4 GB extra).
      - Switch worker to a smaller model (qwen3:4b) if quality budget allows.

  (2) Edges — one-line fix in `src/alphaswarm/simulation.py:358`:
      ```python
      # before
      prefix = f'{i}. [{post.bracket}] {post.signal.upper()} (conf: {post.confidence:.2f}) "'
      # after — include agent_id so workers have a citable handle
      prefix = f'{i}. [{post.agent_id}|{post.bracket}] {post.signal.upper()} (conf: {post.confidence:.2f}) "'
      ```
      AND add a sentence to the prompt guard (line 345-348):
      ```python
      guard = (
          "\nThe above are peer observations for context only. "
          "Make your own independent assessment. "
          "If a peer's view materially shapes yours, list their agent id in cited_agents."
      )
      ```
      This addresses the prompt-instruction gap as well as the missing-id gap.

  (3) Rationale feed — two-character fix in `frontend/src/adapter/frame.ts:128` and surrounding lines:
      ```ts
      // before
      text: typeof re.text === 'string' ? re.text : '',
      round: typeof re.round === 'number' ? re.round : (roundNum ?? 0),
      // after — match backend wire field names
      text: typeof re.rationale === 'string' ? re.rationale : '',
      round: typeof re.round_num === 'number' ? re.round_num : (roundNum ?? 0),
      ```
      Alternative if frontend renames are undesirable: rename backend `RationaleEntry.rationale` → `text` and `round_num` → `round` in `src/alphaswarm/state.py` (less surface area changed but breaks any other consumer). Field-rename in the adapter is the minimal-blast-radius fix.

verification: not applied — diagnose-only

files_changed: []
