<script setup lang="ts">
import { inject, computed, type Ref } from 'vue'
import type { RationaleEntry } from '../types'
import { SIGNAL_COLORS } from '../types'

// REVIEW FIX (MEDIUM): Defensive injection -- runtime error instead of silent undefined
const allRationales = inject<Ref<RationaleEntry[]>>('allRationales')
if (!allRationales) {
  throw new Error('RationaleFeed requires "allRationales" injection from App.vue provide chain')
}

// REVIEW FIX (MEDIUM): Deterministic composite key for TransitionGroup stability.
// agent_id + round_num is unique within any simulation cycle (one decision per agent per round).
// Adding signal as extra safety for edge cases.
function entryKey(entry: RationaleEntry): string {
  return `${entry.agent_id}:${entry.round_num}:${entry.signal}`
}

function formatAgentName(agentId: string): string {
  const num = agentId.replace(/\D/g, '')
  return `Agent ${num.padStart(2, '0')}`
}

function signalColor(signal: string): string {
  return SIGNAL_COLORS[signal] || '#374151'
}

function chipStyle(signal: string): Record<string, string> {
  const color = signalColor(signal)
  return {
    backgroundColor: color + '26',
    color: signal === 'hold' ? 'var(--color-text-secondary)' : color,
  }
}

const isEmpty = computed(() => allRationales.value.length === 0)
</script>

<template>
  <div class="rationale-feed">
    <h3 class="rationale-feed__title">Rationale Feed</h3>
    <div v-if="isEmpty" class="rationale-feed__empty">
      <p>Awaiting agent rationale...</p>
    </div>
    <div v-else class="rationale-feed__list">
      <TransitionGroup name="feed-entry" tag="div">
        <div
          v-for="entry in allRationales"
          :key="entryKey(entry)"
          class="feed-item"
        >
          <div class="feed-item__header">
            <span class="feed-item__agent">{{ formatAgentName(entry.agent_id) }}</span>
            <span class="feed-item__signal" :style="chipStyle(entry.signal)">
              {{ entry.signal.toUpperCase() }}
            </span>
          </div>
          <p class="feed-item__rationale">{{ entry.rationale }}</p>
        </div>
      </TransitionGroup>
    </div>
  </div>
</template>

<style scoped>
.rationale-feed {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.rationale-feed__title {
  font-size: var(--font-size-heading);
  font-weight: var(--font-weight-semibold);
  line-height: var(--line-height-heading);
  color: var(--color-accent);
  margin-bottom: var(--space-sm);
  flex-shrink: 0;
}

.rationale-feed__empty {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  font-size: var(--font-size-body);
  font-style: italic;
  color: var(--color-text-muted);
}

.rationale-feed__list {
  overflow-y: auto;
  overflow-x: hidden;
  flex: 1;
  min-height: 0;
  position: relative;  /* Required for TransitionGroup absolute positioning during leave */
}

.feed-item {
  padding: var(--space-xs) 0;
  border-bottom: none;  /* No separator lines -- rely on spacing per UI-SPEC */
}

.feed-item + .feed-item {
  margin-top: var(--space-sm);
}

.feed-item__header {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  margin-bottom: var(--space-xs);
}

.feed-item__agent {
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-regular);
  line-height: var(--line-height-body);
  color: var(--color-text-primary);
}

.feed-item__signal {
  display: inline-block;
  font-size: var(--font-size-label);
  font-weight: var(--font-weight-regular);
  line-height: var(--line-height-label);
  padding: 2px 6px;
  border-radius: 4px;
}

.feed-item__rationale {
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-regular);
  line-height: var(--line-height-body);
  color: var(--color-text-muted);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  /* Fallback for browsers without -webkit-line-clamp */
  max-height: calc(2 * 14px * 1.5);
}

/* TransitionGroup animations (per D-11, D-12, RESEARCH.md) */
.feed-entry-enter-active {
  transition: transform var(--duration-feed-enter) var(--easing-enter),
              opacity var(--duration-feed-enter) var(--easing-enter);
}

.feed-entry-enter-from {
  transform: translateY(-8px);
  opacity: 0;
}

.feed-entry-leave-active {
  transition: opacity var(--duration-feed-exit) var(--easing-exit);
  position: absolute;  /* CRITICAL: take out of flow for smooth move transitions (RESEARCH Pitfall 4) */
  width: 100%;
}

.feed-entry-leave-to {
  opacity: 0;
}

.feed-entry-move {
  transition: transform var(--duration-feed-enter) var(--easing-enter);
}
</style>
