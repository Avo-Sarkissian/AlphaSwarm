# Phase 33: Web Monitoring Panels - Research

**Researched:** 2026-04-14
**Domain:** Vue 3 SFC components, D3 SVG data visualization, CSS animation/transitions
**Confidence:** HIGH

## Summary

Phase 33 adds two new Vue SFCs (`BracketPanel.vue` and `RationaleFeed.vue`) to the existing browser dashboard, wired into the WebSocket snapshot pipeline via Vue `provide/inject`. The bracket panel renders D3 SVG stacked horizontal bars; the rationale feed renders an animated list via Vue `<TransitionGroup>`. Both are display-only panels with no user interaction beyond passive observation.

The implementation sits entirely within the existing frontend architecture: Vue 3 + Vite + D3 modular imports + CSS custom properties from `variables.css`. The primary technical challenge is integrating D3 imperative DOM manipulation (for bar transitions) inside a Vue reactive component without conflicting with Vue's virtual DOM. The existing `ForceGraph.vue` establishes the pattern: a `watch()` triggers a D3 update function that imperatively mutates an SVG container managed outside Vue's template.

**Primary recommendation:** Use `d3-transition` (new dependency) for smooth D3 bar width animations, following the side-effect import pattern `import 'd3-transition'` to augment `d3-selection`. For the rationale feed, use Vue's built-in `<TransitionGroup>` with pure CSS transitions -- no D3 needed.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Bottom strip layout. `main-content` becomes a flex column: force graph on top (flex: 1), monitoring panels at the bottom in a horizontal split. Bracket bars left, rationale feed right.
- **D-02:** Bottom panel strip height is fixed (not resizable). Graph gets flex: 1, panel strip gets ~220-240px fixed.
- **D-03:** Panels appear/disappear with `!isIdle` condition. No placeholder UI in idle state.
- **D-04:** Stacked horizontal proportion bar per bracket. One `<rect>` per signal type (buy/sell/hold). Width = proportional share of bracket's `total` count.
- **D-05:** All 10 brackets render even when agents still processing. Unresolved portion = transparent/empty segment.
- **D-06:** Bars update via D3 data join on `snapshot.bracket_summaries` watch. Transition duration: `--duration-edge-fade` (600ms).
- **D-07:** Y-axis labels use `BRACKET_ARCHETYPES` display names from `types.ts`.
- **D-08:** `useWebSocket.ts` gains `allRationales: Ref<RationaleEntry[]>` accumulator -- ordered list (newest first) capped at 20 entries. Each snapshot tick prepends new entries, slices to 20.
- **D-09:** `App.vue` provides `allRationales` via `provide('allRationales', allRationales)`.
- **D-10:** Feed entry shows: agent name ("Agent 07"), signal chip (colored), rationale text truncated to ~2 lines (CSS `line-clamp: 2`).
- **D-11:** New entry slide-in: `translateY(-8px) -> 0` + `opacity 0 -> 1` over 200ms. Uses `<TransitionGroup name="feed-entry">`.
- **D-12:** Entries that overflow 20-entry cap fade out via TransitionGroup leave transition.
- **D-13:** Two new Vue SFCs: `BracketPanel.vue` and `RationaleFeed.vue`. Both inject `snapshot` and `allRationales`.
- **D-14:** No new composable needed. Both components inject from App.vue's existing provide chain.

