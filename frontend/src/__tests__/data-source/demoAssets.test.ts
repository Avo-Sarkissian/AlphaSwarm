// The committed demo cycle stays loadable (docs/DECISIONS.md#adr-cycle-export).
import { existsSync, readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { parseCycleExport } from '../../data-source/cycleExport';

const DEMO_DIR = fileURLToPath(new URL('../../../public/demo/', import.meta.url));

describe('committed demo assets', () => {
  it('index.json names a parseable export of a finished multi-round cycle', () => {
    const index = JSON.parse(readFileSync(`${DEMO_DIR}index.json`, 'utf8')) as { cycle_id: string };
    expect(index.cycle_id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
    const file = `${DEMO_DIR}${index.cycle_id}.json`;
    expect(existsSync(file)).toBe(true);
    expect(statSync(file).size).toBeLessThan(1_000_000);
    const exp = parseCycleExport(JSON.parse(readFileSync(file, 'utf8')));
    expect(exp.cycle.cycle_id).toBe(index.cycle_id);
    expect(exp.cycle.status).toBe('complete');
    expect(exp.rounds.length).toBeGreaterThanOrEqual(2);
  });
});
