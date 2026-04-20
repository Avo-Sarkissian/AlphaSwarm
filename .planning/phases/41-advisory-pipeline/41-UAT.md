---
status: testing
phase: 41-advisory-pipeline
source: [41-01-SUMMARY.md, 41-02-SUMMARY.md, 41-03-SUMMARY.md]
started: "2026-04-20T01:45:00Z"
updated: "2026-04-20T04:10:00Z"
---

## Current Test

number: 5
name: Advisory modal opens with cycle_id in title
expected: |
  Click the Advisory button. A full-screen modal opens.
  The title reads "Advisory — " followed by the first 8 characters of the cycle_id.
awaiting: user response

## Tests

### 1. Cold Start Smoke Test
expected: Backend starts cleanly, advisory router imports without error, GET on a nonexistent cycle_id returns 404 JSON (not a 500 crash).
result: pass

### 2. Advisory button hidden at idle
expected: Open http://localhost:5173 before starting a simulation. The ControlBar shows only the seed input and Start/Replay controls — no Advisory button visible.
result: pass

### 3. Advisory button hidden during active simulation
expected: Start a simulation. During rounds 1–3 (while agents are active), the ControlBar shows Stop and Inject Shock — Advisory button is absent.
result: pass

### 4. Advisory button appears at phase=complete with correct layout
expected: After all 3 rounds complete and the simulation reaches phase=complete, the ControlBar shows four buttons left-to-right: Complete · Advisory · Report · Stop. Advisory has a transparent background with accent-colored border and text.
result: pass

### 5. Advisory modal opens with cycle_id in title
expected: Click the Advisory button. A full-screen modal opens. The modal title reads "Advisory — " followed by the first 8 characters of the current cycle_id.
result: [pending]

### 6. Initial modal state — empty, Analyze button enabled
expected: On first open, the modal body shows "No advisory generated yet." (or equivalent empty state). The Analyze button is visible and enabled, not spinning.
result: [pending]

### 7. Analyze triggers synthesis — button transitions
expected: Click Analyze. The button text changes to "Analyzing…" with a pulsing animation. The body shows "Analyzing advisory…" (or a loading indicator). No full re-render of the modal occurs mid-analysis.
result: [pending]

### 8. Synthesis result renders — outlook + ranked table
expected: After 15–60 seconds, the result appears: a portfolio_outlook paragraph at the top, a 1px divider, then a ranked table with columns TICKER · SIGNAL · CONF · EXPOSURE · RATIONALE. Rows are ordered by confidence × exposure descending.
result: [pending]

### 9. Signal color coding
expected: In the SIGNAL column, BUY cells show accent blue, SELL cells show red/destructive, HOLD cells show neutral grey. Colors are readable against the modal background.
result: [pending]

### 10. Footer shows correct position count
expected: The modal footer reads "{N} of {total_holdings} positions affected — generated just now" (or a relative timestamp). N is the number of table rows; total_holdings matches the portfolio size loaded via CSV_HOLDINGS_PATH.
result: [pending]

### 11. Escape key closes modal
expected: With the modal open (in any state), press the Escape key. The modal closes immediately with a fade/slide animation. The ControlBar is visible again.
result: [pending]

### 12. Backdrop click closes modal
expected: With the modal open, click the dark semi-transparent backdrop outside the modal content area. The modal closes.
result: [pending]

### 13. Re-open preserves rendered state — no re-POST
expected: After synthesis has completed and the modal was closed, click Advisory again. The previously rendered portfolio_outlook and table appear immediately — the modal does NOT send another POST request or show a loading state. The footer still shows the same "generated X ago" timestamp.
result: [pending]

### 14. Re-analyze sends new POST
expected: With the modal open and showing a result, click Re-analyze (or Analyze again). A new POST is sent. The table re-renders after the synthesis completes (may produce different LLM output).
result: [pending]

### 15. 409 guard — duplicate synthesis request
expected: Click Analyze, then immediately click Analyze again before synthesis completes. The second click should be rejected (button disabled or an error message). The backend returns 409 for a duplicate in-flight request.
result: [pending]

### 16. No console errors
expected: With DevTools open throughout the entire flow (open → analyze → result → close → re-open), the Console tab shows no Vue warnings, no unhandled Promise rejections, and no unexpected 4xx/5xx errors beyond the intentional 409 test above.
result: [pending]

## Summary

total: 16
passed: 0
issues: 0
pending: 16
skipped: 0
blocked: 0

## Gaps
