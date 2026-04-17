---
id: 260416-trw
type: quick
autonomous: true
bugs_addressed: [B2, B5, B6, B11]
files_modified:
  # Deleted (B2 — Finder duplicates, all untracked, safe to rm):
  - ".planning/ROADMAP 2.md"
  - ".planning/STATE 2.md"
  - "AGENTS 2.md"
  - "uv 2.lock"
  - "frontend/.gitignore 2"
  - "frontend/env.d 2.ts"
  - "frontend/index 2.html"
  - "frontend/package 2.json"
  - "frontend/package-lock 2.json"
  - "frontend/src/App 2.vue"
  - "frontend/src/main 2.ts"
  - "frontend/src/types 2.ts"
  - "frontend/tsconfig 2.json"
  - "frontend/tsconfig.app 2.json"
  - "frontend/tsconfig.node 2.json"
  - "frontend/vite.config 2.ts"
  - "frontend/src/assets 2/ (empty dir)"
  - "frontend/src/components 2/ (empty dir)"
  - "frontend/src/composables 2/ (empty dir)"
  - "src/alphaswarm/web/__init__ 2.py"
  - "src/alphaswarm/web/app 2.py"
  - "src/alphaswarm/web/broadcaster 2.py"
  - "src/alphaswarm/web/connection_manager 2.py"
  - "src/alphaswarm/web/replay_manager 2.py"
  - "src/alphaswarm/web/routes/__init__ 2.py"
  - "src/alphaswarm/web/routes/edges 2.py"
  - "src/alphaswarm/web/routes/health 2.py"
  - "src/alphaswarm/web/routes/interview 2.py"
  - "src/alphaswarm/web/routes/replay 2.py"
  - "src/alphaswarm/web/routes/simulation 2.py"
  - "src/alphaswarm/web/routes/websocket 2.py"
  - "src/alphaswarm/web/simulation_manager 2.py"
  - "tests/test_graph 2.py"
  - "tests/test_replay_red 2.py"
  - "tests/test_web 2.py"
  - "tests/test_web_interview 2.py"
  - ".planning/phases/*/  *2.md (all untracked)"
  - ".planning/phases/35.1-shock-injection-wiring/.gitkeep 2"
  # Modified (B5/B6 gitignore, B11 teardown):
  - frontend/.gitignore
  - frontend/src/composables/useWebSocket.ts

commits:
  - "fix(b2): delete all macOS Finder-duplicate (space-2) files"
  - "fix(b5-b6): add gitignore patterns for emitted artifacts and duplicates"
  - "fix(b11): add onUnmounted teardown to useWebSocket composable"
---

<objective>
Tier 0 mechanical cleanup: delete all remaining Finder-duplicate files (B2), add
.gitignore patterns to prevent future pollution (B5/B6 residual), and wire proper
onUnmounted teardown into useWebSocket (B11).

Note: tsconfig.app.json already has `noEmit: true` (added by 260416-lpb). No .vue.js
artifacts remain in frontend/src. B5/B6 tsconfig work is done; this task handles the
gitignore guard only.
</objective>

<context>
@.planning/BUGFIX-CONTEXT.md
@.planning/STATE.md
</context>

<tasks>

<task type="auto">
  <name>Task 1 (B2): Delete all Finder-duplicate files and empty directories</name>
  <files>
    All files/dirs matching "* 2.*" or "* 2" outside .venv/ — full list confirmed via
    `find` before execution. Includes: .planning/, frontend/, src/, tests/, repo root.
  </files>
  <action>
Run two commands in sequence. Do NOT touch .venv/.

Step 1 — delete all " 2.*" files:
```
find "/Users/avosarkissian/Documents/VS Code/AlphaSwarm" \
  -name "* 2.*" \
  -not -path "*/node_modules/*" \
  -not -path "*/.git/*" \
  -not -path "*/.venv/*" \
  -delete
```

