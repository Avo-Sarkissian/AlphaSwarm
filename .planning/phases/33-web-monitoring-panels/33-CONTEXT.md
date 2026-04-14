# Phase 33: Web Monitoring Panels - Context

**Gathered:** 2026-04-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Add a live rationale feed panel and D3 bracket sentiment bars to the browser UI, both driven by the existing WebSocket `StateSnapshot`. Phase 33 delivers WEB-03 and WEB-04.

Phase 34 (Replay Mode), Phase 35 (Agent Interviews), and Phase 36 (Report Viewer) are out of scope.

</domain>

<decisions>
## Implementation Decisions

### Layout
- **D-01:** Bottom strip layout. The `main-content` area becomes a flex column: force graph on top (takes remaining height), monitoring panels at the bottom in a horizontal split. Bracket bars on the left half, rationale feed on the right half.
- **D-02:** The bottom panel strip height is fixed (not resizable). Graph gets the majority of vertical space (e.g., `flex: 1` for graph, `~220–240px` fixed for the panel strip).
- **D-03:** Panels appear and disappear with the active simulation state — same `!isIdle` condition that gates the force graph. No placeholder UI in idle state.

### Bracket Bars (D3)
- **D-04:** Stacked horizontal proportion bar per bracket. One `<rect>` per signal type (buy/sell/hold), colored with existing signal tokens (`#22c55e`, `#ef4444`, `#6b7280`). Width = proportional share of the bracket's `total` count.
- **D-05:** All 10 brackets render even if `buy_count + sell_count + hold_count < total` (agents still processing). Unresolved portion renders as a transparent/empty segment — no layout jump when it fills in.
- **D-06:** Bars update via D3 data join on `snapshot.bracket_summaries` watch. Transition duration: inherit `--duration-edge-fade` (600ms) for smooth bar width change.
- **D-07:** Y-axis labels use `BRACKET_ARCHETYPES` display names from `types.ts` (e.g., "Quants", "Doom-Posters").

### Rationale Feed
- **D-08:** `useWebSocket.ts` gains a new `allRationales: Ref<RationaleEntry[]>` accumulator — an ordered list (newest first) capped at 20 entries. Each `snapshot.rationale_entries` tick appends new entries to the front, then slices to 20. Distinct from `latestRationales` Map (which stays unchanged).
- **D-09:** `App.vue` provides `allRationales` via `provide('allRationales', allRationales)` alongside the existing provided refs.
- **D-10:** Each feed entry shows: agent name (e.g., "Agent 07"), signal chip (colored background using `SIGNAL_COLORS`, same pattern as `AgentSidebar`), and rationale text truncated to ~2 lines (CSS `line-clamp: 2`).
- **D-11:** New entry slide-in animation: `translateY(-8px) → 0` + `opacity 0 → 1` over 200ms. Uses CSS transitions triggered by Vue `<TransitionGroup name="feed-entry">`.
- **D-12:** Entries that overflow the 20-entry cap fade out (the removed element gets `opacity → 0` via `TransitionGroup` leave transition) rather than abruptly disappearing.

### New Components
- **D-13:** Two new Vue SFCs: `BracketPanel.vue` (D3 stacked bars) and `RationaleFeed.vue` (animated feed list). Both inject `snapshot` and `allRationales` from the existing App.vue provides.
- **D-14:** No new composable needed. Both components inject from App.vue's existing provide chain.

### Claude's Discretion
- Exact panel strip height (220–240px range — fit to content)
- Whether BracketPanel SVG is sized via `viewBox` or explicit width/height binding
- CSS `line-clamp` fallback behavior for browsers without support
- Exact font sizes within panels (use `--font-size-label` and `--font-size-body` from variables.css)
- Whether agent name in feed entries links to sidebar open (probably not — out of scope for phase 33)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements
- `.planning/ROADMAP.md` §"Phase 33: Web Monitoring Panels" — goal, success criteria SC-1 through SC-4

### Frontend types (required reading before implementing)
- `frontend/src/types.ts` — `RationaleEntry`, `BracketSummary`, `StateSnapshot`, `BRACKET_ARCHETYPES`, `BRACKET_DISPLAY`, `SIGNAL_COLORS`; these define all data shapes for both panels

### Files to extend
- `frontend/src/composables/useWebSocket.ts` — add `allRationales: RationaleEntry[]` accumulator (D-08); return alongside existing refs
- `frontend/src/App.vue` — restructure `main-content` for bottom strip layout (D-01); add `provide('allRationales', ...)` (D-09); import and render new panel components
- `frontend/src/assets/variables.css` — add panel strip height CSS custom property here

### Reference pattern files (read before implementing)
- `frontend/src/components/AgentSidebar.vue` — pattern for inject + signal chip + rationale display; `RationaleFeed.vue` entries reuse the same signal chip style
- `frontend/src/components/ForceGraph.vue` — D3 watch + data join pattern; `BracketPanel.vue` follows the same `watch(snapshot, () => updateBars())` structure

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `SIGNAL_COLORS` from `types.ts` — `{buy: '#22c55e', sell: '#ef4444', hold: '#6b7280'}` — D3 stacked bar fill colors come directly from here
- `BRACKET_ARCHETYPES` / `BRACKET_DISPLAY` from `types.ts` — bracket display names and order already defined
- Signal chip pattern in `AgentSidebar.vue` (lines 61–67) — `backgroundColor: signalColor + '26', color: signalColor` — reuse identical pattern for feed entry chips
- `useWebSocket.ts` `latestRationales` accumulator (lines 64–70) — same append-and-cap pattern for `allRationales`, just append to array instead of Map

### Established Patterns
- **D3 in Vue:** `ForceGraph.vue` uses `watch(snapshot, ...)` to trigger D3 data join updates without reheat. `BracketPanel.vue` follows the same pattern — `watch(() => snapshot.value.bracket_summaries, updateBars)`
- **CSS transitions via TransitionGroup:** AgentSidebar uses `<Transition name="sidebar">` in App.vue. Feed entries use `<TransitionGroup name="feed-entry">` inside `RationaleFeed.vue`
- **Inject pattern:** All child components inject `snapshot` (and `latestRationales`) from `App.vue` provides. New components inject `snapshot` + `allRationales` the same way
- **CSS custom properties:** All sizing and animation durations from `variables.css`. New CSS vars (panel strip height, feed animation duration) go there

### Integration Points
- `frontend/src/App.vue` `<template>` — restructure `.main-content` div from single full-height `graph-container` to flex column with graph + bottom panel strip
- `frontend/src/composables/useWebSocket.ts` `return` — add `allRationales` to returned state object
- `frontend/src/App.vue` `<script setup>` — destructure `allRationales` from `useWebSocket()`, add `provide('allRationales', allRationales)`

</code_context>

<specifics>
## Specific Ideas

- Bottom strip layout selected — graph on top, bracket bars (left) + rationale feed (right) at bottom, side by side
- Stacked proportion bars selected — buy/sell/hold colored segments per bracket using existing signal color tokens
- `allRationales` feed capped at 20 entries, newest first, slide-in animation for arrivals, fade-out for removals

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 33-web-monitoring-panels*
*Context gathered: 2026-04-14*
