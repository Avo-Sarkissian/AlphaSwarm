<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

/**
 * Phase 41 — AdvisoryPanel (per D-14 .. D-19)
 *
 * Full-screen modal that triggers POST /api/advisory/{cycle_id} and polls
 * GET /api/advisory/{cycle_id} every 3s. Renders portfolio_outlook as a
 * prose paragraph followed by a ranked AdvisoryItem table.
 *
 * REVISION-1 dual-flag state machine (ported from ReportViewer Phase 36):
 *   - viewState is independent from isAnalyzing. A 404 during polling
 *     does NOT revert the UI to 'empty' — it just means the advisory
 *     file isn't on disk yet (D-11 persistence semantics).
 *   - GET 500 { error: "advisory_generation_failed" } is terminal. The
 *     backend done_callback (Plan 02 Task 1) captures synthesis failures
 *     into app.state.advisory_generation_error[cycle_id] so the GET
 *     endpoint can surface 500 and let the client stop polling.
 *
 * Decisions: D-14 modal chrome, D-15 trigger, D-16 layout, D-17
 * only-affected-holdings, D-18 signal color coding, D-19 dual-flag.
 */

const emit = defineEmits<{
  'close': []
}>()

type Signal = 'BUY' | 'SELL' | 'HOLD'

interface AdvisoryItem {
  ticker: string
  consensus_signal: Signal
  confidence: number
  rationale_summary: string
  position_exposure: string       // Decimal serialized as string by backend
}

interface AdvisoryPayload {
  cycle_id: string
  items: AdvisoryItem[]
  portfolio_outlook: string
  total_holdings: number
  generated_at: string
}

type ViewState = 'loading' | 'empty' | 'rendered'

const viewState = ref<ViewState>('loading')
const isAnalyzing = ref<boolean>(false)
const cycleId = ref<string>('')
const cycleIdShort = computed(() => cycleId.value.slice(0, 8))
const items = ref<AdvisoryItem[]>([])
const portfolioOutlook = ref<string>('')
const holdingsTotal = ref<number>(0)
const generatedAt = ref<string>('')
const errorMessage = ref<string>('')

const MAX_POLL_ITERATIONS = 200        // 200 * 3s = 10 minutes
const POLL_INTERVAL_MS = 3000
const pollIntervalId = ref<ReturnType<typeof setInterval> | null>(null)
const pollIterations = ref(0)

onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  await resolveCycleAndLoad()
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  stopPolling()
})

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
    cycleId.value = data.cycles[0].cycle_id
    await loadAdvisory()
  } catch {
    errorMessage.value = 'Could not load advisory. Try again.'
    viewState.value = 'empty'
  }
}

async function loadAdvisory(): Promise<void> {
  try {
    const res = await fetch(`/api/advisory/${cycleId.value}`)

    if (res.status === 200) {
      const body = await res.json() as AdvisoryPayload
      items.value = body.items
      portfolioOutlook.value = body.portfolio_outlook
      holdingsTotal.value = body.total_holdings
      generatedAt.value = body.generated_at
      viewState.value = 'rendered'
      isAnalyzing.value = false
      errorMessage.value = ''
      stopPolling()
      return
    }

    if (res.status === 404) {
      // REVISION-1: keep polling if a generation is in flight
      if (!isAnalyzing.value) {
        viewState.value = 'empty'
      }
      return
    }

    if (res.status === 500) {
      const body = await res.json().catch(() => ({ detail: {} }))
      const errCode = body?.detail?.error as string | undefined
      const errMsg = body?.detail?.message as string | undefined
      if (errCode === 'advisory_generation_failed') {
        errorMessage.value = errMsg ?? 'Advisory generation failed. Try again.'
      } else {
        errorMessage.value = 'Advisory service error. Try again.'
      }
      stopPolling()
      isAnalyzing.value = false
      viewState.value = 'empty'
      return
    }

    // Other non-ok: only surface when not polling
    if (!isAnalyzing.value) {
      errorMessage.value = 'Could not load advisory. Try again.'
    }
  } catch {
    if (!isAnalyzing.value) {
      errorMessage.value = 'Could not load advisory. Try again.'
    }
  }
}