Step 2 — delete empty "* 2" directories (three empty dirs found: assets 2, components 2,
composables 2 inside frontend/src; also the bare `.gitkeep 2` file was handled by step 1):
```
find "/Users/avosarkissian/Documents/VS Code/AlphaSwarm" \
  -name "* 2" \
  -not -path "*/node_modules/*" \
  -not -path "*/.git/*" \
  -not -path "*/.venv/*" \
  \( -type d -empty \) \
  -delete
```

After deletion, verify zero results with:
```
find "/Users/avosarkissian/Documents/VS Code/AlphaSwarm" \
  -name "* 2.*" -o -name "* 2" \
  -not -path "*/node_modules/*" \
  -not -path "*/.git/*" \
  -not -path "*/.venv/*" \
  2>/dev/null | grep -v "^$" | wc -l
```
Expected output: 0

Commit message: `fix(b2): delete all macOS Finder-duplicate (space-2) files`
Stage only: none (all files were untracked — git sees them as gone without staging).
Use: `git -C "/Users/avosarkissian/Documents/VS Code/AlphaSwarm" add -u && git commit`
(the -u flag stages deletions of tracked files; untracked files simply vanish)

Actually: since all " 2" files were untracked (??), git does not track their removal.
No git staging needed — just verify they're gone, then commit the gitignore in Task 2.
These deletions require no git operation; they only become visible as "untracked files
no longer shown" in `git status`. Confirm with `git status --short | grep " 2"` = empty.
  </action>
  <verify>
    `find "/Users/avosarkissian/Documents/VS Code/AlphaSwarm" -name "* 2.*" -not -path "*/.venv/*" -not -path "*/.git/*" -not -path "*/node_modules/*" | wc -l` outputs 0.
    `git status --short | grep " 2"` outputs nothing.
  </verify>
  <done>No " 2" files or directories exist outside .venv/. git status is clean of all duplicate entries.</done>
</task>

<task type="auto">
  <name>Task 2 (B5/B6 guard): Add gitignore patterns for emitted artifacts and future duplicates</name>
  <files>frontend/.gitignore</files>
  <action>
Read the current frontend/.gitignore (content: `node_modules\ndist\n*.local`).

Append the following sections — do not remove existing lines:

```
# Vue-TSC compiler emission artifacts (noEmit should prevent these, but guard anyway)
*.vue.js
*.vue.js.map
tsconfig.*.tsbuildinfo

# macOS Finder duplicates (space-2 suffix pattern)
* 2.*
* 2/
```

Write the updated file. Run `cat frontend/.gitignore` to verify all patterns are present.

Commit:
```
git add frontend/.gitignore
git commit -m "fix(b5-b6): add gitignore patterns for emitted artifacts and Finder duplicates"
```
  </action>
  <verify>
    `grep "vue.js" frontend/.gitignore` returns a match.
    `grep "tsbuildinfo" frontend/.gitignore` returns a match.
    `grep "2\." frontend/.gitignore` returns a match.
  </verify>
  <done>frontend/.gitignore contains patterns for *.vue.js, tsconfig.*.tsbuildinfo, and "* 2.*".</done>
</task>

<task type="auto">
  <name>Task 3 (B11): Add onUnmounted teardown to useWebSocket composable</name>
  <files>frontend/src/composables/useWebSocket.ts</files>
  <action>
Read the current useWebSocket.ts carefully. The composable has three leak vectors on
unmount: (1) `ws` socket left open, (2) `_reconnectTimer` not cleared, (3) `watch` on
snapshot.value.phase not stopped.

Make the following changes:

1. Add `onUnmounted` to the import line (already imports `watch` from 'vue'):
   Change:
   ```typescript
   import { ref, readonly, watch, type Ref } from 'vue'
   ```
   To:
   ```typescript
   import { ref, readonly, watch, onUnmounted, type Ref } from 'vue'
   ```

