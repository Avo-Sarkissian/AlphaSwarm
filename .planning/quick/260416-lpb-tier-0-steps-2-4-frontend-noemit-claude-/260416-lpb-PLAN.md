---
id: 260416-lpb
title: "Tier 0 steps 2-4: frontend noEmit, CLAUDE.md/AGENTS.md rewrite, ROADMAP Phase 36 fix"
status: ready
created: 2026-04-16
mode: quick
must_haves:
  truths:
    - frontend/tsconfig.app.json has `"noEmit": true` in compilerOptions
    - 13 emitted files (*.vue.js, main.js, types.js, vite.config.js, *.tsbuildinfo) absent from working tree
    - .gitignore contains patterns for .DS_Store, *.vue.js, frontend/tsconfig.*.tsbuildinfo, Schwab/, /*.csv
    - CLAUDE.md is plain Markdown (no shell heredoc wrappers), describes v5 web stack (Vue 3 + FastAPI + D3 + WebSocket + Neo4j)
    - CLAUDE.md no longer mentions Textual or Miro
    - CLAUDE.md retains the Developer Profile and GSD Workflow Enforcement sections verbatim
    - AGENTS.md matches CLAUDE.md content exactly (they are identical today; keep that)
    - .planning/ROADMAP.md Phase 36 "Plans" block no longer lists Phase 34's plans
  artifacts:
    - Commit 1 (step 2): `chore(frontend): add noEmit, delete build artifacts, update gitignore`
    - Commit 2 (step 3): `docs: rewrite CLAUDE.md and AGENTS.md as plain MD reflecting v5 web stack`
    - Commit 3 (step 4): `docs(roadmap): clear Phase 36 Plans copy-paste from Phase 34`
  key_links:
    - frontend/tsconfig.app.json
    - frontend/tsconfig.node.json
    - CLAUDE.md
    - AGENTS.md
    - .planning/ROADMAP.md (lines 204-218 — Phase 36 block)
    - .gitignore
    - .planning/BUGFIX-CONTEXT.md (B6, B14, B15, B16, B17 — rationale)
---

# Quick Task 260416-lpb: Tier 0 Steps 2-4 Bundle

## Context

Three mechanical cleanup items from `.planning/BUGFIX-CONTEXT.md` Tier 0. Each becomes one atomic commit.

## Task 1 — Frontend build artifact cleanup (step 2)

**files:**
- `frontend/tsconfig.app.json` (edit — add `"noEmit": true`)
- `frontend/src/App.vue.js` (delete)
- `frontend/src/components/AgentSidebar.vue.js` (delete)
- `frontend/src/components/BracketPanel.vue.js` (delete)
- `frontend/src/components/ControlBar.vue.js` (delete)
- `frontend/src/components/CyclePicker.vue.js` (delete)
- `frontend/src/components/ForceGraph.vue.js` (delete)
- `frontend/src/components/RationaleFeed.vue.js` (delete)
- `frontend/src/components/ShockDrawer.vue.js` (delete)
- `frontend/src/composables/useWebSocket.js` (delete)
- `frontend/src/main.js` (delete)
- `frontend/src/types.js` (delete)
- `frontend/vite.config.js` (delete)
- `frontend/tsconfig.app.tsbuildinfo` (delete)
- `frontend/tsconfig.node.tsbuildinfo` (delete)
- `.gitignore` (edit — append 5 patterns)

**action:**

1. Edit `frontend/tsconfig.app.json` — add `"noEmit": true,` to `compilerOptions` (alphabetize near other boolean flags). Preserve all other keys and the trailing `"paths"` entry.

2. Delete the 13 emitted JS/tsbuildinfo files listed above. All are untracked — use plain `rm`.

3. Append to `.gitignore`:
   ```
   .DS_Store
   *.vue.js
   frontend/tsconfig.*.tsbuildinfo
   Schwab/
   /*.csv
   ```

**verify:**
- `grep -n noEmit frontend/tsconfig.app.json` → finds one match
- `find frontend/src -name "*.vue.js" -o -name "main.js" -o -name "types.js"` → empty
- `find frontend -maxdepth 2 -name "*.tsbuildinfo"` → empty
- `ls frontend/vite.config.js 2>&1` → "No such file or directory"
- `grep -Fxq ".DS_Store" .gitignore && grep -Fxq "*.vue.js" .gitignore && grep -Fxq "Schwab/" .gitignore` → all succeed

**done:**
- Config has `noEmit: true`
- 13 artifacts removed
- 5 gitignore patterns appended
- Atomic commit: `chore(frontend): add noEmit, delete build artifacts, update gitignore`

---

## Task 2 — Rewrite CLAUDE.md and AGENTS.md as plain MD (step 3)

**files:**
- `CLAUDE.md` (rewrite — strip shell heredoc, update stack)
- `AGENTS.md` (rewrite — identical content to CLAUDE.md)

**action:**

Replace the full content of `CLAUDE.md` and `AGENTS.md` with the block below. Both files get the exact same content (they are duplicates today — keep that invariant).

```markdown
# AlphaSwarm: Core Directives

**Identity:** Senior Quantitative AI Engineer.
**Mission:** Build a localized, multi-agent financial simulation engine. Ingest a "Seed Rumor," run a 3-round iterative consensus cascade across 100 distinct AI personas, and visualize real-time state through a web UI.
**Hardware Target:** Apple M1 Max 64GB. Memory pressure is the primary bottleneck.

## Hard Constraints

1. **Concurrency:** 100% async (`asyncio`). No blocking I/O on the main event loop.
2. **Local First:** All inference local via Ollama. No cloud APIs. Max 2 models loaded simultaneously.
3. **Memory Safety:** Monitor RAM via `psutil`. Dynamically throttle `asyncio` semaphores; pause task queue at 90% utilization.
4. **WebSocket Cadence:** Broadcaster emits snapshots at ~5Hz. Drop-oldest backpressure on per-client queues. Never block the simulation loop on slow clients.

## Technology Stack

- **Runtime:** Python 3.11+ (strict typing), `uv` (package manager), `pytest-asyncio`.
- **Inference:** `ollama-python` (>=0.6.1). Local Ollama server only. Orchestrator + worker model pair.
- **State / Memory:** Neo4j Community (Docker) via async `neo4j` driver.
- **Web Backend:** FastAPI + `uvicorn`, native WebSocket support, `httpx` for outbound calls.
- **Web Frontend:** Vue 3 + TypeScript, Vite build, D3 force-directed graph for the live agent "mirofish" view.
- **Validation / Config:** `pydantic`, `pydantic-settings`.
- **Logging:** `structlog`.

## Conventions

Conventions not yet established. Will populate as patterns emerge during development.

## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.

## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless explicitly asked.

## Developer Profile

- **Role:** Computer Engineer & MIS Analyst.
- **Work Style:** Values structured, step-by-step explanations and practical, maintainable implementations. Prefers a clean and minimalist aesthetic in code architecture and UI design.
- **AI Collaboration:** Uses AI tools as a collaborative assistant to brainstorm, accelerate boilerplate, and double-check logic, not as a replacement for critical thinking.
```

**verify:**
- `head -1 CLAUDE.md` → `# AlphaSwarm: Core Directives` (no `cat << 'EOF'`)
- `tail -1 CLAUDE.md` → ends with developer-profile bullet, NOT `EOF`
- `grep -c "textual\|Textual\|Miro\|miro" CLAUDE.md AGENTS.md` → zero
- `grep -q "Vue 3" CLAUDE.md && grep -q "FastAPI" CLAUDE.md && grep -q "D3" CLAUDE.md` → all succeed
- `grep -q "Developer Profile" CLAUDE.md && grep -q "GSD Workflow Enforcement" CLAUDE.md` → both succeed
- `diff CLAUDE.md AGENTS.md` → empty (they are identical)

**done:**
- Both files are plain MD with no shell wrapper
- v5 stack documented; Miro/Textual gone
- Dev profile and GSD enforcement preserved
- AGENTS.md matches CLAUDE.md byte-for-byte
- Atomic commit: `docs: rewrite CLAUDE.md and AGENTS.md as plain MD reflecting v5 web stack`

---

## Task 3 — Fix ROADMAP.md Phase 36 Plans copy-paste (step 4)

**files:**
- `.planning/ROADMAP.md` (edit lines 213-218)

**action:**

Current content (lines 213-218):
```
**Plans**: 3 plans

Plans:
- [x] 34-01-PLAN.md -- ReplayManager class, replay route implementations, broadcaster coupling, Wave 0 tests
- [x] 34-02-PLAN.md -- CSS tokens, CyclePicker.vue modal, ControlBar replay strip, ForceGraph edge-clear fix, App.vue wiring
- [x] 34-03-PLAN.md -- Human verification of replay mode in browser
```

Replace with:
```
**Plans**: TBD — phase not yet planned

Plans:
- [ ] TBD — plans to be created when Phase 36 work begins
```

Rationale: Phase 36 (Report Viewer) is the last outstanding v5.0 phase. No plans exist yet. The current listing is Phase 34's plans pasted in error (they're even marked `[x]` though Phase 36 is unstarted). A TBD placeholder is accurate.

**verify:**
- `grep -n "34-01-PLAN.md" .planning/ROADMAP.md` → matches only the Phase 34 block (around line 185-189), not Phase 36 block (around line 215+)
- `sed -n '204,220p' .planning/ROADMAP.md` shows "TBD — phase not yet planned" in the Phase 36 block
- No other edits to ROADMAP.md

**done:**
- Phase 36 Plans block reflects reality (TBD)
- Atomic commit: `docs(roadmap): clear Phase 36 Plans copy-paste from Phase 34`

---

## Risk / Rollback

- **Step 2 risk:** None. tsconfig edit is additive (`noEmit: true` is safe — the frontend uses Vite for emission, not tsc). Deleted files are all untracked and regenerable by running `vue-tsc -b`.
- **Step 3 risk:** Low. Content rewrite preserves all semantic sections. If anything is wrong the files are small and can be re-edited.
- **Step 4 risk:** None. Single-block doc edit.
- **Rollback:** `git reset --hard` to pre-task HEAD (`72375fc`) undoes everything.
