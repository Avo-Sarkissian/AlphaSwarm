# AlphaSwarm History

A short history of the project from git (1,138 commits, 2026-03-24 → 2026-08-02)
and the retired `.planning/` records. The milestone numbering comes from the old
roadmap. For the reasoning behind each choice, see [DECISIONS.md](DECISIONS.md).

## Origin (2026-03)

The original spec ([docs/history/original-spec.md](history/original-spec.md), formerly `PROJECT_SPEC.md`) set the goal: an OASIS/MiroFish-style swarm in which 100 LLM
personas react to a single "seed rumor," shown in a Textual terminal grid and on
a Miro board. The spec named a Llama 4 orchestrator and had agents processed in
parallel batches of 16. The hard constraint from day one was the hardware: an
M1 Max with 64 GB, where memory pressure is the main way things fail.

## Milestones

| Milestone | Dates | Delivered |
|---|---|---|
| **v1.0 Core Engine** (Phases 1-10) | 03-24 → 03-27 | Async Ollama client with sequential model loading; memory-aware ResourceGovernor (token pool, psutil + macOS kernel pressure); Neo4j graph state (cycle-scoped, UNWIND batch writes); orchestrator entity extraction; 100 personas in 10 brackets; 3-round cascade with peer context; citation-based INFLUENCED_BY topology; Textual TUI (grid, rationale feed, telemetry, bracket bars). |
| **v2.0 Engine Depth** (11-15) | 03-31 → 04-02 | Live graph memory (RationaleEpisode, REFERENCES, decision narratives); public rationale posts as peer context; entity-aware persona modifiers; post-simulation agent interviews; prompt-based ReAct report agent over Neo4j writing markdown. |
| **v3.0 Stock-Specific Recommendations** (16-23) | 04-05 → 04-08 | SEC-validated ticker extraction, yfinance + Alpha Vantage pipeline with a disk cache, bracket-tailored market enrichment, per-ticker decisions, TUI ticker panel. **Erased on 04-09** by a bad worktree merge (see Lessons). Rebuilt differently in v6.0. |
| **v4.0 Interactive Simulation & Analysis** (24-28) | 04-09 → 04-12 | HTML report export with pygal charts and portfolio overlay (**lost on 04-11**, see Lessons); mid-simulation shock injection; shock-impact analysis; replay of past cycles from Neo4j without re-inference. |
| **v5.0 Web UI** (29-36) | 04-12 → 04-18 | FastAPI + uvicorn lifespan app; 5 Hz WebSocket snapshot broadcaster with per-client drop-oldest queues; Vue 3 + D3 force-directed "mirofish" graph; REST start/stop/shock controls; live rationale feed and bracket bars; replay UI; interview panel; report viewer (marked + DOMPurify); shock wiring end to end (35.1). |
| **v6.0 Real Data + Advisory** (37-41, plus inserted 41.x and backlog 999.x) | 04-18 → (never formally closed) | Isolation foundation (frozen types, provider protocols + fakes, PII-redacting logs, socket-blocked tests, import-linter holdings contract, four-surface canary); yfinance + RSS providers; Schwab CSV holdings loader + `/api/holdings`; grounded market context in Round 1; personalized advisory synthesis + API; auto-advisory on completion (999.1); live RAM telemetry (999.3). |

### Inside v6.0 (inserted phases)

- **41.1 (≈04-20 → 04-22): Vue → React.** Ported a Claude Design UI export to React + Vite + TS and wired it to the existing WS and REST contracts. Recorded 11 accepted regressions (KR-41.1-xx).
- **41.2 (05-05):** Fixed a Codex audit. The fixes covered lowercase Cypher signal comparisons that had silently zeroed the report and advisory data, mismatched ReAct tool names, and `generate(system=)`. The 41.3 "codex remediation" follow-up stayed on an unmerged branch.
- **41.4 (05-06): "R3 stall."**
  - The Vite WS proxy lacked `changeOrigin`.
  - Ollama forces `Parallel=1` for `qwen35` architectures, which made the 100th queued call wait 14-20 minutes.
  - `NUM_PARALLEL=16` spilled about 103 GB of KV cache to CPU.
  - The fix: worker `qwen3:8b`, orchestrator `qwen3.6:27b-q4_K_M`, `think=False`, and NUM_PARALLEL 16 → 4. That took an 8-call batch from 45.6 s to 7.5 s.
