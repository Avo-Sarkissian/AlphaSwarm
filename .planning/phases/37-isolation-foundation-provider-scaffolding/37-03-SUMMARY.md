---
phase: 37
plan: 03
subsystem: logging-security
tags: [structlog, pii-redaction, pytest-socket, hypothesis, isol-04, isol-06, security]

requires:
  - phase: 37-01
    provides: sha256_first8 hasher at alphaswarm.security.hashing (consumed by PII processor D-06)
  - phase: 37-01
    provides: pytest-socket==0.7.0 and hypothesis==6.152.1 dev deps (installed in Plan 01)

provides:
  - pii_redaction_processor in alphaswarm.logging (ISOL-04): recursive, case-insensitive, fail-closed
  - shared_processors chain: pii_redaction_processor inserted BEFORE terminal renderer (Pitfall 1)
  - pytest-socket --disable-socket --allow-unix-socket global gate via pyproject.toml (ISOL-06)
  - enable_socket marker registered as D-12 escape hatch
  - 42 PII redaction tests + 3 network gate tests

affects:
  - 37-04 (importlinter canary): PII processor installed and recursive — canary can assert chain order
  - 38+ (all future tests): --disable-socket gate active globally, INET sockets blocked by default
  - tests/conftest.py (Plan 04): auto-marker for integration/ will layer on top of this gate

tech-stack:
  added: []
  patterns:
    - structlog processor chain: pii_redaction_processor at position 5 (after set_exc_info, before renderer)
    - Recursive event_dict walker with id()-based cycle detection and depth bound (8)
    - Case-insensitive separator-agnostic key normalization via _normalize_key (lowercase + strip _-space)
    - Fail-closed via sys.stderr JSON write (bypasses structlog chain entirely, no re-entry risk)
    - pytest-socket --allow-unix-socket: permits asyncio AF_UNIX self-pipe while blocking AF_INET
    - Hypothesis fuzz with SVAL_ prefixed sensitive values to avoid false-positive substring matches in JSON

key-files:
  created:
    - tests/test_pii_redaction.py
    - tests/test_network_gate.py
  modified:
    - src/alphaswarm/logging.py
    - pyproject.toml

key-decisions:
  - "--allow-unix-socket added alongside --disable-socket: asyncio event loop uses AF_UNIX self-pipe internally; blocking it crashes all async tests. AF_INET is still fully blocked."
  - "Hypothesis value strategy uses SVAL_ prefix (min_size=6) to guarantee generated sensitive values are unique substrings in JSON output — avoids false positives where short values like '0' or 'aa' appear in unicode escapes or key names"
  - "pii_redaction_processor signature uses MutableMapping[str, Any] -> Mapping[str, Any] to satisfy structlog.types.Processor type constraint (mypy strict)"
  - "sys.stderr JSON write for fail-closed marker (not structlog safety logger): avoids any risk of structlog chain re-entry if the PII processor itself is broken"

requirements-completed: [ISOL-04, ISOL-06]

duration: 8min
completed: 2026-04-18
---

# Phase 37 Plan 03: PII Redaction Processor + pytest-socket Gate Summary

**Recursive PII redaction processor added to structlog shared_processors chain before renderer; pytest-socket --disable-socket gate enabled globally with --allow-unix-socket for asyncio compatibility and enable_socket escape hatch**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-04-18T16:34:00Z
- **Completed:** 2026-04-18T16:42:41Z
- **Tasks:** 2 (Task 1: PII processor + tests, Task 2: pyproject.toml gate + network gate tests)
- **Files modified:** 2 new test files, 2 modified (logging.py, pyproject.toml)

## Accomplishments

