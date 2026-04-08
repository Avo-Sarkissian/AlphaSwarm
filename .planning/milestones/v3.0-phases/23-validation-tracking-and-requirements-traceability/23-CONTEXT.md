# Phase 23: Validation Tracking and Requirements Traceability - Context

**Gathered:** 2026-04-08
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix documentation artifacts: update stale test references in VALIDATION.md files for phases 17, 19, and 20; create a missing VALIDATION.md for Phase 16; and add v3 requirements (TICK-*, DATA-*, ENRICH-*, DECIDE-*, DTUI-*, DRPT-*) to REQUIREMENTS.md with full descriptions and traceability rows.

This phase does NOT write new tests, change source code, or add new functionality — only corrects documentation and planning artifacts to reflect the actual codebase state.

</domain>

<decisions>
## Implementation Decisions

### v3 Requirements in REQUIREMENTS.md
- **D-01:** Add a full "## v3 Requirements" section to REQUIREMENTS.md matching v1/v2 format — each requirement ID gets a description, `[x]` checkbox, and a "Maps to" annotation. Do NOT use a table-only approach.
- **D-02:** Add corresponding traceability rows to the existing `## Traceability` table at the bottom of REQUIREMENTS.md for all 16 v3 req IDs (TICK-01/02/03, DATA-01/02/03/04, ENRICH-01/02/03, DECIDE-01/02, DTUI-01/02/03, DRPT-01).
- **D-03:** Update the Coverage summary line to include v3 counts.

### VALIDATION.md Reconciliation (phases 17, 19, 20)
- **D-04:** Full reconciliation — fix stale test class/method names AND update status fields: set `nyquist_compliant: true`, `wave_0_complete: true`, and task status to ✅ for entries where tests now exist and pass.
- **D-05:** Phase 17 (`17-VALIDATION.md`): Replace stale method-level refs (e.g., `test_snapshot_model_valid`) with actual class-level refs: `TestMarketDataSnapshotModel`, `TestYfinanceFetch`, `TestFallbackDegradation`, `TestDiskCache` in `tests/test_market_data.py`.
- **D-06:** Phase 19 (`19-VALIDATION.md`): Replace `tests/test_consensus.py::*` references (file does not exist) with actual `tests/test_tui.py::test_ticker_consensus_panel_*` methods that exist. Remove the Wave 0 stub requirement for `test_consensus.py`.
- **D-07:** Phase 20 (`20-VALIDATION.md`): Classes `TestReportAssemblerMarketContext`, `TestMarketContextTemplate` (test_report.py) and `TestWriteTickerConsensus`, `TestReadMarketContext` (test_graph.py) already exist — no name changes needed. Update status to ✅ and flip reconciliation flags.

### Phase 16 VALIDATION.md (new file)
- **D-08:** Create `16-VALIDATION.md` covering all three test files: `tests/test_ticker_validator.py` (TICK-01/02), `tests/test_seed_pipeline.py` (TICK-03 inject pipeline), `tests/test_cli.py` (TICK-03 CLI inject command).
- **D-09:** Set `nyquist_compliant: true` and `wave_0_complete: true` immediately (tests already exist). Map each test class/method to its TICK requirement.
- **D-10:** Set all task statuses to ✅ for tests confirmed to exist in the test suite.

### Claude's Discretion
- Which specific test methods to list per VALIDATION.md task row (use class-level refs where individual method mapping is unclear)
- Whether to retain the Manual-Only Verifications section from existing VALIDATION.md files as-is

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Files to update
- `.planning/REQUIREMENTS.md` — add v3 section + traceability rows; existing format is the template to match
- `.planning/phases/17-market-data-pipeline/17-VALIDATION.md` — stale test names to fix
- `.planning/phases/19-per-stock-tui-consensus-display/19-VALIDATION.md` — fix missing test_consensus.py refs
- `.planning/phases/20-report-enhancement-and-integration-hardening/20-VALIDATION.md` — reconcile statuses

### Source of truth for requirements
- `.planning/ROADMAP.md` — canonical v3 req IDs, phase assignments, success criteria descriptions

### Actual test inventories (read before updating VALIDATION.md files)
- `tests/test_market_data.py` — Phase 17 tests: `TestMarketDataSnapshotModel`, `TestYfinanceFetch`, `TestFallbackDegradation`, `TestDiskCache`
- `tests/test_tui.py` — Phase 19 tests: `test_ticker_consensus_panel_*` methods (title, empty_state_idle, awaiting_state_round1/2, render_header_both_signals, render_header_agree, render_bracket_bars, multiple_tickers, majority_pct_display)
- `tests/test_report.py` — Phase 20 tests: `TestReportAssemblerMarketContext`, `TestMarketContextTemplate`
- `tests/test_graph.py` — Phase 20 tests: `TestWriteTickerConsensus`, `TestReadMarketContext`
- `tests/test_ticker_validator.py` — Phase 16 tests: 16 methods covering load/validate/download/cache (TICK-01/02)
- `tests/test_seed_pipeline.py` — Phase 16 tests: inject pipeline (TICK-03)
- `tests/test_cli.py` — Phase 16 tests: CLI inject command (TICK-03)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- Existing VALIDATION.md files (phases 01-15, 17-21) — use as format template for the new Phase 16 VALIDATION.md
- Existing REQUIREMENTS.md v1/v2 sections — use as format template for the v3 section

### Established Patterns
- VALIDATION.md frontmatter: `phase`, `slug`, `status`, `nyquist_compliant`, `wave_0_complete`, `created`
- Task status symbols: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky
- REQUIREMENTS.md format: `- [x] **REQ-ID**: Description` with phase annotation
- Traceability table columns: `| Requirement | Phase | Status |`

### Integration Points
- Phase 16 VALIDATION.md must follow the same Nyquist Per-Task Verification Map schema used in phases 17-20
- Traceability table rows must be inserted under the existing `## Traceability` section (not a new section)

</code_context>

<specifics>
## Specific Ideas

- Phase 19's `test_consensus.py` references are dead — `test_tui.py` is where ticker consensus tests live (`test_ticker_consensus_panel_*` methods confirmed present)
- Phase 20 VALIDATION.md is the most correct of the three; primary change is flipping status fields
- The v3 requirements need descriptions derived from ROADMAP.md success criteria — use those as the source

</specifics>

<deferred>
## Deferred Ideas

None — analysis stayed within phase scope.

</deferred>

---

*Phase: 23-validation-tracking-and-requirements-traceability*
*Context gathered: 2026-04-08*
