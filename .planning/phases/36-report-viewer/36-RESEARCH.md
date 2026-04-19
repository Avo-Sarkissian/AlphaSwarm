# Phase 36: Report Viewer - Research

**Researched:** 2026-04-16
**Domain:** Vue 3 SPA modal + FastAPI background-task endpoint + client-side markdown rendering
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**In-Browser Report Generation**
- **D-01:** Full trigger model. `POST /api/report/{cycle_id}/generate` spawns the ReACT engine (`ReportEngine` + `ReportAssembler`) as an `asyncio` background task. Returns 202 Accepted immediately. Phase guard: only available when `phase === 'complete'`.
- **D-02:** Generation in-progress guard — if a generation task is already running for this cycle, `POST /generate` returns 409 Conflict (prevents duplicate runs from double-clicking).
- **D-03:** Report output path: `reports/{cycle_id}_report.md` (same convention as CLI). Sentinel at `.alphaswarm/last_report.json` updated on completion (same as CLI path).
- **D-04:** Frontend polls `GET /api/report/{cycle_id}` every 3 seconds after triggering generation. Shows a "Generating report..." spinner while polling. No WebSocket integration.
- **D-05:** `GET /api/report/{cycle_id}` reads `reports/{cycle_id}_report.md` from disk. Returns `{ cycle_id, content, generated_at }` on 200. Returns 404 if file doesn't exist. No database storage — file system is the source of truth.

**Panel Placement**
- **D-06:** Full-screen modal overlay (~80% of viewport width and height). Follows the `CyclePicker.vue` pattern — mounted in `App.vue` with `v-if` and a `showReportViewer` ref. Force graph stays visible behind a dimmed overlay.
- **D-07:** New `ReportViewer.vue` component. Structure: header row (title + close button), scrollable content area, footer with generation button or status indicator.

**Access Trigger**
- **D-08:** 'Report' button in `ControlBar.vue`, visible only when `snapshot.value.phase === 'complete'`. Emits `open-report-viewer` event up to `App.vue`.
- **D-09:** On open: `ReportViewer.vue` immediately calls `GET /api/report/{cycle_id}`. If 200 → render report. If 404 → show "Generate Report" button. `cycle_id` is resolved from `GET /api/replay/cycles` limit=1 (most recent completed cycle).

**Markdown Rendering**
- **D-10:** `marked` + `DOMPurify` client-side. `npm install marked dompurify @types/dompurify`. Component calls `marked.parse(content)` then `DOMPurify.sanitize(html)`, injects via `v-html`.
- **D-11:** Report modal content area gets scoped CSS for markdown typography: `h2` section headers, `strong` bold, `table` borders using existing `--color-border` token.

### Claude's Discretion

