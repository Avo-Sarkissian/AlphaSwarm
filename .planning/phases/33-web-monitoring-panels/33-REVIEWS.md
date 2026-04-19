---
phase: 33
reviewers: [gemini, codex]
reviewed_at: 2026-04-14T16:25:00Z
plans_reviewed: [33-01-PLAN.md, 33-02-PLAN.md]
---

# Cross-AI Plan Review — Phase 33

## Gemini Review

### 1. Summary

The implementation plan for Phase 33 is well-structured, modular, and aligns perfectly with the architectural decisions established in the project context. By centralizing rationale accumulation within the `useWebSocket` composable and employing a clear `provide/inject` pattern, the plan ensures a "single source of truth" for real-time data. The choice of D3 for the sentiment bars and Vue's `TransitionGroup` for the rationale feed demonstrates a sophisticated understanding of when to use manual DOM manipulation (for complex SVG transitions) versus declarative framework features (for list animations).

### 2. Strengths

- **State Management Efficiency:** Accumulating `allRationales` inside the composable instead of the component prevents redundant logic if the feed were ever needed in multiple views and keeps the components "dumb" and focused on rendering.
- **Animation Strategy:** Using `d3-transition` for the 600ms bar updates provides a much smoother "fluid" feel than standard CSS transitions for SVG rect widths, which can often jitter when tied to rapid WebSocket updates.
- **Performance Awareness:** The hard cap of 20 entries for the rationale feed is a critical safeguard against DOM bloat and performance degradation over long simulation runs.
- **Layout Robustness:** The use of `flex-column` with a fixed-height panel strip and `flex: 1` for the graph ensures the UI remains stable across different viewport heights.

### 3. Concerns

- **D3 Reactive Resizing (MEDIUM):** Task 2 mentions `range [0, containerWidth]`. If `containerWidth` is calculated only once on mount, the D3 bars will not adjust if the user resizes their browser window. The SVG should use a `viewBox` or a `ResizeObserver` to update the D3 scale.
- **Keying Strategy (LOW):** `TransitionGroup` requires unique keys. Rationale entries need a unique identifier (like a timestamp+agentName composite) to prevent rendering glitches or "duplicate key" warnings if the backend sends similar rationales in quick succession.
- **CSS Variable Scope (LOW):** The plan defines `--panel-strip-height`, but integration should explicitly ensure this variable is used to set the `height` of `.panel-strip` and `max-height` of its children to prevent content bleeding.
- **Dependency Completeness (LOW):** The plan installs `d3-transition`, but `d3-selection` and `d3-scale` should be verified in `package.json` to avoid "module not found" errors during build.

### 4. Suggestions

- **SVG ViewBox:** Instead of calculating `containerWidth` in pixels, define a fixed `viewBox` (e.g., `0 0 400 200`) on the SVG. This allows D3 to work with fixed coordinates while the browser handles scaling automatically.
- **Rationale Uniqueness:** Ensure `RationaleEntry` has a unique `id`. If not, create a composite key in the accumulator: `` key: `${Date.now()}-${entry.agent_id}` ``.
- **Empty State Handling:** Explicitly handle the "pristine" state in `BracketPanel.vue` before any round completes — labels should be visible even with zero-width bars.
- **Line Clamping:** Use the standard CSS: `display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;`

### 5. Risk Assessment

**Overall risk: LOW.** The plan builds on top of already-verified WebSocket infrastructure. Tasks are isolated from core simulation logic; failures here are unlikely to break the backend or force-graph visualization. The human visual verification checkpoint at Wave 2 is an appropriate gate for these UI-driven requirements.

---

## Codex Review (gpt-5.4 / reasoning effort: xhigh)

### 1. Summary

The plans are broadly aligned with Phase 33 and cover the main deliverables: a capped animated rationale feed, D3 bracket bars, and App-level layout integration. The split between foundation/component work and App.vue integration is reasonable. The biggest risks are around WebSocket snapshot semantics, TypeScript/D3 transition typing, responsive sizing for the SVG, and lifecycle cleanup/reset behavior. As written, the plan likely achieves the visible phase goals if the existing snapshot payloads are already shaped exactly as assumed, but it needs a few guardrails to avoid duplicated feed entries, stale state across runs, and brittle D3 rendering.

### 2. Strengths

- The plan maps cleanly to the stated decisions from `CONTEXT.md`.
- Component boundaries are appropriate: `BracketPanel.vue` and `RationaleFeed.vue` keep monitoring UI separate from `App.vue`.
- The bottom strip layout matches the user decision and keeps the force graph as the primary visual surface.
- Feed capping at 20 entries directly addresses DOM growth.
- Using `TransitionGroup` for feed animation is a good Vue-native choice.
- D3 is limited to the SVG charting problem, avoiding unnecessary new state abstractions.
- Verification steps include both `vue-tsc` and production build, which matches the project's available quality gates.
- The phased dependency ordering is sensible: composable and components first, App integration second.

### 3. Concerns

