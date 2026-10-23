import { describe, expect, it } from 'vitest';
import { systemChecks } from '../../lib/systemChecks';
import { HEALTH_ALIAS_MISSING } from '../fixtures/health';

const ROSTER = { personas: 100, brackets: 10 };

describe('systemChecks', () => {
  it('maps health components to rows and carries the fix for failures', () => {
    expect(systemChecks(HEALTH_ALIAS_MISSING, null, ROSTER)).toEqual([
      { label: 'Inference', value: 'local', state: 'ok', fix: null },
      { label: 'Neo4j', value: 'ok', state: 'ok', fix: null },
      { label: 'Ollama', value: 'ok', state: 'ok', fix: null },
      {
        label: 'Model aliases',
        value: 'missing: alphaswarm-worker',
        state: 'err',
        fix: 'ollama create alphaswarm-worker -f modelfiles/Modelfile.worker',
      },
      { label: 'Agents', value: '100 personas · 10 brackets', state: 'ok', fix: null },
    ]);
  });

  it('treats a component the current mode does not need as fine', () => {
    const cloud = {
      ...HEALTH_ALIAS_MISSING,
      inference_mode: 'cloud',
      components: { ollama: { ok: false, required: false, detail: 'not running', fix: 'ollama serve' } },
    };
    expect(systemChecks(cloud, null, ROSTER)[1]).toEqual({
      label: 'Ollama',
      value: 'not running (not needed in this mode)',
      state: 'ok',
      fix: null,
    });
  });

  it('labels a component it does not know by its key', () => {
    const extra = { status: 'ok', components: { docker: { ok: true, required: false, detail: null, fix: null } } };
    expect(systemChecks(extra, null, ROSTER)[0]).toEqual({ label: 'docker', value: 'ok', state: 'ok', fix: null });
  });

  it('shows a pending row while the first check is in flight', () => {
    expect(systemChecks(null, null, ROSTER)[0]).toEqual({ label: 'Backend', value: 'checking…', state: 'pending', fix: null });
  });

  it('shows the backend as unreachable with a start command', () => {
    const [row] = systemChecks(null, new Error('Cannot reach the backend. Is it running on port 8000?'), ROSTER);
    expect(row).toMatchObject({ label: 'Backend', state: 'err', fix: 'Start the backend from the repo root: uv run alphaswarm web' });
  });
});