### Claude's Discretion
- Exact panel strip height (220-240px range -- fit to content)
- Whether BracketPanel SVG is sized via `viewBox` or explicit width/height binding
- CSS `line-clamp` fallback behavior for browsers without support
- Exact font sizes within panels (use `--font-size-label` and `--font-size-body` from variables.css)
- Whether agent name in feed entries links to sidebar open (probably not -- out of scope for phase 33)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| WEB-03 | Real-time rationale feed with animated entry transitions in the browser | `RationaleFeed.vue` with Vue `<TransitionGroup>`, CSS slide-in/fade-out animations, `allRationales` accumulator in `useWebSocket.ts` |
| WEB-04 | Bracket sentiment bar charts (D3 SVG) updated after each round in the browser | `BracketPanel.vue` with D3 data join + `d3-transition` for animated bar width changes, watching `snapshot.bracket_summaries` |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Runtime:** Python 3.11+ backend, `uv` package manager, `pytest-asyncio` for backend tests
- **Concurrency:** 100% async (`asyncio`). No blocking I/O on the main event loop.
- **UI stack (CLAUDE.md):** `textual` (TUI) -- but v5.0 web phases use Vue 3 + Vite + D3 (established in Phases 29-32)
- **Developer profile:** Prefers clean and minimalist aesthetic in code architecture and UI design
- **GSD workflow:** All edits through GSD commands

## Standard Stack

### Core (already installed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| vue | ^3.5.0 (installed) | Reactive UI framework | Project standard, all components use Composition API `<script setup>` |
| d3-selection | 3.0.0 (installed) | SVG DOM manipulation | D3 data join for bracket bar `<rect>` elements |
| d3-scale | 4.0.2 (installed) | `scaleLinear` for bar width calculation | Maps `count/total` proportions to pixel widths |

### New Dependencies Required
| Library | Version | Purpose | Why Needed |
|---------|---------|---------|------------|
| d3-transition | 3.0.1 | Animated D3 bar width changes | D-06 requires 600ms smooth transition on bar width updates. Not currently installed. Side-effect import augments `d3-selection`. |
| @types/d3-transition | 3.0.9 | TypeScript definitions | Required for strict TypeScript (`noUnusedLocals: true` in tsconfig) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `d3-transition` | CSS `transition: width 600ms` on `<rect>` | CSS transitions on SVG `width` attribute do NOT work -- SVG attributes are not CSS properties. Must use D3 transition or SMIL. D3 transition is the correct approach. |
| `d3-transition` | Vue reactivity + `requestAnimationFrame` loop | ForceGraph.vue uses this for position (ticks), but bar width is a discrete update, not a continuous simulation. D3 transition is purpose-built for this. |

**Installation:**
```bash
cd frontend && npm install d3-transition@^3.0.0 && npm install -D @types/d3-transition@^3.0.0
```

**Version verification:** d3-transition 3.0.1 is the latest release on npm (verified 2026-04-14). @types/d3-transition 3.0.9 is the latest type package.

## Architecture Patterns

### Project Structure (files touched)
```
frontend/src/
  assets/
    variables.css            # ADD: --panel-strip-height, --duration-feed-enter, --duration-feed-exit
  composables/
    useWebSocket.ts          # MODIFY: add allRationales accumulator + return
  components/
    BracketPanel.vue         # NEW: D3 stacked horizontal bars
    RationaleFeed.vue        # NEW: animated rationale feed list
    ForceGraph.vue           # UNCHANGED (reference only)
    AgentSidebar.vue         # UNCHANGED (reference only)
  App.vue                    # MODIFY: layout restructure, provide allRationales, import new components
  types.ts                   # UNCHANGED (all types already exist)
```

### Pattern 1: D3 Data Join Inside Vue Watch (BracketPanel)
**What:** A Vue `watch()` on snapshot data triggers an imperative D3 function that performs enter/update/exit on SVG elements within a `ref`-ed container.
**When to use:** Any time D3 needs to animate SVG elements that Vue should NOT manage via template.
**Established by:** `ForceGraph.vue` lines 127-148 (`watch(() => snapshot.value.agent_states, ...)`)
**Example:**
```typescript
// Source: ForceGraph.vue pattern, adapted for bracket bars
import { select } from 'd3-selection'
import { scaleLinear } from 'd3-scale'
import 'd3-transition'  // Side-effect: adds .transition() to selections

const svgRef = ref<SVGSVGElement | null>(null)

watch(() => snapshot.value.bracket_summaries, (summaries) => {
  if (!svgRef.value || summaries.length === 0) return
  updateBars(summaries)
})

function updateBars(summaries: BracketSummary[]) {
  const svg = select(svgRef.value!)
  const x = scaleLinear().domain([0, 1]).range([0, barWidth])

  // D3 data join: enter + update + exit
  const groups = svg.selectAll<SVGGElement, BracketSummary>('.bracket-row')
    .data(summaries, d => d.bracket)

  // Enter: create group + rects
  const enter = groups.enter().append('g').attr('class', 'bracket-row')
  // ... append buy/sell/hold rects

  // Update: transition bar widths
  groups.merge(enter)
    .select('.bar-buy')
    .transition()
    .duration(600)  // --duration-edge-fade
    .attr('width', d => x(d.buy_count / d.total))
}
```

