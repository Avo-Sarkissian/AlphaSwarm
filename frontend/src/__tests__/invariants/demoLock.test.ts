// The read-only demo locks exactly five controls, each through demoLock()
// (docs/DECISIONS.md#adr-cycle-export).
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const SRC = fileURLToPath(new URL('../../', import.meta.url));
const FILES = (readdirSync(SRC, { recursive: true }) as string[]).filter(
  (file) => /\.tsx?$/.test(file) && !file.split(/[\\/]/).includes('__tests__'),
);

describe('demo locks', () => {
  it('locks exactly the five controls the static demo cannot offer', () => {
    const keys = FILES.flatMap((file) =>
      [...readFileSync(join(SRC, file), 'utf8').matchAll(/data-demo-lock="([a-z-]+)"/g)].map((m) => m[1]),
    );
    expect(keys.sort()).toEqual(['advisory', 'interview', 'run', 'settings', 'shock']);
  });

  it('reads the lock through demoLock() wherever a control is locked', () => {
    for (const file of FILES) {
      const text = readFileSync(join(SRC, file), 'utf8');
      if (text.includes('data-demo-lock=')) expect(text, file).toMatch(/demoLock\(\)/);
    }
  });
});
