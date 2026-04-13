<script setup lang="ts">
import { inject, ref, shallowRef, triggerRef, watch, onMounted, onUnmounted, type Ref } from 'vue'
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide, forceX, forceY, type SimulationNodeDatum } from 'd3-force'
import type { StateSnapshot } from '../types'
import { BRACKET_ARCHETYPES, BRACKET_RADIUS, SIGNAL_COLORS, PENDING_COLOR } from '../types'

// --- Types ---

interface GraphNode extends SimulationNodeDatum {
  id: string
  bracket: string
  radius: number
  color: string
}

// --- Injected state ---
const snapshot = inject<Ref<StateSnapshot>>('snapshot')!

// --- Reactive state ---
const containerRef = ref<HTMLDivElement | null>(null)
const width = ref(window.innerWidth)
const height = ref(window.innerHeight)
const nodes = shallowRef<GraphNode[]>([])
const selectedAgentId = ref<string | null>(null)

// Emit selected agent to parent (App.vue will pass to AgentSidebar in Plan 04)
const emit = defineEmits<{
  (e: 'select-agent', agentId: string | null): void
}>()

// --- Bracket centroids ---
// 10 centroids arranged in a circle at radius = 35% of smaller viewport dimension (D-07, D-08)
function computeCentroids(w: number, h: number): { x: number; y: number }[] {
  const cx = w / 2
  const cy = h / 2
  const r = Math.min(w, h) * 0.35
  return BRACKET_ARCHETYPES.map((_, i) => {
    const angle = (2 * Math.PI * i) / BRACKET_ARCHETYPES.length - Math.PI / 2
    return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) }
  })
}

let centroids = computeCentroids(width.value, height.value)
let simulation: ReturnType<typeof forceSimulation<GraphNode>> | null = null
let nodesInitialized = false

// --- Initialize nodes from first non-idle snapshot ---
function initializeNodes(agentStates: Record<string, { signal: string | null; confidence: number }>): void {
  if (nodesInitialized) return

  const bracketAssignments = assignBrackets(Object.keys(agentStates))
  const newNodes: GraphNode[] = Object.keys(agentStates).map((agentId) => {
    const bracket = bracketAssignments[agentId]
    const bracketIdx = BRACKET_ARCHETYPES.findIndex(b => b.value === bracket)
    const centroid = centroids[bracketIdx] || centroids[0]
    const signal = agentStates[agentId]?.signal
    return {
      id: agentId,
      bracket,
      radius: BRACKET_RADIUS[bracket] || 8,
      color: signal ? (SIGNAL_COLORS[signal] || PENDING_COLOR) : PENDING_COLOR,
      // Start near bracket centroid with small random offset
      x: centroid.x + (Math.random() - 0.5) * 40,
      y: centroid.y + (Math.random() - 0.5) * 40,
    }
  })

  nodes.value = newNodes
  nodesInitialized = true
  startSimulation()
}

/**
 * Assign bracket archetypes to agent IDs.
 * Agent IDs follow "A_01" to "A_100" pattern. 10 agents per bracket, 10 brackets.
 * Bracket index = floor((agentNum - 1) / 10) where agentNum is extracted from ID.
 */
function assignBrackets(agentIds: string[]): Record<string, string> {
  const sorted = [...agentIds].sort((a, b) => {
    const numA = parseInt(a.replace(/\D/g, ''), 10)
    const numB = parseInt(b.replace(/\D/g, ''), 10)
    return numA - numB
  })
  const result: Record<string, string> = {}
  sorted.forEach((id, i) => {
    const bracketIdx = Math.min(Math.floor(i / 10), BRACKET_ARCHETYPES.length - 1)
    result[id] = BRACKET_ARCHETYPES[bracketIdx].value
  })
  return result
}

// --- D3 force simulation ---
function startSimulation(): void {
  if (simulation) {
    simulation.stop()
  }

  const cx = width.value / 2
  const cy = height.value / 2

  simulation = forceSimulation<GraphNode>(nodes.value)
    .force('charge', forceManyBody<GraphNode>().strength(-30))
    .force('center', forceCenter<GraphNode>(cx, cy))
    .force('collide', forceCollide<GraphNode>().radius((d) => d.radius + 2))
    .force('x', forceX<GraphNode>().x((d) => {
      const idx = BRACKET_ARCHETYPES.findIndex(b => b.value === d.bracket)
      return centroids[idx]?.x ?? cx
    }).strength(0.3))
    .force('y', forceY<GraphNode>().y((d) => {
      const idx = BRACKET_ARCHETYPES.findIndex(b => b.value === d.bracket)
      return centroids[idx]?.y ?? cy
    }).strength(0.3))
    .on('tick', () => {
      triggerRef(nodes)
    })
}

