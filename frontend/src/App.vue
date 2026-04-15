<script setup lang="ts">
import { computed, provide, ref } from 'vue'
import { useWebSocket } from './composables/useWebSocket'
import ForceGraph from './components/ForceGraph.vue'
import AgentSidebar from './components/AgentSidebar.vue'
import ControlBar from './components/ControlBar.vue'
import BracketPanel from './components/BracketPanel.vue'
import RationaleFeed from './components/RationaleFeed.vue'

const { snapshot, connected, reconnectFailed, latestRationales, allRationales } = useWebSocket()

// Provide snapshot to child components (ForceGraph, AgentSidebar, ControlBar)
provide('snapshot', snapshot)
provide('connected', connected)
provide('latestRationales', latestRationales)
provide('allRationales', allRationales)

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
      <template v-else>
        <div class="graph-container" :class="{ 'graph-container--sidebar-open': sidebarOpen }" id="graph-container">
          <ForceGraph @select-agent="onSelectAgent" />
        </div>
        <div class="panel-strip" :class="{ 'panel-strip--sidebar-open': sidebarOpen }">
          <BracketPanel />
          <div class="panel-strip__divider" />
          <RationaleFeed />
        </div>
      </template>
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
  display: flex;
  flex-direction: column;
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
  flex: 1;
  min-height: 0;
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

/* Phase 33: Bottom monitoring panel strip (per D-01, D-02) */
.panel-strip {
  height: var(--panel-strip-height);
  flex-shrink: 0;
  display: flex;
  background-color: var(--color-bg-secondary);
  border-top: 1px solid var(--color-border);
  transition: width var(--duration-sidebar-enter) var(--easing-enter);
}

.panel-strip--sidebar-open {
  width: calc(100vw - var(--sidebar-width));
}

.panel-strip__divider {
  width: 1px;
  flex-shrink: 0;
  background-color: var(--color-border);
}

/* Each panel half fills equally */
.panel-strip > :first-child,
.panel-strip > :last-child {
  flex: 1;
  overflow: hidden;
  padding: var(--space-md);
  min-width: 0;
}

/* Responsive: stack panels vertically below 1024px */
@media (max-width: 1023px) {
  .panel-strip {
    flex-direction: column;
  }
  .panel-strip__divider {
    width: 100%;
    height: 1px;
    flex-shrink: 0;
  }
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