- **HIGH: Potential duplicate rationale entries.** `allRationales.value = [...data.rationale_entries, ...allRationales.value].slice(0, 20)` assumes `data.rationale_entries` contains only new entries. If the WebSocket snapshot includes cumulative entries, every snapshot will duplicate prior rationales.
- **HIGH: Missing reset behavior for new simulations or idle state.** The feed accumulator can retain stale entries after a run ends or a new seed rumor starts unless explicitly cleared when the simulation resets, becomes idle, or receives a new run/session identifier.
- **MEDIUM: D3 chart width may be wrong without explicit resize handling.** `scaleLinear(... range [0, containerWidth])` depends on measuring the container. The plan does not mention `ResizeObserver`, `viewBox`, or a reactive width strategy. Without this, bars may render at width `0`, overflow, or fail to respond to layout changes.
- **MEDIUM: Watch target for bracket updates is underspecified.** Watching the entire `snapshot` may cause unnecessary D3 redraws on every WebSocket update, including rationale-only changes. The watch should target `snapshot.value?.bracket_summaries` or a computed normalized dataset.
- **MEDIUM: Unresolved bracket semantics need definition.** "Unresolved = transparent" is correct visually, but the plan should specify how unresolved proportion is calculated (e.g., `1 - buy - sell - hold`, clamped to `[0, 1]`, with missing brackets defaulting to fully unresolved).
- **MEDIUM: Data ordering for all 10 brackets must be deterministic.** The plan should explicitly build rows from `BRACKET_ARCHETYPES` order, then merge available `snapshot.bracket_summaries` into that canonical list.
- **MEDIUM: Transition typing may be fragile.** Bare `import 'd3-transition'` can work, but TypeScript sometimes still needs verification that `.transition()` is recognized on selections before execution.
- **MEDIUM: Feed entry keys are not mentioned.** `TransitionGroup` requires stable unique keys. The plan needs a deterministic key such as `${round}_${agent_id}_${signal}`.
- **MEDIUM: App.vue `provide`/`inject` typing may be weak.** String-based injection keys are easy to mistype. Components should handle missing injections defensively.
- **LOW: Dependency addition may be redundant.** If the project already depends on the `d3` bundle, `d3-transition` may be transitively available but not directly listed. `d3-selection` and `d3-scale` should also be verified as direct dependencies.
- **LOW: Leave animation with `position: absolute` can cause layout quirks.** The parent container needs appropriate positioning and stable item dimensions to avoid overlap or jumpiness.

### 4. Suggestions

- Add duplicate protection to `allRationales`. Prefer a stable entry ID from the backend. If not available, derive a key from `round`, `agent_id`, `signal` fields.
- Define accumulator behavior based on actual snapshot semantics: if `rationale_entries` is a delta (append), if cumulative (merge by key).
- Clear `allRationales` when simulation returns to idle or a new simulation starts.
- Normalize bracket data before D3 rendering — build from `BRACKET_ARCHETYPES`, merge summaries, compute `unresolved = clamp(1 - buy - sell - hold, 0, 1)`.
- Watch only `snapshot.value?.bracket_summaries` (computed/narrowed), not the full snapshot.
- Use `viewBox` plus `preserveAspectRatio` for responsive SVG sizing.
- Handle empty/malformed data: no snapshot yet, empty `bracket_summaries`, missing brackets, ratios not summing to `1`.
- Give `TransitionGroup` stable keys; ensure feed container has `overflow: hidden`.
- Defensive injection: `if (!allRationales) throw new Error('RationaleFeed requires allRationales provider')`.

### 5. Risk Assessment

**Overall risk: MEDIUM.** The implementation is not conceptually large and the component split is sound. The main risk is correctness at the data boundary: duplicated rationales, stale feed state, missing bracket rows, and ambiguous snapshot semantics could make the UI appear to work while displaying misleading information. The D3 portion has moderate layout risk because responsive SVG sizing is not fully specified. With explicit data normalization, reset behavior, stable keys, and targeted watchers, this becomes low-to-medium risk.

---

## Consensus Summary

### Agreed Strengths

- **Wave ordering is correct:** Foundation components in Wave 1, App.vue integration in Wave 2 — both reviewers approved this dependency structure.
- **`TransitionGroup` for feed animation** is the right Vue-native choice (both agree).
- **Feed cap at 20 entries** directly addresses DOM growth (both agree).
- **D3 confined to SVG charting** avoids unnecessary abstractions (both agree).
- **`vue-tsc + build` as quality gate** is appropriate given no unit test framework (both agree).

### Agreed Concerns

1. **D3 SVG responsive sizing (MEDIUM — both):** `containerWidth` measured once on mount is fragile. Both recommend `viewBox`-based approach as simpler and more reliable for this 232px strip.
2. **TransitionGroup key stability (LOW/MEDIUM — both):** Feed entries need a deterministic unique key. `RationaleEntry` lacks an explicit `id` field — need a composite key from `round_num + agent_id + signal`.
3. **d3-selection / d3-scale as direct dependencies (LOW — both):** Should verify these are in `package.json` directly, not just transitive.

### Divergent Views

- **Overall risk level:** Gemini rates LOW, Codex rates MEDIUM. Codex caught two HIGH concerns (duplicate accumulation if backend sends cumulative snapshots, missing reset on new simulation) that Gemini did not flag. The divergence is worth investigating — check the actual backend WebSocket payload semantics before executing.
- **Codex-only HIGH: Duplicate entry accumulation.** Codex flags a potential correctness issue if `snapshot.rationale_entries` is cumulative (full history) rather than delta (new entries only). If cumulative, the current accumulator will duplicate every prior entry on each tick. **Verify backend behavior before executing Plan 01 Task 1.**
- **Codex-only HIGH: Missing reset behavior.** Feed accumulator will show stale entries from a previous simulation run if not cleared on idle transition. Gemini did not mention this.

---

*To incorporate feedback into planning:*
`/gsd-plan-phase 33 --reviews`
