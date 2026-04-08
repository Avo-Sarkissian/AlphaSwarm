# Phase 22: Fix Report Tool Name Mismatch - Context

**Gathered:** 2026-04-08
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix two stale tool name references in `REACT_SYSTEM_PROMPT` (`report.py`) so the ReACT agent calls tools that exist in the runtime registry. Also update the description text for the renamed tools and update the parser test that uses the old name.

This phase does NOT add new tools, new report sections, or new behaviors — only corrects mismatched identifiers between the system prompt and the registered tool dict.

</domain>

<decisions>
## Implementation Decisions

### System Prompt Tool Names
- **D-01:** Change `consensus_summary` → `bracket_summary` in `REACT_SYSTEM_PROMPT` (line 32 of `src/alphaswarm/report.py`)
- **D-02:** Change `signal_flips` → `signal_flip_analysis` in `REACT_SYSTEM_PROMPT` (line 37 of `src/alphaswarm/report.py`)
- No other tool names in the system prompt need changing — all 6 others already match the runtime registry

### System Prompt Description Text
- **D-03:** Update the description for `bracket_summary` to: `Get per-bracket consensus summary (BUY/SELL/HOLD counts per bracket for Round 3)`
- **D-04:** Keep the description for `signal_flip_analysis` as: `Get agents who changed position between rounds` (already accurate)

### Test Updates
- **D-05:** Update `tests/test_report.py:34` (`test_basic_extraction`) to use `bracket_summary` instead of `consensus_summary` as the ACTION string — keeps test strings consistent with real tool names. No behavioral impact since `_parse_action_input` accepts any string.

### Claude's Discretion
- Whether to add an inline comment in `REACT_SYSTEM_PROMPT` noting the bracket_summary → read_consensus_summary mapping (function name vs tool name differs)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Report Engine
- `src/alphaswarm/report.py` — `REACT_SYSTEM_PROMPT` (lines 27-51), `TOOL_TO_TEMPLATE` (lines 215-224), `SECTION_ORDER` (lines 227-236)
- `src/alphaswarm/cli.py` — runtime tool registry at lines 754-763 (authoritative list of tool names)

### Tests
- `tests/test_report.py` — `TestParseActionInput.test_basic_extraction` at lines 30-39 (uses `consensus_summary` string to be updated)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_parse_action_input` in `report.py` — generic regex parser, accepts any string; no change needed
- `TOOL_TO_TEMPLATE` and `SECTION_ORDER` — already use correct names (`bracket_summary`, `signal_flip_analysis`)

### Established Patterns
- Tool names in `REACT_SYSTEM_PROMPT` must exactly match keys in the `tools` dict passed to `ReportEngine.__init__`
- CLI tool registry (`cli.py:754-763`) is the single source of truth for tool names — system prompt must mirror it

### Integration Points
- `ReportEngine.run()` dispatches via `self._tools.get(action)` — any name not in the dict silently generates `ERROR: Unknown tool '{action}'` and skips that section
- `ReportAssembler.assemble()` looks up observations by `tool_name` — tool name in observation must match `SECTION_ORDER` keys

</code_context>

<specifics>
## Specific Ideas

- The mismatch is historical: `bracket_summary` was introduced as the runtime name during Phase 20 report assembly work, but `REACT_SYSTEM_PROMPT` was not updated at the same time
- The fix is a 2-string change in `REACT_SYSTEM_PROMPT` plus 1-string change in the test

</specifics>

<deferred>
## Deferred Ideas

None — analysis stayed within phase scope.

</deferred>

---

*Phase: 22-fix-report-tool-name-mismatch*
*Context gathered: 2026-04-08*