### Pattern 2: Vue TransitionGroup for List Animation (RationaleFeed)
**What:** Vue's `<TransitionGroup>` wraps a `v-for` list, applying CSS enter/leave/move transitions automatically.
**When to use:** Animated list insertions and removals where items have a stable `:key`.
**Established by:** `<Transition name="sidebar">` in App.vue (simpler variant, single element)
**Example:**
```html
<!-- Source: Vue 3 official docs TransitionGroup -->
<TransitionGroup name="feed-entry" tag="div" class="feed-list">
  <div v-for="entry in allRationales" :key="entry.agent_id + '-' + entry.round_num" class="feed-item">
    <!-- entry content -->
  </div>
</TransitionGroup>
```

### Pattern 3: Provide/Inject Chain
**What:** App.vue provides reactive refs, child components inject them.
**Established by:** Every child component (`ForceGraph`, `AgentSidebar`, `ControlBar`) injects `snapshot` from App.vue.
**Example:**
```typescript
// App.vue
const { snapshot, connected, reconnectFailed, latestRationales, allRationales } = useWebSocket()
provide('allRationales', allRationales)

// RationaleFeed.vue
const allRationales = inject<Ref<RationaleEntry[]>>('allRationales')!
```

### Anti-Patterns to Avoid
- **D3 in Vue template v-for:** Do NOT use `v-for` to render bracket bar `<rect>` elements. Vue template rendering cannot animate SVG attribute transitions (width). Use D3 data join for the bars, Vue template for the feed.
- **Shared mutable state between D3 and Vue:** The SVG container for BracketPanel must be a raw `ref` that D3 owns. Do not bind `:width` in the template for D3-managed rects.
- **Unbounded DOM growth:** The `allRationales` array MUST be capped at 20 in the composable. Never rely on the component to cap -- the composable enforces the invariant.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SVG bar animation | `requestAnimationFrame` loop for width interpolation | `d3-transition` `.transition().duration(600)` | D3 transition handles interpolation, easing, and interruption (new data arriving mid-transition) correctly |
| List enter/leave animation | Manual `animate()` API or custom JS transitions | Vue `<TransitionGroup>` with CSS classes | TransitionGroup handles move animations, FLIP technique, and DOM removal timing automatically |
| Proportional bar scaling | Manual pixel math | `d3-scale` `scaleLinear().domain([0,1]).range([0, barWidth])` | Handles zero-total edge case, domain clamping, clean API |
| Rationale deduplication | Custom dedup logic in component | `allRationales` accumulator in composable with `.slice(0, 20)` | Single source of truth, no component-level filtering |

**Key insight:** D3 transitions and Vue TransitionGroup solve fundamentally different problems. D3 transitions animate SVG attributes (which CSS cannot). Vue TransitionGroup animates DOM element lifecycle (enter/leave/move). Using the right tool for each panel avoids fighting the framework.

## Common Pitfalls

### Pitfall 1: d3-transition Side-Effect Import Missing
**What goes wrong:** `selection.transition is not a function` runtime error.
**Why it happens:** `d3-transition` augments `d3-selection`'s prototype via side-effect import. If you only import named exports, the prototype is never patched.
**How to avoid:** Always include `import 'd3-transition'` as a bare side-effect import at the top of `BracketPanel.vue`, in addition to any named imports.
**Warning signs:** TypeScript compilation passes (types are separate), but runtime crashes.

