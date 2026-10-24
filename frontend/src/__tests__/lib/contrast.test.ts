// Contrast floors: every edge colour stays >= 3:1 against the lightest canvas
// colour at the opacity the graph draws it with, and muted text stays >= 4.5:1
// on the panel backgrounds.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { BRACKETS } from '../../data';
import { citerColor, EDGE_IN, EDGE_NEUTRAL, EDGE_OPACITY, EDGE_OUT } from '../../viz/encodings';

const CSS = readFileSync(fileURLToPath(new URL('../../styles.css', import.meta.url)), 'utf8');
const ROOT = CSS.match(/:root\s*\{([^}]*)\}/)?.[1] ?? '';
const TOKENS = new Map(
  [...ROOT.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)].map((m) => [m[1] ?? '', (m[2] ?? '').trim()]),
);

/** Resolve `var(--x)` chains and plain hex to '#rrggbb'. */
function hex(value: string, depth = 0): string {
  const v = value.trim();
  const ref = v.match(/^var\((--[\w-]+)\)$/);
  if (ref && depth < 8) return hex(TOKENS.get(ref[1] ?? '') ?? '', depth + 1);
  if (/^#[0-9a-f]{6}$/i.test(v)) return v.toLowerCase();
  throw new Error(`not a resolvable colour: "${value}"`);
}

function channels(h: string): [number, number, number] {
  return [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number];
}

function luminance(h: string): number {
  const [r, g, b] = channels(h).map((c) => {
    const s = c / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function blend(fg: string, bg: string, alpha: number): string {
  const f = channels(fg);
  const b = channels(bg);
  return `#${f.map((c, i) => Math.round(alpha * c + (1 - alpha) * (b[i] ?? 0)).toString(16).padStart(2, '0')).join('')}`;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

const CANVAS = hex('var(--canvas-center)');

describe('edge contrast against the canvas', () => {
  const edgeColours: Array<[string, string]> = [
    ['neutral edge', EDGE_NEUTRAL],
    ['ego incoming', EDGE_IN],
    ['ego outgoing', EDGE_OUT],
    ...(['buy', 'sell', 'hold', 'parse_error'] as const).map((s): [string, string] => [`citer ${s}`, citerColor(s)]),
    ...BRACKETS.map((b): [string, string] => [`ribbon ${b.key}`, b.color]),
  ];

  it.each(edgeColours)('%s is at least 3:1 at the drawn opacity', (_name, colour) => {
    expect(contrast(blend(hex(colour), CANVAS, EDGE_OPACITY), CANVAS)).toBeGreaterThanOrEqual(3);
  });
});

describe('muted text contrast', () => {
  it.each(['--bg', '--bg-2', '--bg-3'])('--text-3 is at least 4.5:1 on %s', (bg) => {
    expect(contrast(hex('var(--text-3)'), hex(`var(${bg})`))).toBeGreaterThanOrEqual(4.5);
  });
});