- Exact CSS for the report modal size and overlay backdrop
- Whether to debounce the 3s polling loop (cancel on modal close)
- Error handling for failed `POST /generate` calls (show inline error, don't crash modal)
- Whether `cycle_id` is shown in the modal header as a full UUID or truncated
- Exact button label copy ("Generate Report" vs "Create Report")

*(UI-SPEC.md has already resolved all of these — see `36-UI-SPEC.md`.)*

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| WEB-06 | Post-simulation views — agent interview panel, report viewer, replay mode | `ReportViewer.vue` component + `ControlBar` trigger + `App.vue` mount pattern (Section: Architecture Patterns — Modal Lifecycle; Standard Stack — Vue 3.5 + Vite 6 + marked + DOMPurify). Ships the final missing post-sim view. |
| REPORT-02 | Cypher query tools for bracket summaries, influence topology analysis, entity-level trends, and signal flip metrics (delivered via structured markdown report) | Backend route reuses existing `ReportEngine` + `ReportAssembler` (unchanged); frontend renders the markdown they produce (Section: Don't Hand-Roll — Report generation pipeline; Code Examples — CLI `_handle_report` sequence). |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Concurrency:** 100% async (`asyncio`). Report generation route MUST use `asyncio.create_task()` — no blocking calls. [VERIFIED: CLAUDE.md Hard Constraint 1]
- **Memory safety:** 2 models loaded max. Report generation loads the orchestrator model — must coordinate with simulation/replay to avoid concurrent loads. [VERIFIED: CLAUDE.md Hard Constraint 3 + `_handle_report` pattern in `cli.py:664`]
- **Local first:** No cloud APIs. All markdown parsing, sanitization, and rendering happens client-side or in local Python. [VERIFIED: CLAUDE.md Hard Constraint 2]
- **GSD workflow enforcement:** All file-changing work must flow through `/gsd:execute-phase`. [VERIFIED: CLAUDE.md GSD Workflow section]
- **Strict typing:** Python 3.11+ with `mypy --strict`. TypeScript `strict: true`. [VERIFIED: `pyproject.toml` `[tool.mypy] strict = true`; `tsconfig.app.json` strict mode]

## Summary

Phase 36 finishes the v5.0 Web UI by exposing the Phase 15 `ReportAssembler` output in the browser as a full-screen markdown modal. The work is two-sided but entirely additive:

1. **Backend (FastAPI)** — a new `report.py` route file with two endpoints: `GET /api/report/{cycle_id}` (read-through of `reports/{cycle_id}_report.md`) and `POST /api/report/{cycle_id}/generate` (spawns an `asyncio` background task that mirrors the CLI `_handle_report` flow verbatim — load orchestrator → `ReportEngine.run()` → `ReportAssembler.assemble()` → `write_report()` → `write_sentinel()` → unload). In-progress detection via a single task handle stored on `app.state.report_task`. 409 Conflict if a task is already running for that cycle. Zero changes to `src/alphaswarm/report.py`.

2. **Frontend (Vue 3 + TypeScript)** — a new `ReportViewer.vue` modal component mounted from `App.vue`, opened by a new Report button in `ControlBar.vue`. On mount it resolves the most recent `cycle_id` from `GET /api/replay/cycles`, then `GET /api/report/{cycle_id}`. On 404 it shows a "Generate Report" CTA in the footer. Clicking CTA fires `POST /generate` and starts a 3-second polling loop. Markdown is rendered via `marked.parse()` → `DOMPurify.sanitize()` → `v-html`. Two new npm dependencies only: `marked` (v18) and `dompurify` (v3.4). NOTE: `@types/dompurify` is **deprecated** — DOMPurify 3.x ships its own types.

**Primary recommendation:** Mirror the `CyclePicker.vue` + `interview.py` patterns wholesale. Nothing novel in this phase — every decision (modal shape, backdrop behavior, Escape key, 409 phase guard, task-handle singleton on `app.state`, fetch-on-open) already exists in the codebase. The phase's risk profile is entirely in the new npm dependencies (XSS via `v-html` → DOMPurify mandatory) and in the single-task handle concurrency guard. Both are resolved deterministically by CONTEXT.md decisions.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Vue | 3.5.x (already pinned) | SFC component for `ReportViewer.vue` | Project baseline; all existing modals are Vue 3 `<script setup>` SFCs [VERIFIED: `frontend/package.json` `"vue": "^3.5.0"`] |
| TypeScript | 5.6.x (already pinned) | Typed component props, fetch responses | Project baseline with `strict: true` [VERIFIED: `frontend/package.json` + `tsconfig.app.json`] |
| Vite | 6.x (already pinned) | Build/dev server, serves SPA | Project baseline [VERIFIED: `frontend/package.json`] |
| marked | 18.0.0 (latest) | Parse markdown string → HTML string | De facto JS markdown parser. Synchronous by default (`marked.parse(str) → string`). Pure ESM. [VERIFIED: `npm view marked version` = 18.0.0, published 2026-04-07; engines `node: ">= 20"`] |
| DOMPurify | 3.4.0 (latest) | Sanitize HTML string before `v-html` injection | Industry standard XSS sanitizer (cure53). v3.x ships its own `.d.ts` — no `@types/*` needed. [VERIFIED: `npm view dompurify version` = 3.4.0, published 2026-04-14; `npm view dompurify types` = `./dist/purify.cjs.d.ts`] |
| FastAPI | >=0.115.0 (already pinned) | New `report_router` route file | Project baseline [VERIFIED: `pyproject.toml`] |
| aiofiles | >=25.1.0 (already pinned) | Async file reads/writes in the GET route | Project baseline; `report.py` already uses it for `write_report()` and `write_sentinel()` [VERIFIED: `pyproject.toml` + `src/alphaswarm/report.py:319`] |
| structlog | >=25.5.0 (already pinned) | Structured logging in the new route | Project baseline; mirror `log = structlog.get_logger(component="web.report")` pattern from `web/routes/interview.py:14` [VERIFIED: `src/alphaswarm/web/routes/interview.py`] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Pydantic | >=2.12.5 (already pinned) | Response models for `ReportResponse`, request validation | Required by FastAPI route pattern; mirror `InterviewRequest`/`InterviewResponse` from `interview.py` [VERIFIED: `pyproject.toml`] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| marked | markdown-it | Both synchronous and well-maintained. `marked` is the choice locked by D-10 — ~35KB smaller bundle than `markdown-it`, simpler API surface, faster parse. No reason to revisit. |
| DOMPurify | Built-in browser sanitizer (none exists) / manual regex | There is no native browser HTML sanitizer API widely available (the Sanitizer API is still behind flags on Firefox/Safari as of April 2026). DOMPurify is the only defensible choice. |
| Client-side markdown rendering | Server-side pre-rendering (return HTML from GET) | Keeping markdown as the wire format matches `ReportAssembler.assemble()` output and lets us reuse the same file that the CLI writes to disk. Server-side rendering would require a new HTML template pipeline and break the "file system is source of truth" invariant (D-05). [CITED: CONTEXT.md D-03, D-05] |
| Polling | WebSocket push on completion | CONTEXT.md D-04 locks polling. Justified by the minutes-long duration (3s poll interval has negligible load) and the absence of a real-time progress model in `ReportEngine.run()`. |
| Full-screen modal | Sidebar panel (like `InterviewPanel`) | CONTEXT.md D-06 locks modal. Rationale: report content includes markdown tables and long prose; sidebar width (`var(--sidebar-width)`) is insufficient. |

**Installation:**

```bash
cd frontend && npm install marked dompurify
# NOTE: Do NOT install @types/dompurify — it is deprecated and conflicts with DOMPurify 3.x's
# built-in types. The CONTEXT.md D-10 install command is outdated on this point; see
# "Common Pitfalls → Pitfall 3" below for details.
```

**Version verification (executed 2026-04-16):**
- `marked@18.0.0` — published 2026-04-07 [VERIFIED: npm registry]
- `dompurify@3.4.0` — published 2026-04-14 [VERIFIED: npm registry]
- `@types/dompurify@3.2.0` — **DEPRECATED stub** (registry message: "dompurify provides its own type definitions, so you do not need this installed") [VERIFIED: `npm view @types/dompurify deprecated`]

## Architecture Patterns

### Recommended Project Structure

```
src/alphaswarm/
├── web/
│   ├── app.py                     # MODIFIED: import report_router, init app.state.report_task = None
│   └── routes/
│       ├── interview.py           # reference pattern (phase guard, 503/409)
│       ├── replay.py              # reference pattern (background task, 409, app.state access)
│       └── report.py              # NEW: GET + POST /generate
└── report.py                      # UNCHANGED — reuse ReportEngine, ReportAssembler, write_report, write_sentinel

frontend/src/
├── App.vue                        # MODIFIED: showReportViewer ref + handlers + <ReportViewer> mount
├── components/
│   ├── CyclePicker.vue            # reference pattern (modal, backdrop, Escape, fetch-on-open)
│   ├── ControlBar.vue             # MODIFIED: Report button in complete-phase row, emit open-report-viewer
│   └── ReportViewer.vue           # NEW
└── package.json                   # MODIFIED: +marked, +dompurify

reports/                           # existing dir; runtime read/write target
├── {cycle_id}_report.md           # existing CLI-generated reports
└── (new files from web endpoint — same naming)

.alphaswarm/
└── last_report.json               # existing sentinel, also updated by web endpoint
```

### Pattern 1: Phase-guarded REST route with app.state singleton

**What:** FastAPI route that (a) inspects `app.state.app_state` for required services, (b) checks `snapshot.phase == COMPLETE`, (c) reads/writes a singleton task handle on `app.state.report_task` for in-progress detection.

**When to use:** Any route that invokes long-running work bound to the simulation lifecycle.

**Example:**

```python
# Source: adapted from src/alphaswarm/web/routes/interview.py:33 and .../replay.py:98
from __future__ import annotations

import asyncio
from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from alphaswarm.types import SimulationPhase

log = structlog.get_logger(component="web.report")
router = APIRouter()

REPORTS_DIR = Path("reports")


class ReportResponse(BaseModel):
    cycle_id: str
    content: str
    generated_at: str  # ISO-8601 from filesystem mtime or sentinel


class GenerateResponse(BaseModel):
    status: str
    cycle_id: str


@router.get("/report/{cycle_id}", response_model=ReportResponse)
async def get_report(cycle_id: str, request: Request) -> ReportResponse:
    """Read the generated report file. 404 if it does not exist yet (D-05)."""
    import aiofiles

    report_path = REPORTS_DIR / f"{cycle_id}_report.md"
    if not report_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "report_not_found", "message": f"No report exists for cycle {cycle_id}"},
        )
    async with aiofiles.open(report_path, "r", encoding="utf-8") as f:
        content = await f.read()
    # generated_at = mtime-derived ISO string (fallback if sentinel isn't the one we want)
    import datetime
    mtime = report_path.stat().st_mtime
    generated_at = datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc).isoformat()
    return ReportResponse(cycle_id=cycle_id, content=content, generated_at=generated_at)


@router.post(
    "/report/{cycle_id}/generate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=GenerateResponse,
)
async def generate_report(cycle_id: str, request: Request) -> GenerateResponse:
    """Spawn ReACT + assembler as a background task (D-01).

    503 if services unavailable. 409 if phase != COMPLETE OR task already running (D-02).
    """
    app_state = request.app.state.app_state
    graph_manager = app_state.graph_manager
    ollama_client = app_state.ollama_client
    model_manager = app_state.model_manager

    if graph_manager is None or ollama_client is None or model_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "services_unavailable", "message": "Neo4j or Ollama is not connected"},
        )

    snap = app_state.state_store.snapshot()
    if snap.phase != SimulationPhase.COMPLETE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "report_unavailable",
                "message": "Reports can only be generated after a simulation completes",
                "current_phase": snap.phase.value,
            },
        )

    # D-02: 409 if a generation is already in flight
    existing = getattr(request.app.state, "report_task", None)
    if existing is not None and not existing.done():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "report_generation_in_progress", "message": "A report generation is already running"},
        )

    task = asyncio.create_task(_run_report_generation(app_state, cycle_id))
    request.app.state.report_task = task
    log.info("report_generation_started", cycle_id=cycle_id)
    return GenerateResponse(status="accepted", cycle_id=cycle_id)


async def _run_report_generation(app_state, cycle_id: str) -> None:  # type: ignore[no-untyped-def]
    """Background task — mirrors cli.py:_handle_report structure exactly."""
    from alphaswarm.report import (
        ReportAssembler,
        ReportEngine,
        write_report,
        write_sentinel,
    )

    orchestrator = app_state.settings.ollama.orchestrator_model_alias
    try:
        await app_state.model_manager.load_model(orchestrator)
        gm = app_state.graph_manager
        tools = {
            "bracket_summary": lambda **kw: gm.read_consensus_summary(kw.get("cycle_id", cycle_id)),
            "round_timeline": lambda **kw: gm.read_round_timeline(kw.get("cycle_id", cycle_id)),
            "bracket_narratives": lambda **kw: gm.read_bracket_narratives(kw.get("cycle_id", cycle_id)),
            "key_dissenters": lambda **kw: gm.read_key_dissenters(kw.get("cycle_id", cycle_id)),
            "influence_leaders": lambda **kw: gm.read_influence_leaders(kw.get("cycle_id", cycle_id)),
            "signal_flip_analysis": lambda **kw: gm.read_signal_flips(kw.get("cycle_id", cycle_id)),
            "entity_impact": lambda **kw: gm.read_entity_impact(kw.get("cycle_id", cycle_id)),
            "social_post_reach": lambda **kw: gm.read_social_post_reach(kw.get("cycle_id", cycle_id)),
        }
        # Phase 27: pre-seed shock observation when a ShockEvent exists (mirror cli.py lines 727–731)
        # [...see CLI reference...]
        engine = ReportEngine(ollama_client=app_state.ollama_client, model=orchestrator, tools=tools)
        observations = await engine.run(cycle_id)
        assembler = ReportAssembler()
        content = assembler.assemble(observations, cycle_id)
        output_path = REPORTS_DIR / f"{cycle_id}_report.md"
        await write_report(output_path, content)
        await write_sentinel(cycle_id, str(output_path))
        log.info("report_generation_complete", cycle_id=cycle_id)
    except Exception as exc:
        log.error("report_generation_failed", cycle_id=cycle_id, error=str(exc))
        raise
    finally:
        try:
            await app_state.model_manager.unload_model(orchestrator)
        except Exception:
            log.warning("orchestrator_unload_failed", cycle_id=cycle_id)
```

### Pattern 2: Vue modal with fetch-on-open + Escape + backdrop click

**What:** Full-screen modal mounted in `App.vue` behind a `v-if="showX"` ref, with its own backdrop click handler, global `keydown` listener for Escape, and `onMounted` fetch.

**When to use:** Any post-simulation UI flow that needs full viewport width (reports, comparisons, analytics).

**Example:**

```vue
<!-- Source: distilled from frontend/src/components/CyclePicker.vue lines 23–76 -->
<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const emit = defineEmits<{ 'close': [] }>()

const cycleId = ref<string | null>(null)
const reportContent = ref<string | null>(null)
const renderedHtml = ref<string>('')
const generatedAt = ref<string | null>(null)
const loading = ref(true)
const generating = ref(false)
const errorMessage = ref<string | null>(null)

let pollInterval: number | null = null
let pollIterations = 0
const MAX_POLL_ITERATIONS = 200  // 200 * 3s = 10 minutes (UI-SPEC polling timeout)

async function resolveCycleId(): Promise<string | null> {
  const res = await fetch('/api/replay/cycles')
  if (!res.ok) return null
  const data = await res.json()
  return data.cycles[0]?.cycle_id ?? null
}

async function fetchReport(cid: string): Promise<boolean> {
  const res = await fetch(`/api/report/${encodeURIComponent(cid)}`)
  if (res.status === 404) return false
  if (!res.ok) throw new Error(`GET /api/report failed: ${res.status}`)
  const data = await res.json()
  reportContent.value = data.content
  generatedAt.value = data.generated_at
  // D-10: marked (sync) -> DOMPurify.sanitize -> v-html
  renderedHtml.value = DOMPurify.sanitize(marked.parse(data.content) as string)
  return true
}

async function startGeneration() {
  if (!cycleId.value) return
  generating.value = true
  errorMessage.value = null
  try {
    const res = await fetch(`/api/report/${encodeURIComponent(cycleId.value)}/generate`, { method: 'POST' })
    if (res.status === 202 || res.status === 409) {
      startPolling()
      return
    }
    errorMessage.value = 'Could not start report generation. Try again.'
    generating.value = false
  } catch {
    errorMessage.value = 'Could not start report generation. Try again.'
    generating.value = false
  }
}

function startPolling() {
  pollIterations = 0
  pollInterval = window.setInterval(async () => {
    if (!cycleId.value) return
    pollIterations += 1
    if (pollIterations >= MAX_POLL_ITERATIONS) {
      stopPolling()
      generating.value = false
      errorMessage.value = 'Report generation is taking longer than expected. The task may still complete — try refreshing in a few minutes.'
      return
    }
    try {
      const found = await fetchReport(cycleId.value)
      if (found) {
        stopPolling()
        generating.value = false
      }
    } catch {
      // Silent retry per UI-SPEC — ignore transient errors mid-poll
    }
  }, 3000)
}

function stopPolling() {
  if (pollInterval !== null) {
    window.clearInterval(pollInterval)
    pollInterval = null
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}

function onBackdropClick(e: MouseEvent) {
  if ((e.target as HTMLElement).classList.contains('report-viewer-backdrop')) {
    emit('close')
  }
}

onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  cycleId.value = await resolveCycleId()
  if (!cycleId.value) {
    errorMessage.value = 'Could not load report. Try again.'
    loading.value = false
    return
  }
  try {
    await fetchReport(cycleId.value)
  } catch {
    errorMessage.value = 'Could not load report. Try again.'
  } finally {
    loading.value = false
  }
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  stopPolling()  // CRITICAL — prevents memory leak per UI-SPEC polling lifecycle
})
</script>
```

### Pattern 3: Relative time formatting (footer "Generated X ago")

**What:** Compute a human-readable relative time from an ISO-8601 string, using the browser-native `Intl.RelativeTimeFormat`.

**When to use:** Any timestamp displayed to the user as "N minutes ago" style copy.

**Example:**

```typescript
// Pure TS, no dependency, browser-native
// Source: MDN Intl.RelativeTimeFormat API (stable since 2020)
export function formatRelativeTime(isoString: string): string {
  const then = new Date(isoString).getTime()
  const now = Date.now()
  const deltaSec = Math.floor((then - now) / 1000)  // negative for past
  const absSec = Math.abs(deltaSec)

  const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })

  if (absSec < 10) return 'just now'
  if (absSec < 60) return rtf.format(deltaSec, 'second')
  if (absSec < 3600) return rtf.format(Math.round(deltaSec / 60), 'minute')
  if (absSec < 86400) return rtf.format(Math.round(deltaSec / 3600), 'hour')
  return rtf.format(Math.round(deltaSec / 86400), 'day')
}
```

### Anti-Patterns to Avoid

- **Never inject markdown directly as `v-html` without DOMPurify.** Even locally generated LLM output can contain malicious HTML if the seed rumor or entity name contains `<script>`. UI-SPEC.md § "Security note on `v-html`" mandates the DOMPurify layer; do not omit it.
- **Do not install `@types/dompurify` v3.x.** It is deprecated and will conflict with DOMPurify's own ambient types. Just `import DOMPurify from 'dompurify'` — the types resolve automatically.
- **Do not block the GET route on generation.** CONTEXT.md D-05 is explicit: GET reads from disk, never triggers generation. Triggering on GET would turn every stale-report render into a minute-long spinner and defeat the async model.
- **Do not store the report in Neo4j.** D-05 pins the file system as the single source of truth; mirroring to Neo4j creates a dual-write that can drift.
- **Do not forget `onUnmounted` cleanup of the poll interval.** `setInterval` callbacks hold references to reactive refs and leak across modal reopens. The established precedent for teardown-on-unmount is `useWebSocket.ts:128` (quick commit `260416-trw`). [VERIFIED: `frontend/src/composables/useWebSocket.ts:128`]
- **Do not use Pydantic `BaseModel` for the report content inline in the response.** The content is raw markdown; Pydantic will validate it but the extra schema overhead is pointless for a field that is "any string." Just use `content: str`.
- **Do not stack concurrent orchestrator model loads.** The `model_manager` inside the orchestrator uses an internal lock (`ollama_models.py:50` `self._lock = asyncio.Lock()`), so concurrent calls serialize — but this still means the second caller waits minutes. The 409 phase guard + 409 in-progress guard together prevent this. Do not weaken them.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Markdown → HTML | Custom regex / token parser | `marked` | CommonMark + GFM is hundreds of edge cases (nested lists, tables, fenced code, inline code inside emphasis); hand-rolled parsers always miss some. |
| HTML sanitization | Regex strip of `<script>` / allowlist by hand | `DOMPurify` | Browser XSS vectors include SVG event handlers, CSS `expression()`, `javascript:` URLs, on*= attributes in 100+ shapes. DOMPurify has 10 years of CVE hardening. |
| Relative time strings | Custom `.toLocaleDateString()` math | `Intl.RelativeTimeFormat` | Browser-native, zero-dep, handles pluralization and locale. Already stable for 5+ years. |
| Report generation pipeline | New ReACT loop / new assembler / new Cypher queries | Existing `ReportEngine`, `ReportAssembler`, `write_report`, `write_sentinel` in `src/alphaswarm/report.py` | All of Phase 15 is already shipped and tested. The web route is a literal transliteration of `cli.py:_handle_report` lines 664–760 into a FastAPI handler. Zero logic changes to `report.py`. |
| Task-handle concurrency guard | `asyncio.Lock` + flag fields | Single `asyncio.Task` reference on `app.state.report_task` + `.done()` check | `interview_sessions`, `replay_manager`, `sim_manager` all use `app.state` singletons with lifespan-time init. The established pattern is the simplest correct answer. [VERIFIED: `web/app.py:45–60`] |
| Cycle ID resolution | New `GET /api/most-recent-cycle` endpoint | Reuse `GET /api/replay/cycles` (already returns newest-first) | Interview flow (`interview.py:80`) already uses this pattern: `cycles = await graph_manager.read_completed_cycles(limit=1); cycles[0]["cycle_id"]`. |
| Modal primitives (backdrop, Escape, scroll-lock) | Custom overlay + manual event listeners | Copy `CyclePicker.vue`'s backdrop + `onKeydown` + `Transition` | It is 60 lines of vetted scoped CSS + handlers. Copy-paste with renaming is faster than a "clean" abstraction. |

**Key insight:** Phase 36 is plumbing, not invention. Every problem has a shipped, tested pattern in the repo or a stable library in the ecosystem. The right planner instinct is "grep for the pattern, copy, rename." The only genuinely new decision is the report-task concurrency guard shape — and even that is one field on `app.state`.

## Runtime State Inventory

> **Greenfield addition — no rename/refactor in this phase.** The phase adds new files (`src/alphaswarm/web/routes/report.py`, `frontend/src/components/ReportViewer.vue`) and extends existing files (`App.vue`, `ControlBar.vue`, `app.py`) without renaming any symbols or touching stored data. No string replacement across the codebase. Consequently, this section is **not applicable**. The Phase 36 planner should not include a data-migration subtask.

For completeness:

| Category | Items | Action |
|----------|-------|--------|
| Stored data | None — file system is source of truth (D-05), no new Neo4j writes | N/A |
| Live service config | None | N/A |
| OS-registered state | None | N/A |
| Secrets/env vars | None | N/A |
| Build artifacts | `frontend/node_modules` gains `marked` and `dompurify` after `npm install` — this is expected and gitignored | Run `npm install` once |

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js | `npm install marked dompurify`; Vite build | ✓ | v23.6.0 | — (Node ≥ 20 required by marked@18; v23.6 satisfies) |
| npm | Adding frontend deps | ✓ | (bundled with Node 23) | — |
| Ollama | Orchestrator model for `ReportEngine.run()` at generation time | Runtime dependency — not available at plan time | — | Phase guard (`phase == COMPLETE` implies orchestrator was just used) + `ModelLoadError` surfaces as 503 at generation time |
| Neo4j | `graph_manager.read_*` Cypher queries in background task | Runtime dependency | — | 503 on service check before spawning background task |
| Existing Phase 15 `report.py` | All generation logic | ✓ | shipped | — |
| Existing Phase 35 `interview.py` route | Pattern reference | ✓ | shipped | — |
| `reports/` directory | Read/write path for markdown files | Auto-created by `write_report()` via `path.parent.mkdir(parents=True, exist_ok=True)` | — | `write_report` already handles missing dir [VERIFIED: `report.py:328`] |
| `.alphaswarm/` directory | Sentinel write path | Exists (`last_report.json` present from prior CLI runs) | — | `write_sentinel` auto-creates [VERIFIED: `report.py:350`] |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** None — all runtime services (Ollama, Neo4j) are already required by the running FastAPI app and are service-unavailable-guarded via the standard 503 pattern.

## Common Pitfalls

### Pitfall 1: `@types/dompurify` is deprecated and will break the build

**What goes wrong:** Following CONTEXT.md D-10 verbatim (`npm install marked dompurify @types/dompurify`) installs a deprecated stub package. When DOMPurify 3.x's own bundled types collide with the stub's ambient declarations, `tsc --noEmit` (which is part of the build per `vue-tsc -b`) fails with duplicate identifier errors.

**Why it happens:** DOMPurify 3.0 (2023) shipped a `main` types export in `package.json`. The `@types/dompurify` package on DefinitelyTyped was updated to a deprecation stub (`"This is a stub types definition. dompurify provides its own type definitions, so you do not need this installed."`) but the package name still resolves and installs.

**How to avoid:** Install only `marked` and `dompurify`. Use `import DOMPurify from 'dompurify'` and let TS resolve types via the package's own `exports` map.

**Warning signs:** Compile error mentioning "duplicate identifier 'DOMPurify'" or "Module 'dompurify' already declares a global." [VERIFIED: `npm view @types/dompurify deprecated` returns the deprecation message]

### Pitfall 2: `marked.parse()` return type is `string | Promise<string>` in TS

**What goes wrong:** Since marked v5, the TypeScript signature is `parse(src: string, opt?: MarkedOptions): string | Promise<string>` to accommodate async extensions. Assigning directly to a `string` fails typecheck under `strict: true`.

**Why it happens:** The union type exists to support async token transformers in `marked.use()`. In default synchronous mode (which this phase uses), the runtime return is always a string.

**How to avoid:** Cast explicitly: `renderedHtml.value = DOMPurify.sanitize(marked.parse(content) as string)`. Alternative: use `marked.parse(content, { async: false }) as string` for self-documenting code.

**Warning signs:** TS error "Type 'string | Promise<string>' is not assignable to type 'string'."

### Pitfall 3: Orchestrator model lock deadlock on concurrent report + replay

**What goes wrong:** A user on the `complete` phase clicks "Generate Report" then immediately opens `CyclePicker` and starts a replay. Replay `start()` does not load models, but any future simulation `start()` would block on `model_manager._lock` held by the report task for minutes.

**Why it happens:** The orchestrator model is shared infrastructure. The `ModelManager._lock` serializes load/unload but does not preempt.

**How to avoid:** The phase guard (`phase != COMPLETE` → 409) already prevents `POST /simulate/start` from racing with a running report (because a simulation start moves phase to `seeding`, which contradicts the report's `complete` precondition — and the report 409 guards symmetrically). For replay: verify that replay mode does not load the orchestrator model (it reads signals from Neo4j, no inference). [VERIFIED: `replay.py:139` — `graph_manager.read_full_cycle_signals` only; no model_manager calls]

**Warning signs:** Minute-long hangs on `POST /simulate/start` after a report task has been queued but is still running.

### Pitfall 4: Polling continues after modal close (memory leak)

**What goes wrong:** User opens report viewer → generation starts → user closes modal via backdrop click → `setInterval` callback keeps firing every 3s, holding refs to detached component state.

**Why it happens:** Vue does not auto-clear timers on unmount. `onUnmounted` is the only safety net.

**How to avoid:** `onUnmounted(() => { if (pollInterval) window.clearInterval(pollInterval) })`. Pattern established by `useWebSocket.ts:128` teardown added in quick commit `260416-trw`.

**Warning signs:** Console `net::ERR_ABORTED` messages after modal close with no user action; elevated fetch count in DevTools Network tab with the modal closed.

### Pitfall 5: Report file write partially completes, GET reads truncated content

**What goes wrong:** Background task writes `reports/{cycle_id}_report.md` using `aiofiles.open`. Poll tick fires between "file exists with 0 bytes" and "write complete." GET returns empty markdown, renders as empty modal, polling stops prematurely.

**Why it happens:** Unix filesystem: `open(path, "w")` truncates immediately. There is a race window between truncation and full write completion.

**How to avoid:** Write to a temporary path and rename atomically. `report.py:write_report` currently does NOT do this — it writes directly to the final path. For Phase 36, the planner should either (a) enhance `write_report()` with atomic-rename, or (b) accept the risk (the window is ~milliseconds for a few-KB markdown file, vs 3s poll cadence). **Recommendation:** Option (a) — wrap in `path.with_suffix('.tmp')` write + `os.rename`. Document as a Phase 36 improvement or a separate quick task. This is a MEDIUM-confidence pitfall because the actual race window is very small, but correctness-minded code should close it.

**Warning signs:** Occasional empty modal on first poll-hit; `renderedHtml` empty but no error.

### Pitfall 6: Markdown `<h1>` title inside report conflicts with modal `<h1>` title

**What goes wrong:** The report content starts with `# Post-Simulation Analysis Report` (from `ReportAssembler.assemble()` header, `report.py:298–303`). The modal already shows `Report — a1b2c3d4` in its header. Two `<h1>`s on the page is a minor accessibility smell (heading structure).

**Why it happens:** The Python assembler writes markdown intended to stand alone (CLI output, file viewer). The web context adds a modal chrome around it.

**How to avoid:** The UI-SPEC styles markdown `h1` at `--font-size-display` (24px) with generous top margin — it looks like a document title, not a modal title. The modal header title is `--font-size-heading` (18px). Visual hierarchy reads naturally. Optionally, the component could strip the top-level `<h1>` from `renderedHtml` with a regex before injection, but UI-SPEC does not require this, and stripping would diverge from the CLI-generated file content. **Recommendation:** Accept as-is; the distinct font sizes + "Report — {id}" vs "Post-Simulation Analysis Report" wording prevent confusion.

**Warning signs:** A11y auditor warning "Multiple h1 elements on page."

## Code Examples

### Example 1: Report GET handler (read-through file)

```python
# Source: adapted from src/alphaswarm/web/routes/interview.py pattern
@router.get("/report/{cycle_id}", response_model=ReportResponse)
async def get_report(cycle_id: str, request: Request) -> ReportResponse:
    import datetime
    import aiofiles

    report_path = Path("reports") / f"{cycle_id}_report.md"
    if not report_path.exists():
        raise HTTPException(
            status_code=404,
            detail={"error": "report_not_found", "message": f"No report exists for cycle {cycle_id}"},
        )
    async with aiofiles.open(report_path, "r", encoding="utf-8") as f:
        content = await f.read()
    mtime = report_path.stat().st_mtime
    generated_at = datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc).isoformat()
    return ReportResponse(cycle_id=cycle_id, content=content, generated_at=generated_at)
```

### Example 2: Background task mirrors cli.py:_handle_report

See "Pattern 1" above for the full `_run_report_generation` function. The essential 1:1 mapping from the CLI version:

| CLI line (cli.py) | Web task line | Notes |
|-------------------|---------------|-------|
| 689–691 (build app) | uses `request.app.state.app_state` | Already built in lifespan |
| 699–703 (resolve cycle_id) | `cycle_id` passed in from URL path | Frontend resolves via `/api/replay/cycles` |
| 712 (load_model) | same | Wrapped in try/finally |
| 716–725 (tool registry) | same | Identical |
| 727–731 (shock pre-seed) | same | Identical |
| 734–740 (engine run) | same | Identical |
| 743–744 (assemble) | same | Identical |
| 747 (output_path) | `Path("reports") / f"{cycle_id}_report.md"` | D-03 — no `--output` override for web |
| 750–751 (write) | same | Identical |
| 755–763 (finally) | same | Identical |

### Example 3: Vue modal mount pattern

```vue
<!-- Source: frontend/src/App.vue lines 52–63 (replicated for ReportViewer) -->
<!-- ADDITIONS ONLY — existing code unchanged -->
<script setup lang="ts">
// ... existing imports
import ReportViewer from './components/ReportViewer.vue'

// ... existing state

const showReportViewer = ref(false)

function onOpenReportViewer() {
  showReportViewer.value = true
}
function onCloseReportViewer() {
  showReportViewer.value = false
}
</script>

<template>
  <!-- existing markup -->
  <ControlBar
    @open-cycle-picker="onOpenCyclePicker"
    @open-report-viewer="onOpenReportViewer"
  />

  <!-- existing CyclePicker mount -->

  <ReportViewer
    v-if="showReportViewer"
    @close="onCloseReportViewer"
  />
</template>
```

### Example 4: ControlBar Report button

```vue
<!-- Source: frontend/src/components/ControlBar.vue — ADDITIONS in complete-phase row -->
<script setup lang="ts">
// ... existing script
const isComplete = computed(() => snapshot.value.phase === 'complete')

const emit = defineEmits<{
  'open-cycle-picker': []
  'open-report-viewer': []  // NEW
}>()
</script>

<template>
  <!-- inside the <template v-else-if="isActive"> block OR a new complete-only block -->
  <template v-if="isComplete">
    <span class="control-bar__phase">Complete</span>
    <button
      class="control-bar__btn control-bar__btn--report"
      @click="emit('open-report-viewer')"
    >
      Report
    </button>
    <!-- existing Stop button if applicable -->
  </template>
</template>
```

Note: `ControlBar.vue` currently has branches for `!isActive && !isReplay` (idle), `isActive` (live), and `isReplay`. CONTEXT.md D-08 adds a fourth branch: `complete`. The planner should determine whether to add a new `isComplete` branch or extend the `!isActive && !isReplay` branch with a conditional. **Recommendation:** Add a distinct `v-else-if="isComplete"` branch — cleaner and matches the idle/active/replay/complete state machine the backend already uses (`SimulationPhase` enum).

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `@types/dompurify` stub package | DOMPurify 3.x bundled types | DOMPurify 3.0 released 2023 | Do not install the types package; import direct. |
| `marked v4` sync-only API | `marked v5+` sync OR async via `marked.use({ async: true })` | v5.0 (2023) | Default is still sync; our usage is unchanged. Only matters if you enable async extensions. |
| Custom HTML sanitizers (Caja, Google Closure) | DOMPurify sole survivor | 2015+ | Nothing else worth evaluating. DOMPurify is the only widely vetted option. |
| Polling via `setInterval` | Polling via `setInterval` (still valid for minute-long operations) | Unchanged | WebSocket would be overkill for a 3–5 minute operation; polling remains idiomatic. |
| `async def` FastAPI routes | Same | Unchanged | Project already on 0.115+. |

**Deprecated/outdated:**
- `@types/dompurify` (all v3.x releases) — deprecation stub, do not install [VERIFIED: npm registry deprecation message]
- Older marked v4.x sync-only API — harmless, but v18 is the current line with active security updates
- `marked.parse(..., callback)` callback-style API — removed in v5+

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | Python: `pytest` >= 8.0 with `pytest-asyncio` >= 0.24 (asyncio_mode = auto) [VERIFIED: `pyproject.toml`]; Frontend: no test framework currently installed — `package.json` has no test script |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (pytest); no frontend test config |
| Quick run command | `pytest tests/test_web.py -x` (~5s for web-only subset) |
| Full suite command | `pytest` (runs all of `tests/`) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| WEB-06 (backend GET) | `GET /api/report/{cycle_id}` returns 200 + JSON when file exists | unit (FastAPI TestClient + tmp_path) | `pytest tests/test_web.py::test_get_report_returns_content -x` | ❌ Wave 0 (new test) |
| WEB-06 (backend GET 404) | Returns 404 when report file is missing | unit | `pytest tests/test_web.py::test_get_report_404_when_missing -x` | ❌ Wave 0 |
| WEB-06 (backend POST 409 phase) | `POST /generate` returns 409 when phase != COMPLETE | unit | `pytest tests/test_web.py::test_generate_report_409_wrong_phase -x` | ❌ Wave 0 |
| WEB-06 (backend POST 409 in-progress) | Returns 409 when `app.state.report_task` is not `.done()` | unit | `pytest tests/test_web.py::test_generate_report_409_in_progress -x` | ❌ Wave 0 |
| WEB-06 (backend POST 202) | Returns 202 and creates task on `app.state.report_task` | unit (mocked model_manager + graph_manager) | `pytest tests/test_web.py::test_generate_report_202_spawns_task -x` | ❌ Wave 0 |
| WEB-06 (backend POST 503) | Returns 503 when graph/ollama unavailable | unit | `pytest tests/test_web.py::test_generate_report_503_no_services -x` | ❌ Wave 0 |
| REPORT-02 (generation reuses Phase 15) | Background task calls `ReportEngine.run` → `ReportAssembler.assemble` → `write_report` → `write_sentinel` | unit (mock each boundary; assert order + cycle_id pass-through) | `pytest tests/test_web.py::test_report_generation_pipeline -x` | ❌ Wave 0 |
| WEB-06 (backend POST finally) | Orchestrator unloaded in `finally` even on exception | unit | `pytest tests/test_web.py::test_report_generation_unloads_on_error -x` | ❌ Wave 0 |
| WEB-06 (frontend sanitization) | `marked` + `DOMPurify` produces safe HTML (no `<script>` in output) | manual — no frontend test framework in place | n/a — visual smoke test during acceptance | manual-only |
| WEB-06 (frontend modal a11y) | Escape closes, backdrop click closes, X button closes | manual | n/a | manual-only |

### Sampling Rate

- **Per task commit:** `pytest tests/test_web.py -x` (new report tests live here, matches existing conventions; ~5s)
- **Per wave merge:** `pytest` (full suite, ~60s based on existing test surface)
- **Phase gate:** Full suite green before `/gsd:verify-work`. Manual smoke test of frontend flow: open modal → verify empty state → click "Generate Report" → verify polling spinner → wait for completion → verify rendered markdown → close modal → reopen → verify "Regenerate Report" footer state.

### Wave 0 Gaps

- [ ] `tests/test_web.py` — add `test_get_report_*`, `test_generate_report_*`, `test_report_generation_pipeline` (8 new tests minimum)
- [ ] Test fixture: temp `reports/` directory with fixture cleanup (`tmp_path` builtin is sufficient)
- [ ] Mock helpers for `ReportEngine.run` / `write_report` / `write_sentinel` to isolate the route from Phase 15 logic
- [ ] **No frontend test infrastructure gap to fill:** Phase 36 is consistent with the project's current pattern (no Vue component tests). Introducing Vitest for just this phase would expand scope beyond WEB-06/REPORT-02.

*(Frontend behavior is covered by manual acceptance testing, matching the existing v5.0 Web UI phases 29–35 validation pattern.)*

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Single-operator local-first per CLAUDE.md "Multi-user / network mode" is Out of Scope |
| V3 Session Management | no | Same — no sessions |
| V4 Access Control | no | No users, no auth; operator has full access to their own local server |
| V5 Input Validation | **yes** | `cycle_id` path param: Pydantic string validation + `encodeURIComponent` on frontend; reject traversal (`..`) in route handler |
| V6 Cryptography | no | No secrets, no encryption at rest beyond OS filesystem |
| V14 Configuration | yes | No new environment variables; report output path is hardcoded relative to cwd |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| XSS via `v-html` of attacker-controlled markdown | Tampering / Elevation of Privilege | **DOMPurify.sanitize() mandatory before `v-html`** (D-10 requires; UI-SPEC "Security note on v-html" reinforces). Report content is LLM output from local Ollama so the threat surface is low, but the defensive layer is inexpensive and standard. |
| Path traversal via `cycle_id` (`../../../etc/passwd`) | Tampering | Validate `cycle_id` as UUID-ish format (alphanumeric + dashes) before constructing `reports/{cycle_id}_report.md`. FastAPI path param is already string; add explicit regex: `if not re.match(r'^[a-zA-Z0-9_-]+$', cycle_id): raise 400`. **Recommendation:** enforce in both GET and POST. Pydantic models can use `Annotated[str, StringConstraints(pattern=r'^[a-zA-Z0-9_-]+$')]`. |
| SSRF | N/A | No external URL fetches in the new route |
| DoS via unbounded report generation | Availability | The 409 in-progress guard limits to 1 concurrent generation. The ReACT loop has `MAX_ITERATIONS = 10` (`report.py:25`). Polling cap at 200 iterations (10 min) client-side. |
| Content-type confusion on GET response | Tampering | Pydantic `ReportResponse` with `content: str` (markdown wire format) forces JSON response; DOMPurify on the client handles rendering sanitization. Do NOT set `Content-Type: text/markdown` — keep it JSON. |
| Resource exhaustion from large reports | Availability | Typical report is < 50 KB. Vue `v-html` handles multi-MB strings but is slow. Not a practical concern at current scale. No cap needed for v1. |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `marked.parse()` in v18 is synchronous in default mode (no `marked.use({ async: true })` registered) | Standard Stack, Pattern 2 | If wrong, `renderedHtml` gets a Promise object rendered as `[object Promise]`. Low risk — marked has maintained sync-default for all major versions. [CITED: https://marked.js.org/#usage — example shown as `const html = marked.parse(str)`] |
| A2 | The polling race (Pitfall 5) window is milliseconds — small enough that in-practice hits during active poll are rare | Common Pitfalls → Pitfall 5 | If wrong, users occasionally see empty reports. Mitigation (atomic rename) is a 5-line code change. Low-to-medium risk. |
| A3 | Existing `reports/` directory will be mounted/accessible at runtime (not behind a container volume excluded from writes) | Environment Availability | If wrong, `write_report()` raises `PermissionError`. Would surface as 500 on first generation attempt. Low risk — the CLI already writes here successfully. |
| A4 | `graph_manager.read_completed_cycles(limit=1)` returns the single newest cycle ordered by `created_at DESC` | Cycle ID resolution | If wrong, frontend resolves a non-most-recent cycle; report for wrong cycle displayed. Can verify via `graph.py:1878` — ordering is explicit in the Cypher query. [VERIFIED via grep — method exists, used by interview flow same way] |
| A5 | The ReACT engine's orchestrator model is the same one loaded at seed time; a second load during `complete` phase is safe (no simulation running) | Common Pitfalls → Pitfall 3 | If wrong, concurrent simulation start would deadlock. Mitigated by 409 phase guard and replay's read-only nature. Low risk. |

## Open Questions

1. **Atomic file write for `write_report()` — enhance Phase 15 or accept as-is?**
   - What we know: Current `write_report()` writes directly to final path (`report.py:319`).
   - What's unclear: Whether the race in Pitfall 5 has been observed in practice.
   - Recommendation: Planner should decide — option A: add `write_report_atomic()` to `report.py` that uses `path.with_suffix('.tmp')` + `os.rename` (touches Phase 15 code, needs Phase 15 regression test); option B: accept the theoretical race given the 3s poll interval and few-KB file size. **Suggested default: option A — 5 LoC, eliminates the race cleanly.**

2. **ControlBar layout for the `complete` phase — add a dedicated branch or overlay with existing active?**
   - What we know: Current branches are `!isActive && !isReplay` (idle), `isActive` (live), `isReplay`. CONTEXT.md D-08 says "Report button sits alongside the existing Stop button in the active/complete control row" — but Stop is only shown during `isActive`.
   - What's unclear: Does the user want Stop visible in `complete`? (semantically there's nothing to stop). Or is `complete` actually a new fourth branch?
   - Recommendation: Add a `<template v-else-if="isComplete">` branch showing only the Report button + a "Complete" status label. No Stop button in `complete` (nothing to stop). The CONTEXT.md phrasing was pattern-oriented, not literal. **Flag for planner confirmation.**

3. **Should `POST /generate` return the task ID so the frontend can check a specific generation?**
   - What we know: Current design uses a single `app.state.report_task` singleton across all cycles.
   - What's unclear: If the user regenerates a different cycle mid-flight (theoretically possible if they replay, finish, and generate for a different cycle — but currently D-09 always resolves to the newest), does single-task-handle suffice?
   - Recommendation: Single handle is fine for v1. The UI always operates on the newest cycle; multi-cycle generation is not a user flow we support.

4. **Polling timeout (10 min) — surface the timeout on the backend too?**
   - What we know: Frontend stops polling after 200 iterations. Backend task runs to completion regardless.
   - What's unclear: If a report takes >10 min, should the backend cancel its task? Or let it finish and become available on next open?
   - Recommendation: Let it finish. User reopens → fetches the file → sees it. Cancelling mid-task would waste LLM compute and leave partial files. **UI-SPEC already documents this: "The backend task continues — on next open, user can GET the finished report or see it still generating."**

## Sources

### Primary (HIGH confidence)
- Context7 libraries — not queried (all libraries are standard ecosystem; npm registry direct verification was sufficient)
- **npm registry** via `npm view` — verified versions of `marked`, `dompurify`, `@types/dompurify` (deprecation confirmed) on 2026-04-16
- **Codebase files (directly read):**
  - `src/alphaswarm/report.py` — ReportEngine, ReportAssembler, write_report, write_sentinel signatures
  - `src/alphaswarm/cli.py` lines 664–763 — canonical `_handle_report` reference pattern
  - `src/alphaswarm/web/app.py` — lifespan singleton init pattern
  - `src/alphaswarm/web/routes/interview.py` — phase guard + 503 + app.state access
  - `src/alphaswarm/web/routes/replay.py` — 409 concurrency conflict + background task pattern
  - `src/alphaswarm/web/simulation_manager.py` — `is_running` + `asyncio.Task` lifecycle
  - `src/alphaswarm/ollama_models.py` — `load_model` / `unload_model` internal lock
  - `src/alphaswarm/types.py` — `SimulationPhase` enum
  - `frontend/src/App.vue` — modal mount + ref pattern
  - `frontend/src/components/CyclePicker.vue` — modal chrome, backdrop, Escape, fetch-on-open
  - `frontend/src/components/ControlBar.vue` — phase-conditional button branches
  - `frontend/src/components/InterviewPanel.vue` — async fetch with inline error pattern
  - `frontend/package.json` / `pyproject.toml` — stack versions
  - `.planning/phases/36-report-viewer/36-UI-SPEC.md` — full design contract (authoritative)
  - `.planning/phases/36-report-viewer/36-CONTEXT.md` — locked decisions
  - `.planning/phases/35-agent-interviews-web-ui/35-CONTEXT.md` — pattern history
  - `.planning/REQUIREMENTS.md` — WEB-06 and REPORT-02 wording
  - `.planning/config.json` — workflow flags

### Secondary (MEDIUM confidence)
- **marked official docs** (https://marked.js.org/#usage) — fetched 2026-04-16, confirmed synchronous default API
- **DOMPurify README** (https://github.com/cure53/DOMPurify) — fetched 2026-04-16, confirmed built-in TS types in v3.x
- **MDN `Intl.RelativeTimeFormat`** — relied on long-standing stable API; not re-fetched

### Tertiary (LOW confidence)
- None — all claims in this document are either verified against code/registry/official docs, or explicitly tagged `[ASSUMED]` in the Assumptions Log above.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all versions verified against npm registry 2026-04-16
- Architecture: HIGH — every pattern has a direct reference in the existing codebase (interview.py, replay.py, CyclePicker.vue)
- Pitfalls: MEDIUM-HIGH — Pitfalls 1, 4 are verified via registry/codebase; Pitfalls 2, 3, 5, 6 are reasoned from API signatures and require planner judgment on mitigation depth
- Security: HIGH — Single-operator local-first threat model is narrow; DOMPurify + cycle_id validation covers the relevant surface
- Validation: HIGH — pytest + TestClient patterns are established; frontend manual-acceptance is consistent with phases 29–35

**Research date:** 2026-04-16
**Valid until:** 2026-05-16 (30 days — stack is mature, Node 23 stable, marked and DOMPurify release cadence is slow-major)

---

*Phase: 36-report-viewer*
*Research complete: 2026-04-16*
