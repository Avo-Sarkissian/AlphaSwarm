<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

/**
 * Phase 36 — ReportViewer (revision 1, 2026-04-17)
 *
 * Full-screen modal that reads reports/{cycle_id}_report.md from the backend
 * and renders it as sanitized markdown. Also triggers async report generation
 * via POST /api/report/{cycle_id}/generate and polls for completion every 3s.
 *
 * REVISION-1 notes (from 36-REVIEWS.md):
 *   - `isGenerating` is SEPARATE from `viewState`. During polling a 404 GET
 *     does NOT revert the UI to 'empty' — it just means the file isn't ready
 *     yet. Without this guard the spinner would disappear after the first
 *     poll tick (Codex HIGH severity, T-36-17).
 *   - GET 500 `report_generation_failed` is now a terminal state. The
 *     backend's done_callback (Plan 01 T-36-15) writes the failure into
 *     app.state.report_generation_error[cycle_id]; the GET endpoint then
 *     returns 500 so the client can stop polling immediately instead of
 *     waiting out the 10-minute cap (T-36-18).
 *
 * Decisions: D-01 trigger model, D-02 409 guards, D-03 output path,
 * D-04 polling cadence, D-05 GET contract, D-06 modal placement,
 * D-07 component structure, D-08 access trigger, D-09 open flow,
 * D-10 markdown stack, D-11 scoped CSS.
 */

const emit = defineEmits<{
  'close': []
}>()

// ---- State (REVISION-1: viewState and isGenerating are independent) ----

type ViewState = 'loading' | 'empty' | 'rendered'
// NOTE: 'generating' is NOT a viewState value — it is a computed display
// state derived from isGenerating. The content area only needs to know
// what to render (loading, empty, or rendered); the footer/button handle
// generation status.

const viewState = ref<ViewState>('loading')
const isGenerating = ref<boolean>(false)      // REVISION-1: independent generation flag
const cycleId = ref<string>('')
const cycleIdShort = computed(() => cycleId.value.slice(0, 8))
const rawContent = ref<string>('')
const renderedHtml = ref<string>('')
const generatedAt = ref<string>('')
const errorMessage = ref<string>('')

// Polling infrastructure (D-04, T-36-10, T-36-11)
const MAX_POLL_ITERATIONS = 200 // 200 * 3s = 10 minutes
const POLL_INTERVAL_MS = 3000
const pollIntervalId = ref<ReturnType<typeof setInterval> | null>(null)
const pollIterations = ref(0)

// ---- Lifecycle ----------------------------------------------------------

onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  await resolveCycleAndLoad()
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  stopPolling() // T-36-11: guarantee setInterval is cleared on unmount
})

// ---- Cycle resolution + initial load (D-09) -----------------------------

async function resolveCycleAndLoad(): Promise<void> {
  viewState.value = 'loading'
  errorMessage.value = ''
  try {
    const res = await fetch('/api/replay/cycles')
    if (!res.ok) throw new Error('cycles fetch failed')
    const data = await res.json() as { cycles: { cycle_id: string }[] }
    if (!data.cycles || data.cycles.length === 0) {
      errorMessage.value = 'No completed cycles found. Run a simulation first.'
      viewState.value = 'empty'
      return
    }
    // Most-recent-first ordering is the convention of the replay endpoint.
    cycleId.value = data.cycles[0].cycle_id
    await loadReport()
  } catch {
    errorMessage.value = 'Could not load report. Try again.'
    viewState.value = 'empty'
  }
}

/**
 * loadReport — fetches GET /api/report/{cycle_id} and updates state.
 *
 * REVISION-1 state transitions:
 *   200 -> viewState='rendered', isGenerating=false, stopPolling()
 *   404 (isGenerating === false) -> viewState='empty'   (initial empty state)
 *   404 (isGenerating === true)  -> NO-OP on viewState  (stay in generating
 *                                    display until the file appears or the
 *                                    backend reports failure)
 *   500 (report_generation_failed) -> stopPolling(), isGenerating=false,
 *                                    viewState='empty', errorMessage=body.message
 *                                    (T-36-18 — terminal failure from backend
 *                                    done_callback, do not keep polling)
 *   other non-ok -> errorMessage set (only shown when not polling)
 */
