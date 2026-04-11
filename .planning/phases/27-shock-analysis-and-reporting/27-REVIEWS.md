---
phase: 27
reviewers: [gemini, codex]
reviewed_at: 2026-04-11T00:00:00Z
plans_reviewed: [27-00-PLAN.md, 27-01-PLAN.md, 27-02-PLAN.md]
---

# Cross-AI Plan Review — Phase 27: Shock Analysis and Reporting

## Gemini Review

### Summary
The proposed plans are technically sound, highly structured, and adhere strictly to the project's architectural constraints (local-only, 100% async, Neo4j session patterns). The use of a "delta-bar" mode in the TUI provides a clear visual payoff for the shock injection feature, and the report integration follows the established modular pattern. The TDD-first approach in Wave 0 ensures that the complex data mapping between rounds is validated before UI implementation.

### Strengths
- **Async-Correct TUI Integration**: Using an async worker in `_activate_bracket_delta_mode` to fetch Neo4j data prevents blocking the Textual event loop during the transition to the "Complete" state.
- **Robust Data Comparison**: The decision to use a fixed baseline (Round N-1 vs Round N) provides a mathematically consistent "Pivot" definition that avoids the complexity of tracking cumulative shifts across all rounds.
- **Graceful Degradation**: The TUI and Report logic both include guards to ensure that if no shock was injected, the UI remains in "Live/Final" mode and the report section is omitted entirely rather than showing empty placeholders.
- **TDD Rigor**: Wave 0 explicitly addresses the risk of `ImportError` during test collection by accessing new methods via attributes, which is a sophisticated mitigation for early-stage scaffolding.

### Concerns
- **MEDIUM — Neo4j Inner-Join Risk**: The Cypher query uses two `MATCH` statements for `pre` and `post` decisions. If an agent timed out or failed to record a decision in either Round N-1 or Round N, that agent will be silently dropped from the analysis. This could understate pivot rates.
- **LOW — TUI State Reset**: The `_bracket_panel_delta_active` latch has no explicit reset if the user starts a new cycle within the same TUI session. Delta data from a previous cycle could persist incorrectly.
- **LOW — Report Section Length**: With 100 agents, the "Agent Pivot List" could be quite long. No truncation or pagination strategy is specified.

### Suggestions
- **Improve Cypher Resilience**: Use `OPTIONAL MATCH` for decisions and handle `null` in Python to distinguish "Held Firm" from "Failed to Respond."
- **Explicit State Reset**: Add a `reset_delta_mode()` method to `BracketPanel` to be called during simulation initialization/reset.
- **Report Formatting**: Use a compact layout (e.g., 2-column table) for the Agent Pivot List to prevent excessive report length.
- **Pivot Threshold**: Verify the system uses a simple 3-state signal (BUY/SELL/HOLD); if so, the current plan is perfect.

### Risk Assessment: LOW
The plan builds upon existing proven patterns for Neo4j retrieval and TUI state management. The "Shock" logic is isolated from the core inference loop, meaning any failures would only result in missing analysis sections, not simulation crashes.

---

## Codex Review

### Summary
The plans are directionally solid and cover both phase goals, but need tighter contracts before implementation. The biggest risks are underspecified shock-impact aggregation, TUI worker/lifecycle behavior, report pipeline duplication, and a concrete Python bug in the CLI sketch (`async lambda` is invalid Python syntax). Overall risk is MEDIUM unless the implementation plan is amended with explicit data shapes, empty/missing decision behavior, and Textual worker rules.

### Strengths
- Dependency placement is correct: tests land before production code.
- Explicit RED-state intent avoids silent false positives.
- Import-risk mitigation is sensible: accessing future symbols inside test bodies avoids collection-time failures.
- Coverage areas match the phase surface: graph, TUI, report, CLI.
- TUI activation latch is a good idea to prevent repeated mode activation on every 200ms tick.
- Correctly anchors the baseline to `injected_before_round - 1` vs `injected_before_round`, matching D-09.
- CLI pre-seeding from graph data is the right integration point for a post-simulation report.

### Concerns

**Plan 27-00:**
- MEDIUM: `pytest.fail()` stubs do not lock contracts for aggregation shape, missing shock behavior, or template output.
- MEDIUM: Failing stubs will make the broader suite fail until later waves land — risky if CI runs all tests.
- LOW: `grep <names> | wc -l | grep N` verification is brittle and may produce false confidence from substring matches.

**Plan 27-01:**
- HIGH: `read_shock_impact` aggregation is underspecified. `bracket_deltas`, `largest_shift`, `notable_held_firm_agents`, percentages, bracket ordering, signal normalization, and denominator behavior need explicit definitions.
- HIGH: The Cypher uses `MATCH` for both pre and post decisions, which silently drops agents missing either decision. Pivot rates may be misstated unless `comparable_agents` count is tracked separately from `total_agents`.
- MEDIUM: `shock_round >= 2` prevents round 0 comparison, but `injected_before_round = 1` behavior is not defined — returning empty may look like "no impact" instead of "no baseline."
- MEDIUM: Textual worker behavior needs more detail. `_poll_snapshot()` should not await Neo4j directly, should avoid spawning duplicate workers, and should reset the latch on a new cycle.
- MEDIUM: If `_activate_bracket_delta_mode` sets the latch before impact data is available, the panel could never update after a transient empty result.
- MEDIUM: `_render_delta` swallowing exceptions and falling back silently can hide implementation bugs.
- LOW: `created_at` from Neo4j may need conversion to string before usage.

