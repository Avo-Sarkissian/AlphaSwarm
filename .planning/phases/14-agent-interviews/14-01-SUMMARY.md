---
phase: 14-agent-interviews
plan: 01
subsystem: interview
tags: [dataclass, neo4j, ollama, sliding-window, interview-engine]

# Dependency graph
requires:
  - phase: 11-live-graph-memory
    provides: decision_narrative property on Agent nodes, RationaleEpisode schema
  - phase: 05-seed-injection-and-agent-personas
    provides: AgentPersona with system_prompt, JSON_OUTPUT_INSTRUCTIONS constant
provides:
  - InterviewContext and RoundDecision frozen dataclasses for interview data
  - GraphStateManager.read_agent_interview_context() for Neo4j context reconstruction
  - InterviewEngine with sliding window conversation management
  - _strip_json_instructions utility for persona prompt cleanup
affects: [14-02 TUI interview screen, future report agent]

# Tech tracking
tech-stack:
  added: []
  patterns: [sliding-window-history, summary-generation, persona-prompt-stripping]

key-files:
  created:
    - src/alphaswarm/interview.py
    - tests/test_interview.py
  modified:
    - src/alphaswarm/graph.py

key-decisions:
  - "Persona system_prompt looked up from in-memory self._personas list (D-06) to avoid extra Neo4j query"
  - "InterviewEngine uses OllamaClient.chat() directly (D-13) bypassing governor for sequential single-user interaction"
  - "Summary of dropped pairs merges via string concatenation to accumulate across multiple trims"

patterns-established:
  - "Interview context reconstruction: hybrid persona (in-memory) + graph (Neo4j) read pattern"
  - "Sliding window with summary generation: trim oldest pair, summarize via same worker model, inject as [Earlier: ...] system message"

requirements-completed: [INT-01, INT-02]

# Metrics
duration: 6min
completed: 2026-04-02
---

# Phase 14 Plan 01: Interview Data Layer and Conversation Engine Summary

**InterviewContext/RoundDecision dataclasses with Neo4j graph read method and InterviewEngine with 10-pair sliding window, summary generation, and JSON instruction stripping**

## Performance

- **Duration:** 6 min
- **Started:** 2026-04-02T05:40:23Z
- **Completed:** 2026-04-02T05:46:06Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- InterviewContext and RoundDecision frozen dataclasses for structured interview data
- read_agent_interview_context on GraphStateManager reconstructs full agent context from Neo4j + in-memory personas
- InterviewEngine manages multi-turn conversation with 10-pair sliding window and automatic summary generation
- _strip_json_instructions removes JSON_OUTPUT_INSTRUCTIONS from persona prompts for conversational interview mode

## Task Commits

Each task was committed atomically:

1. **Task 1: Interview data types, graph read method, and _strip_json_instructions**
   - `3ff3b9c` (test: failing tests for data types and graph read)
   - `2bd934e` (feat: implement data types, graph read, strip function)
2. **Task 2: InterviewEngine with sliding window and summary generation**
   - `ac41ae7` (test: failing tests for InterviewEngine)
   - `cc3a6cb` (feat: implement InterviewEngine with sliding window)

## Files Created/Modified
- `src/alphaswarm/interview.py` - InterviewContext, RoundDecision, InterviewEngine, _strip_json_instructions (187 lines)
- `src/alphaswarm/graph.py` - Added read_agent_interview_context method and _read_interview_context_tx static method
- `tests/test_interview.py` - 19 unit tests covering data types, graph reads, engine, sliding window (405 lines)

## Decisions Made
- Persona system_prompt looked up from in-memory self._personas list (D-06) to avoid second Neo4j query
- InterviewEngine bypasses ResourceGovernor via direct OllamaClient.chat() (D-13) -- interviews are sequential, not batched
- Summary accumulates via string concatenation when multiple pairs are trimmed across conversation lifetime
- Context block formatted as readable text (not JSON) with "=== Your Simulation Context ===" header
- Test assertion fixed: messages[-1] for user message since assistant isn't appended until after chat call

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test assertion for message ordering**
- **Found during:** Task 2 (InterviewEngine GREEN phase)
- **Issue:** Test checked messages[-2] for user message but at call time only system+context+user exist (3 messages), so [-2] was system
- **Fix:** Changed assertion to messages[-1] for the user message
- **Files modified:** tests/test_interview.py
- **Verification:** All 19 tests pass
- **Committed in:** cc3a6cb (part of Task 2 feat commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Test assertion logic corrected. No scope creep.

## Issues Encountered
- Pre-existing Neo4j integration test failure (test_graph_integration.py event loop mismatch) -- not caused by this plan, excluded from regression check

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- InterviewEngine and InterviewContext are fully tested and ready for TUI integration in Plan 02
- Plan 02 will create InterviewScreen (Textual Screen overlay) that uses these components
- cycle_id retrieval from AppState/StateStore will be addressed in Plan 02

---
*Phase: 14-agent-interviews*
*Completed: 2026-04-02*