async function loadReport(): Promise<void> {
  try {
    const res = await fetch(`/api/report/${cycleId.value}`)

    if (res.status === 200) {
      const body = await res.json() as { cycle_id: string; content: string; generated_at: string }
      rawContent.value = body.content
      generatedAt.value = body.generated_at
      renderMarkdown(body.content)
      viewState.value = 'rendered'
      isGenerating.value = false
      errorMessage.value = ''
      stopPolling()
      return
    }

    if (res.status === 404) {
      // REVISION-1: Only transition to 'empty' when no generation is in flight.
      // During polling a 404 simply means the file isn't ready yet — keep
      // the spinner visible until success, failure, or timeout.
      if (!isGenerating.value) {
        viewState.value = 'empty'
      }
      return
    }

    if (res.status === 500) {
      // REVISION-1 (T-36-18): Backend done_callback reported a failed task.
      // Stop polling immediately so the operator sees the error instead of
      // waiting out the 10-minute MAX_POLL_ITERATIONS cap.
      const body = await res.json().catch(() => ({ detail: {} }))
      const errCode = body?.detail?.error as string | undefined
      const errMsg = body?.detail?.message as string | undefined
      if (errCode === 'report_generation_failed') {
        errorMessage.value = errMsg ?? 'Report generation failed. Try again.'
      } else {
        errorMessage.value = 'Report service error. Try again.'
      }
      stopPolling()
      isGenerating.value = false
      viewState.value = 'empty'
      return
    }

    // Other non-ok: only surface error when not polling (transient hiccups
    // during polling should be absorbed by the next tick).
    if (!isGenerating.value) {
      errorMessage.value = 'Could not load report. Try again.'
    }
  } catch {
    // Network error. Silent during polling — next tick retries.
    if (!isGenerating.value) {
      errorMessage.value = 'Could not load report. Try again.'
    }
  }
}

// ---- marked + DOMPurify render pipeline (D-10, T-36-08, T-36-09) --------

function renderMarkdown(content: string): void {
  // marked v18 synchronous default: parse() returns string | Promise<string>.
  // We never pass {async: true}, so the return is always a string.
  const rawHtml = marked.parse(content) as string
  // DOMPurify.sanitize scrubs <script>, on*=, javascript: URLs, srcdoc, etc.
  renderedHtml.value = DOMPurify.sanitize(rawHtml)
}

// ---- Generate + polling flow (D-01, D-02, D-04) -------------------------

async function onGenerateClick(): Promise<void> {
  if (isGenerating.value) return
  errorMessage.value = ''
  isGenerating.value = true                // REVISION-1: set flag BEFORE fetch
  try {
    const res = await fetch(`/api/report/${cycleId.value}/generate`, { method: 'POST' })
    if (res.status === 202) {
      startPolling()
      return
    }
    if (res.status === 409) {
      const body = await res.json().catch(() => ({ detail: {} }))
      const errCode = body?.detail?.error as string | undefined
      if (errCode === 'report_generation_in_progress') {
        // Silent recovery — already running, just poll.
        startPolling()
        return
      }
      if (errCode === 'report_unavailable') {
        errorMessage.value = 'Simulation must be complete before generating a report.'
        isGenerating.value = false
        if (viewState.value !== 'rendered') viewState.value = 'empty'
        return
      }
    }
    if (res.status === 503) {
      errorMessage.value = 'Report services are unavailable. Check Neo4j and Ollama.'
      isGenerating.value = false
      if (viewState.value !== 'rendered') viewState.value = 'empty'
      return
    }
    errorMessage.value = 'Could not start report generation. Try again.'
    isGenerating.value = false
    if (viewState.value !== 'rendered') viewState.value = 'empty'
  } catch {
    errorMessage.value = 'Could not start report generation. Try again.'
    isGenerating.value = false
    if (viewState.value !== 'rendered') viewState.value = 'empty'
  }
}