async function onAnalyzeClick(): Promise<void> {
  if (isAnalyzing.value) return
  errorMessage.value = ''
  isAnalyzing.value = true
  try {
    const res = await fetch(`/api/advisory/${cycleId.value}`, { method: 'POST' })
    if (res.status === 202) {
      startPolling()
      return
    }
    if (res.status === 409) {
      const body = await res.json().catch(() => ({ detail: {} }))
      const errCode = body?.detail?.error as string | undefined
      if (errCode === 'advisory_generation_in_progress' || errCode === 'report_generation_in_progress') {
        // Silent recovery — another orchestrator consumer is running, just poll.
        startPolling()
        return
      }
      if (errCode === 'advisory_unavailable') {
        errorMessage.value = 'Simulation must be complete before analyzing.'
        isAnalyzing.value = false
        if (viewState.value !== 'rendered') viewState.value = 'empty'
        return
      }
    }
    if (res.status === 503) {
      const body = await res.json().catch(() => ({ detail: {} }))
      const errCode = body?.detail?.error as string | undefined
      if (errCode === 'no_portfolio' || errCode === 'holdings_unavailable') {
        errorMessage.value = 'Advisory requires a loaded portfolio snapshot.'
      } else {
        errorMessage.value = 'Advisory services are unavailable. Check Neo4j and Ollama.'
      }
      isAnalyzing.value = false
      if (viewState.value !== 'rendered') viewState.value = 'empty'
      return
    }
    errorMessage.value = 'Could not start advisory analysis. Try again.'
    isAnalyzing.value = false
    if (viewState.value !== 'rendered') viewState.value = 'empty'
  } catch {
    errorMessage.value = 'Could not start advisory analysis. Try again.'
    isAnalyzing.value = false
    if (viewState.value !== 'rendered') viewState.value = 'empty'
  }
}

function startPolling(): void {
  stopPolling()
  pollIterations.value = 0
  pollIntervalId.value = setInterval(() => {
    pollIterations.value += 1
    if (pollIterations.value >= MAX_POLL_ITERATIONS) {
      stopPolling()
      isAnalyzing.value = false
      errorMessage.value = 'Advisory analysis is taking longer than expected. The task may still complete — try refreshing in a few minutes.'
      if (viewState.value !== 'rendered') viewState.value = 'empty'
      return
    }
    void loadAdvisory()
  }, POLL_INTERVAL_MS)
}

function stopPolling(): void {
  if (pollIntervalId.value !== null) {
    clearInterval(pollIntervalId.value)
    pollIntervalId.value = null
  }
}

function onBackdropClick(e: MouseEvent): void {
  if ((e.target as HTMLElement).classList.contains('advisory-panel-backdrop')) {
    emit('close')
  }
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape') emit('close')
}

// Relative time for footer (mirrors ReportViewer.relativeGenerated)
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

const analyzeBtnLabel = computed<string>(() => {
  if (isAnalyzing.value) return 'Analyzing...'
  if (viewState.value === 'rendered') return 'Re-analyze'
  return 'Analyze'
})

const footerStatus = computed<string>(() => {
  if (isAnalyzing.value) return 'Analyzing advisory...'
  if (viewState.value === 'rendered') {
    // D-17: "{N} of {total_holdings} positions affected by this simulation."
    return `${items.value.length} of ${holdingsTotal.value} positions affected — generated ${relativeGenerated.value}`
  }
  return 'No advisory generated yet.'
})

const displayMode = computed<'loading' | 'empty-or-analyzing' | 'rendered'>(() => {
  if (viewState.value === 'loading') return 'loading'
  if (viewState.value === 'rendered') return 'rendered'
  return 'empty-or-analyzing'
})

// D-18 signal color classes
function signalClass(signal: Signal): string {
  if (signal === 'BUY') return 'advisory-panel__signal--buy'
  if (signal === 'SELL') return 'advisory-panel__signal--sell'
  return 'advisory-panel__signal--hold'
}

function formatConfidence(c: number): string {
  return `${Math.round(c * 100)}%`
}