### Pitfall 2: SVG rect Width Cannot Be CSS-Transitioned
**What goes wrong:** Adding `transition: width 600ms` CSS to an SVG `<rect>` does nothing.
**Why it happens:** SVG `width` is a presentation attribute, not a CSS property. CSS transitions only work on CSS properties. In SVG 2 spec some attributes are mappable, but browser support is inconsistent, especially for `<rect>` width.
**How to avoid:** Use D3 `.transition().attr('width', ...)` which uses `d3-interpolate` to animate the attribute imperatively.
**Warning signs:** Bars snap to new width instantly instead of animating.

### Pitfall 3: TransitionGroup Key Collision
**What goes wrong:** Vue reuses DOM elements incorrectly, causing visual glitches or entries appearing in wrong positions.
**Why it happens:** If `:key` is not unique across all entries currently in the list, Vue's diff algorithm cannot distinguish items.
**How to avoid:** Use a composite key: `entry.agent_id + '-' + entry.round_num`. A single agent can appear multiple times (once per round), so `agent_id` alone is insufficient.
**Warning signs:** Entries flicker, duplicate, or don't animate on arrival.

### Pitfall 4: TransitionGroup Leave + Position Absolute
**What goes wrong:** When a feed entry is removed (cap overflow), it collapses instantly and other entries jump, defeating the smooth fade-out.
**Why it happens:** The leaving element is removed from layout flow before the transition completes unless `position: absolute` is set during the leave-active phase.
**How to avoid:** Add `position: absolute` to `.feed-entry-leave-active` CSS class. This takes the element out of flow so remaining items can smoothly reposition via the move transition.
**Warning signs:** Remaining entries jump upward abruptly when the oldest entry is removed.

### Pitfall 5: D3 Data Join with Zero Total
**What goes wrong:** `buy_count / total` produces `NaN` when `total === 0` (simulation just started, no agents have responded in a bracket).
**Why it happens:** Division by zero in the proportion calculation.
**How to avoid:** Guard: `total > 0 ? count / total : 0`. All three signal rect widths should be 0 when total is 0, showing the full bar as the transparent "pending" segment.
**Warning signs:** `NaN` width on SVG rects causes them to render with 0 width (harmless visually but triggers console warnings).

### Pitfall 6: D3 Transition Interruption
**What goes wrong:** If a new snapshot arrives while a 600ms bar transition is still in progress, the old transition and new transition conflict.
**Why it happens:** D3 transitions on the same element with the same name interrupt by default -- this is actually correct behavior. But if you use different transition names or fork to multiple transitions, they stack.
**How to avoid:** Use the default (unnamed) transition for all bar updates. D3 will automatically interrupt the in-progress transition and start the new one from the current intermediate value. No manual management needed.
**Warning signs:** None if using default transition -- D3 handles this correctly out of the box.

### Pitfall 7: allRationales Reactivity with Array Spread
**What goes wrong:** Vue does not detect changes if the same array reference is mutated in-place.
**Why it happens:** Vue's reactivity tracks `.value` assignment, not array mutations.
**How to avoid:** Always create a new array: `allRationales.value = [...newEntries, ...existing].slice(0, 20)`. Never use `.unshift()` or `.splice()` on the existing array.
**Warning signs:** Feed doesn't update even though WebSocket messages are arriving.

## Code Examples

Verified patterns from the existing codebase and official sources:

### d3-transition Import Pattern (BracketPanel.vue)
```typescript
// Source: d3-transition v3.0.1 README (https://github.com/d3/d3-transition/tree/v3.0.1)
import { select } from 'd3-selection'
import { scaleLinear } from 'd3-scale'
import 'd3-transition'  // REQUIRED: side-effect import augments Selection.prototype.transition

// Now select(...).transition() is available
```

