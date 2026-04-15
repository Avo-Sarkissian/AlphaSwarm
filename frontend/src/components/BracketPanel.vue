<script setup lang="ts">
import { inject, ref, watch, onMounted, type Ref } from 'vue'
import { select } from 'd3-selection'
import { scaleLinear } from 'd3-scale'
import 'd3-transition'  // REQUIRED side-effect import: augments Selection.prototype.transition
import type { StateSnapshot, BracketSummary } from '../types'
import { BRACKET_ARCHETYPES, SIGNAL_COLORS } from '../types'

// REVIEW FIX (MEDIUM): Defensive injection -- runtime error instead of silent undefined
const snapshot = inject<Ref<StateSnapshot>>('snapshot')
if (!snapshot) {
  throw new Error('BracketPanel requires "snapshot" injection from App.vue provide chain')
}

const svgRef = ref<SVGSVGElement | null>(null)

// REVIEW FIX (MEDIUM): Use fixed viewBox coordinates instead of runtime width measurement.
// The SVG uses viewBox="0 0 VIEWBOX_WIDTH SVG_HEIGHT" with width="100%" and
// preserveAspectRatio="xMinYMin meet", so the browser handles responsive scaling.
// All D3 calculations use these fixed coordinates -- no ResizeObserver needed.
const VIEWBOX_WIDTH = 400      // fixed viewBox width -- browser scales via preserveAspectRatio
const LABEL_WIDTH = 80         // reserved width for bracket y-axis labels
const BAR_RIGHT_MARGIN = 16    // right margin
const BAR_WIDTH = VIEWBOX_WIDTH - LABEL_WIDTH - BAR_RIGHT_MARGIN  // 304px in viewBox space
const BAR_HEIGHT = 20          // height per bracket bar (per UI-SPEC)
const BAR_GAP = 4              // gap between bars (--space-xs)
const BRACKET_COUNT = 10
const SVG_HEIGHT = BRACKET_COUNT * (BAR_HEIGHT + BAR_GAP) - BAR_GAP  // 236
const PENDING_FILL = '#374151' // --color-signal-pending for unresolved segment

function updateBars(summaries: BracketSummary[]): void {
  if (!svgRef.value) return

  const svg = select(svgRef.value)

  // Build ordered data: match BRACKET_ARCHETYPES order (REVIEW FIX MEDIUM: deterministic ordering)
  const ordered: BracketSummary[] = BRACKET_ARCHETYPES.map(arch => {
    const found = summaries.find(s => s.bracket === arch.value)
    return found || {
      bracket: arch.value,
      display_name: arch.display,
      buy_count: 0,
      sell_count: 0,
      hold_count: 0,
      total: 0,
      avg_confidence: 0,
      avg_sentiment: 0,
    }
  })

  // REVIEW FIX (MEDIUM): Use BAR_WIDTH (viewBox constant) instead of runtime container measurement.
  // scaleLinear maps proportions [0,1] to pixel widths [0, BAR_WIDTH] in viewBox space.
  const x = scaleLinear().domain([0, 1]).range([0, BAR_WIDTH]).clamp(true)

  // Data join on bracket rows
  const rows = svg.selectAll<SVGGElement, BracketSummary>('.bracket-row')
    .data(ordered, d => d.bracket)

  // ENTER: create group with label + 4 rects (buy, sell, hold, pending bg)
  const enter = rows.enter().append('g')
    .attr('class', 'bracket-row')
    .attr('transform', (_, i) => `translate(0, ${i * (BAR_HEIGHT + BAR_GAP)})`)

  // Y-axis label (per D-07)
  enter.append('text')
    .attr('class', 'bracket-label')
    .attr('x', LABEL_WIDTH - 8)
    .attr('y', BAR_HEIGHT / 2)
    .attr('dy', '0.35em')
    .attr('text-anchor', 'end')
    .attr('fill', 'var(--color-text-secondary)')
    .attr('font-size', 'var(--font-size-label)')
    .attr('font-weight', 'var(--font-weight-regular)')
    .text(d => d.display_name)

  // Background rect (pending/unresolved segment)
  enter.append('rect')
    .attr('class', 'bar-bg')
    .attr('x', LABEL_WIDTH)
    .attr('y', 0)
    .attr('width', BAR_WIDTH)
    .attr('height', BAR_HEIGHT)
    .attr('rx', 2)
    .attr('fill', PENDING_FILL)

  // Buy rect
  enter.append('rect')
    .attr('class', 'bar-buy')
    .attr('x', LABEL_WIDTH)
    .attr('y', 0)
    .attr('width', 0)
    .attr('height', BAR_HEIGHT)
    .attr('rx', 2)
    .attr('fill', SIGNAL_COLORS.buy)

  // Sell rect
  enter.append('rect')
    .attr('class', 'bar-sell')
    .attr('x', LABEL_WIDTH)
    .attr('y', 0)
    .attr('width', 0)
    .attr('height', BAR_HEIGHT)
    .attr('rx', 2)
    .attr('fill', SIGNAL_COLORS.sell)

  // Hold rect
  enter.append('rect')
    .attr('class', 'bar-hold')
    .attr('x', LABEL_WIDTH)
    .attr('y', 0)
    .attr('width', 0)
    .attr('height', BAR_HEIGHT)
    .attr('rx', 2)
    .attr('fill', SIGNAL_COLORS.hold)

  // UPDATE (merge enter + existing): animate bar widths (per D-06, 600ms transition)
  const merged = rows.merge(enter)

  merged.select('.bar-bg')
    .transition()
    .duration(600)
    .attr('width', BAR_WIDTH)

  merged.select('.bar-buy')
    .transition()
    .duration(600)
    .attr('width', d => {
      const total = d.total
      return total > 0 ? x(d.buy_count / total) : 0
    })

  merged.select('.bar-sell')
    .transition()
    .duration(600)
    .attr('x', d => {
      const total = d.total
      return LABEL_WIDTH + (total > 0 ? x(d.buy_count / total) : 0)
    })
    .attr('width', d => {
      const total = d.total
      return total > 0 ? x(d.sell_count / total) : 0
    })

  merged.select('.bar-hold')
    .transition()
    .duration(600)
    .attr('x', d => {
      const total = d.total
      const buyW = total > 0 ? x(d.buy_count / total) : 0
      const sellW = total > 0 ? x(d.sell_count / total) : 0
      return LABEL_WIDTH + buyW + sellW
    })
    .attr('width', d => {
      const total = d.total
      return total > 0 ? x(d.hold_count / total) : 0
    })
}

watch(() => snapshot.value.bracket_summaries, (summaries) => {
  if (summaries.length === 0) return
  updateBars(summaries)
}, { deep: true })

onMounted(() => {
  if (snapshot.value.bracket_summaries.length > 0) {
    updateBars(snapshot.value.bracket_summaries)
  }
})
</script>

<template>
  <div class="bracket-panel">
    <h3 class="bracket-panel__title">Brackets</h3>
    <svg
      ref="svgRef"
      class="bracket-panel__chart"
      width="100%"
      :viewBox="`0 0 ${VIEWBOX_WIDTH} ${SVG_HEIGHT}`"
      preserveAspectRatio="xMinYMin meet"
    />
  </div>
</template>

<style scoped>
.bracket-panel {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.bracket-panel__title {
  font-size: var(--font-size-heading);
  font-weight: var(--font-weight-semibold);
  line-height: var(--line-height-heading);
  color: var(--color-accent);
  margin-bottom: var(--space-sm);
  flex-shrink: 0;
}

.bracket-panel__chart {
  flex: 1;
  min-height: 0;
}
</style>
