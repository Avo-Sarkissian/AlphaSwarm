# AlphaSwarm Bug Report & Fix Plan — Resumption Context

**Created:** 2026-04-16 (session before context clear)
**User request:** "do a high level analysis of this project... search for all bugs, errors, illogical processes, inefficiencies... form a report of issues, and plan to fix."
**Status:** Analysis complete. No code changes made. Awaiting user approval to start fixes.

---

## Project Snapshot

**AlphaSwarm** = local-first multi-agent financial simulation. Seed rumor → orchestrator extracts entities → 100 personas across 10 brackets run 3-round consensus cascade via local Ollama → state in Neo4j → web UI (Vue 3 + D3 force graph + FastAPI WebSocket).

**Milestone state (per `.planning/ROADMAP.md`):**
- v1.0 (Phases 1–10), v2.0 (11–15), v4.0 (24–28): **shipped**.
- **v5.0 Web UI (Phases 29–36): in progress.** Phases 29–35 complete. **Phase 36 (Report Viewer) outstanding — final phase.**

**Key direction change** (memory `project_v5_direction.md`): TUI being deprecated; Miro integration dropped. CLAUDE.md/AGENTS.md still describe the old Textual+Miro stack — they're stale.

---

## Bugs — complete list, ordered by severity

### Ship-blockers (Tier 1 critical)

**B1. Shock injection is a dead feature in the web UI.**
- `frontend/src/components/ShockDrawer.vue` → `POST /api/simulate/shock`.
- Route: `src/alphaswarm/web/routes/simulation.py:113` calls `sim_manager.inject_shock()`.
- `src/alphaswarm/web/simulation_manager.py:154-170` stores `_pending_shock`, exposes `consume_shock()`.
- **`consume_shock()` has zero callers in the entire codebase.** Verified via `grep -r "consume_shock"`.
- `src/alphaswarm/simulation.py` has zero `shock`/`Shock` references — pipeline can't see queued shocks.
- `src/alphaswarm/graph.py` has `read_shock_event` (line 1526) and `read_shock_impact` (line 1569) but **no `write_shock_event`**. Only mentioned in `.planning/phases/26-shock-injection-core/26-01-PLAN.md` as planned API.
- Consequence: shocks silently dropped; `ShockEvent` nodes never written; `read_shock_impact` always returns zero-filled dict; TUI `_activate_bracket_delta_mode` (`tui.py:1428`) never activates; report shock-impact template always empty.

**B2. Massive macOS Finder-duplicate pollution.**
Files with " 2" suffix sit next to the real ones. Confirmed via `find . -name "* 2.*"`:
- `src/alphaswarm/web/{__init__, app, connection_manager, simulation_manager} 2.py`
- `src/alphaswarm/web/routes/{__init__, health} 2.py`
- `tests/test_web 2.py`
- `.planning/phases/29-fastapi-skeleton-and-event-loop-foundation/*2.md` (10+ files)
- `.planning/phases/33-web-monitoring-panels/33-02-SUMMARY 2.md`
- `.planning/phases/28-simulation-replay/28-02-SUMMARY 2.md`
- Inside `.venv/` (harmless but messy)

`diff app.py "app 2.py"` showed the " 2" versions are older stubs missing broadcaster/replay/interview wiring. No imports reference them (verified). Safe to delete.

**B3. Frontend bracket assignment is numerically wrong.**
- `frontend/src/components/ForceGraph.vue:86-98` `assignBrackets()` hardcodes `floor(i / 10)` → assumes exactly 10 agents per bracket.
- `PROJECT_SPEC.md` section 2: Degens=20, Agents=15, Doom-Posters=5, Policy Wonks=5, Whales=5 (others 10). **Not uniform.**
- WebSocket `agent_states` payload carries `{signal, confidence}` only (no `bracket`). Frontend must guess; guesses wrong → nodes cluster into wrong centroids visually.
- Fix requires backend change (add `bracket` per agent) + frontend rewrite of `assignBrackets`.