- **41.6 (05-10): Second UI replacement.** The AlphaSwarm-2 "Quant Terminal" design, with 6 contexts, a deterministic SVG graph, AdvisoryV2, InterviewV2, onboarding, bracket deep-dive, and 14 new KRs. Live UAT followed in quick tasks 260507-19f, 260510-fdo, 260512-jqn, and 260611-rlx.

## After the roadmap (June–October 2026)

- **05-28: Full-program sweep (SWEEP-260528).** It found that peer context showed every agent the same authority top-10, which manufactured convergence, and that the v1 composition leaned toward HOLD-biased "authority" brackets.
- **06-10/11: Overhaul (3110d11..50ed2db).**
  - Swarm composition v2: Institutions, Sell-Side, Event-Driven, and seven more brackets, with weights as narrative reach.
  - Per-reader, bracket-diverse peer contexts built in memory.
  - `num_rounds` set to 2 or 3.
  - Structured outputs.
  - Per-cycle metrics on the Cycle node, plus `compare_cycles.py` and benchmark seeds.
  - GitHub Actions CI and frontend wire-contract tests.
  - Neo4j backup script.
  - **TUI and Miro code deleted.**
  - **Model stack moved to MLX:** `qwen3.6:35b-a3b-nvfp4` worker and `qwen3.6:27b-nvfp4` orchestrator. Prefill went from 422 to 2361 t/s for the worker and from 111 to 3395 t/s for the orchestrator.
  - Root-caused why the swarm had been running serially for weeks: `launchctl` env vars do not survive a reboot. A LaunchAgent now re-applies them.
