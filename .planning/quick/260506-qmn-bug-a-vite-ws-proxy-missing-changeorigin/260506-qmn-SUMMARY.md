---
quick: 260506-qmn
type: execute-summary
status: code-shipped-pending-manual-smoke
completed_date: 2026-05-06
requirements: [BUG-A-VITE-WS-PROXY]
dependency_graph:
  requires:
    - frontend/vite.config.ts (existing /ws proxy entry)
  provides:
    - WS upgrade-safe Origin rewriting for Vite dev proxy
  affects:
    - All future smoke testing against http://localhost:5173 (UI no longer falsely "stuck")
    - Phase 41.4 Bug B diagnosis (now visible without WS noise masking it)
tech-stack:
  added: []
  patterns:
    - Vite dev proxy with ws:true + changeOrigin:true (matches /api entry shape)
key-files:
  created: []
  modified:
    - frontend/vite.config.ts (+1 token: `changeOrigin: true,` on /ws entry, line 10)
decisions:
  - Fix applied on the proxy side only (not useWebSocket.ts) — diagnosis in 41.4-CONTEXT.md confirmed root cause is purely Vite forwarding the browser Origin header untouched
metrics:
  duration: ~3m
  tasks_completed: 1
  tasks_total: 2 (task 2 is a human-verify checkpoint, deferred per orchestrator constraints)
  files_modified: 1
---

# Quick Task 260506-qmn: Bug A — Vite WS Proxy Missing changeOrigin Summary

One-line addition of `changeOrigin: true` to the Vite dev `/ws` proxy entry, fixing the WS upgrade rejection that made the UI appear hung during 41.3 smoke testing.

## What Shipped

**File:** `frontend/vite.config.ts` (line 10)

**Diff:**
```diff
-      '/ws': { target: 'ws://localhost:8000', ws: true },
+      '/ws': { target: 'ws://localhost:8000', ws: true, changeOrigin: true },
```

Exactly +1 token added. No other files touched.

## Why

Per `.planning/phases/41.4-r3-inference-and-ws-stall/41.4-CONTEXT.md` Bug A: without `changeOrigin: true`, Vite forwarded the browser's `Origin: http://localhost:5173` header upstream untouched, and FastAPI/uvicorn's WS upgrade path rejected it because the Origin didn't match the target host (`localhost:8000`). The browser then logged `WebSocket connection to 'ws://localhost:5173/ws/state' failed: WebSocket is closed before the connection is established` and the UI sat on a stale frame while the client-side ELAPSED counter ticked — making any backend slowness look like a complete hang and masking Bug B (R3 inference latency).

The `/api` proxy entry already had `changeOrigin: true`; we simply brought `/ws` in line.

## Tasks

### Task 1: Add changeOrigin to /ws proxy entry — DONE

- **Action:** Edited `frontend/vite.config.ts` line 10.
- **Automated verify:** `node -e "..."` parse-and-assert script confirmed both `ws: true` AND `changeOrigin: true` present in the `/ws` entry. Output: `ok`.
- **Commit:** `45508dd` — `fix(260506-qmn): Bug A — add changeOrigin:true to vite /ws proxy entry`
- **Done criteria met:** File parses, line 10 contains both flags, no other lines modified (diff verified +1/-1).

### Task 2: Manual browser smoke — PENDING (human-verify checkpoint)

**Status:** Deferred per orchestrator constraints. Code is shipped; manual verification will be performed by the user.

**Verification steps (for the user):**

1. Ensure FastAPI backend is running on `localhost:8000`:
   `uv run uvicorn alphaswarm.web.app:app --port 8000`
2. Start frontend dev server: `npm --prefix frontend run dev`
   Confirm it binds to `http://localhost:5173`.
3. Hard-refresh `http://localhost:5173` (Cmd+Shift+R).
4. DevTools → Console: expect NO `WebSocket connection to 'ws://localhost:5173/ws/state' failed` error.
5. DevTools → Network → filter "WS": expect a single `state` row with `101 Switching Protocols` and snapshot frames flowing in the Messages sub-tab.
6. Visually confirm the UI updates on every backend tick (agent graph / ticker / cycle indicator are not frozen with only the client ELAPSED counter ticking).

**Resume signal:** "approved" if console is clean and WS frames flow. If still failing, capture the exact console error + Network-tab status code.

## Deviations from Plan

None — plan executed exactly as written for Task 1. Task 2 was intentionally deferred to the orchestrator handoff per execution constraints.

## Self-Check: PASSED

- `frontend/vite.config.ts` line 10 contains `changeOrigin: true` — verified via `git diff` and the automated parse-and-assert script.
- Commit `45508dd` exists in `git log` on branch `gsd/phase-41.4-01-vite-ws-proxy`.
- No other files modified in this commit (single-file diff: +1/-1).
