---
phase: 26-shock-injection-core
plan: "03"
subsystem: state-graph
tags: [tdd, shock-injection, state-store, neo4j, wave-1]
dependency_graph:
  requires:
    - phase: 26-01
      provides: test_shock_queue_roundtrip + test_shock_window_event_reflects_state stubs (test_state.py)
    - phase: 26-01
      provides: test_write_shock_event_* + test_ensure_schema_includes_shock_cycle_index stubs (test_graph.py)
  provides:
    - StateStore shock bridge (6 accessor methods + SHOCK_TEXT_MAX_LEN + 3 init fields)
    - GraphStateManager.write_shock_event() + _write_shock_event_tx + shock_cycle_idx schema index
    - SHOCK-01, SHOCK-02, SHOCK-03 formal requirements in REQUIREMENTS.md
  affects: [26-04, 26-05]
tech_stack:
  added: []
  patterns:
    - "asyncio.Queue(maxsize=1) single-slot shock queue — TUI edge-latch guarantees at most one pending submit per window"
    - "asyncio.Event for shock_window — synchronous is_set() readable from sync _poll_snapshot TUI callback"
    - "strip + truncate policy in submit_shock() — SHOCK_TEXT_MAX_LEN = 4096 caps prompt inflation across 100 agents"
    - "session-per-method pattern for write_shock_event() — mirrors create_cycle() and write_decisions() conventions"
    - "Static txfn (_write_shock_event_tx) for Cypher inspection in tests — Codex MEDIUM concern addressed"
key_files:
  created: []
  modified:
    - src/alphaswarm/state.py
    - src/alphaswarm/graph.py
    - .planning/REQUIREMENTS.md
    - tests/test_state.py
    - tests/test_graph.py
decisions:
  - "SHOCK_TEXT_MAX_LEN = 4096 added per 2026-04-11 reviews revision (Codex MEDIUM) — prevents multi-MB input from inflating 100 agent prompts and hitting M1 memory pressure"
  - "submit_shock() normalizes empty string after strip to None (skip signal) — consistent with CONTEXT.md D-07"
  - "Module-level _log = structlog.get_logger(component='state') added to state.py for shock_text_truncated warning — avoids inline import anti-pattern"
  - "write_shock_event wraps Neo4jError with original_error=exc kwarg — matches existing graph.py error convention and satisfies test assertion"
  - "Pre-existing mypy errors in graph.py (lines 750/817/884) confirmed out of scope — exist in base commit 21237c4, zero new mypy issues introduced"
metrics:
  duration: "~3 minutes"
  completed: "2026-04-11"
  tasks_completed: 2
  files_modified: 5
---

# Phase 26 Plan 03: StateStore Shock Bridge + GraphStateManager ShockEvent Summary

**One-liner:** StateStore shock queue/window bridge with 4096-char length cap + GraphStateManager.write_shock_event() persisting ShockEvent nodes via HAS_SHOCK, turning 7 RED stubs GREEN.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | StateStore shock bridge + REQUIREMENTS.md | d06aba1 | src/alphaswarm/state.py, .planning/REQUIREMENTS.md, tests/test_state.py |
| 2 | GraphStateManager.write_shock_event() + schema index | e6313c0 | src/alphaswarm/graph.py, tests/test_graph.py |

## Files Modified

### src/alphaswarm/state.py (+102 lines)
- Added `import structlog` and module-level `_log = structlog.get_logger(component="state")`
- Added `SHOCK_TEXT_MAX_LEN: int = 4096` constant at module level with full docstring explaining reviews revision rationale
- Added 3 fields to `StateStore.__init__`:
  - `self._shock_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=1)`
  - `self._shock_window: asyncio.Event = asyncio.Event()`
  - `self._shock_next_round: int | None = None`
- Added 6 accessor methods after `push_rationale`:
  - `async def request_shock(next_round: int) -> None` — sets shock_window event, stores next_round
  - `async def close_shock_window() -> None` — clears shock_window event, clears next_round
  - `def is_shock_window_open() -> bool` — synchronous (TUI _poll_snapshot compat)
  - `def shock_next_round() -> int | None` — synchronous
  - `async def submit_shock(shock_text: str | None) -> None` — strip + truncate + enqueue
  - `async def await_shock() -> str | None` — blocks until TUI submits

### src/alphaswarm/graph.py (+70 lines)
- Appended `"CREATE INDEX shock_cycle_idx IF NOT EXISTS FOR (s:ShockEvent) ON (s.cycle_id)"` to `SCHEMA_STATEMENTS`
- Added `async def write_shock_event(cycle_id, shock_text, injected_before_round) -> str` — generates UUID4 shock_id, calls execute_write, wraps Neo4jError in Neo4jWriteError(msg, original_error=exc), logs shock_event_written
- Added `@staticmethod async def _write_shock_event_tx(tx, shock_id, cycle_id, shock_text, injected_before_round) -> None` — issues MATCH Cycle + CREATE ShockEvent + CREATE HAS_SHOCK Cypher with parameterized inputs

### .planning/REQUIREMENTS.md (+13 lines)
- Added `### Shock Injection` subsection under `## v4 Requirements` with SHOCK-01, SHOCK-02, SHOCK-03 checkbox entries
- Added 3 traceability table rows: SHOCK-01/02/03 → Phase 26: Shock Injection Core → In Progress
- Updated Coverage line: `v4 requirements: 10 total, 10 mapped (7 Complete, 3 In Progress)`
- Updated footer timestamp to `2026-04-11 — Phase 26 reviews revision (SHOCK-01/02/03 added)`