**Plan 27-02:**
- HIGH: `tools["shock_impact"] = async lambda: shock_impact_result` is invalid Python — `async lambda` does not exist.
- HIGH: The plan may duplicate data by both appending a `ToolObservation` AND registering a tool; may be redundant depending on how report assembly consumes `pre_seeded_observations`.
- HIGH: "Escaped with replace filters" is insufficient for HTML safety. Shock text and agent fields are user/model-controlled and should use Jinja `| e` or sanitization before `| safe` sections.
- MEDIUM: Template rendering with `data.foo` assumes dicts pass through Jinja in a compatible way — confirm existing templates use the same style.
- MEDIUM: `notable_held_firm_agents` selection criteria not defined — report content may be inconsistent.
- LOW: "Create template before modifying registry" is useful locally but not a runtime mitigation if changes land atomically.

### Suggestions
- Replace `async lambda` with a proper named coroutine:
  ```python
  async def shock_impact_tool() -> dict[str, object]:
      return shock_impact_result
  tools["shock_impact"] = shock_impact_tool
  ```
- Decide whether report assembly uses pre-seeded observations or tool registration — avoid both unless the pipeline explicitly requires both.
- Escape `shock_text`, agent names, bracket labels in the HTML template with `| e`.
- Define `notable_held_firm_agents` selection criteria (e.g., top N by confidence, or agents in brackets where majority flipped, ordered by bracket/agent ID).
- Add `comparable_agents` count to the aggregated return dict alongside `pivot_count` and `held_firm_count`.
- Set `_bracket_panel_delta_active` only AFTER successful activation to prevent latch lock on transient errors.

### Risk Assessment: MEDIUM-HIGH
The graph/TUI plan can achieve SHOCK-04 but only if aggregation semantics and Textual lifecycle handling are tightened. The report plan has a concrete Python bug (invalid async lambda) and insufficient HTML escaping.

---

## Consensus Summary

### Agreed Strengths (2/2 reviewers)
- Async-correct TUI integration via `run_worker` (correct Textual pattern)
- Graceful degradation when no ShockEvent exists (TUI stays live, report section absent)
- TDD-first scaffolding with explicit RED state and import-risk mitigation
- Fixed baseline (Round N-1 vs Round N) is mathematically sound and matches D-09
- Activation latch prevents repeated delta-mode triggering on every 200ms tick

### Agreed Concerns (2/2 reviewers)
- **MEDIUM-HIGH — Cypher inner join silently drops agents**: Using `MATCH` (not `OPTIONAL MATCH`) for both pre and post decisions silently excludes agents who missed either round. This can misstate pivot rates. Both reviewers flagged this.
- **MEDIUM — TUI latch does not reset on new cycle**: `_bracket_panel_delta_active` has no reset path for subsequent simulation runs in the same session. Gemini flagged this as LOW; Codex flagged as MEDIUM. Worth addressing.

### High-Priority Divergent Issues (Codex only — actionable before execution)
- **HIGH — `async lambda` is invalid Python**: `tools["shock_impact"] = async lambda: shock_impact_result` in Plan 27-02 will raise a `SyntaxError` at parse time. Must be corrected before execution.
- **HIGH — HTML escaping**: The `| replace` filter approach for shock_text in HTML is insufficient. Use `| e` in the Jinja2 template.
- **MEDIUM — Latch should set after success**: `_bracket_panel_delta_active = True` is set before the async read completes. If the worker fails transiently, the latch is stuck and delta mode never activates.

### Divergent Views
- Gemini: LOW overall risk — treats the phase as well-grounded in existing patterns
- Codex: MEDIUM-HIGH risk — concerned about aggregation contract gaps and the concrete Python syntax bug
- Reconciled: The phase is LOW risk in architecture but has 1 concrete blocking bug (async lambda) and 2 substantive gaps (Cypher inner join, latch timing) that should be addressed in execution

### Recommended Pre-Execution Fixes
Before running `/gsd-execute-phase 27`, address in order of severity:

1. **(BLOCKING) Plan 27-02 async lambda**: Replace with named coroutine `async def shock_impact_tool() -> dict: return shock_impact_result`
2. **(BLOCKING) HTML escaping**: Use `{{ data.shock_text | e }}` not replace filters in report.html.j2
3. **(IMPORTANT) Cypher drop-agents issue**: Note in Plan 27-01 that pivot_rate_pct denominator is comparable agents (those with both pre and post decisions), not total 100 agents. Add a `comparable_agents` field to the return dict.
4. **(NICE-TO-HAVE) Latch timing**: Set `_bracket_panel_delta_active = True` after the first successful `enable_delta_mode()` call rather than before the worker fires.
5. **(NICE-TO-HAVE) Latch reset**: Add `reset_delta_mode()` to BracketPanel for future multi-simulation sessions.