// --- Watch snapshot for signal color updates (D-06: no reheat, just color mutation) ---
watch(() => snapshot.value.agent_states, (agentStates) => {
  if (!nodesInitialized && Object.keys(agentStates).length > 0) {
    initializeNodes(agentStates)
    return
  }

  if (!nodesInitialized) return

  // Update colors WITHOUT touching D3 simulation (D-06)
  let changed = false
  for (const node of nodes.value) {
    const state = agentStates[node.id]
    const newColor = state?.signal ? (SIGNAL_COLORS[state.signal] || PENDING_COLOR) : PENDING_COLOR
    if (node.color !== newColor) {
      node.color = newColor
      changed = true
    }
  }
  if (changed) {
    triggerRef(nodes)
  }
}, { deep: true })

// --- Handle click on node ---
function onNodeClick(agentId: string): void {
  selectedAgentId.value = agentId
  emit('select-agent', agentId)
}

// --- Handle click on empty space ---
function onSvgClick(event: MouseEvent): void {
  if ((event.target as Element).tagName === 'svg' || (event.target as Element).classList.contains('graph-bg')) {
    selectedAgentId.value = null
    emit('select-agent', null)
  }
}

// --- Resize handling ---
function onResize(): void {
  if (containerRef.value) {
    width.value = containerRef.value.clientWidth
    height.value = containerRef.value.clientHeight
    centroids = computeCentroids(width.value, height.value)
    // Reheat simulation on resize (topology change equivalent)
    if (simulation) {
      const cx = width.value / 2
      const cy = height.value / 2
      simulation.force('center', forceCenter<GraphNode>(cx, cy))
      simulation.force('x', forceX<GraphNode>().x((d) => {
        const idx = BRACKET_ARCHETYPES.findIndex(b => b.value === d.bracket)
        return centroids[idx]?.x ?? cx
      }).strength(0.3))
      simulation.force('y', forceY<GraphNode>().y((d) => {
        const idx = BRACKET_ARCHETYPES.findIndex(b => b.value === d.bracket)
        return centroids[idx]?.y ?? cy
      }).strength(0.3))
      simulation.alpha(0.3).restart()
    }
  }
}

let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  if (containerRef.value) {
    width.value = containerRef.value.clientWidth
    height.value = containerRef.value.clientHeight
    centroids = computeCentroids(width.value, height.value)

    resizeObserver = new ResizeObserver(() => onResize())
    resizeObserver.observe(containerRef.value)
  }
})

onUnmounted(() => {
  if (simulation) {
    simulation.stop()
    simulation = null
  }
  if (resizeObserver) {
    resizeObserver.disconnect()
  }
})
</script>

<template>
  <div ref="containerRef" class="force-graph">
    <svg
      :width="width"
      :height="height"
      :viewBox="`0 0 ${width} ${height}`"
      @click="onSvgClick"
    >
      <!-- Background rect for click detection -->
      <rect class="graph-bg" :width="width" :height="height" fill="transparent" />

      <!-- Edges rendered here by Plan 04 via slot or direct integration -->
      <g class="edges-layer">
        <!-- Plan 04: edge <line> elements will be rendered here -->
      </g>

      <!-- Agent nodes -->
      <g class="nodes-layer">
        <circle
          v-for="node in nodes"
          :key="node.id"
          :cx="node.x"
          :cy="node.y"
          :r="node.radius"
          :fill="node.color"
          :stroke="node.id === selectedAgentId ? '#3b82f6' : 'none'"
          :stroke-width="node.id === selectedAgentId ? 2 : 0"
          class="agent-node"
          @click.stop="onNodeClick(node.id)"
        />
      </g>
    </svg>
  </div>
</template>

<style scoped>
.force-graph {
  width: 100%;
  height: 100%;
  background-color: var(--color-bg-primary);
}

.force-graph svg {
  display: block;
}

.agent-node {
  cursor: pointer;
  pointer-events: all;
}
</style>
