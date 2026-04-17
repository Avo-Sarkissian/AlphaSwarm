---
id: 260416-trw
type: quick
status: complete
bugs_addressed: [B2, B5, B6, B11]
completed: "2026-04-16"
commits:
  - hash: 10d739e
    message: "fix(b2): delete all macOS Finder-duplicate (space-2) files"
  - hash: cb949ac
    message: "fix(b5-b6): add gitignore patterns for emitted artifacts and Finder duplicates"
  - hash: 18ad28f
    message: "fix(b11): add onUnmounted teardown to useWebSocket — close ws, clear timer, stop watcher"
---

# Quick Task 260416-trw: Tier 0 Cleanup Summary

**One-liner:** Deleted all macOS Finder-duplicate files (B2), added gitignore guards for *.vue.js / tsbuildinfo / Finder-duplicate patterns (B5/B6), and wired onUnmounted teardown in useWebSocket composable (B11).

## Tasks Completed

| Task | Bug | Description | Commit |
|------|-----|-------------|--------|
| 1 | B2 | Deleted all " 2.*" and ".* 2" Finder-duplicate files/dirs outside .venv/ | 10d739e |
| 2 | B5/B6 | Added gitignore patterns to frontend/.gitignore | cb949ac |
| 3 | B11 | Added onUnmounted teardown to useWebSocket composable | 18ad28f |

## Files Modified

- `frontend/.gitignore` — appended 5 patterns: *.vue.js, *.vue.js.map, tsconfig.*.tsbuildinfo, "* 2.*", "* 2/"
- `frontend/src/composables/useWebSocket.ts` — added onUnmounted import, stopPhaseWatcher capture, onUnmounted hook

## Files Deleted (B2 — all were untracked)

All files/directories matching "* 2.*" or ".* 2" pattern outside .venv/, .git/, node_modules/. Included: .planning/, frontend/, src/alphaswarm/web/, tests/, repo root (uv 2.lock, AGENTS 2.md).

Notable dotfiles caught manually (not matched by find glob): `frontend/.gitignore 2`, `.planning/phases/35.1-shock-injection-wiring/.gitkeep 2`.

## Verification Results

1. `find . -name "* 2.*" ... | wc -l` = 0
2. `git status --short | grep " 2"` = empty
3. `grep "noEmit" frontend/tsconfig.app.json` = present (pre-existing from 260416-lpb)
4. `grep "vue.js|tsbuildinfo" frontend/.gitignore` = both present
5. `grep "onUnmounted" frontend/src/composables/useWebSocket.ts` = present in import + call
6. `vue-tsc --noEmit` = no errors

## Deviations from Plan

**1. [Rule 1 - Bug] Dotfiles not matched by plan's find command**
- Found during: Task 1
- Issue: The plan's `find -name "* 2.*"` glob does not match dotfiles like `.gitignore 2` or `.gitkeep 2` because shell glob `*` excludes leading-dot names.
- Fix: Manually deleted `frontend/.gitignore 2` and `.planning/phases/35.1-shock-injection-wiring/.gitkeep 2` after the find command missed them.
- Verified: `git status --short | grep " 2"` = empty after manual deletion.

**2. [Rule 3 - Blocking] Commits in main project vs worktree**
- Found during: Task 1
- Issue: The worktree branch (`worktree-agent-a398d4a8`) had `frontend/` files staged but not checked out on disk; couldn't use `git add` from worktree for files living at the main project path.
- Fix: Executed all three commits in the main project (master branch) where the files physically reside. The worktree's pre-staged `28-02-SUMMARY 2.md` was removed from the index via `git rm --cached`.
- Impact: All three commits landed on master (0d4aaea base), which is the correct branch for these changes.

## Self-Check

- [x] `10d739e` exists: confirmed via `git log --oneline -3`
- [x] `cb949ac` exists: confirmed
- [x] `18ad28f` exists: confirmed
- [x] `frontend/.gitignore` contains all 5 new patterns
- [x] `useWebSocket.ts` has onUnmounted import + hook with ws.onclose=null guard
- [x] Zero " 2" files remain on filesystem

## Self-Check: PASSED
