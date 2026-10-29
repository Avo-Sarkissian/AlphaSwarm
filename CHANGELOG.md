# Changelog

All notable changes to AlphaSwarm, newest first. Tags `vX.Y` mark milestones; from v6.0
on, the Python package version from `pyproject.toml` is shown in brackets. Entries before
v6.0 are milestone summaries reconstructed from [docs/HISTORY.md](docs/HISTORY.md), which
also tells the story between them.

## v6.0 (0.6.0) — Unreleased

The October 2026 improvement program: a whole-system audit turned into phases of fixes,
refactors, measurement tooling and presentation work. Runs now store what is needed to
reproduce and compare them, the harness to measure the swarm against a control group and
against real outcomes is in place, and a static demo can be built without the hardware.
The results table shows which measurements have been taken; a row reading `not measured`
has not been run yet.

### Results

<!-- results:start -->
| Result | Value | Source |
|---|---|---|
| Swarm accuracy vs the best single-model baseline | not measured | [Evaluation protocol](docs/methodology.md): no runs recorded |
| Peer-attributable flip rate (treated − control) | not measured | Control group: no runs recorded |
| 2 vs 3 rounds | not measured | [Ablation protocol](docs/methodology.md): no runs recorded |
| Peer strategy: stratified vs random vs none | not measured | [Ablation protocol](docs/methodology.md): no runs recorded |
| Peer exposure before → after the selector fix | brackets never shown: 6 → 0; largest slot share: 46.0% → 15.2%; agents shown: 46 → 100 (Round 2) | [Decision](docs/DECISIONS.md#adr-diverse-peer-context) |
| Mean round time before → after the performance work | not measured | [Arms](docs/experiments.md#arms): no runs recorded |
| Worker prefill, GGUF → MLX | 833 → 2,361 tok/s (2.8×, GGUF MoE → MLX MoE) | [Model stack benchmarks](docs/experiments.md#model-stack-benchmarks-2026-06-11) |
| Orchestrator prefill, GGUF → MLX | 111 → 3,395 tok/s (30.6×, same 27B weights) | [Model stack benchmarks](docs/experiments.md#model-stack-benchmarks-2026-06-11) |
<!-- results:end -->

### Correctness
- The web server applies the Neo4j schema and seeds the agents on startup, so a fresh install persists data, and write counts are checked.
- Failures are loud: budget, auth and governor-crisis stops reach the UI as a typed error, a round aborts above a failure threshold, and JSON logs keep tracebacks.
- Cycles have a status (running, complete, failed, cancelled), and each round is persisted in one transaction.
- Report, replay and advisory read models match their consumers, and two-round runs work end to end.
- Shocks are validated, bounded and carried into every later round.

### Methodology
- Peers are sampled per reader with a per-bracket cap and a seeded shuffle, so every bracket is heard.
- Agents see their own previous position, and a seeded no-peer control group can separate peer influence from noise.
- Every cycle stores a run manifest (seeds, model digests, prompt hashes, settings) and what each agent was shown.
- Consensus and dispersion metrics with bootstrap intervals, and a point-in-time evaluation harness with pre-registered metrics, single-model baselines and ablations ([methodology](docs/methodology.md)).

### Live UI and visualization
- WebSocket frames carry the cycle, mode, round count and an edges version, so the live graph always shows the current cycle.
- Top Influencers ranks by citations received, and undecided agents no longer count as HOLD.
- A deterministic layout with directional edges, a round-by-round story, accessible dialogs and a static read-only demo build.
- Placebo controls and mock telemetry are gone, and the advisory carries a not-investment-advice banner.

### Performance and operations
- Per-call telemetry (prefill, decode, load, truncation) and per-round aggregates in the cycle metrics.
- Output caps, a cheap warm-up, per-role timeouts and one worker load per run.
- A kernel-based memory signal and a governor whose limits hold under concurrency.
- `alphaswarm doctor`, Neo4j memory caps, a single-instance lock and a cloud retry policy with a shared cooldown.

### Security and privacy
- Host validation and one origin policy for HTTP and the WebSocket; peer rationales are sanitized and fenced.
- The portfolio reaches a cloud model only after an explicit opt-in, and prompts carry tickers, never quantities or cost basis.
- [docs/SECURITY.md](docs/SECURITY.md) documents the threat model, the mitigations and the known limitations.

### Architecture and quality
- `run_simulation` is a short loop over a round runner, the graph layer is a package with typed rows, services own the report, the advisory and jobs, and there is one launcher.
- CI gates ruff, mypy strict, import-linter contracts, dead code, an offline suite with a coverage floor, Neo4j tests against a throwaway database, and frontend lint, tests and build.

### Repository and docs
- MIT license, package metadata, one version source and an `alphaswarm` console script.
- A rewritten README with generated tables and the advisory disclaimer; [docs/methodology.md](docs/methodology.md), [docs/experiments.md](docs/experiments.md), [docs/graph-schema.md](docs/graph-schema.md), a memory-budget section in [docs/RUNBOOK.md](docs/RUNBOOK.md), and this changelog.

## v5.0 — 2026-04-18

Web UI: a FastAPI app with a 5 Hz WebSocket snapshot broadcaster and per-client drop-oldest queues, a Vue 3 agent graph (later replaced by the React UI), REST start, stop and shock controls, a live rationale feed and bracket bars, replay, agent interviews and a report viewer.

## v4.0 — 2026-04-12

Interactive simulation and analysis: mid-simulation shock injection, shock-impact analysis in the report, and replay of past cycles from Neo4j without re-inference. An HTML report export with charts was lost in a bad merge ([lessons](docs/HISTORY.md#lessons-worth-keeping)).

## v3.0 — 2026-04-08

Stock-specific recommendations: ticker extraction, a market-data pipeline with a disk cache and per-ticker decisions. Erased by a bad merge on 2026-04-09; the real-data work was rebuilt differently in v6.0.

## v2.0 — 2026-04-02

Engine depth: rationale episodes and narrative edges in the graph, public rationales as peer context, entity-aware persona modifiers, post-simulation agent interviews and a markdown report agent.

## v1.0 — 2026-03-27

Core engine: an async Ollama client with sequential model loading, a memory-aware resource governor, cycle-scoped Neo4j state, 100 personas in 10 brackets, a three-round cascade with peer context, citation-based influence edges and a terminal dashboard.
