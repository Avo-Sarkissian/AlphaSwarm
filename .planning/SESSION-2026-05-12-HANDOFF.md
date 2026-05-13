---
session: 2026-05-12
status: ready-to-clear
last_commit: e14ba29
---

# Session Handoff — 2026-05-12

## TL;DR for next session

Read this file first. Then run the stack readiness check below. Then trigger a fresh sim if you want to UAT the changes — **a backend restart is required** to activate the Python-side changes.

## What landed this session (chronological, oldest → newest)

### Bug fixes from initial state (Phase 41.6 polish during live UAT)

1. `fe366ce` fix(state): preserve agent_states across round transitions (debug-session R1)
2. `1da741e` fix(streaming): write agent state per-agent on inference completion (R2)
3. `bd682df` fix(frontend): extend AdvisoryV2 polling cap to 60 min
4. `1be286e` fix(41.6-02): BracketList empty state covers all-zero totals
5. `181b170` fix(41.6-02): AdvisoryV2 polling-exhausted error UI
6. `0a4f0b8` fix(41.6-02): dedupe useCurrentCycle to a module-level singleton
7. `718db32` docs(quick-260510-fdo): W2 polish docs commit
8. `270cd2a`...`a4d58bb` — Phase 41.6 Wave 4 execution (5 commits): port interview_v2 + onboarding + bracket_deep + edges.ts, rewire App.tsx + app_v2.tsx, parity matrix, KR audit, VALIDATION flag flip
9. `38a7628` test(41.6): persist human verification items as UAT
10. `0f94cbd` docs(phase-41.6): complete phase execution
11. `8c7cdd9` docs(phase-41.6): evolve PROJECT.md after phase completion
12. `643f93a` fix(41.6-02): RationalesContext accumulates across frames
13. `6dd2665` fix(41.6-02): dedupe rationales + remove Finder duplicates
14. `ea5202a` fix(41.6-02): vertically center SignalWire ticker events
15. `5d3d7be` fix(41.6-02): unfreeze SignalWire + restore varying agent dot sizes
16. `b116ddc` fix(41.6-02): speed up wire scroll + Top Influencers OUT-DEGREE + active edges meta
17. `1077eec` fix(41.6-03): add missing CSS for AdvisoryV2 takeover
18. `3d56d85` feat(41.6-02): align overflow menu with AlphaSwarm-2 design (7 items + "Coming in v6.x" placeholders)
19. `f4909ba` fix(41.6-03): add missing CSS for DataSourcesTakeover + advisory loading copy
20. `1bb100e` fix(41.6-03): probe-then-trigger report generation
21. `4b035ff` fix(advisory): lazy-reload portfolio snapshot when startup load failed

### Six-task batch (quick task `260512-jqn`, atomic commit per ITEM)

