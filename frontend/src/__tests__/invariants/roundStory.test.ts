// The influence graph tells the round story through the shared primitives
// (docs/DECISIONS.md#adr-hero-graph). A source check, like the structure test.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const read = (rel: string) => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8');
const GRAPH = read('../../viz/InfluenceGraph.tsx');
const LEGEND_ITEMS = read('../../viz/legendItems.ts');

describe('InfluenceGraph round story', () => {
  it('draws agent edges through EdgePath keyed by direction', () => {
    expect(GRAPH).toMatch(/<EdgePath\b/);
    expect(GRAPH).toMatch(/key=\{edgeKey\(/);
  });

  it('never keys an element by its array index', () => {
    expect(GRAPH).not.toMatch(/key=\{(?:i|idx|index)\}/);
  });

  it('places nodes with NodeGroup and transitions their fill', () => {
    expect(GRAPH).toMatch(/<NodeGroup\b/);
    expect(GRAPH).not.toMatch(/transform=\{`translate/);
    expect(GRAPH).toContain('ig-node-fill');
  });

  it('rings flipped agents in their previous colour', () => {
    expect(GRAPH).toMatch(/\.flipped\s*&&\s*\w+\.flippedFrom\s*\?/);
    expect(GRAPH).toMatch(/<FlipRing\b/);
  });

  it('explains the ring as a flip since the previous round', () => {
    expect(LEGEND_ITEMS).not.toContain('Flipped since R1');
    expect(LEGEND_ITEMS).toContain('Ring: flipped since the previous round (colour = previous signal)');
  });
});
