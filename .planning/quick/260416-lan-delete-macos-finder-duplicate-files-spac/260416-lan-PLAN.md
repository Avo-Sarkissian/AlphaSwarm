---
id: 260416-lan
title: Delete macOS Finder-duplicate files (space-2 suffix)
status: ready
created: 2026-04-16
mode: quick
must_haves:
  truths:
    - All 23 " 2.*" duplicate files under src/, tests/, .planning/ are deleted from working tree and index
    - `find . -name "* 2.*" -not -path "*/.venv/*" -not -path "*/.git/*"` returns no results
    - Test suite still collects (no ImportError on test_web.py)
    - No git rm errors from missing files
  artifacts:
    - Single atomic commit removing the 23 duplicate files
  key_links:
    - src/alphaswarm/web/app.py (canonical — " 2" version is stub, delete)
    - src/alphaswarm/web/connection_manager.py (canonical)
    - src/alphaswarm/web/simulation_manager.py (canonical)
    - tests/test_web.py (canonical)
    - .planning/BUGFIX-CONTEXT.md (analysis justifying safety)
---

# Quick Task 260416-lan: Delete macOS Finder-Duplicate Files

## Context

macOS Finder creates `* 2.*` copies when duplicates occur during drag operations. These files have accumulated in the repo. Per `.planning/BUGFIX-CONTEXT.md` B2, a prior session diffed the code versions and confirmed " 2" copies are older stubs lacking broadcaster/replay/interview wiring. Zero imports reference any " 2" file (verified via grep in the calling session).

## Task 1 — Delete 23 duplicate files

**files:**
- `src/alphaswarm/web/__init__ 2.py`
- `src/alphaswarm/web/app 2.py`
- `src/alphaswarm/web/connection_manager 2.py`
- `src/alphaswarm/web/simulation_manager 2.py`
- `src/alphaswarm/web/routes/__init__ 2.py`
- `src/alphaswarm/web/routes/health 2.py`
- `tests/test_web 2.py`
- `tests/__pycache__/test_web 2.cpython-311-pytest-9.0.2.pyc`
- `.planning/phases/28-simulation-replay/28-02-SUMMARY 2.md`
- `.planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-01-PLAN 2.md`
- `.planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-01-SUMMARY 2.md`
- `.planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-02-PLAN 2.md`
- `.planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-02-SUMMARY 2.md`
- `.planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-03-PLAN 2.md`
- `.planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-03-SUMMARY 2.md`
- `.planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-04-PLAN 2.md`
- `.planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-05-PLAN 2.md`
- `.planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-CONTEXT 2.md`
- `.planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-DISCUSSION-LOG 2.md`
- `.planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-RESEARCH 2.md`
- `.planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-VALIDATION 2.md`
- `.planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-VERIFICATION 2.md`
- `.planning/phases/33-web-monitoring-panels/33-02-SUMMARY 2.md`

**action:**

All 23 files are currently untracked (confirmed via git status at session start). Use `rm` (plain filesystem delete) rather than `git rm` since none are in the index. Quote paths due to embedded spaces.

```bash
cd "/Users/avosarkissian/Documents/VS Code/AlphaSwarm"

# Source code and tests
rm "src/alphaswarm/web/__init__ 2.py"
rm "src/alphaswarm/web/app 2.py"
rm "src/alphaswarm/web/connection_manager 2.py"
rm "src/alphaswarm/web/simulation_manager 2.py"
rm "src/alphaswarm/web/routes/__init__ 2.py"
rm "src/alphaswarm/web/routes/health 2.py"
rm "tests/test_web 2.py"
rm "tests/__pycache__/test_web 2.cpython-311-pytest-9.0.2.pyc"

# Planning docs
rm ".planning/phases/28-simulation-replay/28-02-SUMMARY 2.md"
rm ".planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-01-PLAN 2.md"
rm ".planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-01-SUMMARY 2.md"
rm ".planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-02-PLAN 2.md"
rm ".planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-02-SUMMARY 2.md"
rm ".planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-03-PLAN 2.md"
rm ".planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-03-SUMMARY 2.md"
rm ".planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-04-PLAN 2.md"
rm ".planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-05-PLAN 2.md"
rm ".planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-CONTEXT 2.md"
rm ".planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-DISCUSSION-LOG 2.md"
rm ".planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-RESEARCH 2.md"
rm ".planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-VALIDATION 2.md"
rm ".planning/phases/29-fastapi-skeleton-and-event-loop-foundation/29-VERIFICATION 2.md"
rm ".planning/phases/33-web-monitoring-panels/33-02-SUMMARY 2.md"
```

**verify:**

```bash
find . -name "* 2.*" -not -path "*/.venv/*" -not -path "*/.git/*" -not -path "*/node_modules/*"
# Expected output: empty
```

Also verify test collection still works:

```bash
uv run pytest --collect-only tests/test_web.py 2>&1 | tail -5
# Expected: no ImportError; collects the real test_web.py
```

**done:**
- 23 listed files absent from working tree
- `find` verification returns empty
- Test collector doesn't error on any " 2" reference
- Single atomic commit created for the deletion

## Commit

```
chore(cleanup): remove 23 macOS Finder-duplicate files (* 2.*)

These files accumulated from Finder drag-copy operations. Per
BUGFIX-CONTEXT.md B2, diff confirmed " 2" copies are older stubs.
Zero imports reference them (verified via grep). Safe removal.

Scope: src/alphaswarm/web/{__init__, app, connection_manager,
simulation_manager} 2.py, src/alphaswarm/web/routes/{__init__,
health} 2.py, tests/test_web 2.py, and 15 planning doc twins
under .planning/phases/.
```

## Risk / Rollback

- **Risk:** negligible. All files are untracked (no history to lose). If any were needed they can be reconstructed from their canonical counterparts (which are strictly more complete).
- **Rollback:** `git status` pre-deletion already empty of these files; no index changes to revert.