**B4. Replay can run on top of a live simulation.**
- `src/alphaswarm/web/routes/replay.py:98-142` `replay_start` does not check `sim_manager.is_running`.
- `src/alphaswarm/web/broadcaster.py:45-48` silently prefers `replay_manager.store.snapshot()` whenever `replay_manager.is_active`.
- Effect: live simulation keeps burning inference while UI shows replay frames. Add 409 guard both ways.

**B5. `App.vue.js` (committed compiler artifact) has `debugger;` at line 37.**
- `frontend/src/App.vue.js:37` contains `debugger; /* PartiallyEnd: #3632/scriptSetup.vue */`.
- If that `.js` ever gets served in place of the `.vue`, every visitor with devtools open hits a breakpoint.
- Symptom of B6 (all `.vue.js` files are Vue-TSC emission leakage).

### High severity (Tier 1/2)

**B6. Frontend build emits polluting the source tree.**
- `frontend/tsconfig.app.json` lacks `"noEmit": true`.
- `vue-tsc -b && vite build` produces `.vue.js` per `.vue`, `.js` twins of `.ts` (main.js, types.js, vite.config.js), plus `tsconfig.*.tsbuildinfo` — all committed (see `git status`).
- Fix: add `noEmit: true`, delete twins, gitignore patterns.

**B7. `ConnectionManager` leaks client entries on unclean disconnect.**
- `src/alphaswarm/web/connection_manager.py:51-61` `_writer` catches `Exception` with bare `pass`. **Does not pop `_clients[ws]` / `_tasks[ws]`.**
- A crashed client that doesn't route through `disconnect()` leaves residue forever. `broadcast()` then puts into queues whose writer task is dead → memory grows unbounded.
- Fix: have `_writer`'s `finally` clean up its own entries.

**B8. `SimulationManager._on_task_done` race with `start()`.**
- `src/alphaswarm/web/simulation_manager.py:109-133`.
- On cancel/fail: sync callback releases lock, then schedules `_reset_phase_to_idle()` via `create_task`. A concurrent `POST /simulate/start` can slip between release and phase reset → fresh sim starts, then reset overwrites phase to IDLE.
- Fix: reset phase synchronously before releasing lock, or hold lock across reset.

**B9. `ReplayManager` mutates state without the lock in `advance`/`stop`.**
- `src/alphaswarm/web/replay_manager.py:74-122` `start()` uses `async with self._lock`.
- `advance()` (124-168) and `stop()` (170-177) mutate `_store`, `_cycle_id`, `_round_num` with no lock.
- Fix: wrap both in `async with self._lock`.

**B10. Duplicate `set_phase(COMPLETE)` call.**
- `src/alphaswarm/simulation.py:1109` sets `COMPLETE`.
- `src/alphaswarm/web/simulation_manager.py:107` sets it again with stale comment ("Caller (TUI) is responsible…").
- Harmless but confusing. Remove the manager-level one.

**B11. `useWebSocket` composable has no teardown.**
- `frontend/src/composables/useWebSocket.js` (also `.ts`, but JS is the committed artifact — see B6).
- No `onUnmounted`: socket never closed, `_reconnectTimer` never cleared, `watch` never stopped. HMR or route re-mount leaks sockets/timers.

**B12. Interview always targets most-recent cycle, ignoring replay context.**
- `src/alphaswarm/web/routes/interview.py:80` always `read_completed_cycles(limit=1)`.
- If user clicks an agent while replaying an older cycle, they talk to the wrong simulation's agent.
- Fix: prefer `request.app.state.replay_manager.cycle_id` when `replay_manager.is_active`, else fall back to most recent.

**B13. `interview_sessions` dict grows unbounded.**
- Only cleared in `sim_manager.start()` (`app.py:49`, `simulation_manager.py:81-82`).
- Between simulations, sessions accumulate — each holds an engine + conversation history. Needs TTL or LRU cap.

### Medium

