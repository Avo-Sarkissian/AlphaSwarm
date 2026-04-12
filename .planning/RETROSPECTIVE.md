# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

---

## Milestone: v4.0 — Interactive Simulation & Analysis

**Shipped:** 2026-04-12
**Phases:** 4 (24, 25, 26, 27, 28) | **Plans:** 13 | **Commits:** 107

### What Was Built
- HTML report export with pygal SVG charts (TUI dark theme, self-contained, <1MB) and `--format html` CLI flag
- Schwab portfolio overlay — CSV parser, `--portfolio` CLI flag, HTML portfolio impact section cards
- Mid-simulation shock injection — governor suspend/resume with memory-pressure guard, `ShockInputScreen` modal, `write_shock_event` Neo4j persistence, `_collect_inter_round_shock` wiring
- Shock impact analysis — `read_shock_impact` Cypher inner-join, `_aggregate_shock_impact` pivot/held-firm computation, `BracketPanel` delta mode, Jinja2 shock template, CLI pre-seeding
- Simulation replay — `ReplayStore` no-drain semantics, `CyclePickerScreen`, full TUI replay mode (3s timer, manual step, exit differentiation), `alphaswarm replay` CLI subcommand

### What Worked
- **Wave 0 TDD scaffolding** — Writing all failing stubs before production code kept scope tight and made regressions immediately visible across all 5 phases
- **Worktree isolation** — Parallel phase execution via git worktrees prevented merge conflicts on shared files (`tui.py`, `graph.py`, `report.py`)
- **Decision-first architecture** — Locking decisions (D-01 through D-12) in the plan before executing Phase 28 eliminated mid-execution surprises on race conditions
- **Callee-side guard pattern** — Placing the memory-pressure guard inside `governor.resume()` rather than at the call site was the right call; reviewers caught this early
- **Cross-AI review** — Phases 26 and 28 both had Codex/Gemini reviews that surfaced HIGH-severity issues (deadlock, TOCTOU) before implementation

### What Was Inefficient
- **Worktree base divergence** — Phase 27 and 28 worktrees were based on commits before Phase 26 merged, requiring auto-fixes for missing attributes (`_shock_window_was_open`) that were already in main
- **Phase 24/25 planning directory corruption** — A worktree agent deleted planning artifacts, requiring a fix commit (`fix(roadmap): restore v4.0 phases`). Binary collision during cleanup led to empty `24-html-report-export 2/` directory that persists as an artifact
- **No SUMMARY files for Phase 24 and 26** — Executor agents wrote plan docs and verification but didn't produce per-plan SUMMARY.md files, leaving gaps in the accomplishments record for this retrospective
- **MILESTONES.md only had v2.0** — Previous milestone archive (v3.0) was never formally completed, leaving a gap in the history record

### Patterns Established
- `_latch_after_success` pattern: set latch INSIDE async worker AFTER side-effectful call succeeds, never at the sync call site
- `ReplayStore` as no-drain sibling to `StateStore`: when a store's semantics differ (no drain, no timer), create a separate class rather than adding conditional branches
- Pre-seeding via standalone helper (`_collect_shock_observation`, `_collect_portfolio_data`): module-level async function takes `gm + cycle_id`, returns `ToolObservation | None` — testable without full `AppState`
- Stale-load guard: check `round_num != self._replay_round` after each `await` in multi-step data loaders
- Decision-first planning for TUI work: enumerate all ORDERING/race decisions before writing a single line of code

### Key Lessons
1. **Worktree base commit matters more than branch name** — always verify the worktree base includes all previously-merged features before executing; a pre-merge base silently drops attributes that are already in `main`
2. **Write SUMMARY.md during execution, not retroactively** — Phase 24 and 26 missing summaries required git archaeology at milestone time; add SUMMARY.md write as a blocking step in the executor checklist
3. **Cross-AI review pays off on safety-critical async code** — Both Phase 26 (queue deadlock) and Phase 28 (ReplayStore race) had HIGH-severity issues caught by review that would have been hard to reproduce in tests
4. **Separate the read-only store from the live store at design time** — the `ReplayStore` decision was obvious in retrospect but took discussion to arrive at; any time you find yourself adding `if replay_mode:` branches to a stateful object, it's a sign to split

### Cost Observations
- Model mix: primarily sonnet (executor agents), opus (planning and review agents)
- Sessions: ~8-10 across 4 phases
- Notable: Wave 0 TDD + cross-AI review added ~20% upfront planning cost but eliminated post-implementation rework almost entirely

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 | 10 | 21 | Initial scaffold — no TDD, no cross-AI review |
| v2.0 | 5 | 11 | WriteBuffer pattern established, ReACT engine added |
| v4.0 | 4 | 13 | Wave 0 TDD standard, cross-AI review on safety-critical phases, worktree parallelism |

### Cumulative Quality

| Milestone | Tests | Notable |
|-----------|-------|---------|
| v1.0 | ~200 | Core async patterns established |
| v2.0 | ~480 | Graph memory + ReACT patterns |
| v4.0 | 530+ | Shock injection + replay with full TDD coverage |

### Top Lessons (Verified Across Milestones)

1. **Async correctness requires adversarial review** — every milestone has had at least one concurrency bug (governor deadlock in v2.0, queue deadlock in v4.0) caught before production; treat all async code as suspect
2. **Snapshot-based rendering scales** — the 200ms tick + diff-based pattern from v1.0 Phase 9 held through all TUI additions (interviews, shock, replay) without modification
3. **Keep simulation uncontaminated** — the discipline of never writing portfolio/shock/replay data back into simulation state (Schwab CSV in-memory only, `ReplayStore` separate) prevented data leakage bugs across all milestones