function formatExposure(e: string): string {
  // Backend serializes Decimal as string. Coerce to Number for display; fall back to raw if NaN.
  const n = Number(e)
  if (Number.isNaN(n)) return e
  return `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}
</script>

<template>
  <Transition name="modal">
    <div class="advisory-panel-backdrop" @click="onBackdropClick">
      <div class="advisory-panel-modal" role="dialog" aria-modal="true" :aria-label="`Advisory — ${cycleIdShort}`">
        <!-- Header (D-16.1) -->
        <div class="advisory-panel__header">
          <h2 class="advisory-panel__title">Advisory — {{ cycleIdShort || '...' }}</h2>
          <button
            class="advisory-panel__close-btn"
            aria-label="Close advisory panel"
            @click="emit('close')"
          >
            &#10005;
          </button>
        </div>

        <!-- Content -->
        <div class="advisory-panel__content">
          <div v-if="displayMode === 'loading'" class="advisory-panel__state-block">
            <p class="advisory-panel__state-body">Loading advisory...</p>
          </div>

          <div v-else-if="displayMode === 'empty-or-analyzing'" class="advisory-panel__state-block">
            <h3 class="advisory-panel__state-heading">No advisory generated yet</h3>
            <p class="advisory-panel__state-body">
              Analyze this cycle to see which positions the simulation affects.
            </p>
          </div>

          <div v-else-if="displayMode === 'rendered'" class="advisory-panel__body">
            <!-- Narrative block (D-16.2) -->
            <p class="advisory-panel__outlook">{{ portfolioOutlook }}</p>

            <!-- Divider (D-16.3) -->
            <div class="advisory-panel__divider" />

            <!-- Table (D-16.4, D-17, D-18) -->
            <table v-if="items.length > 0" class="advisory-panel__table">
              <thead>
                <tr>
                  <th>TICKER</th>
                  <th>SIGNAL</th>
                  <th>CONF</th>
                  <th>EXPOSURE</th>
                  <th>RATIONALE</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in items" :key="item.ticker">
                  <td class="advisory-panel__cell-ticker">{{ item.ticker }}</td>
                  <td :class="['advisory-panel__cell-signal', signalClass(item.consensus_signal)]">
                    {{ item.consensus_signal }}
                  </td>
                  <td class="advisory-panel__cell-conf">{{ formatConfidence(item.confidence) }}</td>
                  <td class="advisory-panel__cell-exposure">{{ formatExposure(item.position_exposure) }}</td>
                  <td class="advisory-panel__cell-rationale">{{ item.rationale_summary }}</td>
                </tr>
              </tbody>
            </table>
            <p v-else class="advisory-panel__empty-table">No holdings were affected by this simulation.</p>
          </div>
        </div>

        <!-- Inline error (above footer) -->
        <div v-if="errorMessage" class="advisory-panel__error">{{ errorMessage }}</div>

        <!-- Footer (D-16.5) -->
        <div class="advisory-panel__footer">
          <span
            class="advisory-panel__status"
            :class="{ 'advisory-panel__status--analyzing': isAnalyzing }"
          >
            {{ footerStatus }}
          </span>
          <button
            class="advisory-panel__analyze-btn"
            :class="{ 'advisory-panel__analyze-btn--disabled': isAnalyzing }"
            :disabled="isAnalyzing || !cycleId"
            @click="onAnalyzeClick"
          >
            {{ analyzeBtnLabel }}
          </button>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
/* ---- Modal chrome (D-14: same 80vw × 80vh, 1200 × 900 cap) ---- */
.advisory-panel-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 17, 23, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}
.advisory-panel-modal {
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
.advisory-panel__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-lg);
  border-bottom: 1px solid var(--color-border);
  flex-shrink: 0;
}
.advisory-panel__title {
  font-size: var(--font-size-heading);
  font-weight: var(--font-weight-semibold);
  line-height: var(--line-height-heading);
  color: var(--color-text-primary);
  margin: 0;
}
.advisory-panel__close-btn {
  background: none;
  border: none;
  color: var(--color-text-secondary);
  font-size: 16px;
  padding: var(--space-sm);
  cursor: pointer;
  line-height: 1;
}
.advisory-panel__close-btn:hover { color: var(--color-accent); }

.advisory-panel__content {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-lg);
  min-height: 0;
}

/* ---- Empty / loading states ---- */
.advisory-panel__state-block {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-sm);
  text-align: center;
}
.advisory-panel__state-heading {
  font-size: var(--font-size-heading);
  font-weight: var(--font-weight-semibold);
  line-height: var(--line-height-heading);
  color: var(--color-text-primary);
  margin: 0;
}
.advisory-panel__state-body {
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-regular);
  line-height: var(--line-height-body);
  color: var(--color-text-muted);
  margin: 0;
}

/* ---- Rendered body: narrative + divider + table (D-16.2 .. D-16.4) ---- */
.advisory-panel__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
}
.advisory-panel__outlook {
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-regular);
  line-height: 1.6;
  color: var(--color-text-primary);
  margin: 0;
  white-space: pre-wrap;     /* preserve LLM-generated paragraph breaks */
}
.advisory-panel__divider {
  height: 1px;
  background: var(--color-border);
}
.advisory-panel__table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-body);
}
.advisory-panel__table th {
  background: var(--color-bg-primary);
  color: var(--color-text-secondary);
  font-weight: var(--font-weight-semibold);
  font-size: var(--font-size-label);
  text-align: left;
  padding: var(--space-sm) var(--space-md);
  border-bottom: 1px solid var(--color-border);
}
.advisory-panel__table td {
  color: var(--color-text-primary);
  padding: var(--space-sm) var(--space-md);
  border-bottom: 1px solid var(--color-border);
  vertical-align: top;
}
.advisory-panel__cell-ticker {
  font-family: 'Courier New', monospace;
  font-weight: var(--font-weight-semibold);
}
.advisory-panel__cell-conf,
.advisory-panel__cell-exposure {
  font-family: 'Courier New', monospace;
  white-space: nowrap;
}
.advisory-panel__cell-rationale {
  line-height: 1.5;
  color: var(--color-text-primary);
}
/* D-18 signal color coding */
.advisory-panel__cell-signal {
  font-weight: var(--font-weight-semibold);
  font-family: 'Courier New', monospace;
}
.advisory-panel__signal--buy  { color: var(--color-accent); }
.advisory-panel__signal--sell { color: var(--color-destructive); }
.advisory-panel__signal--hold { color: var(--color-text-secondary); }

.advisory-panel__empty-table {
  font-size: var(--font-size-body);
  color: var(--color-text-muted);
  margin: 0;
  text-align: center;
}

/* ---- Footer ---- */
.advisory-panel__footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-md) var(--space-lg);
  border-top: 1px solid var(--color-border);
  flex-shrink: 0;
  min-height: 48px;
}
.advisory-panel__status {
  font-size: var(--font-size-label);
  font-weight: var(--font-weight-regular);
  line-height: var(--line-height-label);
  color: var(--color-text-secondary);
}
.advisory-panel__status--analyzing {
  color: var(--color-text-muted);
  animation: analyzing-pulse 1.5s ease-in-out infinite;
}
.advisory-panel__analyze-btn {
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
.advisory-panel__analyze-btn:hover:not(:disabled) {
  background: var(--color-accent-hover);
}
.advisory-panel__analyze-btn--disabled,
.advisory-panel__analyze-btn:disabled {
  background: var(--color-border);
  color: var(--color-text-muted);
  cursor: not-allowed;
}

.advisory-panel__error {
  font-size: var(--font-size-label);
  font-weight: var(--font-weight-regular);
  line-height: var(--line-height-label);
  color: var(--color-destructive);
  padding: var(--space-xs) var(--space-lg);
  border-top: 1px solid var(--color-border);
  flex-shrink: 0;
}

@keyframes analyzing-pulse {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 1.0; }
}

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

@media (max-width: 1023px) {
  .advisory-panel-modal {
    width: 90vw;
    height: 85vh;
    max-width: none;
    min-width: 0;
  }
}
@media (max-width: 767px) {
  .advisory-panel-modal {
    width: 95vw;
    height: 95vh;
  }
}
</style>
