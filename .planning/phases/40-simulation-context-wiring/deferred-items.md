# Phase 40 — Deferred Items (pre-existing, out of scope)

Discovered during Plan 01 execution (2026-04-19). These mypy errors in
`src/alphaswarm/simulation.py` pre-exist the Plan 01 changes (verified via
`git stash` + mypy re-run). They are NOT caused by market_context plumbing
and fall outside Plan 01's scope boundary.

## Pre-existing mypy strict errors in simulation.py (verified on base commit 2f841ca)

| Line | Code | Error |
|------|------|-------|
| 28 | attr-defined | Module "alphaswarm.config" does not explicitly export attribute "BracketConfig" |
| 107 | assignment | Incompatible types in assignment (expression has type "str \| None", variable has type "str") |
| 1179/1185 | type-arg | Missing type parameters for generic type "dict" |
| 1198/1204 | type-arg | Missing type parameters for generic type "dict" |
| 1201/1207 | type-arg | Missing type parameters for generic type "dict" |
| 1238/1244 | call-arg | Unexpected keyword argument "system" for "generate" of OllamaClient |

(Line numbers shift by +6 after Plan 01 due to run_round1 docstring extension.)

## Disposition

- **Not fixed in Plan 01.** These errors are independent of the market_context
  threading change. Plan 01 verification confirms the three files (worker.py,
  batch_dispatcher.py, simulation.py) show the same error set before and after
  Plan 01 changes — no new errors introduced.
- **Consider a quick fix** once v6.0 milestone work lands, likely under a
  dedicated typing-cleanup plan or a `/gsd:quick` ticket.
