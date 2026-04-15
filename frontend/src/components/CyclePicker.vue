<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'

interface CycleItem {
  cycle_id: string
  created_at: string
  seed_rumor: string
  round_count: number
}

const emit = defineEmits<{
  'start-replay': [cycleId: string]
  'close': []
}>()

const cycles = ref<CycleItem[]>([])
const selectedCycleId = ref<string | null>(null)
const loading = ref(true)
const error = ref(false)
const starting = ref(false)
const startError = ref<string | null>(null)

onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  await fetchCycles()
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
})

async function fetchCycles() {
  loading.value = true
  error.value = false
  try {
    const res = await fetch('/api/replay/cycles')
    if (!res.ok) throw new Error('fetch failed')
    const data = await res.json()
    cycles.value = data.cycles
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

async function startReplay() {
  if (!selectedCycleId.value || starting.value) return
  starting.value = true
  startError.value = null
  try {
    const res = await fetch(`/api/replay/start/${selectedCycleId.value}`, { method: 'POST' })
    if (!res.ok) {
      if (res.status === 404) {
        startError.value = 'Cycle not found in Neo4j. Select a different cycle.'
        return
      }
      throw new Error('start failed')
    }
    emit('start-replay', selectedCycleId.value)
  } catch {
    startError.value = 'Could not start replay. Try again.'
  } finally {
    starting.value = false
  }
}

function onBackdropClick(e: MouseEvent) {
  if ((e.target as HTMLElement).classList.contains('cycle-picker-backdrop')) {
    emit('close')
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}
</script>

<template>
  <Transition name="modal">
    <div class="cycle-picker-backdrop" @click="onBackdropClick">
      <div class="cycle-picker-modal">
        <h2 class="cycle-picker-title">Select a Cycle to Replay</h2>

        <!-- Loading state -->
        <div v-if="loading" class="cycle-picker-status">Loading cycles...</div>

        <!-- Error state -->
        <div v-else-if="error" class="cycle-picker-status">
          Could not load cycles. <span class="cycle-picker-retry" @click="fetchCycles">Try again</span>
        </div>

        <!-- Empty state -->
        <div v-else-if="cycles.length === 0" class="cycle-picker-status">
          <div>No completed cycles found.</div>
          <div class="cycle-picker-status-body">Run a simulation to create a replayable cycle.</div>
        </div>

        <!-- Cycle list -->
        <div v-else class="cycle-picker-list">
          <label
            v-for="cycle in cycles"
            :key="cycle.cycle_id"
            class="cycle-row"
            :class="{
              'cycle-row--selected': selectedCycleId === cycle.cycle_id,
            }"
          >
            <input
              type="radio"
              :value="cycle.cycle_id"
              v-model="selectedCycleId"
              class="cycle-row__radio"
            />
            <span class="cycle-row__id">{{ cycle.cycle_id.slice(0, 8) }}</span>
            <span class="cycle-row__date">{{ cycle.created_at.slice(0, 10) }}</span>
            <span class="cycle-row__rumor">{{ cycle.seed_rumor.slice(0, 60) }}{{ cycle.seed_rumor.length > 60 ? '...' : '' }}</span>
          </label>
        </div>

        <!-- Start error -->
        <div v-if="startError" class="cycle-picker-error">{{ startError }}</div>

        <!-- Actions -->
        <div class="cycle-picker-actions">
          <button class="cycle-picker-btn cycle-picker-btn--close" @click="emit('close')">Close Picker</button>
          <button
            class="cycle-picker-btn cycle-picker-btn--start"
            :class="{ 'cycle-picker-btn--disabled': !selectedCycleId || starting }"
            :disabled="!selectedCycleId || starting"
            @click="startReplay"
          >
            {{ starting ? 'Starting...' : 'Start Replay' }}
          </button>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.cycle-picker-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 17, 23, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}

.cycle-picker-modal {
  max-width: 480px;
  width: calc(100% - var(--space-xl) * 2);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: var(--space-lg);
}

.cycle-picker-title {
  font-size: var(--font-size-heading);
  font-weight: var(--font-weight-semibold);
  line-height: var(--line-height-heading);
  color: var(--color-text-primary);
  margin-bottom: var(--space-md);
}

.cycle-picker-list {
  max-height: 320px;
  overflow-y: auto;
  margin-bottom: var(--space-md);
}

.cycle-row {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  height: 48px;
  padding: 0 var(--space-sm);
  cursor: pointer;
  border-left: 2px solid transparent;
  transition: background 150ms ease-in;
}
.cycle-row:hover { background: rgba(255, 255, 255, 0.04); }
.cycle-row--selected {
  border-left-color: var(--color-accent);
  background: rgba(59, 130, 246, 0.08);
}

.cycle-row__radio { flex-shrink: 0; accent-color: var(--color-accent); }
.cycle-row__id {
  font-family: 'Courier New', monospace;
  font-size: var(--font-size-label);
  color: var(--color-text-primary);
  flex-shrink: 0;
}
.cycle-row__date {
  font-size: var(--font-size-label);
  color: var(--color-text-muted);
  flex-shrink: 0;
}
.cycle-row__rumor {
  font-size: var(--font-size-body);
  color: var(--color-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

.cycle-picker-status {
  font-size: var(--font-size-body);
  color: var(--color-text-muted);
  padding: var(--space-lg) 0;
  text-align: center;
}
.cycle-picker-status-body {
  font-size: var(--font-size-body);
  color: var(--color-text-muted);
  margin-top: var(--space-xs);
}
.cycle-picker-retry {
  color: var(--color-accent);
  cursor: pointer;
}

.cycle-picker-error {
  font-size: var(--font-size-label);
  color: var(--color-destructive);
  margin-bottom: var(--space-sm);
}

.cycle-picker-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-sm);
}

.cycle-picker-btn {
  height: 32px;
  padding: 0 var(--space-md);
  border-radius: 4px;
  font-family: var(--font-family);
  font-size: var(--font-size-label);
  cursor: pointer;
  border: none;
  white-space: nowrap;
}
.cycle-picker-btn--close {
  background: transparent;
  border: 1px solid var(--color-border);
  color: var(--color-text-secondary);
  font-weight: var(--font-weight-regular);
}
.cycle-picker-btn--close:hover { background: var(--color-border); }
.cycle-picker-btn--start {
  background: var(--color-accent);
  color: var(--color-text-primary);
  font-weight: var(--font-weight-semibold);
}
.cycle-picker-btn--start:hover:not(:disabled) { background: var(--color-accent-hover); }
.cycle-picker-btn--disabled {
  background: var(--color-border);
  color: var(--color-text-muted);
  cursor: not-allowed;
}

/* Modal transition (UI-SPEC Animation Contract) */
.modal-enter-active { transition: opacity var(--duration-modal-enter) ease-out, transform var(--duration-modal-enter) ease-out; }
.modal-leave-active { transition: opacity var(--duration-modal-exit) ease-in, transform var(--duration-modal-exit) ease-in; }
.modal-enter-from { opacity: 0; transform: translateY(-8px); }
.modal-leave-to { opacity: 0; transform: translateY(-8px); }
</style>
