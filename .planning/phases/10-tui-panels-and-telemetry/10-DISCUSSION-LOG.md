# Phase 10: TUI Panels and Telemetry - Discussion Log

**Session:** 2026-03-27
**Human audit trail only — not consumed by downstream agents.**

---

## Gray Areas Presented

1. Dashboard layout — where 3 new panels fit around the existing grid
2. Rationale sidebar — selection criteria and display format
3. Telemetry metrics — TPS calculation and queue depth definition
4. Bracket panel style — visual format and scope

---

## Dashboard Layout

**Q:** How should the 3 new panels be arranged around the agent grid?

**Options presented:**
- Right sidebar + bottom row (Recommended)
- Bottom-heavy (3-panel bottom row)
- Full right panel

**Selected:** Right sidebar + bottom row

---

## Rationale Sidebar

**Q:** What makes a rationale entry 'impactful' — how should agents be selected for the rationale queue?

**Options presented:**
- High influence weight (Recommended)
- Highest confidence decisions
- Signal movers (round-over-round changes)
- FIFO — all agents as they resolve

**Selected:** High influence weight

---

**Q:** What information shows per rationale entry in the sidebar?

**Options presented:**
- Agent ID + signal + truncated rationale (Recommended)
- Bracket + signal + truncated rationale
- Rationale text only
- Agent ID + bracket + signal + rationale

**Selected:** Agent ID + signal + truncated rationale

---

**Q:** How should rationale entries render in the sidebar — as a live log or fixed slots?

**Options presented:**
- Scrolling log, newest at top (Recommended)
- Fixed slots, newest replaces oldest
- You decide

**Selected:** Scrolling log, newest at top

---

## Telemetry Metrics

**Q:** How should tokens-per-second be calculated?

**Options presented:**
- Track Ollama eval_count + elapsed per response (Recommended)
- Infer from agent completion rate
- Omit TPS, show inferences/sec instead
- You decide

**Selected:** Track Ollama eval_count + elapsed per response

---

**Q:** What does 'API queue depth' mean for this system?

**Options presented:**
- ResourceGovernor active_count (Recommended)
- Pending tasks waiting on TokenPool
- Both active + pending

**Selected:** ResourceGovernor active_count

---

## Bracket Panel Style

**Q:** How should bracket sentiment be displayed in the aggregation panel?

**Options presented:**
- Compact text rows, dominant signal colored (Recommended)
- Signal distribution inline
- Progress bar per bracket
- You decide

**Selected:** Progress bar per bracket

---

**Q:** Which brackets show in the panel?

**Options presented:**
- All 10 brackets (Recommended)
- Top 5 by activity
- You decide

**Selected:** All 10 brackets

---

*Log generated: 2026-03-27*