function startPolling(): void {
  stopPolling() // clear any previous interval
  pollIterations.value = 0
  pollIntervalId.value = setInterval(() => {
    pollIterations.value += 1
    if (pollIterations.value >= MAX_POLL_ITERATIONS) {
      stopPolling()
      isGenerating.value = false
      errorMessage.value = 'Report generation is taking longer than expected. The task may still complete — try refreshing in a few minutes.'
      if (viewState.value !== 'rendered') viewState.value = 'empty'
      return
    }
    void loadReport()
  }, POLL_INTERVAL_MS)
}

function stopPolling(): void {
  if (pollIntervalId.value !== null) {
    clearInterval(pollIntervalId.value)
    pollIntervalId.value = null
  }
}

// ---- Close handlers (CyclePicker pattern) -------------------------------

function onBackdropClick(e: MouseEvent): void {
  if ((e.target as HTMLElement).classList.contains('report-viewer-backdrop')) {
    emit('close')
  }
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape') emit('close')
}

// ---- Relative time formatter for footer status --------------------------

const relativeGenerated = computed<string>(() => {
  if (!generatedAt.value) return ''
  const then = new Date(generatedAt.value).getTime()
  if (Number.isNaN(then)) return ''
  const diffSec = Math.max(0, Math.floor((Date.now() - then) / 1000))
  if (diffSec < 10) return 'just now'
  if (diffSec < 60) return `${diffSec} seconds ago`
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin} minute${diffMin === 1 ? '' : 's'} ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr} hour${diffHr === 1 ? '' : 's'} ago`
  const diffDay = Math.floor(diffHr / 24)
  return `${diffDay} day${diffDay === 1 ? '' : 's'} ago`
})

// ---- Derived UI state (REVISION-1: all derived from both flags) --------

const generateBtnLabel = computed<string>(() => {
  if (isGenerating.value) return 'Generating...'
  if (viewState.value === 'rendered') return 'Regenerate Report'
  return 'Generate Report'
})

const footerStatus = computed<string>(() => {
  if (isGenerating.value) return 'Generating report...'
  if (viewState.value === 'rendered') return `Generated ${relativeGenerated.value}`
  return 'No report generated yet.'
})

// Combined display mode for the content area (mutually exclusive rendering).
// REVISION-1: 'generating' display is derived, not a raw state value.
const displayMode = computed<'loading' | 'empty-or-generating' | 'rendered'>(() => {
  if (viewState.value === 'loading') return 'loading'
  if (viewState.value === 'rendered') return 'rendered'
  return 'empty-or-generating' // covers both empty and active generation
})
</script>

<template>
  <Transition name="modal">
    <div class="report-viewer-backdrop" @click="onBackdropClick">
      <div class="report-viewer-modal" role="dialog" aria-modal="true" :aria-label="`Report — ${cycleIdShort}`">
        <!-- Header -->
        <div class="report-viewer__header">
          <h2 class="report-viewer__title">Report — {{ cycleIdShort || '...' }}</h2>
          <button
            class="report-viewer__close-btn"
            aria-label="Close report viewer"
            @click="emit('close')"
          >
            &#10005;
          </button>
        </div>

        <!-- Content -->
        <div class="report-viewer__content">
          <div v-if="displayMode === 'loading'" class="report-viewer__state-block">
            <p class="report-viewer__state-body">Loading report...</p>
          </div>

          <div v-else-if="displayMode === 'empty-or-generating'" class="report-viewer__state-block">
            <h3 class="report-viewer__state-heading">No report generated yet</h3>
            <p class="report-viewer__state-body">
              Generate a market analysis report from this cycle's simulation data.
            </p>
          </div>

          <div
            v-else-if="displayMode === 'rendered'"
            class="report-viewer__markdown"
            v-html="renderedHtml"
          />
        </div>

        <!-- Inline error (above footer) -->
        <div v-if="errorMessage" class="report-viewer__error">{{ errorMessage }}</div>

        <!-- Footer -->
        <div class="report-viewer__footer">
          <span
            class="report-viewer__status"
            :class="{ 'report-viewer__status--generating': isGenerating }"
          >
            {{ footerStatus }}
          </span>
          <button
            class="report-viewer__generate-btn"
            :class="{ 'report-viewer__generate-btn--disabled': isGenerating }"
            :disabled="isGenerating || !cycleId"
            @click="onGenerateClick"
          >
            {{ generateBtnLabel }}
          </button>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
/* ---------------- Modal chrome (UI-SPEC Anatomy) ---------------- */

.report-viewer-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 17, 23, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}

.report-viewer-modal {
  width: 80vw;
  max-width: 1200px;
  min-width: 640px;
  height: 80vh;
  max-height: 900px;
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.4);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.report-viewer__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-lg);
  border-bottom: 1px solid var(--color-border);
  flex-shrink: 0;
}

.report-viewer__title {
  font-size: var(--font-size-heading);
  font-weight: var(--font-weight-semibold);
  line-height: var(--line-height-heading);
  color: var(--color-text-primary);
  margin: 0;
}

.report-viewer__close-btn {
  background: none;
  border: none;
  color: var(--color-text-secondary);
  font-size: 16px;
  padding: var(--space-sm);
  cursor: pointer;
  line-height: 1;
}
.report-viewer__close-btn:hover {
  color: var(--color-accent);
}

.report-viewer__content {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-lg);
  min-height: 0;
}

/* Loading / empty / generating states share a centered layout */
.report-viewer__state-block {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-sm);
  text-align: center;
}
.report-viewer__state-heading {
  font-size: var(--font-size-heading);
  font-weight: var(--font-weight-semibold);
  line-height: var(--line-height-heading);
  color: var(--color-text-primary);
  margin: 0;
}
.report-viewer__state-body {
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-regular);
  line-height: var(--line-height-body);
  color: var(--color-text-muted);
  margin: 0;
}

/* ---------------- Footer (UI-SPEC Footer) ---------------- */

.report-viewer__footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-md) var(--space-lg);
  border-top: 1px solid var(--color-border);
  flex-shrink: 0;
  min-height: 48px;
}

.report-viewer__status {
  font-size: var(--font-size-label);
  font-weight: var(--font-weight-regular);
  line-height: var(--line-height-label);
  color: var(--color-text-secondary);
}
.report-viewer__status--generating {
  color: var(--color-text-muted);
  animation: generating-pulse 1.5s ease-in-out infinite;
}

.report-viewer__generate-btn {
  height: 32px;
  padding: 0 var(--space-md);
  background: var(--color-accent);
  color: var(--color-text-primary);
  border: none;
  border-radius: 4px;
  font-family: var(--font-family);
  font-size: var(--font-size-label);
  font-weight: var(--font-weight-semibold);
  cursor: pointer;
}
.report-viewer__generate-btn:hover:not(:disabled) {
  background: var(--color-accent-hover);
}
.report-viewer__generate-btn--disabled,
.report-viewer__generate-btn:disabled {
  background: var(--color-border);
  color: var(--color-text-muted);
  cursor: not-allowed;
}

.report-viewer__error {
  font-size: var(--font-size-label);
  font-weight: var(--font-weight-regular);
  line-height: var(--line-height-label);
  color: var(--color-destructive);
  padding: var(--space-xs) var(--space-lg);
  border-top: 1px solid var(--color-border);
  flex-shrink: 0;
}

/* ---------------- Scoped markdown typography (D-11) ---------------- */
/*
 * Per UI-SPEC: headings retain --line-height-heading (1.2); prose uses
 * 1.6 for long-form readability. Accent is reserved for `strong` + links.
 * h1 reset is scoped to `.report-viewer__markdown` ONLY (Pitfall 6).
 */

.report-viewer__markdown {
  color: var(--color-text-primary);
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-regular);
  line-height: 1.6;
}
.report-viewer__markdown :deep(h1) {
  font-size: var(--font-size-display);
  font-weight: var(--font-weight-semibold);
  line-height: var(--line-height-heading);
  color: var(--color-text-primary);
  margin: 0 0 var(--space-md);
}
.report-viewer__markdown :deep(h2) {
  font-size: var(--font-size-heading);
  font-weight: var(--font-weight-semibold);
  line-height: var(--line-height-heading);
  color: var(--color-text-primary);
  margin: var(--space-xl) 0 var(--space-md);
  padding-bottom: var(--space-xs);
  border-bottom: 1px solid var(--color-border);
}
.report-viewer__markdown :deep(h3) {
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin: var(--space-lg) 0 var(--space-sm);
}
.report-viewer__markdown :deep(p) {
  font-size: var(--font-size-body);
  line-height: 1.6;
  color: var(--color-text-primary);
  margin: 0 0 var(--space-md);
}
.report-viewer__markdown :deep(strong) {
  font-weight: var(--font-weight-semibold);
  color: var(--color-accent);
}
.report-viewer__markdown :deep(em) {
  font-style: italic;
  color: var(--color-text-primary);
}
.report-viewer__markdown :deep(a) {
  color: var(--color-accent);
  text-decoration: underline;
}
.report-viewer__markdown :deep(a:hover) {
  color: var(--color-accent-hover);
}
.report-viewer__markdown :deep(ul),
.report-viewer__markdown :deep(ol) {
  margin: 0 0 var(--space-md);
  padding-left: var(--space-lg);
}
.report-viewer__markdown :deep(li) {
  font-size: var(--font-size-body);
  line-height: 1.6;
  margin-bottom: var(--space-xs);
}
.report-viewer__markdown :deep(blockquote) {
  margin: 0 0 var(--space-md);
  padding: var(--space-sm) var(--space-md);
  border-left: 3px solid var(--color-border);
  color: var(--color-text-secondary);
  font-style: italic;
}
.report-viewer__markdown :deep(code) {
  font-family: 'Courier New', monospace;
  font-size: var(--font-size-label);
  background: var(--color-bg-primary);
  padding: var(--space-xs) var(--space-xs);
  border-radius: 2px;
}
.report-viewer__markdown :deep(pre) {
  margin: 0 0 var(--space-md);
  overflow-x: auto;
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: 4px;
  padding: var(--space-md);
}
.report-viewer__markdown :deep(pre code) {
  background: transparent;
  padding: 0;
  border-radius: 0;
  font-size: var(--font-size-label);
}
.report-viewer__markdown :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 0 0 var(--space-md);
  font-size: var(--font-size-body);
}
.report-viewer__markdown :deep(th) {
  background: var(--color-bg-primary);
  color: var(--color-text-primary);
  font-weight: var(--font-weight-semibold);
  text-align: left;
  padding: var(--space-sm) var(--space-md);
  border: 1px solid var(--color-border);
}
.report-viewer__markdown :deep(td) {
  color: var(--color-text-primary);
  padding: var(--space-sm) var(--space-md);
  border: 1px solid var(--color-border);
}
.report-viewer__markdown :deep(hr) {
  border: none;
  border-top: 1px solid var(--color-border);
  margin: var(--space-xl) 0;
}

/* ---------------- Animations ---------------- */

@keyframes generating-pulse {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 1.0; }
}

/* Modal enter/exit (reuse CyclePicker tokens) */
.modal-enter-active {
  transition: opacity var(--duration-modal-enter) ease-out, transform var(--duration-modal-enter) ease-out;
}
.modal-leave-active {
  transition: opacity var(--duration-modal-exit) ease-in, transform var(--duration-modal-exit) ease-in;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

/* ---------------- Responsive breakpoints (UI-SPEC) ---------------- */

@media (max-width: 1023px) {
  .report-viewer-modal {
    width: 90vw;
    height: 85vh;
    max-width: none;
    min-width: 0;
  }
}
@media (max-width: 767px) {
  .report-viewer-modal {
    width: 95vw;
    height: 95vh;
  }
}
</style>