**B14. `CLAUDE.md` and `AGENTS.md` are shell heredocs stored as content.**
- Both literally start with `cat << 'EOF' > CLAUDE.md` and end with `EOF`.
- Someone ran the heredoc command with the shell prefix included; the file on disk is the command, not its rendered output.
- They still read as instructions (heredoc body *is* prose) but structurally broken. Rewrite as plain MD.

**B15. `CLAUDE.md` is stale.**
- Says UI is "textual (>=8.1.1)" and Miro has strict batching rules — both obsolete per v5 direction memo.
- No mention of FastAPI/Vue/D3/Vite/WebSocket.
- Rewrite to match reality.

**B16. `Schwab/` has personal portfolio CSVs in repo root.**
- `holdings.csv`, `Individual-Positions-2026-04-09-154713.csv`, `Roth Contributory IRA-Positions-2026-04-09-154953.csv`.
- Currently untracked but one `git add -A` from leakage.
- Gitignore `Schwab/` + `*.csv`; consider moving folder outside repo.

**B17. `.DS_Store` in repo root.**
- Untracked but should be globally gitignored.

**B18. `docker-compose.yml` has hardcoded weak Neo4j credentials.**
- `NEO4J_AUTH: neo4j/alphaswarm`. Fine for local dev; move to `.env` for hygiene.

**B19. `ConnectionManager.broadcast` drop-oldest has a theoretical `QueueFull` race.**
- `src/alphaswarm/web/connection_manager.py:63-77`. `put_nowait` after `get_nowait` could still raise under unusual contention. Wrap the final put in try/except.

**B20. `pyproject.toml` likely still lists `textual` and miro-related deps.**
- Audit and prune anything only used by `tui.py`/`miro.py` once TUI retirement is confirmed.

### Inefficiencies (Tier 3)

- **`_generate_decision_narratives`** (`simulation.py:1137-1233`): 100 concurrent `governor.__aenter__` via `asyncio.gather`. Governor serializes anyway — use bounded `as_completed`.
- **5Hz broadcaster serializes full snapshot unconditionally.** Dirty-diff pushes or conditional broadcast for large payloads.
- **`read_ranked_posts` called N=100 times per round** in `simulation.py:860-864` and `983-987`. Batch into one Cypher call.
- **`broadcaster._broadcast_loop`** sleeps 200 ms then serializes: if serialization > 200ms, drift accumulates. Consider `asyncio.wait_for` or proper timer.

### Planning/Hygiene