- Implemented `pii_redaction_processor` in `src/alphaswarm/logging.py` with full REVIEW revision (2026-04-18):
  - `_redact_mapping` + `_redact_value`: recursive walk through dicts, lists, tuples, sets
  - `_MAX_REDACTION_DEPTH=8` stack-overflow guard; `id()`-based seen-set cycle detection
  - `_normalize_key`: lowercase + strip `_`, `-`, whitespace — catches `costBasis`, `Cost-Basis`, `HOLDINGS` etc.
  - `_LITERAL_NORMALIZED`: holdings/portfolio/positions/costbasis/qty/shares/positionsbyaccount → `[REDACTED]`
  - `_HASHED_NORMALIZED`: accountnumber/accountid/acctid/acctnumber → `acct:<sha256_first8>`
  - `_PASSTHROUGH_NORMALIZED`: accountnumberhash → pass through (no double-hash)
  - `_FREE_TEXT_NORMALIZED`: currency/SSN regex backstop scoped to note/summary/message/text/description/reason only
  - `_emit_redaction_failed_marker`: writes `{"event": "redaction_failed"}` directly to `sys.stderr` — bypasses structlog chain, no re-entry risk
  - Inserted at position 5 in `shared_processors` — AFTER `set_exc_info`, BEFORE `JSONRenderer`/`ConsoleRenderer` (Pitfall 1)
- Wrote 42 PII redaction tests including Hypothesis nested-variant fuzz (D-08, deadline=2000, max_examples=150)
- Added `--disable-socket --allow-unix-socket` to `[tool.pytest.ini_options]` addopts in pyproject.toml
- Registered `enable_socket` as a named marker in pyproject.toml (D-12 escape hatch)
- Wrote 3 network gate smoke tests: AF_INET blocked, loopback blocked, enable_socket allows creation

## Review Concerns Closed

| Concern | Source | Resolution |
|---------|--------|------------|
| Recursive sanitization misses nested payloads | Codex HIGH | `_redact_mapping`/`_redact_value` walk full tree; `test_processor_recurses_into_nested_dict` + list/tuple variants |
| Fail-closed recursion risk | Codex HIGH | `sys.stderr` direct JSON write, never structlog; `test_safety_marker_bypasses_structlog_chain` |
| Case-insensitive/variant key matching | Codex+Gemini HIGH/MEDIUM | `_normalize_key` lowercases + strips separators; 8-variant parametrized test |
| Over-redaction of market prices | Codex MEDIUM | Regex scoped to `_FREE_TEXT_NORMALIZED`; `test_processor_does_NOT_scrub_currency_in_non_free_text_key` |
| account_number_hash double-hash | Codex MEDIUM | `_PASSTHROUGH_NORMALIZED` set; `test_account_number_hash_is_not_rehashed` |
| Hypothesis flaky deadline | Codex LOW | `deadline=2000, max_examples=150` |

## Files Created/Modified

- `src/alphaswarm/logging.py` — Full rewrite with PII processor, recursive walker, safety bypass
- `tests/test_pii_redaction.py` — 42 tests: tabular, variant-case, recursion, cycle/depth, fail-closed, fuzz
- `tests/test_network_gate.py` — 3 tests: raw socket blocked, loopback blocked, enable_socket opt-in
- `pyproject.toml` — addopts with `--disable-socket --allow-unix-socket`, markers declaration

## Decisions Made

- **`--allow-unix-socket` alongside `--disable-socket`**: asyncio event loop uses an AF_UNIX socket pair as its internal wakeup self-pipe. Blocking it prevents all async tests from running. Adding `--allow-unix-socket` allows the AF_UNIX self-pipe while still blocking all AF_INET socket creation and connection. The network gate tests confirm AF_INET (raw socket creation + loopback connect) remain blocked.
- **Hypothesis SVAL_ prefix on sensitive values**: Generated sensitive values use a `SVAL_` prefix with min_size=6 to guarantee they form unique substrings in rendered JSON. Short values (e.g., `'0'`, `'aa'`) would appear inside unicode escapes (`\u00b5`) or safe key names (`'aaa'`), creating false positives. The prefix makes false matches impossible without compromising fuzz coverage.
- **`MutableMapping` processor signature**: structlog's `Processor` type requires `Callable[[Any, str, MutableMapping[str, Any]], Mapping[str, Any] | ...]`. Using `dict[str, Any]` narrower type fails mypy strict. The processor converts `event_dict` to `dict` internally via `dict(event_dict)` before passing to `_redact_mapping`.

