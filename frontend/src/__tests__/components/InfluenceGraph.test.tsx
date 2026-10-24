// @vitest-environment happy-dom
// The hero graph: stable positions, ribbons overview, all-edges toggle, ego
// network on hover/pin, honest legend per layout, round-1 caption
// (docs/DECISIONS.md#adr-hero-graph).
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Edge } from '../../api/edges';
import type { AgentSignal, AgentView } from '../../types';
import { DEFAULT_ALL_EDGES, InfluenceGraph, type InfluenceGraphProps } from '../../viz/InfluenceGraph';
import { rosterFromBrackets } from '../../viz/layout';
import { makeAgent } from '../helpers/agents';

const SIGNALS: ReadonlyArray<AgentSignal | null> = ['buy', 'sell', 'hold', 'buy', 'parse_error', null];
const AGENTS: AgentView[] = rosterFromBrackets().map((e, i) => {
  const signal = SIGNALS[i % SIGNALS.length];
  return makeAgent(e.id, signal === undefined ? 'hold' : signal, 0.6);
});
const IDS = AGENTS.map((a) => a.id);

/** Every agent cites one agent in another bracket: deterministic citations. */
const EDGES: Edge[] = IDS.flatMap((id, i) => {
  const target = IDS[(i * 7 + 13) % IDS.length] ?? id;
  return target.replace(/_\d+$/, '') === id.replace(/_\d+$/, '') ? [] : [{ source_id: id, target_id: target, weight: 0.01 }];
});

function renderGraph(props: Partial<InfluenceGraphProps> = {}) {
  const onInterview = vi.fn();
  const view = render(
    <InfluenceGraph
      agents={AGENTS}
      edges={EDGES}
      edgesRound={2}
      roundNum={3}
      layout="clusters"
      allEdges={false}
      onInterview={onInterview}
      {...props}
    />,
  );
  return { ...view, onInterview };
}

const node = (container: HTMLElement, id: string) =>
  container.querySelector(`[data-agent="${id}"]`) as SVGGElement;
const legendKeys = (container: HTMLElement) =>
  [...container.querySelectorAll('.ig-legend-item')].map((li) => li.getAttribute('data-key'));

afterEach(cleanup);

describe('InfluenceGraph layout', () => {
  it('is a memoised component', () => {
    expect((InfluenceGraph as unknown as { $$typeof: symbol }).$$typeof).toBe(Symbol.for('react.memo'));
  });

  it('starts with the owner-chosen overview', () => {
    // Recorded in docs/DECISIONS.md#adr-hero-graph: false = bracket ribbons first.
    expect(DEFAULT_ALL_EDGES).toBe(false);
  });

  it('draws one node per agent and ignores frame order', () => {
    const first = renderGraph();
    const where = node(first.container, 'quants_01').getAttribute('transform');
    expect(first.container.querySelectorAll('.ig-node')).toHaveLength(100);
    cleanup();
    const second = renderGraph({ agents: [...AGENTS].reverse() });
    expect(node(second.container, 'quants_01').getAttribute('transform')).toBe(where);
  });

  it('labels every bracket', () => {
    const { container } = renderGraph();
    const labels = [...container.querySelectorAll('.ig-label')].map((t) => t.textContent);
    expect(labels).toHaveLength(10);
    expect(labels[1]).toBe('SELL-SIDE · 10');
  });

  it('marks failed agents with a cross', () => {
    const { container } = renderGraph();
    expect(node(container, 'institutions_05').querySelector('.ig-fail-mark')).not.toBeNull();
    expect(node(container, 'institutions_01').querySelector('.ig-fail-mark')).toBeNull();
  });
});

describe('InfluenceGraph edges', () => {
  it('shows at most 90 bracket ribbons and no agent edges by default', () => {
    const { container } = renderGraph();
    const ribbons = container.querySelectorAll('.ig-ribbon').length;
    expect(ribbons).toBeGreaterThan(0);
    expect(ribbons).toBeLessThanOrEqual(90);
    expect(container.querySelectorAll('.ig-edge')).toHaveLength(0);
  });

  it('draws every citation with All edges on', () => {
    const { container } = renderGraph({ allEdges: true });
    expect(container.querySelectorAll('.ig-edge')).toHaveLength(EDGES.length);
    expect(container.querySelectorAll('.ig-ribbon')).toHaveLength(0);
  });

  it('never draws edges in the grid layout', () => {
    const { container } = renderGraph({ layout: 'grid', allEdges: true });
    expect(container.querySelectorAll('.ig-edge, .ig-ribbon')).toHaveLength(0);
  });

  it('labels the five most-cited agents', () => {
    const { container } = renderGraph();
    expect(container.querySelectorAll('.ig-top-label')).toHaveLength(5);
  });

  it('draws every node the same size while there are no citations', () => {
    const { container } = renderGraph({ edges: [], edgesRound: null, roundNum: 1 });
    const radii = new Set([...container.querySelectorAll('.ig-node circle')].map((c) => c.getAttribute('r')));
    expect(radii.size).toBe(1);
  });
});