22. `41d8d4c` fix(41.6-04): InterviewV2 + Onboarding + BracketDeepDive CSS — initial commit, used WRONG class prefixes (iv-/bdd-) — fixed in #28
23. `890a220` fix(api): compute INFLUENCED_BY edges after Round 3 so /api/edges?round=3 is non-empty (+ tests/test_edges_route.py)
24. `de31313` feat(state): emit governor current_slots + active_count in WS frame (closes KR-41.1-05)
25. `0003375` feat(state): rationale sliding window — replaces drain-once queue with persistent deque(maxlen=50); streams per-agent in batch_dispatcher (closes tasks #4 + #9)
26. `fc7a568` feat(data): live SignalWire audit — backend data_audit.py + provider sinks + frontend useDataSourceAudit hook (mocks stay as DEV fallback per KR-41.6-14)
27. `4234035` feat(advisory): one-item-per-holding + sector enrichment + UI fallback (closes task #10) — sector_map.py covers 32 unique tickers
28. `6cb238a` fix(41.6-04): port correct CSS class prefixes (iv2-/bd-/full ob-) + simplify RationalesContext — gap-fix for verifier-flagged Gap 1 of `260512-jqn`
29. `cac7e58` docs(quick-260512-jqn): final docs commit (PLAN + SUMMARY + VERIFICATION + STATE)

### UX polish post-batch

30. `5814853` feat(idle): add "Browse previous runs" affordance on dormant screen
31. `4ead80b` fix(history): add missing CSS for CycleHistory takeover (was invisible)
32. `b5d7b14` fix(history): polish CycleHistory row layout — 9-column grid + formatted dates + dropped verbose KR placeholder
33. `7de7828` fix(idle): browse-previous-runs button no longer inherits ghost-btn 34px width
34. `115a288` fix(report): probe via one-shot useEffect, not usePolling maxAttempts=1
35. `e14ba29` fix(settings): add missing CSS for Settings takeover (st-*)

## Big picture: family of bugs we hunted down

**"Component was ported in W2/W3/W4 with invented class names, no matching CSS"** — six instances patched this session:

| Component | Commit |
|-----------|--------|
| AdvisoryV2 | `1077eec` |
| DataSourcesTakeover | `f4909ba` |
| InterviewV2 / Onboarding / BracketDeepDive | `6cb238a` (after `41d8d4c` had wrong prefixes) |
| CycleHistory | `4ead80b` + polish `b5d7b14` |
| Settings | `e14ba29` |

If any remaining modal renders "as an unstyled inline block at the bottom of the page," it's the same family bug — enumerate class names in the .tsx, grep styles.css for them, write a CSS block mirroring `.adv-takeover` / `.ds-takeover` pattern.

## Required to activate backend changes

```bash
# Pane 2 (uvicorn) — Ctrl-C the current process, then:
cd "/Users/avosarkissian/Documents/VS Code/AlphaSwarm"
uv run uvicorn alphaswarm.web.app:app --port 8000
```

The `cd` is critical — uvicorn must launch from the project root so `Schwab/holdings.csv` resolves correctly. Earlier in this session the user launched uvicorn from `frontend/` and the advisory route 503'd for hours.

## Stack readiness check

```bash
echo "uvicorn  : $(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/health)"
echo "holdings : $(curl -s http://localhost:8000/api/holdings | python3 -c 'import sys,json; d=json.load(sys.stdin); print(len(d["holdings"]),"positions") if "holdings" in d else print("FAILED:",d)')"
echo "frontend : $(curl -s -o /dev/null -w "%{http_code}" http://localhost:5173)"
echo "ollama   : $(curl -s -o /dev/null -w "%{http_code}" http://localhost:11434/api/version)"
docker ps --format '{{.Names}} ({{.Status}})' | grep -i neo4j
```

Expected (all green):
- `uvicorn: 200`
- `holdings: 34 positions`
- `frontend: 200`
- `ollama: 200`
- `neo4j (Up …)`

## What to UAT on the next sim

| Expectation | Activates |
|-------------|-----------|
| Force graph dots stream in progressively (NOT 0→100 jump) | `fe366ce` + `1da741e` |
| Varying dot sizes by bracket | `5d3d7be` |
| SignalWire ticker shows real yfinance/FRED/reddit/etc. calls (NOT mock seed) | `fc7a568` |
| `PARALLEL SLOTS` tile shows actual count (e.g. `4/16`) | `de31313` |
| Rationale Feed populates LIVE mid-round (1 → 100 over round) | `0003375` |
| R3 rationales remain visible after cycle complete | `0003375` |
| Post-cycle: Top Influencers flips CONFIDENCE → OUT-DEGREE | `b116ddc` + `890a220` |
| Post-cycle: topstrip shows "N active edges" | `b116ddc` + `890a220` |
| Advisory auto-fires on cycle complete | already in place (quick task `260507-19f`) |
| Advisory shows one item per holding with sector-aware reasoning | `4234035` |
| Advisory Overview tiles show real values (not $0K/0/SELL 0%/LOW 0%) | `4234035` |
| InterviewV2 / BracketDeepDive / Onboarding render as proper modals | `6cb238a` |
| Browse previous runs button on dormant screen | `5814853` + `7de7828` |
| CycleHistory renders cleanly with formatted dates | `4ead80b` + `b5d7b14` |
| Settings gear opens a proper takeover with left nav + right pane | `e14ba29` |
| Report modal probes first, asks before generating | `1bb100e` + `115a288` |

## Known deferred (NOT bugs — do not chase)

- KR-41.1-03 (`flipped: 0` adapter stub) — backend doesn't emit per-agent flip status. "0 flips since R1" stays 0. Deferred indefinitely.
- 4 overflow menu placeholders show "Coming in v6.x" modals — by design. These features need backend work (What-if Compare, Multi-seed Synthesis, Portfolio Stress Test, Customize Brackets).
- KR-41.1-07 — `/api/replay/cycles` list endpoint doesn't carry consensus/flips/duration/shocks. CycleHistory shows "—" in those columns. Backend extension is a future-phase item.
- 4 pre-existing `tests/test_simulation.py::_format_peer_context_*` failures — predate this session. Logged in `.planning/phases/41.6-…/deferred-items.md`.
- 22 pre-existing pytest failures in Neo4j integration + report/seed_pipeline format strings — predate W4.

## Where things live (file map)

### Backend (Python)
- `src/alphaswarm/state.py` — `_rationale_window` deque (replaces queue), `set_phase` preserves agent_states
- `src/alphaswarm/batch_dispatcher.py` — `_safe_agent_inference` streams BOTH `update_agent_state` AND `push_rationale` per inference
- `src/alphaswarm/governor.py` — emits `current_slots` + `active_count` in `GovernorMetrics`
- `src/alphaswarm/data_audit.py` — NEW, 100-entry deque ring buffer for provider call audit
- `src/alphaswarm/advisory/prompt.py` — "NEVER OMIT" prompt (rewritten)
- `src/alphaswarm/advisory/sector_map.py` — NEW, 32-ticker curated map (sector / region / supply-chain / macro_beta)
- `src/alphaswarm/advisory/engine.py` — sector enrichment + relevance scoring
- `src/alphaswarm/web/routes/advisory.py` — lazy-reload portfolio_snapshot if startup load failed
- `src/alphaswarm/web/routes/edges.py` — `/api/edges/{cycle_id}?round=N` Cypher fix
- `src/alphaswarm/web/broadcaster.py` — drops `drain_rationales`, reads from persistent state

### Frontend (React + TS)
- `frontend/src/context/RationalesContext.tsx` — simplified to one-line `useMemo` on `frame.rationales` (backend now persists)
- `frontend/src/components/v2.tsx` — SignalWire consumes `useDataSourceAudit()` (mocks stay as DEV fallback); AdvisoryV2 has items=[] fallback
- `frontend/src/components/app_v2.tsx` — overflow menu has 7 items; Top Influencers OUT-DEGREE; topstrip "N active edges"
- `frontend/src/components/ReportModal.tsx` — probe-then-trigger via one-shot `useEffect`
- `frontend/src/components/states.jsx` — IdleState has "Browse previous runs" button
- `frontend/src/hooks/useDataSourceAudit.ts` — NEW, reads `dataSourceAudit` slice from WS frame
- `frontend/src/styles.css` — ALL the CSS for adv-/ds-/iv2-/bd-/ob-/ch-/st- takeovers

## Open tasks (none)

All 7 tracked tasks (#4–#10) closed in this session. No outstanding follow-ups from gsd-verifier.

## Backend cwd gotcha (recurring)

If `curl http://localhost:8000/api/holdings` returns `holdings_unavailable`, uvicorn was started from the wrong directory. Fix:

```bash
ps -ef | grep "uvicorn alphaswarm" | grep -v grep   # find the pid
lsof -p <PID> | awk '/cwd/ {print $NF}'              # check cwd
```

Should be `…/AlphaSwarm` (project root), NOT `…/AlphaSwarm/frontend`. If wrong, Ctrl-C and restart from project root.

## Hardware/runtime expectations

- M1 Max 64GB
- Ollama runs as desktop app (no CLI start needed)
- Worker: `qwen3:8b` Q4_K_M (~5.6 GB with NUM_PARALLEL=4 slots)
- Orchestrator: `qwen3.6:27b-q4_K_M` (~17 GB, loads on-demand for advisory)
- Cycle wall-clock estimate: ~42–55 min to dashboard-complete, ~55–85 min to advisory file
- Parallelism IS working: ONE ollama process with N internal slots that share base weights. Don't be alarmed that "only 5.6 GB" is showing for ollama in Activity Monitor — that's the full process with 4 parallel slots.

## Resume protocol for next session

1. Read this file.
2. Run the stack readiness check above.
3. If everything green: trigger a sim or ask user what's next.
4. If broken: re-check backend `cwd`, then re-check Ollama is running.
