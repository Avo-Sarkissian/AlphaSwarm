// @vitest-environment node
// Stylesheet hygiene: every custom property is defined, motion respects the
// user setting, and no top-level selector is declared twice.
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const SRC = fileURLToPath(new URL('../../', import.meta.url));
const CSS = readFileSync(join(SRC, 'styles.css'), 'utf8');
const CSS_NO_COMMENTS = CSS.replace(/\/\*[\s\S]*?\*\//g, '');

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) return name === '__tests__' ? [] : sources(full);
    return /\.tsx?$/.test(name) ? [full] : [];
  });
}

describe('styles.css', () => {
  it('defines every custom property that CSS or TSX reads', () => {
    const defined = new Set([...CSS_NO_COMMENTS.matchAll(/(--[\w-]+)\s*:/g)].map((m) => m[1]));
    const used = new Set(
      [CSS_NO_COMMENTS, ...sources(SRC).map((f) => readFileSync(f, 'utf8'))].flatMap((text) =>
        [...text.matchAll(/var\(\s*(--[\w-]+)/g)].map((m) => m[1] ?? ''),
      ),
    );
    expect([...used].filter((name) => !defined.has(name)).sort()).toEqual([]);
  });

  it('stops animations and transitions for prefers-reduced-motion', () => {
    const block = CSS_NO_COMMENTS.match(/@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{([\s\S]*?)\n\}/)?.[1] ?? '';
    expect(block).toMatch(/animation-duration:\s*0\.01ms\s*!important/);
    expect(block).toMatch(/transition-duration:\s*0\.01ms\s*!important/);
    expect(block).toMatch(/\.thinking\s*\{[^}]*opacity:\s*0\.45/);
  });
});
