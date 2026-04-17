# Phase 36: Report Viewer - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-16
**Phase:** 36-report-viewer
**Areas discussed:** In-browser generation, Panel placement, Access trigger, Markdown rendering

---

## In-Browser Generation

| Option | Description | Selected |
|--------|-------------|----------|
| Full trigger | POST /generate spawns ReACT engine as asyncio background task; frontend polls GET until file appears | ✓ |
| Read-only | GET 404 if file missing; user must run CLI first; no browser generation | |
| Hybrid — trigger via CLI subprocess | POST /generate runs CLI command as subprocess; frontend polls same way | |

**User's choice:** Full trigger
**Notes:** Matches ROADMAP SC-4 as written. Accepts backend complexity for self-contained browser experience.

---

## Loading State During Generation

| Option | Description | Selected |
|--------|-------------|----------|
| Polling spinner | "Generating report..." indicator; frontend polls every 3s until 200 OK | ✓ |
| Progress via WebSocket | Backend emits step events over existing WS; frontend shows ReACT tool progress | |
| You decide | Claude handles loading state design | |

**User's choice:** Polling spinner
**Notes:** Simple and sufficient for a minutes-long operation.

---

## Panel Placement

| Option | Description | Selected |
|--------|-------------|----------|
| Full-screen modal | ~80% viewport overlay; CyclePicker pattern; graph visible behind dimmed backdrop | ✓ |
| Right-side sliding panel | Same as InterviewPanel; narrows graph; not ideal for long-form content | |
| You decide | Claude picks based on content type | |

**User's choice:** Full-screen modal
**Notes:** Long structured report (sections, tables, narratives) needs viewport width to render legibly.

---

## Access Trigger

| Option | Description | Selected |
|--------|-------------|----------|
| ControlBar button | 'Report' button in ControlBar, visible when phase === 'complete'; same as Replay button pattern | ✓ |
| AgentSidebar footer | 'View Report' button at bottom of AgentSidebar; requires opening an agent first | |
| Panel strip button | Small icon button in BracketPanel/RationaleFeed area | |

**User's choice:** ControlBar button
**Notes:** Global access from the main toolbar — most discoverable placement.

---

## Markdown Rendering

| Option | Description | Selected |
|--------|-------------|----------|
| marked + DOMPurify | Two npm packages; client-side parse + sanitize; v-html injection; standard Vue approach | ✓ |
| Pre-render on backend | Python markdown library during assembly; serves HTML; no frontend dep | |
| Preformatted plain text | <pre> tag; zero cost; markdown symbols show as-is; visually unpolished | |

**User's choice:** marked + DOMPurify
**Notes:** Report is locally generated so XSS risk minimal; DOMPurify still best practice.

---

## Claude's Discretion

- CSS for report modal size, overlay backdrop, and markdown typography scoping
- Polling debounce / cancel-on-close behavior
- Error handling for failed POST /generate calls
- cycle_id display format (full UUID vs truncated) in modal header
- Exact button label copy ("Generate Report" vs "Create Report")

## Deferred Ideas

None mentioned during discussion.
