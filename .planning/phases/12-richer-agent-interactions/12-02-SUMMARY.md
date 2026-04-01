---
phase: 12-richer-agent-interactions
plan: 02
subsystem: simulation
tags: [simulation, peer-context, ranked-posts, budget-enforcement, social-dynamics]

# Dependency graph
requires:
  - phase: 12-richer-agent-interactions
    provides: write_posts(), read_ranked_posts(), write_read_post_edges(), RankedPost dataclass from Plan 01
  - phase: 07-rounds-2-3-peer-influence-and-consensus
    provides: _format_peer_context() (rewritten), run_simulation() (extended), _dispatch_round() (preserved)
provides:
  - RankedPost-based _format_peer_context with 4000-char greedy budget enforcement
  - Post node writes after every round's write_decisions in run_simulation
  - Ranked post reads and formatted peer context injection for Rounds 2-3
  - READ_POST edge writes before dispatching Rounds 2-3
  - 13 new tests covering budget enforcement, post-write ordering, ranked-post flow
affects: [tui-rationale-sidebar, post-simulation-reports, agent-interviews]

# Tech tracking
tech-stack:
  added: []
  patterns: [greedy-fill budget enforcement with word-boundary truncation, direct dispatch_wave bypass of _dispatch_round for post-based peer context, PeerDecision-to-RankedPost adapter in _dispatch_round]

key-files:
  created: []
  modified:
    - src/alphaswarm/simulation.py
    - tests/test_simulation.py

key-decisions:
  - "_dispatch_round preserved for backward compatibility but no longer called by run_simulation for Rounds 2-3"
  - "Rounds 2-3 call dispatch_wave directly with pre-built peer contexts from read_ranked_posts"
  - "_dispatch_round converts PeerDecision to RankedPost via adapter function for _format_peer_context compatibility"
  - "sanitize_rationale import kept (used by _push_top_rationales) even though _format_peer_context no longer uses it"
  - "Budget enforcement uses greedy fill with word-boundary truncation via rsplit(' ', 1)[0]"

patterns-established:
  - "Budget-capped context: greedy fill loop with overhead accounting for header + guard"
  - "Post lifecycle in run_simulation: write_decisions -> write_posts -> read_ranked_posts -> format -> write_read_post_edges -> dispatch"
  - "Direct dispatch_wave call with per-agent pre-built peer_contexts list (bypassing _dispatch_round)"

requirements-completed: [SOCIAL-01, SOCIAL-02]

# Metrics
duration: 33min
completed: 2026-04-01
---

# Phase 12 Plan 02: Simulation Post Integration Summary

**RankedPost-based _format_peer_context with 4000-char budget, write_posts/read_ranked_posts/write_read_post_edges wired into all 3 rounds of run_simulation, 13 new tests**

## Performance

- **Duration:** 33 min
- **Started:** 2026-04-01T19:02:07Z
- **Completed:** 2026-04-01T19:35:00Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments
- Rewrote _format_peer_context to accept RankedPost list with 4000-char greedy budget enforcement and word-boundary truncation
- Wired write_posts into run_simulation for all 3 rounds (Post nodes created from Decision rationale)
- Rounds 2-3 now build peer contexts from read_ranked_posts + _format_peer_context, with READ_POST edge writes for audit trail
- Updated _dispatch_round to convert PeerDecision to RankedPost via adapter (backward compatibility)
- 13 new tests + 13 updated existing tests, 462 unit tests pass with zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Rewrite _format_peer_context for RankedPost + 4000-char budget** - `dcd11c0` (test) + `b783b16` (feat)
2. **Task 2: Wire write_posts, read_ranked_posts, write_read_post_edges into run_simulation** - `4d98cd3` (feat)
3. **Task 3: New simulation integration tests for post-write and ranked-post flow** - `2604ba5` (feat)

_Note: Task 1 used TDD (RED test commit + GREEN implementation commit)_

## Files Created/Modified
- `src/alphaswarm/simulation.py` - Rewrote _format_peer_context for RankedPost+budget, updated _dispatch_round with PeerDecision-to-RankedPost adapter, replaced Round 2-3 _dispatch_round calls with direct dispatch_wave + ranked post flow
- `tests/test_simulation.py` - 12 format_peer_context tests (4 updated + 8 new), 5 new run_simulation integration tests, 13 existing run_simulation tests updated from _dispatch_round mock to dispatch_wave mock

## Decisions Made
- _dispatch_round function preserved but no longer called by run_simulation for Rounds 2-3 -- Rounds 2-3 now call dispatch_wave directly with pre-built peer contexts from read_ranked_posts. This avoids test breakage from changing _dispatch_round's internal logic (Research Pitfall 5).
- PeerDecision-to-RankedPost adapter function added inside _dispatch_round so it still works in isolation with PeerDecision inputs from graph_manager.read_peer_decisions.
- sanitize_rationale import retained because _push_top_rationales still uses it for rationale truncation (50-char sidebar entries).
- Budget overhead calculation includes header, guard, and newline separators to prevent off-by-one budget violations.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added PeerDecision-to-RankedPost adapter in _dispatch_round**
- **Found during:** Task 1 (GREEN phase)
- **Issue:** After rewriting _format_peer_context to accept RankedPost, the existing _dispatch_round function still builds PeerDecision objects and passes them to _format_peer_context, causing AttributeError ('PeerDecision' has no 'content')
- **Fix:** Added `_peer_to_ranked()` helper inside _dispatch_round and updated both dynamic and static paths to convert PeerDecision to RankedPost before calling _format_peer_context
- **Files modified:** src/alphaswarm/simulation.py
- **Verification:** All _dispatch_round tests pass (test_dispatch_round_reads_peers_per_agent, test_dispatch_round_formats_and_passes_peer_contexts, test_dispatch_round_returns_round_dispatch_result)
- **Committed in:** b783b16 (Task 1 GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Auto-fix necessary for backward compatibility. _dispatch_round is preserved per plan requirement but needs adapter for the new _format_peer_context signature.

## Issues Encountered
- Pre-existing Neo4j integration test failure (RuntimeError: Task got Future attached to different loop) in test_graph_integration.py is unrelated to this plan -- noted in Plan 01 SUMMARY as known issue affecting all integration tests.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Social dynamics complete: agents publish rationale posts, read ranked peer posts with budget-capped context, and READ_POST edges trace information flow
- SOCIAL-01 (Post nodes from rationale, zero extra inference) and SOCIAL-02 (ranked posts with token budget) are fully implemented
- Phase 12 is complete -- all 2 plans done
- Ready for Phase 13 (Post-Simulation Report Generation) or Phase 14 (Dynamic Persona Generation)

## Self-Check: PASSED

All 2 modified files exist on disk. All 4 task commits verified in git log.

---
*Phase: 12-richer-agent-interactions*
*Completed: 2026-04-01*