- **06-10:** Found that the pytest Neo4j fixture had been running unscoped `DETACH DELETE` against the live database after every test. All cycle history before June was lost. Cleanup is now scoped.
- **06-21: Optional cloud inference** (53 commits, merged locally in `4317843`). An `InferenceProvider` protocol with Ollama, OpenAI-compatible, and Anthropic adapters, token-bucket rate limiting, a budget meter with a hard spend cap, a pre-run cost estimate, and a Settings UI.
- **06-21 → 06-26: Deep audit** (PR #2). 35 findings (F-01..F-35) plus 3 uncertain ones fixed, each with a regression test. The audit's smoke checklist targets 1,269 backend and 96 frontend tests passing. (A local run on 2026-10-03: 1,327 backend tests passed, plus 1 failure caused only by untracked iCloud duplicate files; 97 frontend tests passed.)
- **06-26 → 08-02:** Ran the full simulation on NVIDIA's free OpenAI-compatible API (llama-3.1-8b worker, llama-3.3-70b orchestrator) by tuning RPM, in-flight, and retry settings. The CLI was fixed to honor the cloud config (342b285).
- **08-01/02: Four Claude Security scans.** Fixes: no default Neo4j password, loopback-only Neo4j, fenced RSS headlines in prompts, WS Origin validation, an Origin guard on state-changing routes, and owner-only key files.
- **10-03:** GSD planning retired. Its knowledge was ported to `docs/`.
- **2026-10: Repository hygiene.** Fictional holdings fixtures, iCloud duplicates removed and ignored, an MIT LICENSE, package metadata, an `alphaswarm` console script with a single version source (0.6.0), README false claims removed, and the working copy moved out of iCloud Drive to `~/dev/AlphaSwarm`.

## Major pivots

| Area | Path |
|---|---|
| UI | Textual TUI (v1) → Vue 3 + D3 force graph (v5) → React port of Claude Design UI (41.1) → AlphaSwarm-2 Quant Terminal (41.6) → TUI deleted (06-11) |
| Models | qwen3.5 32B/7B (Phase 2) → qwen3.5 35B/9B → qwen3:8b + qwen3.6:27b GGUF, think off (05-06) → qwen3.5:35b MoE (briefly) → MLX qwen3.6 35B-A3B + 27B nvfp4 (06-11); optional cloud (06-21) |
| Real data | v3.0 ticker pipeline (erased 04-09) → v6.0 `ingestion/` providers that never raise, plus a Round-1 context block |
| Visualization | Miro board (planned, stubbed) → web force graph → deterministic SVG clusters |
| Swarm | v1 brackets (Quants, Degens, Sovereigns, Macro, Suits, Insiders, Agents, Doom-Posters, Policy Wonks, Whales) → v2 narrative-ecosystem brackets (06-10) |
| Peer influence | Static-authority top-5 → posts ranked by INFLUENCED_BY → per-reader diverse in-memory selection |
| Process | GSD phases, plans, and verifications (03-24 → 06-11) → lighter superpowers spec + plan (06-21) → plain git + `docs/` (10-03) |

## Lessons worth keeping

1. **Check the diffstat of agent and worktree merges before trusting them.** Three commits with innocent messages deleted large amounts of work:
   - `7226d2e` ("feat(24-01)…", 04-09): removed v3.0. −25.6k lines in total: about 4.4k of source and tests, and about 20.6k of planning docs.
   - `f5330a6` ("test(27-01)…", 04-11): removed the HTML export and governor suspend/resume. −18.8k lines: about 4.7k of source and tests, and about 14.0k of planning docs.
   - `343669f` ("test(32-01)…", 04-14): removed Phase 29-31 planning docs for good. It also deleted the Phase 31 Vue frontend, which `02ae850` restored ("restore frontend directory deleted by executor agent scope error").
2. **Never point tests at the live database.** Community Edition has a single DB. Back up first (`scripts/backup_neo4j.sh`).
3. **Silent environment loss looks like a performance bug.** When a simulation is suddenly slow, check the Ollama server env first (RUNBOOK).
4. **Writer and reader schemas drift silently.** Examples: uppercase versus lowercase signals in Cypher; `content` versus `portfolio_outlook`; `text` versus `rationale`. Wire-contract tests (`frontend/src/__tests__/frame.test.ts`) and registry invariants (`tests/test_report.py:28`) are the fix.
5. **Measure before optimizing.** The "serial dispatch" hypothesis was wrong: the TaskGroup fan-out was already correct, and the real cause was Ollama's per-architecture parallel cap plus prefill cost.

## Candidate resume bullets

1. Built **AlphaSwarm**, a local-first multi-agent LLM simulation engine (Python 3.11 asyncio, FastAPI, Neo4j, Ollama/MLX). It runs 100 market personas in 10 archetypes through a multi-round consensus cascade, and influence edges built from agent citations are stored in a cycle-scoped Neo4j graph.
2. Designed a memory-aware concurrency governor (token pool, 5-state machine, macOS kernel-pressure + psutil signals) for a 64 GB M1 Max. Diagnosed an inference stall caused by Ollama's per-architecture parallel cap and KV-cache spill (8-call batch: 45.6 s → 7.5 s). Benchmarked and migrated to MLX MoE models for 5.6× worker and about 30× orchestrator prefill throughput.
3. Built a real-time React/TypeScript + D3 dashboard driven by a 5 Hz WebSocket broadcaster with per-client drop-oldest backpressure. It also supports replay from graph state, multi-turn agent interviews, and a prompt-based ReAct agent that queries Neo4j to write analysis reports.
4. Delivered a privacy-isolated personalized portfolio advisory. Brokerage holdings are kept out of agent prompts, the database, WebSocket frames, and logs by an import-linter contract, a fail-closed PII-redacting log processor, and a four-surface sentinel canary test.
5. Added a pluggable inference layer (Ollama, OpenAI-compatible, Anthropic) with token-bucket rate limiting, pre-run cost estimates, and a hard spend cap, and ran the full simulation on a free cloud API tier.
6. Hardened the codebase: 1,300+ backend tests and 97 frontend wire-contract tests running in GitHub Actions CI, 35 deep-audit findings fixed with regression tests, and 6 security-scan issues remediated (CSRF Origin guard, WebSocket origin checks, prompt-injection fencing, secret handling).