- **Phase 36 roadmap entry is wrong** (`.planning/ROADMAP.md:215-218` lists Phase 34's plans — copy-paste error). Fix before executing Phase 36.
- **Redundant " 2.md" planning docs** (covered by B2).

---

## Fix Plan — Execution Order

### Tier 0: Cleanup (safe, mechanical, do first)
1. Delete all `" 2.py"`, `" 2.md"`, `" 2.json"`, `" 2.pyc"` duplicates in `src/`, `tests/`, `.planning/`. Leave `.venv/` alone (regenerated on install).
2. Add `"noEmit": true` to `frontend/tsconfig.app.json`. Delete all `.vue.js`, `main.js`, `types.js`, `vite.config.js`, `*.tsbuildinfo`. Update `.gitignore` with: `*.vue.js`, `tsconfig.*.tsbuildinfo`, `.DS_Store`, `Schwab/`, `*.csv` (scoped).
3. Rewrite `CLAUDE.md` and `AGENTS.md` as plain Markdown reflecting v5 stack (Vue 3 / FastAPI / D3 / WebSocket / Neo4j). Remove Miro/Textual references. Keep developer profile and GSD enforcement sections.
4. Fix `.planning/ROADMAP.md` Phase 36 plans list (lines 215–218 currently duplicate Phase 34).

### Tier 1: Correctness (the real bugs)
5. **Finish shock injection end-to-end** (B1). This is a proper phase, not a quick fix. Propose creating an inserted phase (e.g. `27.1` or `35.1`) via `/gsd:insert-phase`. Tasks:
   - Implement `GraphStateManager.write_shock_event(cycle_id, shock_text, injected_before_round)` in `graph.py`.
   - Thread a `shock_provider: Callable[[int], str | None]` parameter through `run_simulation`; call `sim_manager.consume_shock()` between rounds (before Round 2 and before Round 3); mutate that round's `user_message` (or append to peer context) and call `write_shock_event`.
   - Add test: queued shock via `sim_manager.inject_shock` results in a `ShockEvent` node + non-zero `read_shock_impact` output.
   - Update `SimulationManager._run` to pass `lambda: self.consume_shock()` (or similar) to `run_simulation`.
6. Expose per-agent `bracket` in WebSocket `agent_states` payload (modify `StateStore` snapshot + broadcaster serialization), and rewrite `ForceGraph.assignBrackets` to consume it (B3).
7. Guard `POST /api/replay/start` with `is_running` check; symmetrical guard in `sim_manager.start` against active replay (B4).
8. Fix `ConnectionManager._writer` to clean `_clients[ws]`/`_tasks[ws]` in `finally` (B7).
9. Close `_on_task_done` race — reset phase synchronously before lock release (B8).
10. Wrap `ReplayManager.advance`/`stop` in `async with self._lock` (B9).
11. Remove duplicate `set_phase(COMPLETE)` in `SimulationManager._run` (B10).

### Tier 2: UX / Hygiene
12. Add `onUnmounted` teardown to `useWebSocket` — close ws, clear timer, stop watcher (B11).
13. Make interview cycle-aware in replay mode (B12).
14. Add TTL/LRU cap to `interview_sessions` (B13).
15. Move Neo4j creds to `.env` (B18).

### Tier 3: Performance
16. Batch `read_ranked_posts` per round (one Cypher for all personas).
17. Dirty-diff or conditional broadcaster.
18. Prune dead deps in `pyproject.toml` (B20).

---

## Key Facts for Resumption

- **CLAUDE.md enforces GSD workflow:** before any `Edit/Write`, start through `/gsd:quick` (small fixes), `/gsd:debug` (investigation), or `/gsd:execute-phase` (planned work). Don't edit directly.
- **Recommended GSD routing:**
  - Tier 0 items → `/gsd:quick` each (mechanical cleanup).
  - B1 (shock) → `/gsd:insert-phase` because it's a real feature not a quick fix. Needs planning doc.
  - B3 (bracket exposure) → `/gsd:insert-phase` (touches state model + WebSocket + frontend).
  - Other Tier 1 bugs → `/gsd:debug` (investigation + fix) or bundled into `/gsd:quick` each.
- **Git status at analysis time:** `master` branch, 37dfb4f (Phase 35 complete). Many untracked files — the `.vue.js` / `main.js` / `types.js` pollution, the " 2" duplicates, `Schwab/`, `.DS_Store`, and `.planning/milestones/` + `.planning/phases/29,31,33-...` new dirs.
- **User preferences (from CLAUDE.md + memory):** structured step-by-step explanations; minimalist aesthetic; practical maintainable implementations; prefers no emojis; Opus 4.7 max effort already set.
- **Terminal quirk noticed:** `start` script launches `python -m alphaswarm tui` — that's the old TUI entry point. May need updating to `python -m alphaswarm web` or equivalent once TUI is officially retired.

---

## Recommended First Action After Resume

1. Re-read this file.
2. Confirm with user which tier to start with. Suggest: **Tier 0 first** (mechanical, unblocks everything, low risk), then discuss whether B1 (shock) should be Phase 35.1/36.1 before finishing Phase 36 (Report Viewer) — since the report depends on shock data.
3. For Tier 0 step 1 (deleting " 2" files), use:
   ```
   find "/Users/avosarkissian/Documents/VS Code/AlphaSwarm" -name "* 2.*" \
     -not -path "*/node_modules/*" -not -path "*/.git/*" -not -path "*/.venv/*"
   ```
   Verify zero imports reference any " 2" file before deleting.
