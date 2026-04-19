---
phase: 05-seed-injection-and-agent-personas
plan: 02
subsystem: simulation
tags: [ollama, neo4j, argparse, seed-injection, entity-extraction, cli]

# Dependency graph
requires:
  - phase: 05-01
    provides: "Domain types (SeedEvent, SeedEntity, ParsedSeedResult, EntityType) and parse_seed_event() 3-tier parser"
  - phase: 04
    provides: "GraphStateManager with create_cycle(), write_decisions(), read_peer_decisions()"
  - phase: 02
    provides: "OllamaClient.chat() with format/think support, OllamaModelManager load/unload"
provides:
  - "inject_seed() end-to-end pipeline: orchestrator LLM parse -> atomic Neo4j persist -> model cleanup"
  - "create_cycle_with_seed_event() for single-transaction Cycle+Entity+MENTIONS persistence"
  - "Entity node schema constraint (name+type uniqueness)"
  - "CLI inject subcommand with argparse routing"
  - "Overall sentiment persisted on Cycle node"
affects: [06-cascade-rounds, 07-prompt-engineering, 09-tui-dashboard]

# Tech tracking
tech-stack:
  added: [argparse]
  patterns: [atomic-graph-transactions, cli-subcommand-routing, model-lifecycle-finally]

key-files:
  created:
    - src/alphaswarm/seed.py
    - src/alphaswarm/cli.py
    - tests/test_seed_pipeline.py
    - tests/test_cli.py
  modified:
    - src/alphaswarm/graph.py
    - src/alphaswarm/__main__.py
    - tests/test_graph.py
    - tests/test_app.py
    - tests/conftest.py

key-decisions:
  - "Atomic create_cycle_with_seed_event replaces separate create_cycle+write_seed_event to prevent orphan Cycle nodes"
  - "Entity uniqueness constraint on (name, type) composite key for MERGE idempotency"
  - "ORCHESTRATOR_SYSTEM_PROMPT uses in-prompt chain-of-thought to compensate for think+format=json incompatibility"
  - "CLI uses argparse subparsers for extensible subcommand routing"

patterns-established:
  - "Atomic graph transaction: single execute_write wrapping Cycle+Entity+relationship creation"
  - "Model lifecycle in finally block: orchestrator loaded before extraction, unloaded after even on error"
  - "CLI subcommand pattern: argparse subparsers with async handler functions"

requirements-completed: [SIM-01, SIM-02, SIM-03]

# Metrics
duration: 8min
completed: 2026-03-25
---

# Phase 5 Plan 2: Seed Injection Pipeline and CLI Summary

**End-to-end seed injection pipeline with atomic Cycle+Entity Neo4j persistence, orchestrator model lifecycle, and argparse CLI inject subcommand**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-25T17:09:03Z
- **Completed:** 2026-03-25T17:17:29Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments
- inject_seed() pipeline orchestrates model load, LLM chat with format=json+think, 3-tier parse, atomic Neo4j persist, and model unload with finally-block safety
- create_cycle_with_seed_event() creates Cycle+Entity+MENTIONS in a single transaction, preventing orphan Cycle nodes on partial failure
- Entity uniqueness constraint added to SCHEMA_STATEMENTS for MERGE idempotency
- CLI inject subcommand with ensure_schema(), driver close in finally, and formatted output showing parse tier and entity table
- __main__.py refactored to 6-line thin shim delegating to cli.main()

## Task Commits

Each task was committed atomically:

1. **Task 1: Atomic graph Entity persistence and seed injection pipeline**
   - `365b44c` (test) - Failing tests for create_cycle_with_seed_event and inject_seed
   - `eba845f` (feat) - Implement graph Entity persistence and seed injection pipeline

2. **Task 2: CLI module with inject subcommand and __main__.py refactor**
   - `7254f8b` (test) - Failing tests for CLI module
   - `bad7aca` (feat) - Implement CLI module, refactor __main__.py

## Files Created/Modified
- `src/alphaswarm/seed.py` - Seed injection pipeline: inject_seed() with orchestrator model lifecycle and ORCHESTRATOR_SYSTEM_PROMPT
- `src/alphaswarm/cli.py` - CLI entry point with argparse subcommand routing, inject handler, banner, injection summary output
- `src/alphaswarm/graph.py` - Extended with create_cycle_with_seed_event(), Entity constraint, _create_cycle_with_entities_tx
- `src/alphaswarm/__main__.py` - Refactored to thin shim delegating to cli.main()
- `tests/test_seed_pipeline.py` - 9 unit tests for inject_seed pipeline with mocked Ollama and graph
- `tests/test_cli.py` - 9 unit tests for CLI parsing, output formatting, and error handling
- `tests/test_graph.py` - Extended with 7 new tests for create_cycle_with_seed_event
- `tests/test_app.py` - Updated test_main_entry_point and test_main_invalid_config for argparse compatibility
- `tests/conftest.py` - Entity node cleanup added to graph_manager fixture

## Decisions Made
- Atomic create_cycle_with_seed_event replaces separate create_cycle+write_seed_event calls to prevent orphan Cycle nodes on partial failure
- Entity uniqueness constraint uses composite (name, type) key so MERGE is idempotent across cycles
- ORCHESTRATOR_SYSTEM_PROMPT includes explicit JSON schema instructions to compensate for think+format=json incompatibility (Pitfall 1 from research)
- CLI uses argparse subparsers (not click/typer) to avoid new dependencies per RESEARCH.md recommendation

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed existing test_app.py tests for argparse compatibility**
- **Found during:** Task 2 (CLI implementation)
- **Issue:** Existing test_main_entry_point and test_main_invalid_config tests in test_app.py called main() without monkeypatching sys.argv, causing argparse to parse pytest's arguments
- **Fix:** Added monkeypatch.setattr("sys.argv", ["alphaswarm"]) to both tests
- **Files modified:** tests/test_app.py
- **Verification:** All 238 tests pass
- **Committed in:** bad7aca (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug fix)
**Impact on plan:** Necessary fix for backward compatibility with existing test suite. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 5 is now complete: seed injection pipeline, domain types, parsing, Entity persistence, and CLI entry point are all operational
- Ready for Phase 6 cascade rounds to use inject_seed() output and create_cycle_with_seed_event() for simulation
- inject_seed() returns (cycle_id, ParsedSeedResult) which Phase 6 needs to initiate round 1

---
## Self-Check: PASSED

All 9 files verified (4 created, 5 modified). All 4 task commits found. SUMMARY.md exists.

---
*Phase: 05-seed-injection-and-agent-personas*
*Completed: 2026-03-25*