### tests/test_state.py (+59 lines net)
Replaced 2 `pytest.fail` stubs and added 1 new test:
1. `test_shock_queue_roundtrip` — verifies text roundtrip, None passthrough, whitespace-only→None
2. `test_shock_window_event_reflects_state` — verifies request_shock/close_shock_window/is_shock_window_open/shock_next_round
3. `test_shock_text_truncation` (new — reviews revision) — verifies 4596-char input truncated to 4096

### tests/test_graph.py (+97 lines net)
Replaced 4 `pytest.fail` stubs:
1. `test_write_shock_event_creates_node_and_edge` — inspects actual Cypher via static txfn (Codex MEDIUM fix)
2. `test_write_shock_event_returns_uuid` — verifies UUID4 format via regex
3. `test_write_shock_event_wraps_driver_errors` — verifies Neo4jWriteError wrapping + original_error kwarg
4. `test_ensure_schema_includes_shock_cycle_index` — verifies shock_cycle_idx in SCHEMA_STATEMENTS

## Test Results

| Suite | Before | After |
|-------|--------|-------|
| tests/test_state.py | 22 passed, 2 stubs failing | 25 passed (0 failed) |
| tests/test_graph.py | 62 passed, 4 stubs failing | 66 passed (0 failed) |
| Combined | 84 passed, 6 failing | 91 passed (0 failed) |

## StateStore API Surface Added

```python
SHOCK_TEXT_MAX_LEN: int = 4096

class StateStore:
    async def request_shock(self, next_round: int) -> None: ...
    async def close_shock_window(self) -> None: ...
    def is_shock_window_open(self) -> bool: ...
    def shock_next_round(self) -> int | None: ...
    async def submit_shock(self, shock_text: str | None) -> None: ...
    async def await_shock(self) -> str | None: ...
```

## GraphStateManager API Surface Added

```python
async def write_shock_event(
    self,
    cycle_id: str,
    shock_text: str,
    injected_before_round: int,
) -> str: ...  # returns UUID4 shock_id
```

## Deviations from Plan

**1. [Rule 2 - Missing Critical Functionality] Module-level structlog logger added to state.py**
- **Found during:** Task 1, implementing submit_shock()
- **Issue:** The plan's action item noted "inline import structlog" as a fallback if no module logger exists. state.py had no module-level logger.
- **Fix:** Added `import structlog` and `_log = structlog.get_logger(component="state")` at module level — cleaner than inline import on every submit_shock() call, consistent with graph.py pattern.
- **Files modified:** src/alphaswarm/state.py
- **Commit:** d06aba1

**2. [Out of Scope - Pre-existing] mypy errors in graph.py lines 750/817/884**
- 3 pre-existing `[type-arg]` mypy errors confirmed present in base commit 21237c4 — zero new errors introduced by this plan. Logged to deferred-items per scope boundary rule.

## Reviews Revision Notes (2026-04-11)

**Codex MEDIUM — length cap:** `SHOCK_TEXT_MAX_LEN = 4096` added. `submit_shock()` strips, normalizes empty→None, and truncates with `shock_text_truncated` warning log. `test_shock_text_truncation` validates this path.

**Codex MEDIUM — Cypher inspection:** `test_write_shock_event_creates_node_and_edge` calls `_write_shock_event_tx` directly with a mock transaction and asserts the actual Cypher string contains `ShockEvent`, `HAS_SHOCK`, `MATCH (c:Cycle`, `CREATE (se:ShockEvent`, `CREATE (c)-[:HAS_SHOCK]->(se)` — not just that `execute_write` was called.

## Known Stubs

None — all 7 stubs from Plan 01 in this plan's scope are now implemented.

## Next Step

- **Plan 04** (TUI ShockInputScreen) consumes `StateStore.is_shock_window_open()`, `shock_next_round()`, and `submit_shock()` from this plan
- **Plan 05** (simulation wiring) consumes `StateStore.request_shock()`, `close_shock_window()`, `await_shock()`, `GraphStateManager.write_shock_event()`, and `ResourceGovernor.suspend()`/`resume()` from Plans 02+03

## Self-Check: PASSED

- src/alphaswarm/state.py modified: FOUND
- src/alphaswarm/graph.py modified: FOUND
- .planning/REQUIREMENTS.md modified: FOUND
- tests/test_state.py modified: FOUND
- tests/test_graph.py modified: FOUND
- `grep -c "SHOCK_TEXT_MAX_LEN" src/alphaswarm/state.py` = 5 (≥3): VERIFIED
- `grep -c "def request_shock" src/alphaswarm/state.py` = 1: VERIFIED
- `grep -c "write_shock_event" src/alphaswarm/graph.py` = 3 (≥3): VERIFIED
- `grep -c "shock_cycle_idx" src/alphaswarm/graph.py` = 1: VERIFIED
- `grep -c "SHOCK-01" .planning/REQUIREMENTS.md` = 3 (≥2): VERIFIED
- `grep -c "Phase 26: Shock Injection Core" .planning/REQUIREMENTS.md` = 3: VERIFIED
- 91 tests passed (test_state.py + test_graph.py), 0 failures: VERIFIED
- Commit d06aba1: FOUND
- Commit e6313c0: FOUND
