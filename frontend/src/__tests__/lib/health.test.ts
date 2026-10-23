import { describe, expect, it } from 'vitest';
import { parseHealth } from '../../lib/health';

const DEGRADED = {
  status: 'degraded',
  components: {
    neo4j: { ok: true, required: true, detail: null, fix: null, missing: [] },
    ollama: { ok: false, required: false, detail: 'not used in cloud mode', fix: null, missing: [] },
    aliases: {
      ok: false,
      required: true,
      detail: 'missing: alphaswarm-worker',
      fix: 'ollama create alphaswarm-worker -f modelfiles/Modelfile.worker',
      missing: ['alphaswarm-worker'],
    },
  },
};

describe('parseHealth', () => {
  it('lists components in order and flags required ones that are down', () => {
    const h = parseHealth(DEGRADED);
    expect(h.status).toBe('degraded');
    expect(h.components.map((c) => c.name)).toEqual(['neo4j', 'ollama', 'aliases']);
    expect(h.down.map((c) => c.name)).toEqual(['aliases']);
    expect(h.down[0]?.fix).toBe('ollama create alphaswarm-worker -f modelfiles/Modelfile.worker');
    expect(h.down[0]?.missing).toEqual(['alphaswarm-worker']);
  });

  it('accepts a healthy backend without components', () => {
    expect(parseHealth({ status: 'ok' })).toEqual({ status: 'ok', components: [], down: [] });
  });

  it('never throws on garbage', () => {
    expect(parseHealth(null)).toEqual({ status: 'unknown', components: [], down: [] });
    expect(parseHealth({ status: 'great', components: { neo4j: 'yes' } }).down[0]?.name).toBe('neo4j');
  });
});
