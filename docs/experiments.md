# Experiments

The results log: every number the project quotes, with the command or record it came from.

## Headline numbers (v6.0)

The one place a measured number is written; each row links to the table it came from. The
README, the CHANGELOG and the résumé bullets in [HISTORY.md](HISTORY.md) quote these rows
only through generated blocks, which `uv run python scripts/docs_sync.py write` fills and
`docs_sync.py check` compares ([why](DECISIONS.md#adr-docs-sync)). None of those blocks
exists yet, so no document carries a generated copy today; until they all exist, along with
`docs/media/captures.json`, both commands stop with exit status 2 and change nothing. A
value of `not measured` means the measurement was not run; it is shown as such, never
estimated.
Rows whose source is plain text have no results table yet. Method and pre-registered
metrics: `methodology.md` (not written yet).

<!-- headline:start -->
| Key | Result | Value | Source |
|---|---|---|---|
| `eval_accuracy` | Swarm accuracy vs the best single-model baseline | not measured | Evaluation: not run |
| `eval_verdict` | Evaluation verdict (paired bootstrap) | not measured | Evaluation: not run |
| `peer_effect` | Peer-attributable flip rate (treated − control) | not measured | Control group: control-group run not done |
| `peer_effect_verdict` | Peer-effect verdict | not measured | Control group: control-group run not done |
| `ablation_rounds` | 2 vs 3 rounds | not measured | Ablations: not run |
| `ablation_peers` | Peer strategy: stratified vs random vs none | not measured | Ablations: not run |
| `peer_exposure` | Peer exposure before → after the selector fix | brackets never shown: 6 → 0; largest slot share: 46.0% → 15.2%; agents shown: 46 → 100 (Round 2) | [Decision](DECISIONS.md#adr-diverse-peer-context) |
| `speedup` | Mean round time before → after the performance work | not measured | Arms: performance arms not run |
| `mlx_prefill_worker` | Worker prefill, GGUF → MLX | 833 → 2,361 tok/s (2.8×, GGUF MoE → MLX MoE) | [Model stack benchmarks](#model-stack-benchmarks-2026-06-11) |
| `mlx_prefill_orchestrator` | Orchestrator prefill, GGUF → MLX | 111 → 3,395 tok/s (30.6×, same 27B weights) | [Model stack benchmarks](#model-stack-benchmarks-2026-06-11) |
| `model_weights` | Model memory (loaded, Ollama) | not measured | Memory budget: memory measurement not done |
| `wall_clock_3r` | 3-round run, median wall time | not measured | Arms: performance arms not run |
| `wall_clock_2r` | 2-round run, median wall time | not measured | Ablations: rounds ablation not run |
| `backend_tests` | Backend tests (offline suite; Neo4j suite not measured) | 2,284 | [Test suite](#test-suite-v60) |
| `backend_coverage` | Backend coverage (line + branch, offline suite) | 91% | [Test suite](#test-suite-v60) |
| `frontend_tests` | Frontend tests (vitest) | 392 | [Test suite](#test-suite-v60) |
| `import_contracts` | Import-linter contracts kept | 1 | [Test suite](#test-suite-v60) |
| `demo_url` | Static demo | not published | Static demo not built yet |
<!-- headline:end -->

## Protocol

The performance arms below are measured on the reference machine (Apple M1 Max, 64 GB,
Ollama with the MLX backend). Every number comes from the cycle metrics of a real run,
read with `scripts/telemetry_report.py`; the cycle ids and git SHAs let anyone re-read
them from Neo4j. Metric definitions: `docs/DECISIONS.md#adr-inference-telemetry`.

- **Server:** Ollama started with `OLLAMA_USE_MLX=1` and `OLLAMA_NUM_PARALLEL=4`
  (`docs/RUNBOOK.md` §1). `alphaswarm-worker` = qwen3.6:35b-a3b-nvfp4,
  `alphaswarm-orchestrator` = qwen3.6:27b-nvfp4. No other model and no other
  AlphaSwarm process running.
- **Seeds:** `apple-anthropic`, `nvda-earnings-miss`, `fed-emergency-cut` from
  `scripts/benchmark_seeds.json`; one run per seed per arm; `ALPHASWARM_NUM_ROUNDS=3`.
- **Confound:** Round 1 prompts carry market and news context fetched at run time
  (`docs/DECISIONS.md#adr-market-context`), so Round 1 prompt sizes differ between
  runs. Prefill comparisons use Rounds 2-3.
- **Distribution rule:** total-variation (TV) distance between the final
  buy/sell/hold distributions of the same seed in two arms. "Unchanged" means mean
  TV ≤ 0.15 over the seeds and no seed above 0.25. When one seed is above 0.25,
  re-run that seed once on the later arm: if the two later-arm runs differ from
  each other by at least as much as the earlier-vs-later pair, the shift is
  run-to-run noise and the rule passes.
- **Prefill rule:** a prompt-layout change is kept only if the mean change of
  `r2`/`r3` `mean_prefill_ms` across seeds is −10% or better and the distribution
  rule holds.
- **Rationale spot-check:** 10 sampled final-round rationales per seed per arm
  (`telemetry_report.py rationales --sample 10 --rng-seed 7`), each marked "gives a
  reason tied to the rumor" (yes/no) and "cut off mid-sentence" (yes/no).

## Arms

| Arm | Git SHA | Change under test |
|---|---|---|

## A0 — baseline (telemetry only)

No runs recorded: the three baseline runs happen on the reference machine.

## A1 — output caps, warm-up and timeouts (vs A0)

No runs recorded: this arm needs the A0 baseline first.

## A2 — prefix-reuse prompt layout (vs A1, or vs A1b when the rationale cap was reverted)

No runs recorded: this arm needs the A1 result first.

## Web and UI efficiency

No measurement recorded: idle serialization and React Profiler commits are measured on the
reference machine.

## Model stack benchmarks (2026-06-11)

Single-stream throughput on the reference M1 Max with Ollama 0.30.7, recorded when the MLX
stack was chosen ([adr-model-stack](DECISIONS.md#adr-model-stack)). The raw figures are in
the headers of [Modelfile.worker](../modelfiles/Modelfile.worker) and
[Modelfile.orchestrator](../modelfiles/Modelfile.orchestrator).

| Role | Model (backend) | Prefill tok/s | Decode tok/s |
|---|---|---:|---:|
| Worker | qwen3:8b (GGUF, llama.cpp) | 422 | 43 |
| Worker | qwen3.5:35b (GGUF, llama.cpp) | 833 | 60 |
| Worker | qwen3.6:35b-a3b-nvfp4 (MLX) | 2,361 | 56 |
| Orchestrator | qwen3.6:27b-q4_K_M (GGUF, llama.cpp) | 111 | 9.0 |
| Orchestrator | qwen3.6:27b-nvfp4 (MLX) | 3,395 | 11.3 |

## Test suite (v6.0)

Counted on 2026-10-22 on branch `plan/24-phase-9-presentation`, based on master `05743c4`.
The offline count leaves out all six tests in
`tests/integration/test_yfinance_provider_live.py`: four call Yahoo Finance and need the
network, one checks the empty-list guard without a network call, and one checks that the
module stays under `tests/integration/`.

| Suite | Command | Result |
|---|---|---|
| Backend, offline | `ALPHASWARM_INFERENCE_CONFIG_PATH=/nonexistent/inference.json uv run pytest -q -m "not neo4j" -p no:cacheprovider --ignore=tests/integration/test_yfinance_provider_live.py --cov=alphaswarm --cov-branch --cov-report=term` | 2,284 passed; coverage 91% (line + branch) |
| Backend, Neo4j | `scripts/neo4j_test.sh up && uv run pytest -q -m neo4j --require-neo4j` | not measured: neo4j-test was in use by another run when this was counted |
| Frontend | `npm --prefix frontend test` | 392 passed |
| Import contracts | `uv run lint-imports` | 1 kept, 0 broken |
