---
phase: 13-dynamic-persona-generation
plan: 01
subsystem: inference
tags: [pydantic, dataclass, parsing, sanitization, persona-generation]

# Dependency graph
requires:
  - phase: 05-seed-injection-and-agent-personas
    provides: BracketType, SeedEntity, SeedEvent, ParsedSeedResult, generate_personas, BRACKET_MODIFIERS
provides:
  - ParsedModifiersResult frozen dataclass for modifier parse observability
  - sanitize_entity_name() for prompt injection prevention
  - _truncate_modifier() for word-boundary modifier capping
  - parse_modifier_response() with 3-tier fallback for orchestrator output
  - generate_personas() now accepts optional modifiers kwarg for dynamic persona generation
affects: [13-02-PLAN, simulation, persona-pipeline]

# Tech tracking
tech-stack:
  added: [unicodedata]
  patterns: [3-tier-parse-fallback, per-bracket-fallback, keyword-only-optional-parameter]

key-files:
  created: []
  modified:
    - src/alphaswarm/types.py
    - src/alphaswarm/config.py
    - src/alphaswarm/parsing.py
    - tests/test_seed.py
    - tests/test_config.py
    - tests/test_parsing.py
    - tests/test_personas.py

key-decisions:
  - "Local import of BRACKET_MODIFIERS inside parse_modifier_response to avoid circular dependency (config imports types, parsing would circularly import config)"
  - "sanitize_entity_name strips Cc and Cf Unicode categories while preserving all punctuation for real entity names like S&P 500"
  - "_truncate_modifier uses word-boundary truncation at 150 chars to avoid mid-word cuts in LLM-generated modifiers"
  - "generate_personas modifiers parameter is keyword-only with None default to guarantee backward compatibility"

patterns-established:
  - "3-tier modifier parsing: direct JSON -> code-fence strip -> static fallback (mirrors seed parse pattern)"
  - "Per-bracket fallback: missing keys in partial JSON get static BRACKET_MODIFIERS[bracket][0]"
  - "Case-insensitive key normalization: all JSON keys lowercased before BracketType enum lookup"

requirements-completed: [PERSONA-01, PERSONA-02]

# Metrics
duration: 5min
completed: 2026-04-02
---

# Phase 13 Plan 01: Dynamic Persona Data Layer Summary

**ParsedModifiersResult type, sanitize_entity_name helper, 3-tier parse_modifier_response, and generate_personas with optional modifiers kwarg -- 18 new tests green**

## Performance

- **Duration:** 5 min
- **Started:** 2026-04-02T03:37:07Z
- **Completed:** 2026-04-02T03:42:00Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- ParsedModifiersResult frozen dataclass with modifiers dict and parse_tier for observability
- sanitize_entity_name() strips Cc/Cf Unicode categories while preserving real punctuation (S&P 500, Berkshire's)
- parse_modifier_response() with 3-tier fallback matching existing seed parse pattern, plus per-bracket fallback and case normalization
- generate_personas() now accepts optional modifiers kwarg -- backward compatible with all 12 existing persona tests unchanged

## Task Commits

Each task was committed atomically:

1. **Task 1: Types, sanitization, and parse function with tests**
   - `6b19d9c` (test): failing tests for ParsedModifiersResult, sanitize_entity_name, parse_modifier_response
   - `7507a8d` (feat): implement ParsedModifiersResult, sanitize_entity_name, parse_modifier_response
2. **Task 2: Modify generate_personas() to accept optional modifiers and add tests**
   - `c2301c6` (test): failing tests for generate_personas with modifiers kwarg
   - `dfb1dcc` (feat): modify generate_personas to accept optional modifiers kwarg

## Files Created/Modified
- `src/alphaswarm/types.py` - Added ParsedModifiersResult frozen dataclass
- `src/alphaswarm/config.py` - Added sanitize_entity_name(), _truncate_modifier(), modified generate_personas() signature
- `src/alphaswarm/parsing.py` - Added parse_modifier_response() with 3-tier fallback
- `tests/test_seed.py` - 2 new tests for ParsedModifiersResult
- `tests/test_config.py` - 6 new tests for sanitize_entity_name and _truncate_modifier
- `tests/test_parsing.py` - 5 new tests for parse_modifier_response
- `tests/test_personas.py` - 5 new tests for generate_personas with modifiers

## Decisions Made
- Local import of BRACKET_MODIFIERS inside parse_modifier_response to avoid circular dependency
- sanitize_entity_name strips Cc and Cf Unicode categories (not just ASCII control chars) for comprehensive format character removal
- generate_personas modifiers parameter is keyword-only (after *) with None default for strict backward compatibility
- conftest.py NOT modified -- all_personas fixture works unchanged with default None parameter

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Known Stubs

None - all functions are fully implemented with complete test coverage.

## Next Phase Readiness
- All data layer contracts established for Plan 02 (LLM integration)
- parse_modifier_response() ready to receive orchestrator output
- generate_personas(modifiers=...) ready to be called with ParsedModifiersResult.modifiers
- sanitize_entity_name() ready for entity name sanitization in modifier prompt template

---
*Phase: 13-dynamic-persona-generation*
*Completed: 2026-04-02*
