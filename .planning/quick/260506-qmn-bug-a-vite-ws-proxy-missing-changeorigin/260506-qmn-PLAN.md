---
quick: 260506-qmn
type: execute
wave: 1
depends_on: []
files_modified: [frontend/vite.config.ts]
autonomous: false
requirements: [BUG-A-VITE-WS-PROXY]
must_haves:
  truths:
    - "Browser console shows no WebSocket upgrade error against ws://localhost:5173/ws/state during dev"
    - "useWebSocket hook flips connected=true within a few seconds of page load"
    - "Live snapshots flow into the UI on every backend tick (no stuck-frame + climbing ELAPSED counter)"
  artifacts:
    - path: "frontend/vite.config.ts"
      provides: "Vite dev server proxy config with WS upgrade-safe Origin rewriting"
      contains: "changeOrigin: true"
  key_links:
    - from: "frontend/vite.config.ts (/ws proxy entry)"
      to: "ws://localhost:8000/ws/state (FastAPI WS endpoint)"
      via: "Vite dev proxy with ws:true + changeOrigin:true"
      pattern: "'/ws':\\s*\\{[^}]*ws:\\s*true[^}]*changeOrigin:\\s*true"
---

<objective>
Fix Bug A from Phase 41.4 context: the Vite dev proxy `/ws` entry is missing `changeOrigin: true`, causing FastAPI/uvicorn to reject WS upgrades because the forwarded `Origin: http://localhost:5173` header doesn't match the upstream target host. This makes the UI appear hung during smoke testing (stuck frame + climbing client-side ELAPSED counter) and masks any backend slowness.

Purpose: Unblock future smoke testing — without this fix, every smoke run looks like a backend hang regardless of what the backend is actually doing. This is also a prerequisite for diagnosing Bug B (R3 inference latency) cleanly.

Output: One-line edit to `frontend/vite.config.ts` adding `changeOrigin: true` to the `/ws` proxy entry, verified manually via dev server + browser console.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
</execution_context>

<context>
@.planning/phases/41.4-r3-inference-and-ws-stall/41.4-CONTEXT.md
@frontend/vite.config.ts

<interfaces>
<!-- Current /ws proxy entry (frontend/vite.config.ts:10) — missing changeOrigin -->
```ts
'/ws': { target: 'ws://localhost:8000', ws: true },
```

<!-- Reference: /api entry already has the right shape (line 9) -->
```ts
'/api': { target: 'http://localhost:8000', changeOrigin: true },
```

<!-- Frontend WS URL construction is correct (per 41.4-CONTEXT.md), no changes needed there:
     useWebSocket.ts:34-35 uses window.location.host → resolves to localhost:5173 in dev → proxied via Vite -->
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add changeOrigin to /ws proxy entry</name>
  <files>frontend/vite.config.ts</files>
  <action>
    Edit `frontend/vite.config.ts` line 10. Change:
      `'/ws': { target: 'ws://localhost:8000', ws: true },`
    to:
      `'/ws': { target: 'ws://localhost:8000', ws: true, changeOrigin: true },`

    Rationale (per 41.4-CONTEXT.md Bug A): without `changeOrigin: true`, Vite forwards the
    browser's `Origin: http://localhost:5173` header upstream, and FastAPI/uvicorn rejects
    the WS upgrade because Origin doesn't match target host. The `/api` entry already does
    this correctly — we're just bringing `/ws` in line.

    No other changes. Do not touch `useWebSocket.ts`, the backend, or any other file —
    diagnosis (CONTEXT.md lines 22-32) confirms the bug is purely on the proxy side.
  </action>
  <verify>
    <automated>node -e "const c=require('fs').readFileSync('frontend/vite.config.ts','utf8'); const m=c.match(/'\/ws':\s*\{[^}]*\}/); if(!m) process.exit(1); if(!/ws:\s*true/.test(m[0])||!/changeOrigin:\s*true/.test(m[0])) { console.error('missing ws:true or changeOrigin:true in /ws entry'); process.exit(1);} console.log('ok');"</automated>
  </verify>
  <done>
    `frontend/vite.config.ts` line 10 contains both `ws: true` AND `changeOrigin: true` in the `/ws` proxy entry. File still parses (no syntax errors). No other lines modified.
  </done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 2: Manual smoke — confirm WS connects in browser</name>
  <what-built>One-line addition of `changeOrigin: true` to the Vite dev `/ws` proxy entry, intended to stop the WS upgrade rejection that made the UI appear hung during 41.3 smoke testing.</what-built>
  <how-to-verify>
    1. Make sure the FastAPI backend is running on `localhost:8000` (uvicorn).
       If not already up: `uv run uvicorn alphaswarm.web.app:app --port 8000`
       (run from a separate terminal — not required to be a fresh sim; just needs the WS endpoint live).
    2. Start the frontend dev server: `npm --prefix frontend run dev`
       Wait for "VITE ... ready" line. Confirm it binds to `http://localhost:5173`.
    3. Hard-refresh `http://localhost:5173` in the browser (Cmd+Shift+R to bypass cache).
    4. Open DevTools → Console tab.
       Expected: NO `WebSocket connection to 'ws://localhost:5173/ws/state' failed: WebSocket is closed before the connection is established` error.
       Expected: WS handshake succeeds silently.
    5. Open DevTools → Network tab → filter "WS".
       Expected: a single `state` row with status `101 Switching Protocols` (green/active),
       and a Messages sub-tab showing snapshot frames flowing in (one per backend tick).
    6. Visually confirm the UI updates — agent graph / ticker / cycle indicator should not be a frozen stale frame with only the client ELAPSED counter ticking.
  </how-to-verify>
  <resume-signal>Type "approved" if console is clean and WS frames flow. If still failing, describe the exact console error and Network-tab status code so we can iterate (likely targets: backend not running, port collision, or a second proxy issue not in CONTEXT.md).</resume-signal>
</task>

</tasks>

<verification>
- `frontend/vite.config.ts` diff is exactly +1 token (`changeOrigin: true,`) on the `/ws` entry; no other lines changed.
- Manual browser smoke (Task 2 checkpoint) confirms WS upgrade succeeds and live frames flow.
</verification>

<success_criteria>
- Bug A from `41.4-CONTEXT.md` is closed: `/ws` proxy entry has `changeOrigin: true`.
- Browser console shows no WS upgrade error during dev.
- Live snapshots flow on every backend tick — UI is no longer falsely "stuck".
- Phase 41.4 Bug B can now be diagnosed without WS noise masking the symptom.
</success_criteria>

<output>
After completion, append a one-row entry to STATE.md "Quick Tasks Completed" table:
| 260506-qmn | Bug A — Vite WS proxy missing changeOrigin (frontend/vite.config.ts) | 2026-05-06 | {commit-sha} | [260506-qmn-bug-a-vite-ws-proxy-missing-changeorigin](./quick/260506-qmn-bug-a-vite-ws-proxy-missing-changeorigin/) |
</output>
