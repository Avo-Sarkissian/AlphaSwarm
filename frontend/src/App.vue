<script setup lang="ts">
import { computed, provide } from 'vue'
import { useWebSocket } from './composables/useWebSocket'

const { snapshot, connected, reconnectFailed, latestRationales } = useWebSocket()

// Provide snapshot to child components (ForceGraph, AgentSidebar in later plans)
provide('snapshot', snapshot)
provide('connected', connected)
provide('latestRationales', latestRationales)

const isIdle = computed(() => snapshot.value.phase === 'idle')
</script>

<template>
  <div class="app-root">
    <!-- Empty state: shown when no simulation running (UI-SPEC: Graph - Empty) -->
    <div v-if="isIdle" class="empty-state">
      <h1 class="empty-state__heading">Waiting for Simulation</h1>
      <p class="empty-state__body">Start a simulation to see 100 agents deliberate in real time.</p>
    </div>

    <!-- Graph container: Plan 03 replaces this with ForceGraph.vue -->
    <div v-else class="graph-container" id="graph-container">
      <!-- ForceGraph.vue will be mounted here in Plan 03 -->
    </div>

    <!-- Connection error banner (UI-SPEC: Error State - WebSocket Disconnected) -->
    <div v-if="reconnectFailed" class="connection-error">
      Connection Lost -- Attempting to reconnect to the simulation server.
    </div>
  </div>
</template>

<style scoped>
.app-root {
  width: 100vw;
  height: 100vh;
  position: relative;
  overflow: hidden;
  background-color: var(--color-bg-primary);
}

/* Empty state (UI-SPEC: centered h+v, pulse animation on heading) */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: var(--space-sm);
}

.empty-state__heading {
  font-size: var(--font-size-heading);
  font-weight: var(--font-weight-semibold);
  line-height: var(--line-height-heading);
  color: var(--color-accent);
  animation: pulse 2s ease-in-out infinite;
}

.empty-state__body {
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-regular);
  line-height: var(--line-height-body);
  color: var(--color-text-muted);
}

@keyframes pulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1.0; }
}

/* Graph container: fills viewport, shrinks when sidebar opens */
.graph-container {
  width: 100%;
  height: 100%;
  transition: width var(--duration-sidebar-enter) var(--easing-enter);
}

/* Connection error banner (UI-SPEC: fixed bottom-center, 32px from bottom) */
.connection-error {
  position: fixed;
  bottom: 32px;
  left: 50%;
  transform: translateX(-50%);
  background-color: var(--color-bg-secondary);
  border: 1px solid var(--color-destructive);
  padding: var(--space-sm) var(--space-md);
  border-radius: 4px;
  font-size: var(--font-size-label);
  font-weight: var(--font-weight-regular);
  line-height: var(--line-height-label);
  color: var(--color-destructive);
  z-index: 100;
}
</style>
