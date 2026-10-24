// @vitest-environment happy-dom
import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { Edge } from '../../api/edges';
import { EdgePath, FlipRing, NodeGroup, edgeKey } from '../../viz/story';

const ab: Edge = { source_id: 'quants_01', target_id: 'sell_side_01', weight: 1, cited_signal: 'sell' };
const cd: Edge = { source_id: 'degens_02', target_id: 'macro_01', weight: 1 };

function edges(list: Edge[], className?: string) {
  return (
    <svg>
      {list.map((e) => (
        <EdgePath key={edgeKey(e)} edge={e} d="M0 0 L10 10" stroke="red" className={className} />
      ))}
    </svg>
  );
}

afterEach(cleanup);

describe('round-story primitives', () => {
  it('keys edges by direction', () => {
    expect(edgeKey(ab)).toBe('quants_01->sell_side_01');
    expect(edgeKey({ source_id: 'sell_side_01', target_id: 'quants_01' })).not.toBe(edgeKey(ab));
  });

  it('keeps the DOM node of an edge that stays, so only new edges draw in', () => {
    const { container, rerender } = render(edges([ab]));
    const kept = container.querySelector('[data-edge="quants_01->sell_side_01"]');
    rerender(edges([cd, ab]));
    expect(container.querySelector('[data-edge="quants_01->sell_side_01"]')).toBe(kept);
    expect(kept?.getAttribute('class')).toContain('ig-edge--draw');
    expect(kept?.getAttribute('pathLength')).toBe('1');
    expect(kept?.getAttribute('stroke')).toBe('red');
  });

  it("merges the caller's classes without repeating ig-edge", () => {
    const { container } = render(edges([ab], 'ig-edge ig-edge-in'));
    expect(container.querySelector('path')?.getAttribute('class')).toBe('ig-edge ig-edge--draw ig-edge-in');
  });

  it('names what the citing agent saw', () => {
    const { container } = render(edges([ab, cd]));
    const titles = Array.from(container.querySelectorAll('path > title')).map((t) => t.textContent);
    expect(titles).toEqual(['quants_01 cited sell_side_01 (saw SELL)', 'degens_02 cited macro_01']);
    expect(
      container.querySelector('[data-edge="quants_01->sell_side_01"]')?.getAttribute('data-cited-signal'),
    ).toBe('sell');
  });

  it('positions a node with a CSS transform so it can move smoothly', () => {
    const { container } = render(
      <svg>
        <NodeGroup id="quants_01" x={10} y={20}>
          <circle r={4} />
        </NodeGroup>
      </svg>,
    );
    const group = container.querySelector('[data-agent="quants_01"]') as SVGGElement | null;
    expect(group?.style.transform).toBe('translate(10px, 20px)');
    expect(group?.getAttribute('class')).toBe('ig-node');
  });

  it("keeps the caller's node classes and attributes (focus, dimming)", () => {
    const { container } = render(
      <svg>
        <NodeGroup id="quants_01" x={0} y={0} className="focused" opacity={0.06}>
          <circle r={4} />
        </NodeGroup>
      </svg>,
    );
    const group = container.querySelector('[data-agent="quants_01"]');
    expect(group?.getAttribute('class')).toBe('ig-node focused');
    expect(group?.getAttribute('opacity')).toBe('0.06');
  });

  it('rings a flipped agent in its previous signal colour', () => {
    const { container } = render(
      <svg>
        <FlipRing r={6} from="buy" />
      </svg>,
    );
    const ring = container.querySelector('circle.ig-flip');
    expect(ring?.getAttribute('r')).toBe('9');
    expect(ring?.getAttribute('stroke')).toBe('var(--buy)');
    expect(ring?.querySelector('title')?.textContent).toBe('Flipped from BUY');
  });
});