## Deviations from Plan

**1. [Rule 1 - Bug] Hypothesis strategy definition order**
- **Found during:** Task 1 GREEN phase
- **Issue:** `_SAFE_KEY_STRATEGY` referenced `_normalize_safe` before it was defined (module-level ordering error in plan's code template)
- **Fix:** Moved `_normalize_safe` function definition above `_SAFE_KEY_STRATEGY` assignment
- **Files modified:** `tests/test_pii_redaction.py`

**2. [Rule 1 - Bug] Hypothesis false-positive sensitive value match**
- **Found during:** Task 1 GREEN phase
- **Issue:** Short sensitive values (e.g., `'0'`, `'aa'`) generated by `st.text(min_size=1)` coincidentally appeared in unicode escape sequences or as substrings of key names in rendered JSON, causing the fuzz assertion to fail even though no actual leakage occurred
- **Fix:** Changed `_VALUE_STRATEGY` to use `st.text(min_size=6).map(lambda s: f"SVAL_{s}")` — guarantees unique, identifiable sensitive values
- **Files modified:** `tests/test_pii_redaction.py`

**3. [Rule 2 - Missing critical functionality] `--allow-unix-socket` required for asyncio compatibility**
- **Found during:** Task 2 GREEN phase, full suite run
- **Issue:** `--disable-socket` alone blocks `asyncio`'s internal AF_UNIX self-pipe, causing `INTERNALERROR` and `SocketBlockedError` in all async tests (including the entirely unrelated `test_governor_stub_async`)
- **Fix:** Added `--allow-unix-socket` to addopts alongside `--disable-socket`. This allows asyncio internals while keeping all AF_INET sockets blocked. D-09 intent (block network calls) is fully preserved.
- **Files modified:** `pyproject.toml`

**4. [Rule 1 - Bug] mypy strict type errors in logging.py**
- **Found during:** Task 1 acceptance criteria check
- **Issue:** `pii_redaction_processor` used `dict[str, Any]` return type instead of `Mapping[str, Any]`; `get_logger` had unresolved `no-any-return`
- **Fix:** Updated processor signature to `MutableMapping[str, Any] -> Mapping[str, Any]`; added `# type: ignore[no-any-return]` on `get_logger` return
- **Files modified:** `src/alphaswarm/logging.py`

## Pre-existing Test Failures (Not Caused by Plan 03)

These failures exist on the base commit and are out of scope:

| Test File | Count | Root Cause |
|-----------|-------|------------|
| `tests/test_report.py` | 19 | `ReportAssembler` missing methods (pre-Phase 37 stub) |
| `tests/test_replay_red.py` | 1 | Replay module scaffold pending |
| `tests/test_graph_integration.py` | 15 | Neo4j server not running (expected; integration tests) |

## Known Stubs

None — this plan creates complete, functional implementations with no data-path stubs.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns introduced. The PII processor reduces the threat surface (T-37-14 through T-37-25 all mitigated).

## Verification

```
uv run pytest tests/test_pii_redaction.py tests/test_network_gate.py tests/test_logging.py -v
# 49 passed in 0.37s

uv run mypy src/alphaswarm/logging.py
# Success: no issues found in 1 source file

uv run python -c "from alphaswarm.logging import configure_logging, pii_redaction_processor; print('ok')"
# ok
```

## Next Phase Readiness

- Plan 37-04 (importlinter canary) unblocked: PII processor is installed and recursive (can assert chain ordering invariant)
- All future plans: pytest-socket gate active globally — any test that calls an INET socket will fail explicitly rather than silently, providing reliable isolation
- Plan 04 conftest auto-marker: the `enable_socket` marker escape hatch is registered and ready for directory-scoped auto-application in `tests/integration/`

---
*Phase: 37-isolation-foundation-provider-scaffolding*
*Completed: 2026-04-18*
