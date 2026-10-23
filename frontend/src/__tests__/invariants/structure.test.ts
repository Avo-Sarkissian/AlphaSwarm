// @vitest-environment node
// Structural invariants for frontend/src. Every allow-list in this file may
// only shrink; when a list reaches zero entries, delete it and its exemption.
import { readdirSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const SRC = fileURLToPath(new URL('../../', import.meta.url));

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

const FILES: readonly string[] = walk(SRC)
  .map((file) => relative(SRC, file).split(sep).join('/'))
  .sort();

describe('frontend structure', () => {
  it('has no JavaScript sources', () => {
    expect(FILES.filter((file) => /\.jsx?$/.test(file))).toEqual([]);
  });
});