2. Capture the watch stop handle. The existing watch call:
   ```typescript
   watch(() => snapshot.value.phase, (newPhase) => {
     if (newPhase === 'idle') {
       allRationales.value = []
     }
   })
   ```
   Change to:
   ```typescript
   const stopPhaseWatcher = watch(() => snapshot.value.phase, (newPhase) => {
     if (newPhase === 'idle') {
       allRationales.value = []
     }
   })
   ```

3. Add the onUnmounted hook immediately after the watch (before the return statement):
   ```typescript
   onUnmounted(() => {
     // Stop reconnect timer so no new connection attempt fires after unmount
     if (_reconnectTimer !== null) {
       clearTimeout(_reconnectTimer)
       _reconnectTimer = null
     }
     // Close the socket cleanly — suppress the onclose handler to avoid scheduling
     // a reconnect after the component is gone
     if (ws !== null) {
       ws.onclose = null
       ws.close()
       ws = null
     }
     // Stop the phase watcher
     stopPhaseWatcher()
   })
   ```

The key subtlety: set `ws.onclose = null` BEFORE calling `ws.close()`. This prevents the
`onclose` handler from firing `scheduleReconnect()` after the component has been torn down.

Do NOT change any other logic. Do NOT add any imports other than `onUnmounted`.

After editing, run `cd frontend && npx tsc --noEmit 2>&1 | head -20` to confirm no type
errors were introduced.

Commit:
```
git add frontend/src/composables/useWebSocket.ts
git commit -m "fix(b11): add onUnmounted teardown to useWebSocket — close ws, clear timer, stop watcher"
```
  </action>
  <verify>
    `cd "/Users/avosarkissian/Documents/VS Code/AlphaSwarm/frontend" && npx vue-tsc --noEmit 2>&1 | head -20` produces no errors.
    `grep -n "onUnmounted" frontend/src/composables/useWebSocket.ts` shows at least 2 hits (import + call).
    `grep "ws.onclose = null" frontend/src/composables/useWebSocket.ts` returns a match.
    `grep "stopPhaseWatcher" frontend/src/composables/useWebSocket.ts` returns 2 matches (assignment + call).
  </verify>
  <done>
    useWebSocket.ts has onUnmounted hook that: clears _reconnectTimer, nulls ws.onclose
    then closes ws, calls stopPhaseWatcher(). vue-tsc --noEmit passes with no errors.
  </done>
</task>

</tasks>

<verification>
After all three tasks and three commits:
1. `find . -name "* 2.*" -not -path "*/.venv/*" -not -path "*/.git/*" | wc -l` = 0
2. `git status --short | grep " 2"` = empty output
3. `grep "noEmit" frontend/tsconfig.app.json` = present (pre-existing)
4. `grep "vue.js\|tsbuildinfo" frontend/.gitignore` = both present
5. `grep "onUnmounted" frontend/src/composables/useWebSocket.ts` = present in import and call
6. `git log --oneline -3` shows three commits, one per bug group
</verification>

<success_criteria>
- Zero " 2" files remain outside .venv/ and .git/
- frontend/.gitignore guards against future *.vue.js, *.tsbuildinfo, and "* 2.*" pollution
- useWebSocket.ts tears down cleanly on unmount: no leaked sockets, no orphan timers, no dangling watchers
- Three atomic git commits, one per bug group (B2 / B5-B6 / B11)
- vue-tsc --noEmit passes after Task 3
</success_criteria>

<output>
No SUMMARY.md required for quick tasks. Update .planning/STATE.md Quick Tasks Completed
table with entry: `| 260416-trw | Tier 0: delete Finder dupes B2, gitignore guard B5-B6, useWebSocket teardown B11 | 2026-04-16 | [commit] | [260416-trw-tier-0-cleanup-delete-finder-duplicate-f/](./quick/260416-trw-tier-0-cleanup-delete-finder-duplicate-f/) |`
</output>
