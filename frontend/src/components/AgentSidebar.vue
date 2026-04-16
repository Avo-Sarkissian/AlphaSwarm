<script setup lang="ts">
import { inject, computed, type Ref } from 'vue'
import type { StateSnapshot, RationaleEntry } from '../types'
import { BRACKET_DISPLAY, SIGNAL_COLORS, PENDING_COLOR } from '../types'

const props = defineProps<{
  agentId: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'open-interview', agentId: string): void
}>()

const snapshot = inject<Ref<StateSnapshot>>('snapshot')!
const latestRationales = inject<Ref<Map<string, RationaleEntry>>>('latestRationales')!

// Agent name: "A_01" -> "Agent 01"
const agentName = computed(() => {
  const num = props.agentId.replace(/\D/g, '')
  return `Agent ${num.padStart(2, '0')}`
})

// Bracket: agents 1-10=quants, 11-20=degens, etc.
const bracket = computed(() => {
  const num = parseInt(props.agentId.replace(/\D/g, ''), 10)
  const BRACKETS = [
    'quants', 'degens', 'sovereigns', 'macro', 'suits',
    'insiders', 'agents', 'doom_posters', 'policy_wonks', 'whales',
  ]
  const idx = Math.min(Math.floor((num - 1) / 10), 9)
  return BRACKETS[idx] || 'quants'
})

const bracketDisplay = computed(() => BRACKET_DISPLAY[bracket.value] || bracket.value)

const agentState = computed(() => snapshot.value.agent_states[props.agentId])
const signal = computed(() => agentState.value?.signal || null)
const signalLabel = computed(() => {
  if (!signal.value || signal.value === 'parse_error') return 'PENDING'
  return signal.value.toUpperCase()
})
const signalColor = computed(() => {
  if (!signal.value) return PENDING_COLOR
  return SIGNAL_COLORS[signal.value] || PENDING_COLOR
})

// Rationale from accumulated entries
const rationale = computed(() => {
  const entry = latestRationales.value.get(props.agentId)
  return entry?.rationale || null
})

const isComplete = computed(() => snapshot.value.phase === 'complete')
</script>

<template>
  <div class="sidebar">
    <div class="sidebar__header">
      <h2 class="sidebar__name">{{ agentName }}</h2>
      <button class="sidebar__close" @click="emit('close')" aria-label="Close sidebar">X</button>
    </div>
    <span class="sidebar__bracket">{{ bracketDisplay }}</span>
    <span class="sidebar__signal-chip"
      :style="{
        backgroundColor: signalColor + '26',
        color: signal === 'hold' ? '#9ca3af' : signalColor,
      }">
      {{ signalLabel }}
    </span>
    <hr class="sidebar__divider" />
    <span class="sidebar__rationale-label">Current Rationale</span>
    <div class="sidebar__rationale-body">
      <p v-if="rationale">{{ rationale }}</p>
      <p v-else class="sidebar__rationale-empty">Awaiting rationale for this round.</p>
    </div>
    <template v-if="isComplete">
      <hr class="sidebar__interview-divider" />
      <button
        class="sidebar__interview-btn"
        @click="emit('open-interview', props.agentId)"
      >
        Interview {{ agentName }}
      </button>
    </template>
  </div>
</template>

<style scoped>
.sidebar {
  position: fixed;
  top: 0;
  right: 0;
  width: var(--sidebar-width);
  height: 100vh;
  background-color: var(--color-bg-secondary);
  border-left: 1px solid var(--color-border);
  z-index: 10;
  display: flex;
  flex-direction: column;
  padding: var(--space-md);
  gap: var(--space-sm);
  overflow-y: auto;
}
.sidebar__header { display: flex; justify-content: space-between; align-items: center; }
.sidebar__name {
  font-size: var(--font-size-heading);
  font-weight: var(--font-weight-semibold);
  line-height: var(--line-height-heading);
  color: var(--color-text-primary);
  margin: 0;
}
.sidebar__close {
  background: none; border: none;
  color: var(--color-text-secondary);
  font-size: 16px; padding: var(--space-sm);
  cursor: pointer; line-height: 1;
}
.sidebar__close:hover { color: var(--color-accent); }
.sidebar__bracket {
  font-size: var(--font-size-label); font-weight: var(--font-weight-regular);
  line-height: var(--line-height-label); color: var(--color-text-secondary);
}
.sidebar__signal-chip {
  display: inline-block; align-self: flex-start;
  font-size: var(--font-size-label); font-weight: var(--font-weight-regular);
  line-height: var(--line-height-label);
  padding: var(--space-xs) var(--space-sm); border-radius: 4px;
}
.sidebar__divider { border: none; border-top: 1px solid var(--color-border); margin: var(--space-md) 0; }
.sidebar__rationale-label {
  font-size: var(--font-size-label); font-weight: var(--font-weight-regular);
  line-height: var(--line-height-label); color: var(--color-text-secondary);
}
.sidebar__rationale-body {
  font-size: var(--font-size-body); font-weight: var(--font-weight-regular);
  line-height: var(--line-height-body); color: var(--color-text-primary);
  overflow-y: auto; flex: 1;
}
.sidebar__rationale-empty { font-style: italic; color: var(--color-text-muted); }

.sidebar__interview-divider {
  border: 0;
  border-top: 1px solid var(--color-border);
  margin: var(--space-md) 0;
}

.sidebar__interview-btn {
  width: 100%;
  height: 32px;
  margin-top: auto;
  background: transparent;
  border: 1px solid var(--color-accent);
  border-radius: 4px;
  font-size: var(--font-size-label);
  font-weight: var(--font-weight-semibold);
  color: var(--color-accent);
  cursor: pointer;
  flex-shrink: 0;
}
.sidebar__interview-btn:hover {
  background: rgba(59, 130, 246, 0.08);
}
</style>
