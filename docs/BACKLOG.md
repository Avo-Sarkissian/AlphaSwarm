# AlphaSwarm Backlog

Open items carried over from the retired `.planning/` system: STATE.md todos and
blockers, unfinished ROADMAP phases, handoff and UAT lists, debug sessions, the
SWEEP-260528 and BUGFIX-CONTEXT reports, and the v6 open-items list. Each item
was checked against the code at commit `820b8fe` on 2026-10-03.

**Status values:**
- **open**: verified still present.
- **likely done**: code shows it was addressed, but no live run confirms it.
- **done**: verified.
- **unknown**: needs a live stack or Neo4j data to tell.
- **won't fix**: not a real problem.

Decision context lives in [DECISIONS.md](DECISIONS.md), and anchors are cited as `D#…`.

---

## 1. Defects confirmed in current code

| # | Item | Status | Evidence | Suggested fix |
|---|---|---|---|---|
| 1.1 | **Report "social post reach" section is always empty for new cycles.** Post nodes are still written. The June 2026 peer-context rewrite removed READ_POST writes on purpose ("~10k edges/round recording 'everyone read everything' carried no analytical value", `simulation.py:1200-1202, 1391`), but the report tool that reads them was left in place | done (2026-10): section removed, see D#adr-report-react | `graph.py` (`read_social_post_reach`) reads `(:Agent)-[:READ_POST]->(:Post)`, and both report paths still register it (`cli.py:645`, `web/routes/report.py:251`). `simulation.py:1090,1246,1445` call `write_posts`, but nothing writes READ_POST: `write_read_post_edges` had no caller and was deleted in 2026-10 (item 2.2) | Write READ_POST from the actual in-memory peer sets (reader → each peer's post) with a new writer, which is more meaningful than the old "all posts", or re-base the tool on CITED counts. Add a regression test. See D#hist-read-post |
| 1.2 | **Shock text has no length cap.** The 4096-char cap from STATE.md is not enforced, and the text is concatenated into every agent's user message | done (2026-10, post-run pipeline work) | `web/routes/simulation.py:40-43` (`shock_text: str`, no `max_length`); `graph.py:1924` says "caller enforces"; `simulation.py:1150,1307` | `Field(..., min_length=1, max_length=4096)`, plus the same fencing used for RSS headlines. D#hist-shock-max-len. Done: ShockText 10-1000 chars, shock window 409, carry-forward. Fencing shock text like RSS headlines is not done |
| 1.3 | **Historical cycles cannot be regenerated or interviewed after a restart.** Report, advisory, and interview all require the in-memory phase to be COMPLETE, and interview always uses the latest cycle (Phase 41.2 D-06, BUGFIX B12) | done (2026-10, post-run pipeline work) | `web/routes/report.py:183-192`; `web/routes/advisory.py:161`; `web/routes/interview.py:67-76,95` | Gate on "cycle exists in Neo4j" (404 `cycle_not_found`) instead of phase. Keep the orchestrator 409 guards. Pass `cycle_id` explicitly to the interview route. The unmerged branch `gsd/phase-41.3-codex-remediation` has a stale take on this. Done: status-based gating, interview cycle_id, replay no longer writes the live phase |
| 1.4 | **Frontend hardcodes three rounds.** This blocks making `ALPHASWARM_NUM_ROUNDS=2` the default | done (Oct 2026: useRounds reads num_rounds from the frame) | `KpiStrip` (`fe/components/panels.jsx`), `ModelStatus` and `AdvisoryV2` (`fe/components/v2.tsx`), `Tooltip` (`fe/components/app_v2.tsx`, "Flipped R1→R{finalRound}") and `SignalTrajectory`/`InterviewV2` (`fe/components/interview_v2.tsx`: trajectory and rationale log; the opening line, `openingLine` in `fe/lib/interview.ts`, gets the frame's `num_rounds`) read `useRounds()`. `ShockDrawer` (`fe/components/modals.jsx`) names the round a shock lands before, or says the window is closed, from the frame's round, `num_rounds` and shock window (`shockTargetRound` in `fe/lib/shock.ts`). `Onboarding` renders above the frame providers, so `App` passes it the frame's `num_rounds` (`fe/App.tsx`). Live and replay frames carry `num_rounds`, read through `useRounds()` (`fe/hooks/useRounds.ts`); `/api/replay/cycles` returns `round_count` (`graph.py`, `read_completed_cycles`) | Read `useRounds()` in those components instead of the literal 3 |
| 1.5 | **`scripts/start_ollama.sh` omits `OLLAMA_USE_MLX=1`**, so the nvfp4 models silently fall back when Ollama is started from a terminal. Its header still says NUM_PARALLEL=16 fits a "9B q4 worker" | done (2026-10): exports OLLAMA_USE_MLX=1 with a corrected header; one shared variable file for both start scripts was left optional (each script stays self-contained) | `scripts/start_ollama.sh:4-9,17-19` vs `scripts/configure_ollama_app_env.sh:24-28` | Export `OLLAMA_USE_MLX=1`, refresh the comment, and source both scripts from one var list |
| 1.6 | **The Neo4j restore command printed by the backup script fails as written.** `neo4j-admin database load` expects `neo4j.dump`, but the backups are renamed `neo4j-<stamp>.dump` | open | `scripts/backup_neo4j.sh` (last line); the README notes the filename rule | Print a restore that copies or symlinks the chosen dump to `neo4j.dump` in a temp dir, or ship `scripts/restore_neo4j.sh` |
| 1.7 | **A unit test writes into the real `advisory/` directory** (`advisory/c1_advisory.json`) | done (2026-10, post-run pipeline work) | `tests/unit/test_task5b_provider_migration.py:413` calls `_run_advisory_synthesis(app_state, "c1", …)`; the route writes to the CWD-relative `ADVISORY_DIR = Path("advisory")` (`web/routes/advisory.py:41,356-357`) with no redirect | `monkeypatch.chdir(tmp_path)` or inject the output dir. Done: test uses tmp settings |
| 1.8 | **CI runs live-network integration tests.** CI's `backend` job runs `-m "not neo4j"`; `tests/integration/` auto-enables sockets and its yfinance/RSS live tests have no skip, so every CI run hits Yahoo and Google News (Phase 41.2 D-08 was never done) | done (2026-10: `live_network`/`ollama` markers skip unless `--run-live`; `.github/workflows/nightly.yml` runs them daily) | `.github/workflows/ci.yml:56` (`uv run pytest -q -rxX -m "not neo4j"`); `tests/integration/conftest.py:13-20`; `pyproject.toml:68-71` registers `enable_socket` and `neo4j`, but no `integration` marker | Register an `integration` marker, default `-m "not integration"`, and run integration tests on demand |
| 1.9 | REFERENCES edges match Entity by name only, despite the `(name, type)` constraint (Phase 41.2 D-SKIP-B). A seed that lists the same entity twice also writes duplicate MENTIONS and REFERENCES edges. Report entity impact has joined through the cycle's own MENTIONS and counted each (entity, decision) pair once since 2026-10, so only the stored edges are wrong (D#p11-d-08) | done (2026-10): typed, cycle-scoped REFERENCES, see D#adr-neo4j-schema | `graph.py:915` `MATCH (e:Entity {name: m.entity_name})`; `_create_cycle_with_entities_tx` CREATEs one MENTIONS per seed entry | Match on name and type, or dedupe at write time |
| 1.10 | `interview_sessions` grows without bound between simulations (BUGFIX B13). It is cleared only on sim start | open (low) | `web/app.py:94`; `web/routes/interview.py:83-91` | Cap with LRU or TTL; `aclose` providers on eviction |
| 1.11 | Report and advisory file writes are not atomic (T-36-16, accepted LOW) | done (2026-10, post-run pipeline work) | `web/routes/report.py:316`; `web/routes/advisory.py:8` | Temp file + `os.replace` (same pattern as F-25). Done: fsutil.atomic_write_text |
| 1.12 | **`data/backups/` is not gitignored.** `scripts/backup_neo4j.sh` writes full Neo4j dumps there, and `git check-ignore data/backups/x.dump` matches nothing, so a `git add -A` after a backup would commit the whole graph | done (2026-10: the root `.gitignore` ignores `/data/`) | `.gitignore` (no `data/backups` entry; only `data/sec_tickers.json`); `scripts/backup_neo4j.sh:23,98` | Add `/data/backups/` to the root `.gitignore` |
| 1.13 | **Health and Settings report `mode=local` for an Ollama orchestrator that the advisory treats as cloud.** `inference_mode()` counts any Ollama provider as local and `OllamaProvider.is_local()` always returns True, so an Ollama cloud model or a non-loopback Ollama host shows as local while the advisory refuses with "cloud or remote orchestrator". Not a holdings leak (the advisory gate is the only path that sends the portfolio and it checks model and host), but the two views disagree. Since 2026-10-22 the Settings footer, Privacy tab and API-keys row derive the mode from the roles with the advisory's off-machine rule, so the UI shows two indicators that can disagree: the topbar chip still reads `inference_mode` from `/api/health` and says Local where Settings says local + cloud | open (low, 2026-10-21; frontend Settings part done 2026-10-22) | `inference/factory.py:inference_mode`; `inference/ollama_provider.py:is_local`; `web/routes/health.py:45`; `web/routes/settings.py:298` vs `inference/factory.py:advisory_block_reason`; frontend: `lib/privacyCopy.ts:privacyFactsFromSettings` (Settings) vs `components/v2.tsx:ModelStatus` (topbar chip) | Make `inference_mode`/`is_local` reuse `is_local_ollama` with the shared client's `base_url`, or show an `ollama-remote`/`ollama-cloud` label, so the UI matches the advisory guard |
| 1.14 | **Peer rationales reach the system role.** In Rounds 2-3 the worker sends the peer context, other agents' free-text rationales copied in raw, as a second system message. That breaks the rule that untrusted text is fenced and never placed in the system role (CLAUDE.md): Round 1 rationales can echo fenced RSS headlines, a newline in a rationale can forge a peer line, and injected text gets system priority across about 99 agents | open (2026-10-22) | `worker.py:177` (`{"role": "system", "content": f"Peer context:\n{peer_context}"}`); `simulation.py:382` (`_format_peer_context` copies `post.content` unsanitized); the own-prior tests in `tests/test_worker.py` and `tests/engine/test_fast_track_rounds.py` count it as the second of two system messages, and `tests/engine/test_scenarios.py` (`_peer_block`) reads each reader's peer block from it | Clean each rationale the way `sanitize_rationale` does, move the peer block into the user message inside a fence, and keep a fixed guard as the second system message, as `MARKET_CONTEXT_GUARD` does for market data (the system-message count stays 2) |
| 1.15 | **A hard-killed run leaves its Cycle `running` forever.** `run_simulation` writes `failed`/`cancelled` from Python, so `kill -9`, an OOM kill or a power loss skips the write. So does an unreachable Neo4j: that write gives up after 5 s rather than hold Stop for the driver's 30 s of retries | open (low, 2026-10-23) | `simulation.py` (`run_simulation` wrapper, `_record_terminal_status`, `_TERMINAL_STATUS_TIMEOUT_S`); `graph.py` (`set_cycle_status`) | Once a single-instance lock exists (nothing enforces one CLI or web process yet), mark `running` cycles that predate the lock holder as `failed` at web startup. Until then they are only excluded from listings and defaults |
| 1.16 | **A Stop or a failure during FINALIZING hides a cycle whose rounds are all persisted.** `complete` is written only after the worker teardown and the metrics write, a window of seconds. A Stop there marks the cycle `cancelled`, and an exception there marks it `failed`. The legacy completeness rule counted such a cycle complete; now it drops out of `/api/replay/cycles`, and the report, advisory and interview routes answer 422 `cycle_not_ready`. The data stays, and `alphaswarm report --cycle <id>` still reads it | open (low, 2026-10-23); narrowed 2026-10 from minutes to seconds: runs make no narrative calls (D#p11-d-11), so only the teardown and the metrics write remain in FINALIZING | `simulation.py` (`run_simulation` wrapper; the `complete` write follows the worker teardown and `write_cycle_metrics`); D#adr-cycle-metrics | Write `complete` once the last round is persisted, and keep a later Stop or failure from overwriting it |

## 2. Cleanup and tech debt

| # | Item | Status | Evidence |
|---|---|---|---|
| 2.1 | Remove the unused `textual` dependency (BUGFIX B20). The TUI was deleted in 76b7537 | done (2026-10: `uv remove textual`) | `pyproject.toml:14`; no `textual` import in `src/` or `tests/` |
| 2.2 | Remove dead code. Peer context: `_dispatch_round` (docstring says "UNUSED IN PRODUCTION"; `tests/test_simulation.py` still exercises it, so those tests go too), `GraphStateManager.read_peer_decisions`, `read_ranked_posts`, and `write_read_post_edges` unless 1.1 revives it. Also: `_push_top_rationales` (its calls were removed in 260512-jqn; only `tests/test_state.py:375` calls it), `OllamaClient.generate()` (no production caller; narratives go through `provider.chat`, `simulation.py:1626`), and the frontend `MemoryPausedState` (exported, never imported) plus the DEV tweak "Demo state → Mem ceiling", which sets a `demoState` nothing reads | done (2026-10): backend dead code removed; frontend `MemoryPausedState` and the Tweaks panel deleted | `simulation.py:741-913`, `simulation.py:317`; `graph.py:585` (`read_ranked_posts`), `graph.py:671` (`write_read_post_edges`), `graph.py:727` (`read_peer_decisions`); `ollama_client.py:132-195`; `fe/components/states.jsx:116`, `fe/components/tweaks.jsx:53-63`, `fe/components/app_v2.tsx:32,271-277` |
| 2.3 | Remove the TUI sentinel `.alphaswarm/last_report.json` writer, which no longer has a reader (Phase 15 D-05) | done (2026-10) | `report.py:346-364` (`write_sentinel`), called from `cli.py:796` and `web/routes/report.py:394`; files exist at `.alphaswarm/last_report.json` and `frontend/.alphaswarm/last_report.json` |
| 2.4 | Remove dead config `OllamaSettings.num_parallel` and `max_loaded_models`, which are never read. `.env.example` sets the misleading `ALPHASWARM_OLLAMA__NUM_PARALLEL=16`. The real knob is the Ollama server env (RUNBOOK) | open | `config.py:40-41`; `.env.example` (Ollama block) |
| 2.5 | Fix stale comments: `simulation.py:1100-1103` (claims R2 uses `read_ranked_posts`); `fe/components/v2.tsx:12-14` and `app_v2.tsx:4` (KR-41.6-08 hardcoded model, now closed); `web/simulation_manager.py:157,212` (cite `simulation.py:1109`, actual ~1507); `web/app.py:219-221` ("Vue SPA", "Vue Router"); `fe/components/v2.tsx:952-965` (25-50 min advisory copy predates MLX, now about 2-5 min); `web/routes/replay.py:26` and `fe/api/replay.ts:11` (claim `round_count` is "always 3", false since 2-round cycles) | partly done (2026-10): fixed are the `simulation.py` comment (it says the in-memory diverse path replaced `read_ranked_posts`, which was deleted in 2026-10), the `web/simulation_manager.py` line citations and the `web/app.py` Vue wording. Open: the `fe/components/v2.tsx` and `app_v2.tsx` model notes, the `v2.tsx` advisory wait copy, and the `round_count` "always 3" comments | as listed |
| 2.6 | Replace `.planning/...` comment links with DECISIONS anchors | done (2026-10-03, GSD retirement) | `seed.py:70`; `simulation.py:1103`; `tests/test_seed_pipeline.py:88`; `modelfiles/Modelfile.orchestrator:17`; `web/routes/holdings.py:28,58` |
| 2.7 | Fold `tests/test_replay_red.py` (a "TDD RED" scaffold that now passes) into the regular replay tests (Phase 41.2 D-07) | done (2026-10: deleted; tests/test_web.py covers its route, model and 503 checks through the routes themselves) | `tests/test_web.py`: `test_replay_routes_registered_in_production_app`, `test_replay_cycles_503`, `test_replay_cycles_lists_completed_cycles` (`CycleItem`, `ReplayCyclesResponse`), `test_replay_start_real_logic` and `test_replay_advance_real_logic` (start and advance responses); the scaffold itself: `git show c670c82:tests/test_replay_red.py` |
| 2.8 | Give the import-linter subprocess test its own `UV_CACHE_DIR` (Phase 41.2 D-09) | open (low) | `tests/invariants/test_importlinter_contract.py:25-27` |
| 2.9 | `scripts/diagnose_sim.py` (April 2026) tallies uppercase `"BUY"/"SELL"/"HOLD"` against lowercase `SignalType` values, so its RESULT line always prints zeros. Fix or delete | done (2026-10): script deleted | `scripts/diagnose_sim.py:192-195`; `types.py:65-70` |
| 2.10 | mypy strict is configured but not gated (about 34 baseline errors), and ruff is not gated. Decide whether to burn down and gate, or relax the config | done (2026-10: ruff check, ruff format at 120 columns, mypy strict and vulture gated in the CI `lint` job; remaining mypy errors exempt through a shrink-only override list, `tests/invariants/test_mypy_overrides.py`) | `pyproject.toml [tool.ruff]`, `[tool.mypy]` and `[[tool.mypy.overrides]]`; `.github/workflows/ci.yml` (`lint` job: ruff check + ruff format --check + mypy + lint-imports + vulture); `tests/invariants/test_ci_workflow.py` |
| 2.11 | Archive or delete the unmerged branch `gsd/phase-41.3-codex-remediation` | done (2026-10-03): tagged `archive/gsd-41.3-codex-remediation`, branch deleted | `git log master..gsd/phase-41.3-codex-remediation` shows 2 commits from 2026-05-06; it touches the deleted `tui.py` |
| 2.12 | Optional: generate REST types from the OpenAPI schema with `openapi-typescript` and add a CI drift check. Deferred 2026-10 as the default option, taken while small decisions were delegated rather than chosen by the owner: the WebSocket frame is already pinned by golden fixtures, and the advisory GET declares `response_model=AdvisoryReport` | open (optional) | hand-written types in `frontend/src/api/*.ts`; `create_app().openapi()` |
| 2.13 | **Route tests that build AppState can blind later `capture_logs` tests.** `create_app_state()` calls `configure_logging()`, which swaps structlog's processor list. Logger proxies cached earlier in the session (`cache_logger_on_first_use=True`; `alphaswarm.simulation`'s is cached during `tests/test_round_abort.py`) keep the old list, so `capture_logs` in a later test no longer sees their events: 3 tests in `tests/test_simulation.py` (`test_run_simulation_skips_context_when_*_missing`) fail when a file sorted between those two builds an app. A `structlog.reset_defaults()` teardown does not help (it swaps the list too). Two files work around it with the same autouse `_keep_logging_config` fixture, which no-ops `alphaswarm.app.configure_logging`. Fix once: keep loggers uncached for the whole test session (`cache_logger_on_first_use=False` in a session fixture), or move that fixture to `tests/conftest.py`, then delete the two copies | open (low, 2026-10-22) | `tests/test_shock_window.py` and `tests/test_settings_update.py` (`_keep_logging_config`); `app.py:create_app_state` (`configure_logging` call); `logging.py` (`cache_logger_on_first_use`); the failing tests without the fixture: `tests/test_simulation.py::test_run_simulation_skips_context_when_{market,news,both}_provider(s)_missing` |
| 2.14 | Upgrade vitest (3.2.x pulls `tinypool` GHSA-5gmw-xhrv-c9v3 and GHSA-85c8-ppgw-ccpr, critical, and `@vitest/mocker` GHSA-82fw-gwwq-j7x9 and GHSA-qxg6-89mg-rqv8, moderate) to clear the dev-only audit findings (needs a major version; npm audit fix --force not applied: it proposes a breaking vitest@2.0.5) | open (low; dev dependencies only, the CI gate is `npm audit --omit=dev --audit-level=high`) | `npm audit` in frontend/ |
| 2.15 | **The offline suite misses its under-10 s target.** It takes about 18 s on the M1 Max without coverage (18.36 s and 18.14 s for 2,323 tests on 2026-10-22, down from about 22 s before the 2026-10 sleep cleanup); the target dates from a suite of about 1,380 tests. No test waits on a real sleep any more: retry, backoff and pacing sleeps are recorded by `instant_sleep`, and engine scenarios fail on wall-clock sleeps. The slowest tests are a subprocess (`test_hermetic_env`, 1.3 s), statistical and hypothesis checks (`test_peer_selection`, 1.1 s and 0.4 s; the `test_pii_redaction` fuzz, 0.3 s) and pytester teardowns (`test_marker_policy`, 4 × 0.24 s); the rest averages about 6 ms per test. Next: measure `pytest-xdist` (`-n auto`) on the offline suite, or profile per-test overhead (autouse fixtures such as `hermetic_env`, app and AppState construction) | open (low) | `uv run pytest -q -m "not neo4j and not live_network and not ollama" -p no:cacheprovider --durations=25` |

## 3. Documentation and presentation (resume-facing)

| # | Item | Status | Evidence |
|---|---|---|---|
| 3.1 | **README is stale in several places:** Textual badge and "legacy TUI" section (`uv run start` now launches the web UI, `pyproject.toml [project.scripts]`); v1 bracket table (Sovereigns, Whales…); "35B orchestrator + 9B workers"; "No cloud. No API keys." (cloud is now optional); claims a prebuilt `dist/` ships (it is gitignored, `frontend/.gitignore:2`); "Post reads" in the pipeline diagram; the v6.0 line lists NewsAPI, SEC EDGAR, Polygon, and Reddit (only yfinance and RSS exist in `ingestion/`); v3.0 missing from "What's Shipped"; `report <cycle_id>` should be `report --cycle <cycle_id>` (`cli.py:847-850`) | done (2026-10: false claims removed; a full README rewrite is still open) | `README.md:11,13,46,53,69,96-131,142,157,173,190,290-294,301,384` |
| 3.2 | **Screenshots predate the current UI.** They are from 2026-04-22 (Phase 41.1 port); the Quant Terminal UI landed 2026-05-10 | open (2026-10: removed from the README until real captures exist) | `git log -- docs/screenshots` → 36fc125, 438ee1d |
| 3.3 | AGENTS.md is a stale near-copy of CLAUDE.md (Vue 3, no swarm composition, GSD block) | done (2026-10-03): AGENTS.md is now a symlink to CLAUDE.md | — |
| 3.4 | `PROJECT_SPEC.md` (2026-03 v0 spec: Textual, Miro, Llama 4, v1 brackets) is misleading as a current spec. Archive it; HISTORY.md keeps the origin story | done (2026-10: moved to `docs/history/original-spec.md`) | `PROJECT_SPEC.md:9-35` |

## 4. Experiments and research (not started unless noted)

From SWEEP-260528 §2-4 and the June 2026 open-items list. Every experiment
needs fresh cycles, because history before June 2026 was wiped
(D#adr-tests-scoped-cleanup). Use `scripts/benchmark_seeds.json` together with
`scripts/compare_cycles.py`.

| # | Experiment | Status | Evidence |
|---|---|---|---|
| 4.1 | A/B test 2 vs 3 rounds on the four benchmark seeds (wall time, flips, final distribution) | unknown (needs Neo4j data) | `config.py:440`; `scripts/compare_cycles.py` |
| 4.2 | Validate v2 personas on Round 1: brackets should disagree, intra-bracket variance should exceed one signal, HOLD share should be under 70% | unknown | no recorded result |
| 4.3 | A/B test dropping modifier generation (one orchestrator call; suspected below the noise floor) | open | `seed.py:95-108` still generates modifiers |
| 4.4 | Lazy, on-demand decision narratives instead of 100 eager worker calls after the last round | done (2026-10): lazy narratives, see D#p11-d-11 | `simulation.py:892,1430` (`generate_narratives=True`) |
| 4.5 | Feed dissent (Round 1 vs final flips, key dissenters) into the advisory prompt | open | no `flip` or `dissent` references in `advisory/` |
| 4.6 | Labeled historical-outcome eval set, plus a single-orchestrator-call baseline ("is the swarm better than one prompt?") | open | `benchmark_seeds.json` has qualitative `expectation` only |
| 4.7 | Advisory progress endpoint (queued → loading → synthesizing → ready) instead of polling 404s | open | `web/routes/advisory.py` GET returns 404 until the file exists |
| 4.8 | Streaming per-round advisory ("headline shift after R2") | open (exploratory) | SWEEP-260528 §4.4 |
| 4.9 | Trim persona system prompts. Prefill dominates cost, at about 2.5k tokens per agent | open | `config.py` bracket templates; D#adr-model-stack |
| 4.10 | Evaluate the Gemma 4 26B MoE worker as an alternative | open | D#adr-model-stack |
| 4.11 | Profile the replay `read_full_cycle_signals` query (STATE.md blocker). Low risk at 100 agents | unknown | `graph.py:2032` |
| 4.12 | Per-agent peer reach below the top two brackets. At the default knobs (10 peers, cap 3), a full feed already spans at least 4 brackets, so the `min_brackets` floor adds no diversity there. It only lifts small brackets per agent: Allocators (weight 0.60) are seen by 11.6 readers per agent against 9.4 for Institutions (0.65). Offline with `min_brackets=0`, every feed still spanned at least 4 brackets, and per-agent reach followed weight more closely (Sell-Side 12.5, Narrators 11.9, the 0.60-0.65 brackets 10.2-10.4, Algos 7.9). The invariant still held (worst max share 21.3%, worst min readers 29%). Owner decision: keep the floor as it is, or move the default to 0 through an ablation (plan 21) | open | D#adr-diverse-peer-context (Rationale, per-agent reach); `tests/test_peer_selection.py::test_highest_reach_brackets_are_seen_most_per_agent`; 200 R2 run seeds on `generate_personas(DEFAULT_BRACKETS)` |

## 5. Feature gaps tracked as KRs

These are accepted gaps; see DECISIONS §4 for evidence. Open ones that would
improve the product:
- Per-agent `flipped` and `roundLastSpoke` on the wire (KR-41.1-03).
- Rationale citations on the wire (KR-41.1-10).
- Streaming interviews (KR-41.1-11).
- Replay rewind (KR-41.1-06).
- AdvisoryV2 shares, basis, last price, sentiment (KR-41.6-01), and the Risk tab (KR-41.6-05).
- Runtime governor and agent-count settings (KR-41.6-06).
- Overflow-menu placeholders "Coming in v6.x": What-if Compare, Multi-seed Synthesis, Portfolio Stress Test, Customize Brackets (KR-41.6-02).

## 6. Roadmap phases left open in `.planning/ROADMAP.md`

| Phase | Planned | Status | Evidence |
|---|---|---|---|
| 41.1-05 | Update the CLAUDE.md stack line to React and run the 28-row parity UAT | done / superseded | CLAUDE.md says React. Parity was superseded by the 41.6 UI replacement |
| 41.2-01 | Cypher signal/round case normalization | done, re-implemented on master | The original 41.2-01 commits sit on the unmerged branch `worktree-agent-a886d1bc`. Master got the fix in e6f8722 (06-11) and F-01..F-03 (6ced8a8) |
| 41.2-02 | ReAct tool-name unification | done, re-implemented | Original commits on the unmerged `worktree-agent-af07b727` renamed the registry. Master's F-06 (90dd0f9) went the other way and renamed the prompt. Invariant at `tests/test_report.py:28` |
| 41.2-03 | `generate(system=)` | done, since superseded: narratives now go through `provider.chat` (`simulation.py:1626`), and `OllamaClient.generate()` was deleted in 2026-10 (item 2.2) | `OllamaClient.generate()` and its tests were deleted (item 2.2) |
| 41.2-04 | Real ReportModal, advisory `items[]`, historical-cycle regeneration with per-cycle lock, polling timeout | partial: modals done (ReportModal.tsx, AdvisoryV2) and timeout done (`usePolling.ts:83`). Historical regeneration done 2026-10 (item 1.3) | — |
| 41.2-05 | Delete red tests, opt-in integration marker, `UV_CACHE_DIR`, ReAct JSON hardening, model-tag reconciliation | partial: ReAct hardening re-done in 3110d11 (`report.py:195-197`) and models reconciled (`config.py:37-38`). Open: item 2.8 (1.8 and 2.7 done 2026-10). The original commits sit on the unmerged `worktree-agent-aa61fcfe` and `worktree-agent-a013a1a5` | — |
| 41.5 | Advisory hero, KPI strip, per-holding table | done (absorbed by 41.6 AdvisoryV2) | `fe/components/v2.tsx` (`AdvisoryV2`) |
| 41.6 | Quant Terminal port | code done. **Formal UAT never signed off** (6 HUMAN-UAT items pending; 31 parity rows unsigned) | see section 7 |
| 999.1 | Auto-trigger advisory on completion | done; the in-process trigger was replaced by PostRunPipeline (2026-10) | `web/post_run.py`; `web/app.py:WebPostRunJobs` |
| 999.3 | Live memory telemetry | done | `web/broadcaster.py` (`_host_memory_percent`); `web/wire.py` (`_governor`) |
| 41.3 (branch only) | Codex remediation | superseded, never merged | item 2.11 |

## 7. UAT that was never signed off (needs one live run)

The 41.6 HUMAN-UAT list, the 41.1 parity row 26, and the 2026-05-12 handoff
watch-list, merged. Run them with the smoke checklist in RUNBOOK.md and
tick them off there.

| Check | Code evidence | Status |
|---|---|---|
| Agent dots fill in progressively during a round and do not vanish at round entry | `state.py` (`StateStore.begin_run`, `set_phase`); `batch_dispatcher.py` (`_safe_agent_inference`) | likely done |
| Rationale feed updates live mid-round; R3 rationales stay after completion | `state.py` `_rationale_window`; `web/wire.py` (`build_frame`) | likely done |
| PARALLEL SLOTS shows live numbers | `fe/adapter/frame.ts:111-120` | likely done |
| Signal Wire shows real provider calls, not the mock seed | `data_audit.py`; `fe/hooks/useDataSourceAudit.ts`; `fe/lib/dataSources.ts` | likely done (no mock fallback since 2026-10: an empty audit says so) |
| From round 2 on, Top Influencers ranks by CITED BY (citations received) for the round on screen, and the top strip shows "N active edges" | `fe/lib/influence.ts`; `fe/hooks/useCycleEdges.ts`; `fe/components/app_v2.tsx` (Top Influencers panel) | likely done |
| Advisory auto-fires, one item per holding, Overview tiles show real values; report auto-generates afterwards | `web/app.py:118`; `advisory/engine.py:148-260`; `web/routes/advisory.py:288` | likely done |
| InterviewV2 returns real `/api/interview` answers (no PERSONA filler) | `fe/components/interview_v2.tsx` | likely done |
| Onboarding lists each required component that is down with its fix, offers Re-check and Skip to dashboard, and enables Run only when /api/health is ok | `fe/components/onboarding.tsx` (`ObSeedStep`); `fe/lib/health.ts` | likely done |
| AdvisoryV2 four tabs render against a completed cycle; stubs show "—" | `fe/components/v2.tsx` (`AdvisoryV2`) | unknown |
| BracketDeepDive shows members live, and influence counts for the round on screen from round 2's edges on ("—" before them) | `fe/components/bracket_deep.tsx`; `fe/hooks/useCycleEdges.ts` | unknown |
| Memory-paused overlay via a DEV tweak (41.1 row 26) | The full-screen `MemoryPausedState` and the "Demo state → Mem ceiling" tweak were deleted (2026-10, item 2.2). Live governor PAUSED/CRISIS shows a dismissible banner instead (`app_v2.tsx:255-263, 477-503`) | superseded: retire the row |
| CycleHistory, Settings, and Report modals render as styled takeovers | `fe/styles.css` (ch-/st- blocks) | likely done |

## 8. Closed by later work (kept for traceability)

- **Fake UI removed (2026-10).** KR-41.1-02, KR-41.1-07, KR-41.1-08, KR-41.6-07 and KR-41.6-11 closed; KR-41.6-14 obsolete; cycle history pages past the newest ten cycles. See DECISIONS §4.

- **Debug `parallel-swarm-serial-dispatch` (2026-05-07): done.**
  - Dispatch was never serial.
  - 0 edges: peer IDs are now in the prompt and agents are told to cite them (`simulation.py:388-400`).
  - Empty feed: the adapter reads `rationale` and `round_num` (`fe/adapter/frame.ts:195-196`).
  - Slowness: addressed by the MLX stack.
- **Debug `ws-agent-states-not-emitted-mid-sim` (2026-05-10): likely done.** The status was "awaiting_human_verify", but the fix is in code (see section 7).
- **SWEEP-260528:**
  - B-1..B-4: test debt cleared. The format-peer-context tests now assert `[agent_00|quants]` (`tests/test_simulation.py:751`), and Neo4j tests skip cleanly (`tests/conftest.py:158-179`).
  - B-5: done.
  - B-6: done (diverse peers wired).
  - B-7, B-8: done.
  - C-1: done (AdvisoryV2 "Generating advisory…" state, `v2.tsx:596-608`).
  - C-2: done (BracketList empty state, `panels.jsx:9-15`).
  - C-4: done (`.gitignore` covers `/advisory/`, `/reports/`, `/typings/`).
  - Composition rebalance: done (v2).
- **BUGFIX-CONTEXT:**
  - B1, B4, B7-B10: done.
  - B2: macOS duplicates. **Done (2026-10):** the copies were deleted (archived outside the repo), `* [2-9].*` and `* [2-9]` are gitignored, pytest runs with `--ignore-glob='* [2-9].py'`, and the import-linter coverage test skips names that are not identifiers. The repo moved out of iCloud Drive to `~/dev/AlphaSwarm` (2026-10), which removes the root cause. Original note: 32 untracked `* 2.py`, `* 3.py`, and similar copies exist now. The ones under `src/alphaswarm/` make `tests/invariants/test_importlinter_coverage.py::test_source_modules_covers_every_actual_package` fail: it enumerates them as packages (`alphaswarm.app 2`, …) missing from `source_modules` (1 failed / 1327 passed in a 2026-10-03 run). CI is unaffected because they are untracked. Root-cause the iCloud sync, then delete them, and add `* [0-9].*` to the root `.gitignore`. Only `frontend/.gitignore` has `* 2.*`.
  - B3: done (bracket comes from the agent ID, `bracketOf` in `fe/data.ts`).
  - B5, B6, B11: moot (Vue removed).
  - B12: done (2026-10), as item 1.3.
  - B13: open, as item 1.10.
  - B14, B15: done.
  - B16, B17: done (gitignored).
  - B18: done (Aug security).
  - B19: **won't fix.** On a single-threaded event loop, nothing can await between `get_nowait()` and `put_nowait()`, so `QueueFull` cannot happen (`web/connection_manager.py:80-92`).
  - B20: open, as item 2.1.
- **STATE.md "Pending Todos: None".** The handoff "Open tasks (none)" is accurate for its date.
