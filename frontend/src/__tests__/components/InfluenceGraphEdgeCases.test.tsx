// @vitest-environment happy-dom
// Inputs the happy path never sees: a canvas measured at 0 x 0, an agent the
// registry does not know, a focused agent that changes or leaves between
// frames, a focused agent with no citations, and hovering before any citation
// exists.
import { act, cleanup, fireEvent, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Edge } from '../../api/edges';
import { InfluenceGraph } from '../../viz/InfluenceGraph';
import { rosterFromBrackets } from '../../viz/layout';
import { makeAgent } from '../helpers/agents';

const AGENTS = rosterFromBrackets().map((e) => makeAgent(e.id, 'buy', 0.6));
const EDGES: Edge[] = [
  { source_id: 'quants_01', target_id: 'sell_side_03', weight: 0.01 },
  { source_id: 'degens_02', target_id: 'quants_01', weight: 0.01 },
];
const props = { edges: EDGES, edgesRound: 2, roundNum: 3, layout: 'clusters' as const, allEdges: false };
const node = (c: HTMLElement, id: string) => c.querySelector(`[data-agent="${id}"]`) as SVGGElement;

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('InfluenceGraph edge cases', () => {
  it('keeps the last real size when the canvas reports 0 x 0', () => {
    const callbacks: ResizeObserverCallback[] = [];
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(cb: ResizeObserverCallback) {
          callbacks.push(cb);
        }
        observe() {}
        disconnect() {}
      },
    );
    const { container } = render(<InfluenceGraph agents={AGENTS} {...props} />);
    const resize = (width: number, height: number) =>
      act(() => callbacks.forEach((cb) => cb([{ contentRect: { width, height } } as ResizeObserverEntry], {} as ResizeObserver)));
    resize(1200, 800);
    const before = node(container, 'quants_01').getAttribute('transform');
    resize(0, 0);
    expect(node(container, 'quants_01').getAttribute('transform')).toBe(before);
    expect(container.querySelector('svg')?.getAttribute('viewBox')).toBe('0 0 1200 800');
  });

  it('draws an agent the registry does not know in an Unknown cluster', () => {
    const { container } = render(<InfluenceGraph agents={[...AGENTS, makeAgent('whales_01')]} {...props} />);
    expect(node(container, 'whales_01')).not.toBeNull();
    expect([...container.querySelectorAll('.ig-label')].map((t) => t.textContent)).toContain('UNKNOWN · 1');
  });

  it('drops the card when the pinned agent leaves the frame', () => {
    const { container, rerender } = render(<InfluenceGraph agents={AGENTS} {...props} />);
    fireEvent.click(node(container, 'quants_01'));
    expect(container.querySelector('.ig-tooltip')).not.toBeNull();
    rerender(<InfluenceGraph agents={AGENTS.filter((a) => a.id !== 'quants_01')} {...props} />);
    expect(container.querySelector('.ig-tooltip')).toBeNull();
  });

  it('keeps the pin while new frames arrive', () => {
    const { container, rerender } = render(<InfluenceGraph agents={AGENTS} {...props} />);
    fireEvent.click(node(container, 'quants_01'));
    fireEvent.mouseLeave(node(container, 'quants_01'));
    rerender(<InfluenceGraph agents={AGENTS.map((a) => ({ ...a, signal: 'sell' as const }))} {...props} />);
    expect(container.querySelector('.ig-tooltip')?.textContent).toContain('SELL');
  });
});

describe('InfluenceGraph focus without neighbours', () => {
  it('keeps the overview and an honest legend for an agent with no citations', () => {
    const { container } = render(<InfluenceGraph agents={AGENTS} {...props} />);
    fireEvent.mouseEnter(node(container, 'macro_01'));
    expect(container.querySelector('.ig-tooltip')?.textContent).toContain('macro_01');
    expect(container.querySelectorAll('.ig-ribbon').length).toBeGreaterThan(0);
    expect([...container.querySelectorAll('.ig-node')].filter((g) => g.getAttribute('opacity') !== '1')).toEqual([]);
    const keys = [...container.querySelectorAll('.ig-legend-item')].map((li) => li.getAttribute('data-key'));
    expect(keys).not.toContain('ego-in');
    expect(keys).toContain('ribbon');
  });
});

describe('InfluenceGraph without citations', () => {
  it('hovering in round 1 dims nobody', () => {
    const { container } = render(<InfluenceGraph agents={AGENTS} {...props} edges={[]} edgesRound={null} roundNum={1} />);
    fireEvent.mouseEnter(node(container, 'quants_01'));
    expect([...container.querySelectorAll('.ig-node')].filter((g) => g.getAttribute('opacity') !== '1')).toEqual([]);
    expect(container.querySelector('.ig-tooltip')?.textContent).toContain('Citations appear from round 2.');
  });
});