### allRationales Accumulator (useWebSocket.ts)
```typescript
// Source: Existing latestRationales pattern at line 64-70 of useWebSocket.ts
const allRationales = ref<RationaleEntry[]>([])

// Inside ws.onmessage handler, after snapshot assignment:
if (data.rationale_entries && data.rationale_entries.length > 0) {
  allRationales.value = [...data.rationale_entries, ...allRationales.value].slice(0, 20)
}
```

### Signal Chip Pattern (from AgentSidebar.vue lines 61-67)
```html
<!-- Source: AgentSidebar.vue lines 61-67 -->
<span class="feed-entry__signal"
  :style="{
    backgroundColor: signalColor + '26',
    color: entry.signal === 'hold' ? 'var(--color-text-secondary)' : signalColor,
  }">
  {{ entry.signal.toUpperCase() }}
</span>
```

### TransitionGroup CSS (from Vue 3 official docs)
```css
/* Source: https://vuejs.org/guide/built-ins/transition-group */
.feed-entry-enter-active {
  transition: transform var(--duration-feed-enter) var(--easing-enter),
              opacity var(--duration-feed-enter) var(--easing-enter);
}
.feed-entry-enter-from {
  transform: translateY(-8px);
  opacity: 0;
}
.feed-entry-leave-active {
  transition: opacity var(--duration-feed-exit) var(--easing-exit);
  position: absolute;  /* CRITICAL: take out of flow for smooth move transitions */
}
.feed-entry-leave-to {
  opacity: 0;
}
.feed-entry-move {
  transition: transform var(--duration-feed-enter) var(--easing-enter);
}
```

### Bottom Panel Strip Layout (App.vue restructure)
```html
<!-- Source: UI-SPEC layout contract -->
<div v-if="isIdle" class="empty-state">...</div>
<template v-else>
  <div class="graph-container" :class="{ 'graph-container--sidebar-open': sidebarOpen }">
    <ForceGraph @select-agent="onSelectAgent" />
  </div>
  <div class="panel-strip" :class="{ 'panel-strip--sidebar-open': sidebarOpen }">
    <BracketPanel />
    <div class="panel-strip__divider" />
    <RationaleFeed />
  </div>
</template>
```

