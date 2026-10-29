# Experiments

The results log: every number the project quotes, with the command or record it came from.

## Headline numbers (v6.0)

The one place a measured number is written; each row links to the table it came from. The
README, the CHANGELOG and the résumé bullets in [HISTORY.md](HISTORY.md) quote these rows
only through generated blocks, which `uv run python scripts/docs_sync.py write` fills and
`docs_sync.py check` compares ([why](DECISIONS.md#adr-docs-sync)). A value of
`not measured` means the measurement was not run; it is shown as such, never estimated.
`eval_verdict` takes the claim-rule verdict `eval/run_eval.py` prints (`better`,
`inconclusive` or `worse`). Method and pre-registered metrics:
[methodology.md](methodology.md).

<!-- headline:start -->
| Key | Result | Value | Source |
|---|---|---|---|
| `eval_accuracy` | Swarm accuracy vs the best single-model baseline | not measured | [Evaluation protocol](methodology.md): no runs recorded |
| `eval_verdict` | Evaluation verdict (paired bootstrap) | not measured | [Evaluation protocol](methodology.md): no runs recorded |
| `peer_effect` | Peer-attributable flip rate (treated − control) | not measured | Control group: no runs recorded |
| `peer_effect_verdict` | Peer-effect verdict | not measured | Control group: no runs recorded |
| `ablation_rounds` | 2 vs 3 rounds | not measured | [Ablation protocol](methodology.md): no runs recorded |
| `ablation_peers` | Peer strategy: stratified vs random vs none | not measured | [Ablation protocol](methodology.md): no runs recorded |
| `peer_exposure` | Peer exposure before → after the selector fix | brackets never shown: 6 → 0; largest slot share: 46.0% → 15.2%; agents shown: 46 → 100 (Round 2) | [Decision](DECISIONS.md#adr-diverse-peer-context) |
| `speedup` | Mean round time before → after the performance work | not measured | [Arms](#arms): no runs recorded |
| `mlx_prefill_worker` | Worker prefill, GGUF → MLX | 833 → 2,361 tok/s (2.8×, GGUF MoE → MLX MoE) | [Model stack benchmarks](#model-stack-benchmarks-2026-06-11) |
| `mlx_prefill_orchestrator` | Orchestrator prefill, GGUF → MLX | 111 → 3,395 tok/s (30.6×, same 27B weights) | [Model stack benchmarks](#model-stack-benchmarks-2026-06-11) |
| `model_weights` | Model memory (loaded, Ollama) | not measured | [Memory budget](RUNBOOK.md#memory-budget): not measured yet |
| `wall_clock_3r` | 3-round run, median wall time | not measured | [Arms](#arms): no runs recorded |
| `wall_clock_2r` | 2-round run, median wall time | not measured | [Ablation protocol](methodology.md): no runs recorded |
| `backend_tests` | Backend tests (offline + Neo4j) | 4,037 | [Test suite](#test-suite-v60) |
| `backend_coverage` | Backend coverage (line + branch, offline suite) | 95.5% | [Test suite](#test-suite-v60) |
| `frontend_tests` | Frontend tests (vitest) | 881 | [Test suite](#test-suite-v60) |
| `import_contracts` | Import-linter contracts kept | 5 | [Test suite](#test-suite-v60) |
| `demo_url` | Static demo | not published | [Pages workflow](../.github/workflows/pages.yml): not run yet |
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
- **Confound:** prompts carry market and news context fetched at run time
  (`docs/DECISIONS.md#adr-market-context`), so prompt sizes differ between runs. Since
  the block reaches every round by default, prefill comparisons set
  `ALPHASWARM_SIMULATION__MARKET_CONTEXT_ROUNDS=1` and use Rounds 2-3.
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

Counted on 2026-10-29 on branch `plan/24-phase-9-presentation-rest`, based on master
`e1c631e`. The offline suite deselects the tests marked `neo4j`, `live_network` (Yahoo
Finance and RSS calls, run nightly) and `ollama`; the Neo4j suite ran against the throwaway
`neo4j-test` database on 127.0.0.1:7688.

| Suite | Command | Result |
|---|---|---|
| Backend, offline | `ALPHASWARM_INFERENCE_CONFIG_PATH=/nonexistent/inference.json uv run pytest -q -m "not neo4j and not live_network and not ollama" -p no:cacheprovider --cov=alphaswarm --cov-branch --cov-fail-under=85` | 3,845 passed, 204 deselected; coverage 95.5% (line + branch) |
| Backend, Neo4j | `scripts/neo4j_test.sh up && uv run pytest -q -m neo4j --require-neo4j -p no:cacheprovider` | 192 passed |
| Frontend | `npx vitest run` (in `frontend/`) | 881 passed (130 files) |
| Import contracts | `uv run lint-imports` | 5 kept, 0 broken |

## P7.1 — reproducibility (same manifest, same seed)

Protocol: two `alphaswarm run` cycles of `fed-emergency-cut` with `ALPHASWARM_SIMULATION__SIM_SEED=4242` and `ALPHASWARM_SIMULATION__EXPERIMENT_TAG=p7-1-repro`, read with `scripts/peer_effect.py exposure-diff` and `scripts/compare_cycles.py --group-by experiment_tag --tag p7-1-repro`. Round 2 peers depend only on the run seed and on which Round 1 agents failed, so they must match exactly when the Round 1 PARSE_ERROR sets match. Round 3 may differ, because Round 2 citations differ (sampling is not bit-exact under NUM_PARALLEL batching).

No runs recorded: the reproducibility pair runs on the reference machine.

## P7.3 — peer-attributable flips (control holdout)

Protocol: eight 3-round cycles, the four `scripts/benchmark_seeds.json` rumors × `sim_seed` 1901 and 1902, `ALPHASWARM_SIMULATION__CONTROL_FRACTION=0.2`, tag `p7-3-control`, `ALPHASWARM_SIMULATION__RETEST_ROUND1=true` on the 1901 runs. Estimator: per bracket, each cycle's treated flip rate minus its control flip rate (Rounds 2-3 pooled), averaged over cycles, with a percentile bootstrap 95% interval over cycles (`scripts/peer_effect.py effect --tag p7-3-control --markdown`). A PARSE_ERROR on either side of a round pair is not a flip. Twenty control readers per cycle means two to eight control observations per bracket per cycle (Rounds 2-3), so per-bracket intervals are wide; the "all" row is the headline number.

No runs recorded: the eight control cycles run on the reference machine.

## Noise floor (Round 1 retest)

Protocol: the four `p7-3-control` cycles with `sim_seed` 1901 draw Round 1 twice with different call seeds (`scripts/peer_effect.py noise --tag p7-3-control --markdown`). A flip rate at or below this floor is indistinguishable from sampling noise.

No runs recorded: the retest comes from the `sim_seed` 1901 control cycles.

## Shock treatment split

Protocol (optional owner run): two cycles with `ALPHASWARM_SIMULATION__SHOCK_TREATMENT_SPLIT=true`, tag `p7-3-shock`, and one shock injected during Round 1 through the web API (`scripts/peer_effect.py shock --tag p7-3-shock --markdown`). The split is implemented but not measured.

No runs recorded: this optional pilot runs on the reference machine.

## P7.5 — market-context probe (benchmark seeds)

Protocol: `uv run python scripts/context_probe.py --show-block` on the reference machine (Ollama per RUNBOOK §1, network, the SEC map cached per RUNBOOK §2 "SEC ticker map"). The probe parses each of the four `scripts/benchmark_seeds.json` rumors with the orchestrator against a graph stub (nothing persisted), resolves tickers on the swarm side and builds the market block with the real yfinance and RSS providers. Record the printed table here with the git sha, the date and whether `ticker_map_loaded source=sec` appeared.

Verify: the market block is non-empty for at least 3 of the 4 seeds. Expected: the three seeds that name public companies resolve tickers and show price lines; a private company stays unresolved; the central-bank seed has no company ticker but gets a news-only block.

No runs recorded: the probe needs the orchestrator and the network and runs on the reference machine.

## P7.6 — persona heterogeneity (Round 1 agreement among prompt twins)

Arms: `p76-baseline` (`ALPHASWARM_SIMULATION__PERSONA_TRAITS=false`) vs `p76-traits` (`=true`, the default); the four `scripts/benchmark_seeds.json` seeds with `sim_seed` 101-104, `ALPHASWARM_NUM_ROUNDS=2`, one tagged cycle per seed and arm. Twin groups: 43 (agents that share a bracket and a round-robin modifier, `personas.prompt_twin_groups` over the trait-less personas). Analysis (read-only): `uv run python scripts/persona_agreement.py --tag p76-baseline --tag p76-traits` prints, per arm, twin agreement, same-bracket cross-modifier agreement, within-bracket entropy and between-bracket total-variation distance with bootstrap intervals over cycles, then the paired change per field. Record the table and the paired lines here with the git sha and the cycle ids.

Verify: Round 1 twin agreement drops versus the baseline (mean drop > 0 and lower in at least 3 of the 4 seeds). If it does not, `persona_traits` becomes opt-in (default off) and BACKLOG 4.2 stays open with the numbers.

No runs recorded: the measurement needs real inference on the reference machine.

## P7.7 — Accuracy against outcomes

Protocol: `docs/methodology.md`. Reproduce with `uv run python eval/run_eval.py score`
(reads the tagged cycles, their decisions and manifests from Neo4j).

### Compute budget (gate G-23)

Backend: A, local Ollama/MLX (decided 2026-10 under the owner's delegation): swarm cycles
use 2 rounds except the Round 3 arms (`rounds3`, `boost_0`, `boost_005`), and the ablations
use the 5-event subset × 3 seeds. Hours per phase come from
`uv run python eval/run_eval.py budget --n-events <N>` on the reference machine (recent
complete cycles' `total_seconds`, `seed_seconds` and `agent_count`); the table is recorded
here before the first evaluation cycle.

No runs recorded: the event set, fixtures, labels and evaluation cycles are prepared and run on the reference machine.

## P7.8 — Ablations

Protocol: `docs/methodology.md` §9. Reproduce with `uv run python eval/run_eval.py ablations`.

No runs recorded: the ablation cycles run on the reference machine after the accuracy runs.