describe('InfluenceGraph focus', () => {
  const target = EDGES[0]?.target_id ?? '';

  it('hovering an agent draws its ego network and dims everyone else', () => {
    const { container } = renderGraph();
    fireEvent.mouseEnter(node(container, target));
    const incoming = EDGES.filter((e) => e.source_id === target).length;
    const outgoing = EDGES.filter((e) => e.target_id === target).length;
    expect(container.querySelectorAll('.ig-edge-in')).toHaveLength(incoming);
    expect(container.querySelectorAll('.ig-edge-out')).toHaveLength(outgoing);
    expect(container.querySelectorAll('.ig-ribbon')).toHaveLength(0);
    const dimmed = [...container.querySelectorAll('.ig-node')].filter((g) => g.getAttribute('opacity') === '0.06');
    expect(dimmed.length).toBe(100 - 1 - incoming - outgoing);
    fireEvent.mouseLeave(node(container, target));
    expect(container.querySelectorAll('.ig-edge-in, .ig-edge-out')).toHaveLength(0);
  });

  it('shows THINKING for a pending agent and who it cites', () => {
    const pending = AGENTS.find((a) => a.signal === null);
    const { container } = renderGraph();
    fireEvent.mouseEnter(node(container, pending?.id ?? ''));
    const card = container.querySelector('.ig-tooltip');
    expect(card?.textContent).toContain('THINKING');
    expect(card?.textContent).toContain('Cites');
    expect(card?.textContent).not.toContain('Flipped');
  });

  it('click pins the agent; the card opens the interview; Esc unpins', () => {
    const { container, onInterview } = renderGraph();
    fireEvent.click(node(container, target));
    fireEvent.mouseLeave(node(container, target));
    fireEvent.click(screen.getByRole('button', { name: `Interview ${target} →` }));
    expect(onInterview).toHaveBeenCalledWith(target);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(container.querySelector('.ig-tooltip')).toBeNull();
  });

  it('keeps hover state inside the graph', () => {
    // Pointer movement must never re-render the dashboard panels next to the graph.
    const siblingRender = vi.fn();
    function Sibling() {
      siblingRender();
      return null;
    }
    const { container } = render(
      <>
        <InfluenceGraph agents={AGENTS} edges={EDGES} edgesRound={2} roundNum={3} layout="clusters" allEdges={false} />
        <Sibling />
      </>,
    );
    const before = siblingRender.mock.calls.length;
    fireEvent.mouseEnter(node(container, target));
    fireEvent.mouseLeave(node(container, target));
    expect(siblingRender.mock.calls.length).toBe(before);
  });

  it('clicking the background unpins', () => {
    const { container } = renderGraph();
    fireEvent.click(node(container, target));
    fireEvent.mouseLeave(node(container, target));
    fireEvent.click(container.querySelector('.ig-bg') as Element);
    expect(container.querySelector('.ig-tooltip')).toBeNull();
  });
});

describe('InfluenceGraph legend and caption', () => {
  it.each([
    ['clusters', false, ['buy', 'sell', 'hold', 'failed', 'pending', 'size', 'ribbon']],
    ['clusters', true, ['buy', 'sell', 'hold', 'failed', 'pending', 'size', 'agent-edge']],
    ['radial', false, ['buy', 'sell', 'hold', 'failed', 'pending', 'size', 'hint']],
    ['grid', false, ['buy', 'sell', 'hold', 'failed', 'pending', 'hint']],
  ] as const)('lists only what %s (all edges: %s) draws', (layout, allEdges, keys) => {
    const { container } = renderGraph({ layout, allEdges });
    expect(legendKeys(container)).toEqual(keys);
  });

  it('explains an empty round 1 instead of drawing nothing', () => {
    renderGraph({ edges: [], edgesRound: null, roundNum: 1 });
    expect(screen.getByText('Round 1: agents decide independently. Peer influence starts in round 2.')).toBeTruthy();
  });

  it('shows no caption while citations are drawn', () => {
    const { container } = renderGraph();
    expect(container.querySelector('.ig-caption')).toBeNull();
  });
});