```css
.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}
.panel-strip {
  height: var(--panel-strip-height);
  flex-shrink: 0;
  display: flex;
  background-color: var(--color-bg-secondary);
  border-top: 1px solid var(--color-border);
}
.panel-strip--sidebar-open {
  width: calc(100vw - var(--sidebar-width));
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| D3 monolithic bundle | Modular D3 (`d3-selection`, `d3-transition`, etc.) | D3 v4+ (2016) | Tree-shake unused modules. Only install what you need. |
| Vue 2 `<transition-group>` | Vue 3 `<TransitionGroup>` (PascalCase, Composition API) | Vue 3.0 (2020) | Same API, slightly different naming. `tag` prop no longer required (defaults to `<span>`). |
| CSS transitions on SVG attributes | Still not fully supported in 2026 | Ongoing | D3 transition remains the correct solution for animating SVG presentation attributes |

**Deprecated/outdated:**
- `d3.select()` global import: Use modular `import { select } from 'd3-selection'`
- Vue 2 `<transition-group>` lowercase: Use Vue 3 `<TransitionGroup>` PascalCase

## Open Questions

1. **TransitionGroup key uniqueness for same-agent multi-round entries**
   - What we know: An agent can produce rationale in rounds 1, 2, and 3. All three could be in the 20-entry feed simultaneously.
   - What's unclear: The backend `RationaleEntry` type has `agent_id` + `round_num` fields, which together are unique per entry.
   - Recommendation: Use composite key `${entry.agent_id}-${entry.round_num}` -- this is guaranteed unique within any simulation cycle. Verified from `types.ts` that both fields exist.

2. **BracketPanel SVG sizing: viewBox vs explicit dimensions**
   - What we know: UI-SPEC says "viewBox-based, width 100% of container, height auto-calculated from bracket count."
   - Recommendation (Claude's discretion): Use `viewBox` with calculated height from bracket count (10 bars * 24px per row = 240px), width bound to container via `width="100%"` and `preserveAspectRatio="xMinYMin meet"`. This auto-scales cleanly.

3. **Responsive stacking below 1024px**
   - What we know: UI-SPEC says panels stack vertically below 1024px width.
   - Recommendation: Use CSS `@media (max-width: 1023px)` to change `.panel-strip` from `flex-direction: row` to `flex-direction: column`, each panel taking 50% of the strip height. Low priority -- developer desktop tool.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | No frontend test framework installed |
| Config file | None |
| Quick run command | `cd frontend && npx vue-tsc --noEmit` (type-check only) |
| Full suite command | `cd frontend && npm run build` (type-check + Vite build) |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| WEB-03 | Rationale feed shows entries with slide-in animation | manual | Visual verification: start simulation, observe feed entries arriving with animation | N/A |
| WEB-03 | allRationales accumulator caps at 20 entries | unit (backend proxy) | `cd frontend && npx vue-tsc --noEmit` (type-safety only; no unit test runner) | No test infra |
| WEB-04 | Bracket bars render D3 SVG with proportional widths | manual | Visual verification: start simulation, observe bars growing per bracket | N/A |
| WEB-04 | Bars animate on snapshot update (600ms transition) | manual | Visual verification: watch bar width change smoothly between rounds | N/A |

### Sampling Rate
- **Per task commit:** `cd frontend && npx vue-tsc --noEmit` (type-check passes in < 5s)
- **Per wave merge:** `cd frontend && npm run build` (full type-check + Vite production build)
- **Phase gate:** Full build + manual browser verification before `/gsd:verify-work`

### Wave 0 Gaps
- No frontend unit test framework (vitest, jest). Installing one is out of scope for this phase (display-only components with no complex logic beyond the accumulator).
- Type-checking via `vue-tsc --noEmit` is the automated quality gate. All template bindings, inject types, and prop types are verified at compile time.
- Manual visual verification is the primary validation method for animation and layout correctness.

## Sources

### Primary (HIGH confidence)
- `frontend/src/types.ts` -- `RationaleEntry`, `BracketSummary`, `StateSnapshot`, `BRACKET_ARCHETYPES`, `BRACKET_DISPLAY`, `SIGNAL_COLORS` types verified in codebase
- `frontend/src/composables/useWebSocket.ts` -- existing `latestRationales` accumulator pattern (lines 64-70)
- `frontend/src/components/ForceGraph.vue` -- D3 `watch()` + data join pattern (lines 127-148)
- `frontend/src/components/AgentSidebar.vue` -- signal chip style pattern (lines 61-67)
- `frontend/src/assets/variables.css` -- all CSS custom properties verified
- `frontend/package.json` -- dependency versions verified against `node_modules`
- d3-transition v3.0.1 README (https://github.com/d3/d3-transition/tree/v3.0.1) -- side-effect import pattern

### Secondary (MEDIUM confidence)
- Vue 3 TransitionGroup docs (https://vuejs.org/guide/built-ins/transition-group) -- enter/leave/move CSS class API
- npm registry -- `d3-transition@3.0.1`, `@types/d3-transition@3.0.9` version verification

### Tertiary (LOW confidence)
- None -- all findings verified against primary sources

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already in use or verified on npm; versions confirmed
- Architecture: HIGH -- patterns directly copied from existing codebase (ForceGraph.vue, AgentSidebar.vue)
- Pitfalls: HIGH -- d3-transition side-effect import is well-documented; SVG CSS limitation is established fact; TransitionGroup `position: absolute` is in Vue official docs

**Research date:** 2026-04-14
**Valid until:** 2026-05-14 (stable -- no fast-moving dependencies)
