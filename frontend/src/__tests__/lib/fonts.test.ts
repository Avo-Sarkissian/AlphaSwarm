import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const SRC = fileURLToPath(new URL('../../', import.meta.url));

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) return name === '__tests__' ? [] : sourceFiles(full);
    return /\.(tsx?|jsx)$/.test(name) ? [full] : [];
  });
}

describe('self-hosted fonts', () => {
  it('main.tsx imports both font packages before the stylesheet', () => {
    const main = readFileSync(join(SRC, 'main.tsx'), 'utf8');
    const mono = main.indexOf('@fontsource-variable/jetbrains-mono');
    const sans = main.indexOf('@fontsource/ibm-plex-sans');
    expect(mono).toBeGreaterThanOrEqual(0);
    expect(sans).toBeGreaterThanOrEqual(0);
    expect(Math.max(mono, sans)).toBeLessThan(main.indexOf('./styles.css'));
  });

  it('styles.css defines the tokens and never names a family directly', () => {
    const css = readFileSync(join(SRC, 'styles.css'), 'utf8');
    expect(css).toMatch(/--font-sans:\s*'IBM Plex Sans'/);
    expect(css).toMatch(/--font-mono:\s*'JetBrains Mono Variable'/);
    expect(css.match(/font-family:\s*'/g) ?? []).toEqual([]);
  });

  it('no component hard-codes a font family', () => {
    const offenders = sourceFiles(SRC).filter((f) => /JetBrains|Plex/.test(readFileSync(f, 'utf8')));
    expect(offenders.map((f) => f.slice(SRC.length))).toEqual([]);
  });
});
