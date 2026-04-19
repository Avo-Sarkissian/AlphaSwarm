# Deferred Items - Phase 02

## Pre-existing Lint/Type Issues (Out of Scope)

### ruff UP042: str + Enum inheritance pattern
- **Files:** src/alphaswarm/types.py (BracketType, SignalType, SimulationPhase)
- **Issue:** ruff UP042 recommends `StrEnum` over `(str, Enum)` pattern
- **Origin:** Phase 1 code
- **Fix:** Change to `enum.StrEnum` (requires Python 3.11+, which is the floor)

### ruff I001: Import sorting in __main__.py
- **File:** src/alphaswarm/__main__.py
- **Issue:** Import block is un-sorted or un-formatted
- **Origin:** Phase 1 code
- **Fix:** Run `ruff check --fix src/alphaswarm/__main__.py`

### mypy no-any-return in logging.py
- **File:** src/alphaswarm/logging.py:46
- **Issue:** Returning Any from function declared to return BoundLogger
- **Origin:** Phase 1 code
- **Fix:** Add explicit type annotation or cast
