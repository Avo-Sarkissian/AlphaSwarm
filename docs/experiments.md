# Experiments

The results log: every number the project quotes, with the command or record it came from.

## Headline numbers (v6.0)

The numbers the README, the CHANGELOG and the résumé bullets in [HISTORY.md](HISTORY.md)
quote. Each row links to the table it came from. `uv run python scripts/docs_sync.py write`
copies them and `tests/test_docs_sync.py` fails when a copy is out of date. A value of
`not measured` means the measurement was not run; it is shown as such, never estimated.
Rows whose source is plain text have no results table yet. Method and pre-registered
metrics: `methodology.md` (not written yet).

<!-- headline:start -->
| Key | Result | Value | Source |
|---|---|---|---|
| `eval_accuracy` | Swarm accuracy vs the best single-model baseline | not measured | Evaluation: pilot deferred to the owner |
| `eval_verdict` | Evaluation verdict (paired bootstrap) | not measured | Evaluation: pilot deferred to the owner |
| `peer_effect` | Peer-attributable flip rate (treated − control) | not measured | Control group: control-group run not done |
| `peer_effect_verdict` | Peer-effect verdict | not measured | Control group: control-group run not done |
| `ablation_rounds` | 2 vs 3 rounds | not measured | Ablations: not run |
| `ablation_peers` | Peer strategy: stratified vs random vs none | not measured | Ablations: not run |
| `peer_exposure` | Peer exposure before → after the selector fix | brackets never shown: 6 → 0; largest slot share: 46.0% → 15.2%; agents shown: 46 → 100 (Round 2) | [Decision](DECISIONS.md#adr-diverse-peer-context) |
| `speedup` | Mean round time before → after the performance work | not measured | P6 arms: performance arms not run |
| `mlx_prefill_worker` | Worker prefill, GGUF → MLX | 833 → 2,361 tok/s (2.8×, GGUF MoE → MLX MoE) | [Model stack benchmarks](#model-stack-benchmarks-2026-06-11) |
| `mlx_prefill_orchestrator` | Orchestrator prefill, GGUF → MLX | 111 → 3,395 tok/s (30.6×, same 27B weights) | [Model stack benchmarks](#model-stack-benchmarks-2026-06-11) |
| `model_weights` | Model memory (loaded, Ollama) | not measured | Memory budget: memory measurement not done |
| `wall_clock_3r` | 3-round run, median wall time | not measured | P6 arms: performance arms not run |
| `wall_clock_2r` | 2-round run, median wall time | not measured | Ablations: rounds ablation not run |
| `backend_tests` | Backend tests (offline suite; Neo4j suite not measured) | 2,284 | [Test suite](#test-suite-v60) |
| `backend_coverage` | Backend coverage (line + branch, offline suite) | 91% | [Test suite](#test-suite-v60) |
| `frontend_tests` | Frontend tests (vitest) | 392 | [Test suite](#test-suite-v60) |
| `import_contracts` | Import-linter contracts kept | 1 | [Test suite](#test-suite-v60) |
| `demo_url` | Static demo | not published | Static demo not built yet |
<!-- headline:end -->

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
The offline count leaves out the three live Yahoo Finance tests, which need the network.

| Suite | Command | Result |
|---|---|---|
| Backend, offline | `ALPHASWARM_INFERENCE_CONFIG_PATH=/nonexistent/inference.json uv run pytest -q -m "not neo4j" -p no:cacheprovider --ignore=tests/integration/test_yfinance_provider_live.py --cov=alphaswarm --cov-branch --cov-report=term` | 2,284 passed; coverage 91% (line + branch) |
| Backend, Neo4j | `scripts/neo4j_test.sh up && uv run pytest -q -m neo4j --require-neo4j` | not measured: neo4j-test was in use by another run when this was counted |
| Frontend | `npm --prefix frontend test` | 392 passed |
| Import contracts | `uv run lint-imports` | 1 kept, 0 broken |
