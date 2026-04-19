# Phase 33: Web Monitoring Panels - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the discussion.

**Date:** 2026-04-14
**Phase:** 33-web-monitoring-panels
**Mode:** discuss
**Areas discussed:** Panel layout, Bracket bar design

---

## Gray Areas Presented

| Area | Options Offered | User Choice |
|------|----------------|-------------|
| Panel layout | Right column (recommended) vs Bottom strip | Bottom strip |
| Bracket bar design | Stacked proportion (recommended) vs Net sentiment bar | Stacked proportion |

---

## Discussion Detail

### Panel Layout
- **Options presented:**
  - Right column — fixed ~260px wide right panel, force graph fills left, bracket bars on top + feed below. Recommended for consistency with AgentSidebar width.
  - Bottom strip — panels side-by-side at bottom, force graph above.
- **User chose:** Bottom strip
- **Consequence:** `App.vue` main-content becomes a flex column (graph flex:1, panel strip fixed height). Both panels are direct siblings in a horizontal flex row at the bottom.

### Bracket Bar Design
- **Options presented:**
  - Stacked proportion — one horizontal bar per bracket with green/red/gray buy/sell/hold segments. Recommended for signal color reuse and composition clarity.
  - Net sentiment — bidirectional bar from avg_sentiment. Cleaner but loses composition detail.
- **User chose:** Stacked proportion (recommended)
- **No correction needed.**

---

## Decisions Confirmed (no corrections)

All assumptions from codebase analysis confirmed:
- `allRationales` accumulator in `useWebSocket.ts` (needed for feed; current `latestRationales` Map insufficient)
- `snapshot.bracket_summaries` watch in `BracketPanel.vue` for D3 data joins
- Two new Vue SFCs: `BracketPanel.vue` + `RationaleFeed.vue`
- Panels visible only during active simulation (`!isIdle`)
- 20-entry feed cap with TransitionGroup for slide-in / fade-out

---

## No Scope Creep Detected

Discussion stayed within phase 33 boundary.
