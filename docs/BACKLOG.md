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
| 1.1 | **Report "social post reach" section is always empty for new cycles.** Post nodes are still written. The June 2026 peer-context rewrite removed READ_POST writes on purpose ("~10k edges/round recording 'everyone read everything' carried no analytical value", `simulation.py:1163-1165, 1321`), but the report tool that reads them was left in place | open | `graph.py:1573-1610` reads `(:Agent)-[:READ_POST]->(:Post)`, and both report paths still register it (`cli.py:767`, `web/routes/report.py:363`). `simulation.py:1091,1213,1364` call `write_posts`, but nothing calls `write_read_post_edges` (`graph.py:671`) | Write READ_POST from the actual in-memory peer sets (reader → each peer's post), which is more meaningful than the old "all posts", or re-base the tool on CITED counts. Add a regression test. See D#hist-read-post |
| 1.2 | **Shock text has no length cap.** The 4096-char cap from STATE.md is not enforced, and the text is concatenated into every agent's user message | open | `web/routes/simulation.py:40-43` (`shock_text: str`, no `max_length`); `graph.py:1924` says "caller enforces"; `simulation.py:1150,1307` | `Field(..., min_length=1, max_length=4096)`, plus the same fencing used for RSS headlines. D#hist-shock-max-len |
| 1.3 | **Historical cycles cannot be regenerated or interviewed after a restart.** Report, advisory, and interview all require the in-memory phase to be COMPLETE, and interview always uses the latest cycle (Phase 41.2 D-06, BUGFIX B12) | open | `web/routes/report.py:183-192`; `web/routes/advisory.py:161`; `web/routes/interview.py:67-76,95` | Gate on "cycle exists in Neo4j" (404 `cycle_not_found`) instead of phase. Keep the orchestrator 409 guards. Pass `cycle_id` explicitly to the interview route. The unmerged branch `gsd/phase-41.3-codex-remediation` has a stale take on this |
| 1.4 | **Frontend hardcodes three rounds.** This blocks making `ALPHASWARM_NUM_ROUNDS=2` the default | open | `fe/components/app_v2.tsx:372`, `fe/components/panels.jsx:121`, `fe/components/v2.tsx:369`, `fe/components/modals.jsx:196`. `round_count` is available from `/api/replay/cycles` (`graph.py:2091`) but not on the live frame | Add `num_rounds` to StateSnapshot and read it in the adapter |
| 1.5 | **`scripts/start_ollama.sh` omits `OLLAMA_USE_MLX=1`**, so the nvfp4 models silently fall back when Ollama is started from a terminal. Its header still says NUM_PARALLEL=16 fits a "9B q4 worker" | open | `scripts/start_ollama.sh:4-9,17-19` vs `scripts/configure_ollama_app_env.sh:24-28` | Export `OLLAMA_USE_MLX=1`, refresh the comment, and source both scripts from one var list |
| 1.6 | **The Neo4j restore command printed by the backup script fails as written.** `neo4j-admin database load` expects `neo4j.dump`, but the backups are renamed `neo4j-<stamp>.dump` | open | `scripts/backup_neo4j.sh` (last line); the README notes the filename rule | Print a restore that copies or symlinks the chosen dump to `neo4j.dump` in a temp dir, or ship `scripts/restore_neo4j.sh` |
| 1.7 | **A unit test writes into the real `advisory/` directory** (`advisory/c1_advisory.json`) | open (confirmed: the file's mtime was refreshed to 2026-10-03 15:05 by a `pytest` run during this audit) | `tests/unit/test_task5b_provider_migration.py:414` calls `_run_advisory_synthesis(app_state, "c1", …)`; the route writes to the CWD-relative `ADVISORY_DIR = Path("advisory")` (`web/routes/advisory.py:41,356-357`) with no redirect | `monkeypatch.chdir(tmp_path)` or inject the output dir |
| 1.8 | **CI runs live-network integration tests.** CI ignores only `test_graph_integration.py` and `test_integration_inference.py`; `tests/integration/` auto-enables sockets and its yfinance/RSS live tests have no skip, so every CI run hits Yahoo and Google News (Phase 41.2 D-08 was never done) | open | `.github/workflows/ci.yml:28` (`uv run pytest -q --ignore=… --ignore=…`); `tests/integration/conftest.py:13-20`; `pyproject.toml:55-56` registers only `enable_socket` | Register an `integration` marker, default `-m "not integration"`, and run integration tests on demand |
| 1.9 | REFERENCES edges match Entity by name only, despite the `(name, type)` constraint (Phase 41.2 D-SKIP-B) | open (low) | `graph.py:912` `MATCH (e:Entity {name: m.entity_name})` | Match on name and type, or dedupe at write time |
| 1.10 | `interview_sessions` grows without bound between simulations (BUGFIX B13). It is cleared only on sim start | open (low) | `web/app.py:94`; `web/routes/interview.py:79-87` | Cap with LRU or TTL; `aclose` providers on eviction |
| 1.11 | Report and advisory file writes are not atomic (T-36-16, accepted LOW) | open (low) | `web/routes/report.py:316`; `web/routes/advisory.py:8` | Temp file + `os.replace` (same pattern as F-25) |
| 1.12 | **`data/backups/` is not gitignored.** `scripts/backup_neo4j.sh` writes full Neo4j dumps there, and `git check-ignore data/backups/x.dump` matches nothing, so a `git add -A` after a backup would commit the whole graph | done (2026-10: the root `.gitignore` ignores `/data/`) | `.gitignore` (no `data/backups` entry; only `data/sec_tickers.json`); `scripts/backup_neo4j.sh:23,98` | Add `/data/backups/` to the root `.gitignore` |

## 2. Cleanup and tech debt

| # | Item | Status | Evidence |
|---|---|---|---|
| 2.1 | Remove the unused `textual` dependency (BUGFIX B20). The TUI was deleted in 76b7537 | done (2026-10: `uv remove textual`) | `pyproject.toml:14`; no `textual` import in `src/` or `tests/` |
| 2.2 | Remove dead code. Peer context: `_dispatch_round` (docstring says "UNUSED IN PRODUCTION"; `tests/test_simulation.py` still exercises it, so those tests go too), `GraphStateManager.read_peer_decisions`, `read_ranked_posts`, and `write_read_post_edges` unless 1.1 revives it. Also: `_push_top_rationales` (its calls were removed in 260512-jqn; only `tests/test_state.py:375` calls it), `OllamaClient.generate()` (no production caller; narratives go through `provider.chat`, `simulation.py:1626`), and the frontend `MemoryPausedState` (exported, never imported) plus the DEV tweak "Demo state → Mem ceiling", which sets a `demoState` nothing reads | open | `simulation.py:741-913`, `simulation.py:317`; `graph.py:585` (`read_ranked_posts`), `graph.py:671` (`write_read_post_edges`), `graph.py:727` (`read_peer_decisions`); `ollama_client.py:132-195`; `fe/components/states.jsx:136`, `fe/components/tweaks.jsx:53-63`, `fe/components/app_v2.tsx:31,255-258` |
| 2.3 | Remove the TUI sentinel `.alphaswarm/last_report.json` writer, which no longer has a reader (Phase 15 D-05) | open | `report.py:346-364` (`write_sentinel`), called from `cli.py:796` and `web/routes/report.py:394`; files exist at `.alphaswarm/last_report.json` and `frontend/.alphaswarm/last_report.json` |
| 2.4 | Remove dead config `OllamaSettings.num_parallel` and `max_loaded_models`, which are never read. `.env.example` sets the misleading `ALPHASWARM_OLLAMA__NUM_PARALLEL=16`. The real knob is the Ollama server env (RUNBOOK) | open | `config.py:40-41`; `.env.example` (Ollama block) |
| 2.5 | Fix stale comments: `simulation.py:1100-1103` (claims R2 uses `read_ranked_posts`); `fe/components/v2.tsx:14-16` and `app_v2.tsx:4` (KR-41.6-08 hardcoded model, now closed); `web/simulation_manager.py:157,212` (cite `simulation.py:1109`, actual ~1507); `web/app.py:219-221` ("Vue SPA", "Vue Router"); `fe/components/v2.tsx:941-954` (25-50 min advisory copy predates MLX, now about 2-5 min); `web/routes/replay.py:26` and `fe/api/replay.ts:11` (claim `round_count` is "always 3", false since 2-round cycles) | open | as listed |
| 2.6 | Replace `.planning/...` comment links with DECISIONS anchors | done (2026-10-03, GSD retirement) | `seed.py:70`; `simulation.py:1103`; `tests/test_seed_pipeline.py:93`; `modelfiles/Modelfile.orchestrator:17`; `web/routes/holdings.py:28,58` |
| 2.7 | Fold `tests/test_replay_red.py` (a "TDD RED" scaffold that now passes) into the regular replay tests (Phase 41.2 D-07) | open (low) | `tests/test_replay_red.py:1-12` |
| 2.8 | Give the import-linter subprocess test its own `UV_CACHE_DIR` (Phase 41.2 D-09) | open (low) | `tests/invariants/test_importlinter_contract.py:27-30` |
| 2.9 | `scripts/diagnose_sim.py` (April 2026) tallies uppercase `"BUY"/"SELL"/"HOLD"` against lowercase `SignalType` values, so its RESULT line always prints zeros. Fix or delete | open | `scripts/diagnose_sim.py:192-195`; `types.py:65-70` |
| 2.10 | mypy strict is configured but not gated (about 34 baseline errors), and ruff is not gated. Decide whether to burn down and gate, or relax the config | open | `pyproject.toml [tool.mypy]`; `.github/workflows/ci.yml` (pytest + frontend only) |
| 2.11 | Archive or delete the unmerged branch `gsd/phase-41.3-codex-remediation` | done (2026-10-03): tagged `archive/gsd-41.3-codex-remediation`, branch deleted | `git log master..gsd/phase-41.3-codex-remediation` shows 2 commits from 2026-05-06; it touches the deleted `tui.py` |

## 3. Documentation and presentation (resume-facing)

| # | Item | Status | Evidence |
|---|---|---|---|
| 3.1 | **README is stale in several places:** Textual badge and "legacy TUI" section (`uv run start` now launches the web UI, `pyproject.toml [project.scripts]`); v1 bracket table (Sovereigns, Whales…); "35B orchestrator + 9B workers"; "No cloud. No API keys." (cloud is now optional); claims a prebuilt `dist/` ships (it is gitignored, `frontend/.gitignore:2`); "Post reads" in the pipeline diagram; the v6.0 line lists NewsAPI, SEC EDGAR, Polygon, and Reddit (only yfinance and RSS exist in `ingestion/`); v3.0 missing from "What's Shipped"; `report <cycle_id>` should be `report --cycle <cycle_id>` (`cli.py:847-850`) | open | `README.md:11,13,46,53,69,96-131,142,157,173,190,290-294,301,384` |
| 3.2 | **Screenshots predate the current UI.** They are from 2026-04-22 (Phase 41.1 port); the Quant Terminal UI landed 2026-05-10 | open | `git log -- docs/screenshots` → 36fc125, 438ee1d |
| 3.3 | AGENTS.md is a stale near-copy of CLAUDE.md (Vue 3, no swarm composition, GSD block) | done (2026-10-03): AGENTS.md is now a symlink to CLAUDE.md | — |
| 3.4 | `PROJECT_SPEC.md` (2026-03 v0 spec: Textual, Miro, Llama 4, v1 brackets) is misleading as a current spec. Archive it; HISTORY.md keeps the origin story | done (2026-10: moved to `docs/history/original-spec.md`) | `PROJECT_SPEC.md:9-35` |

## 4. Experiments and research (not started unless noted)

From SWEEP-260528 §2-4 and the June 2026 open-items list. Every experiment
needs fresh cycles, because history before June 2026 was wiped
(D#adr-tests-scoped-cleanup). Use `scripts/benchmark_seeds.json` together with
`scripts/compare_cycles.py`.

| # | Experiment | Status | Evidence |
|---|---|---|---|
| 4.1 | A/B test 2 vs 3 rounds on the four benchmark seeds (wall time, flips, final distribution) | unknown (needs Neo4j data) | `config.py:446`; `scripts/compare_cycles.py` |
| 4.2 | Validate v2 personas on Round 1: brackets should disagree, intra-bracket variance should exceed one signal, HOLD share should be under 70% | unknown | no recorded result |
| 4.3 | A/B test dropping modifier generation (one orchestrator call; suspected below the noise floor) | open | `seed.py:97-110` still generates modifiers |
| 4.4 | Lazy, on-demand decision narratives instead of 100 eager worker calls after the last round | open | `simulation.py:926,1444` (`generate_narratives=True`) |
| 4.5 | Feed dissent (Round 1 vs final flips, key dissenters) into the advisory prompt | open | no `flip` or `dissent` references in `advisory/` |
| 4.6 | Labeled historical-outcome eval set, plus a single-orchestrator-call baseline ("is the swarm better than one prompt?") | open | `benchmark_seeds.json` has qualitative `expectation` only |
| 4.7 | Advisory progress endpoint (queued → loading → synthesizing → ready) instead of polling 404s | open | `web/routes/advisory.py` GET returns 404 until the file exists |
| 4.8 | Streaming per-round advisory ("headline shift after R2") | open (exploratory) | SWEEP-260528 §4.4 |
| 4.9 | Trim persona system prompts. Prefill dominates cost, at about 2.5k tokens per agent | open | `config.py` bracket templates; D#adr-model-stack |
| 4.10 | Evaluate the Gemma 4 26B MoE worker as an alternative | open | D#adr-model-stack |
| 4.11 | Profile the replay `read_full_cycle_signals` query (STATE.md blocker). Low risk at 100 agents | unknown | `graph.py:1988` |

## 5. Feature gaps tracked as KRs

These are accepted gaps; see DECISIONS §4 for evidence. Open ones that would
improve the product:
- Per-agent `flipped` and `roundLastSpoke` on the wire (KR-41.1-03).
- Cycle-list metrics: the data already exists on the Cycle node (KR-41.1-07).
- Rationale citations on the wire (KR-41.1-10).
- Streaming interviews (KR-41.1-11).
- Replay rewind (KR-41.1-06).
- Structured error stream (KR-41.1-08).
- AdvisoryV2 shares, basis, last price, sentiment (KR-41.6-01), and the Risk tab (KR-41.6-05).
- Cycle compare (KR-41.6-07).
- Runtime governor and agent-count settings (KR-41.6-06).
- Live Data Sources view (KR-41.1-02).
- Overflow-menu placeholders "Coming in v6.x": What-if Compare, Multi-seed Synthesis, Portfolio Stress Test, Customize Brackets (KR-41.6-02).

## 6. Roadmap phases left open in `.planning/ROADMAP.md`

| Phase | Planned | Status | Evidence |
|---|---|---|---|
| 41.1-05 | Update the CLAUDE.md stack line to React and run the 28-row parity UAT | done / superseded | CLAUDE.md says React. Parity was superseded by the 41.6 UI replacement |
| 41.2-01 | Cypher signal/round case normalization | done, re-implemented on master | The original 41.2-01 commits sit on the unmerged branch `worktree-agent-a886d1bc`. Master got the fix in e6f8722 (06-11) and F-01..F-03 (6ced8a8) |
| 41.2-02 | ReAct tool-name unification | done, re-implemented | Original commits on the unmerged `worktree-agent-af07b727` renamed the registry. Master's F-06 (90dd0f9) went the other way and renamed the prompt. Invariant at `tests/test_report.py:28` |
| 41.2-03 | `generate(system=)` | done, since superseded: narratives now go through `provider.chat` (`simulation.py:1626`), so `OllamaClient.generate()` has no production caller (item 2.2) | `ollama_client.py:149`; tests in `tests/test_ollama_client.py:139` |
| 41.2-04 | Real ReportModal, advisory `items[]`, historical-cycle regeneration with per-cycle lock, polling timeout | partial: modals done (ReportModal.tsx, AdvisoryV2) and timeout done (`usePolling.ts:92`). **Historical regeneration is open** (item 1.3) | — |
| 41.2-05 | Delete red tests, opt-in integration marker, `UV_CACHE_DIR`, ReAct JSON hardening, model-tag reconciliation | partial: ReAct hardening re-done in 3110d11 (`report.py:195-197`) and models reconciled (`config.py:37-38`). Open: items 1.8, 2.7, 2.8. The original commits sit on the unmerged `worktree-agent-aa61fcfe` and `worktree-agent-a013a1a5` | — |
| 41.5 | Advisory hero, KPI strip, per-holding table | done (absorbed by 41.6 AdvisoryV2) | `fe/components/v2.tsx:743+` |
| 41.6 | Quant Terminal port | code done. **Formal UAT never signed off** (6 HUMAN-UAT items pending; 31 parity rows unsigned) | see section 7 |
| 999.1 | Auto-trigger advisory on completion | done | `web/app.py:118`; `web/simulation_manager.py:24` |
| 999.3 | Live memory telemetry | done | `web/broadcaster.py:47-90` |
| 41.3 (branch only) | Codex remediation | superseded, never merged | item 2.11 |

## 7. UAT that was never signed off (needs one live run)

The 41.6 HUMAN-UAT list, the 41.1 parity row 26, and the 2026-05-12 handoff
watch-list, merged. Run them with the smoke checklist in RUNBOOK.md and
tick them off there.

| Check | Code evidence | Status |
|---|---|---|
| Agent dots fill in progressively during a round and do not vanish at round entry | `state.py:143-185`; `batch_dispatcher.py:105-126` | likely done |
| Rationale feed updates live mid-round; R3 rationales stay after completion | `state.py` `_rationale_window`; `broadcaster.py:95` | likely done |
| PARALLEL SLOTS shows live numbers | `fe/adapter/frame.ts:69-78` | likely done |
| Signal Wire shows real provider calls, not the mock seed | `data_audit.py`; `fe/hooks/useDataSourceAudit.ts` | likely done (falls back to the DEV mock when empty) |
| After completion, Top Influencers switches to OUT-DEGREE and the top strip shows "N active edges" | `simulation.py:1396-1416` (R3 edges); `fe/components/app_v2.tsx:316-329` | likely done |
| Advisory auto-fires, one item per holding, Overview tiles show real values; report auto-generates afterwards | `web/app.py:118`; `advisory/engine.py:148-260`; `web/routes/advisory.py:288` | likely done |
| InterviewV2 returns real `/api/interview` answers (no PERSONA filler) | `fe/components/interview_v2.tsx` | likely done |
| Onboarding disables the run button when the backend is down | `fe/components/onboarding.tsx:256-264` (`disabled` when `backendOk !== true`; label "Start backend first") | likely done |
| AdvisoryV2 four tabs render against a completed cycle; stubs show "—" | `fe/components/v2.tsx:743-1210` | unknown |
| BracketDeepDive shows members live and influences after completion | `fe/components/bracket_deep.tsx` | unknown |
| Memory-paused overlay via a DEV tweak (41.1 row 26) | The full-screen `MemoryPausedState` (`fe/components/states.jsx:136`) is never imported, and the tweak "Demo state → Mem ceiling" (`tweaks.jsx:59`) sets a `demoState` nothing reads. Live governor PAUSED/CRISIS shows a dismissible banner instead (`app_v2.tsx:238-246, 552-554`) | superseded: retire the row and delete the dead code (item 2.2) |
| CycleHistory, Settings, and Report modals render as styled takeovers | `fe/styles.css` (ch-/st- blocks) | likely done |

## 8. Closed by later work (kept for traceability)

- **Debug `parallel-swarm-serial-dispatch` (2026-05-07): done.**
  - Dispatch was never serial.
  - 0 edges: peer IDs are now in the prompt and agents are told to cite them (`simulation.py:388-400`).
  - Empty feed: the adapter reads `rationale` and `round_num` (`fe/adapter/frame.ts:160-161`).
  - Slowness: addressed by the MLX stack.
- **Debug `ws-agent-states-not-emitted-mid-sim` (2026-05-10): likely done.** The status was "awaiting_human_verify", but the fix is in code (see section 7).
- **SWEEP-260528:**
  - B-1..B-4: test debt cleared. The format-peer-context tests now assert `[agent_00|quants]` (`tests/test_simulation.py:751`), and Neo4j tests skip cleanly (`tests/conftest.py:158-179`).
  - B-5: done.
  - B-6: done (diverse peers wired).
  - B-7, B-8: done.
  - C-1: done (AdvisoryV2 "Generating advisory…" state, `v2.tsx:935-946`).
  - C-2: done (BracketList empty state, `panels.jsx:6-12`).
  - C-4: done (`.gitignore` covers `/advisory/`, `/reports/`, `/typings/`).
  - Composition rebalance: done (v2).
- **BUGFIX-CONTEXT:**
  - B1, B4, B7-B10: done.
  - B2: macOS duplicates. **Done (2026-10):** the copies were deleted (archived outside the repo), `* [2-9].*` and `* [2-9]` are gitignored, pytest runs with `--ignore-glob='* [2-9].py'`, and the import-linter coverage test skips names that are not identifiers. Original note: 32 untracked `* 2.py`, `* 3.py`, and similar copies exist now. The ones under `src/alphaswarm/` make `tests/invariants/test_importlinter_coverage.py::test_source_modules_covers_every_actual_package` fail: it enumerates them as packages (`alphaswarm.app 2`, …) missing from `source_modules` (1 failed / 1327 passed in a 2026-10-03 run). CI is unaffected because they are untracked. Root-cause the iCloud sync, then delete them, and add `* [0-9].*` to the root `.gitignore`. Only `frontend/.gitignore` has `* 2.*`.
  - B3: done (bracket comes from the agent ID, `fe/adapter/agentId.ts`).
  - B5, B6, B11: moot (Vue removed).
  - B12: open, as item 1.3.
  - B13: open, as item 1.10.
  - B14, B15: done.
  - B16, B17: done (gitignored).
  - B18: done (Aug security).
  - B19: **won't fix.** On a single-threaded event loop, nothing can await between `get_nowait()` and `put_nowait()`, so `QueueFull` cannot happen (`web/connection_manager.py:78-93`).
  - B20: open, as item 2.1.
- **STATE.md "Pending Todos: None".** The handoff "Open tasks (none)" is accurate for its date.
