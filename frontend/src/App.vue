<script setup lang="ts">
import { computed, provide, ref } from 'vue'
import { useWebSocket } from './composables/useWebSocket'
import ForceGraph from './components/ForceGraph.vue'
import AgentSidebar from './components/AgentSidebar.vue'
import ControlBar from './components/ControlBar.vue'

const { snapshot, connected, reconnectFailed, latestRationales } = useWebSocket()

// Provide snapshot to child components (ForceGraph, AgentSidebar, ControlBar)
provide('snapshot', snapshot)
provide('connected', connected)
provide('latestRationales', latestRationales)

const selectedAgentId = ref<string | null>(null)
provide('selectedAgentId', selectedAgentId)

function onSelectAgent(agentId: string | null) {
  selectedAgentId.value = agentId
}

function onCloseSidebar() {
  selectedAgentId.value = null
}

const sidebarOpen = computed(() => selectedAgentId.value !== null)
const isIdle = computed(() => snapshot.value.phase === 'idle' || snapshot.value.phase === 'complete')
</script>

<template>
  <div class="app-root">
    <!-- ControlBar owns ShockDrawer internally -- no event wiring needed -->
    <ControlBar />

    <!-- Main content area: fills remaining space -->
    <div class="main-content">
      <div v-if="isIdle" class="empty-state">
        <h1 class="empty-state__heading">Waiting for Simulation</h1>
        <p class="empty-state__body">Start a simulation to see 100 agents deliberate in real time.</p>
      </div>
      <div v-else class="graph-container" :class="{ 'graph-container--sidebar-open': sidebarOpen }" id="graph-container">
        <ForceGraph @select-agent="onSelectAgent" />
      </div>
    </div>

    <Transition name="sidebar">
      <AgentSidebar v-if="selectedAgentId" :agentId="selectedAgentId" @close="onCloseSidebar" />
    </Transition>

    <div v-if="reconnectFailed" class="connection-error">
      Connection Lost -- Attempting to reconnect to the simulation server.
    </div>
  </div>
</template>

<style scoped>
.app-root {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  background-color: var(--color-bg-primary);
}

.main-content {
  flex: 1;
  overflow: hidden;
  position: relative;
  min-height: 0;
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

.graph-container--sidebar-open {
  width: calc(100vw - var(--sidebar-width));
}

/* Sidebar slide transition (300ms enter ease-out, 200ms exit ease-in) */
.sidebar-enter-active {
  transition: transform var(--duration-sidebar-enter) var(--easing-enter);
}
.sidebar-leave-active {
  transition: transform var(--duration-sidebar-exit) var(--easing-exit);
}
.sidebar-enter-from,
.sidebar-leave-to {
  transform: translateX(100%);
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
