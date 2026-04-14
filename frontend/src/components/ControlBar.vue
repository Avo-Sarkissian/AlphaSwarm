<script setup lang="ts">
import { computed, inject, ref, watch, type Ref } from 'vue'
import type { StateSnapshot } from '../types'
import ShockDrawer from './ShockDrawer.vue'

const snapshot = inject<Ref<StateSnapshot>>('snapshot')!

// Phase detection
const isActive = computed(() =>
  snapshot.value.phase !== 'idle' && snapshot.value.phase !== 'complete'
)

// Seed input
const seedText = ref('')

// Double-click prevention (addresses review concern #6):
// startPending is set to true when the POST /api/simulate/start request
// is in flight. Cleared when the WebSocket snapshot.phase changes away
// from 'idle' (meaning the backend has started), OR when the fetch fails.
// Start button is disabled when: isActive || startPending || !seedText.trim()
const startPending = ref(false)

// Watch for phase change away from idle to clear startPending
watch(() => snapshot.value.phase, (newPhase) => {
  if (newPhase !== 'idle' && newPhase !== 'complete') {
    startPending.value = false
  }
})

const canStart = computed(() =>
  !isActive.value && !startPending.value && seedText.value.trim().length > 0
)

// Phase label formatting (addresses review concern #7):
// Maps raw phase enum to human-readable display text.
// Shows "Round N / 3" format instead of raw "round_2" string.
const phaseLabel = computed(() => {
  const phaseMap: Record<string, string> = {
    'seeding': 'Seeding...',
    'round_1': 'Round 1 / 3',
    'round_2': 'Round 2 / 3',
    'round_3': 'Round 3 / 3',
    'complete': 'Complete',
    'replay': 'Replay',
  }
  return phaseMap[snapshot.value.phase] ?? snapshot.value.phase
})

// Shock drawer state -- owned entirely by ControlBar (review concern #3)
const showDrawer = ref(false)

function toggleDrawer() {
  showDrawer.value = !showDrawer.value
}

function closeDrawer() {
  showDrawer.value = false
}

// REST calls
async function startSimulation() {
  if (!canStart.value) return
  startPending.value = true
  try {
    const res = await fetch('/api/simulate/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ seed: seedText.value.trim() }),
    })
    if (!res.ok) {
      console.error('Start failed:', res.status)
      startPending.value = false
    }
    // On success: startPending cleared by the phase watcher when
    // WebSocket snapshot.phase changes away from 'idle'
  } catch (err) {
    console.error('Start error:', err)
    startPending.value = false
  }
}

async function stopSimulation() {
  try {
    await fetch('/api/simulate/stop', { method: 'POST' })
  } catch (err) {
    console.error('Stop error:', err)
  }
}
</script>

<template>
  <div class="control-bar-wrapper">
    <div class="control-bar">
      <textarea
        v-model="seedText"
        class="control-bar__seed"
        :class="{ 'control-bar__seed--disabled': isActive }"
        :disabled="isActive"
        placeholder="Enter a seed rumor..."
        rows="1"
      />
      <button
        class="control-bar__btn control-bar__btn--start"
        :class="{ 'control-bar__btn--disabled': !canStart }"
        :disabled="!canStart"
        @click="startSimulation"
      >
        {{ startPending ? 'Starting...' : 'Start Simulation' }}
      </button>

      <template v-if="isActive">
        <span class="control-bar__phase">{{ phaseLabel }}</span>
        <button
          class="control-bar__btn control-bar__btn--stop"
          @click="stopSimulation"
        >
          Stop
        </button>
        <button
          class="control-bar__btn control-bar__btn--shock"
          @click="toggleDrawer"
        >
          +Inject Shock
        </button>
      </template>
    </div>

    <!-- ShockDrawer owned by ControlBar, NOT by App.vue (review concern #3) -->
    <ShockDrawer :open="showDrawer" @close="closeDrawer" />
  </div>
</template>

<style scoped>
.control-bar-wrapper {
  flex-shrink: 0;
  z-index: 20;
}

.control-bar {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  height: var(--control-bar-height);
  padding: 0 var(--space-md);
  background-color: var(--color-bg-secondary);
  border-bottom: 1px solid var(--color-border);
}

.control-bar__seed {
  flex: 1;
  max-height: 32px;
  padding: var(--space-xs) var(--space-sm);
  background-color: var(--color-bg-primary);
  color: var(--color-text-primary);
  border: 1px solid var(--color-border);
  border-radius: 4px;
  font-family: var(--font-family);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
  resize: none;
  outline: none;
}

.control-bar__seed:focus {
  border-color: var(--color-accent);
}

.control-bar__seed--disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.control-bar__btn {
  height: 32px;
  padding: 0 var(--space-md);
  border-radius: 4px;
  font-family: var(--font-family);
  font-size: var(--font-size-label);
  font-weight: var(--font-weight-semibold);
  cursor: pointer;
  border: none;
  white-space: nowrap;
}

.control-bar__btn--start {
  background-color: var(--color-accent);
  color: var(--color-text-primary);
}
.control-bar__btn--start:hover:not(:disabled) {
  background-color: var(--color-accent-hover);
}

.control-bar__btn--disabled {
  background-color: var(--color-border);
  color: var(--color-text-muted);
  cursor: not-allowed;
}

.control-bar__btn--stop {
  background-color: var(--color-destructive);
  color: var(--color-text-primary);
}
.control-bar__btn--stop:hover {
  background-color: var(--color-destructive-hover);
}

.control-bar__btn--shock {
  background-color: transparent;
  color: var(--color-accent);
  border: 1px solid var(--color-accent);
  font-weight: var(--font-weight-regular);
}
.control-bar__btn--shock:hover {
  background-color: rgba(59, 130, 246, 0.1);
}

.control-bar__phase {
  margin-left: auto;
  font-size: var(--font-size-label);
  font-weight: var(--font-weight-regular);
  color: var(--color-text-secondary);
  white-space: nowrap;
}
</style>
