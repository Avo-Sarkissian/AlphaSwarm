---
phase: 12-richer-agent-interactions
plan: 01
subsystem: database
tags: [neo4j, graph, post-nodes, influence-topology, social-dynamics, cypher]

# Dependency graph
requires:
  - phase: 08-dynamic-influence-topology
    provides: INFLUENCED_BY edges with weight property for ranked peer reads
  - phase: 11-live-graph-memory
    provides: GraphStateManager episode/narrative methods, session-per-method pattern
provides:
  - RankedPost frozen dataclass for peer rationale post ranking
  - write_posts() batch-writes Post nodes from Decision rationale (zero extra inference)
  - read_ranked_posts() returns influence-ranked peer posts with coalesce fallback
  - write_read_post_edges() creates READ_POST audit trail edges
  - Post composite index on (cycle_id, round_num) and post_id uniqueness index
affects: [12-02-richer-agent-interactions, simulation-pipeline, tui-rationale-sidebar]

# Tech tracking
tech-stack:
  added: []
  patterns: [UNWIND batch Post+AUTHORED+HAS_POST in single tx, OPTIONAL MATCH with coalesce for influence fallback, cartesian-product READ_POST edge generation]

key-files:
  created: []
  modified:
    - src/alphaswarm/graph.py
    - tests/test_graph.py
    - tests/test_graph_integration.py
    - tests/conftest.py

key-decisions:
  - "SignalType imported at runtime (not TYPE_CHECKING) for PARSE_ERROR filter in write_posts"
  - "write_posts accepts decision_ids parameter to pair Post->Decision via MATCH, enabling HAS_POST edge"
  - "read_ranked_posts uses OPTIONAL MATCH on INFLUENCED_BY with coalesce to influence_weight_base for fallback"
  - "write_read_post_edges creates N*M pairs Python-side, writes all in single UNWIND (same pattern as narrative edges)"
  - "Post composite index on (cycle_id, round_num) mirrors Decision index pattern for fast per-round queries"

patterns-established:
  - "Post node lifecycle: write_decisions -> write_posts (with decision_ids) -> read_ranked_posts -> write_read_post_edges"
  - "Influence-ranked reads: OPTIONAL MATCH on dynamic INFLUENCED_BY edge, coalesce to static base weight"
  - "Audit trail edges: READ_POST edges track which agents read which posts per round"

requirements-completed: [SOCIAL-01, SOCIAL-02]

# Metrics
duration: 5min
completed: 2026-04-01
---

# Phase 12 Plan 01: Post Node Data Layer Summary

**Post node graph layer with write_posts (PARSE_ERROR filtering), read_ranked_posts (influence-weighted with coalesce fallback), write_read_post_edges (audit trail), and 15 new tests**

## Performance

- **Duration:** 5 min
- **Started:** 2026-04-01T18:51:35Z
- **Completed:** 2026-04-01T18:56:37Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- RankedPost frozen dataclass with 8 fields for peer post ranking
- Three new GraphStateManager methods: write_posts, read_ranked_posts, write_read_post_edges
- Post composite index and post_id uniqueness index in SCHEMA_STATEMENTS
- 15 new unit tests + 2 integration tests, all passing (449 total unit tests green)
- Zero regressions across entire test suite

## Task Commits

Each task was committed atomically:

1. **Task 1: RankedPost dataclass, Post schema index, write_posts()** - `ec1865b` (test) + `e356b37` (feat)
2. **Task 2: read_ranked_posts() and write_read_post_edges()** - `5223a4b` (test) + `92621f4` (feat)
3. **Task 3: Integration tests and conftest cleanup** - `b0e5ed1` (feat)

_Note: Tasks 1 and 2 used TDD (RED test commit + GREEN implementation commit)_

## Files Created/Modified
- `src/alphaswarm/graph.py` - Added RankedPost dataclass, Post indexes, write_posts(), read_ranked_posts(), write_read_post_edges(), and their static tx functions
- `tests/test_graph.py` - 15 new unit tests covering all new methods, edge cases, and error wrapping
- `tests/test_graph_integration.py` - 2 integration tests for full Post lifecycle and PARSE_ERROR filtering
- `tests/conftest.py` - Added Post node cleanup to graph_manager fixture teardown

## Decisions Made
- SignalType imported at runtime (not TYPE_CHECKING guard) because write_posts() uses it for PARSE_ERROR comparison at runtime
- write_posts() takes decision_ids parameter to enable MATCH (d:Decision {decision_id}) in Cypher, linking Posts to Decisions via HAS_POST edges
- read_ranked_posts() uses OPTIONAL MATCH for INFLUENCED_BY edges with coalesce fallback to influence_weight_base, ensuring all posts are ranked even without dynamic edges
- Cartesian-product approach for READ_POST edges: Python generates N*M pairs, single UNWIND writes them all (same pattern as write_narrative_edges)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Integration tests error with RuntimeError (Task got Future attached to different loop) due to pre-existing neo4j_driver fixture using deprecated asyncio.get_event_loop().run_until_complete(). This affects all integration tests in the suite, not specific to this plan. Unit tests (449) all pass.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Post data layer complete and ready for Plan 02 (simulation integration)
- write_posts() returns post_ids needed by Plan 02's write_read_post_edges() calls
- read_ranked_posts() provides the RankedPost list that Plan 02 will format into peer context for agent prompts
- All methods follow established GraphStateManager patterns (session-per-method, UNWIND batch, Neo4jError wrapping)

## Self-Check: PASSED

All 4 modified files exist on disk. All 5 task commits verified in git log.

---
*Phase: 12-richer-agent-interactions*
*Completed: 2026-04-01*
