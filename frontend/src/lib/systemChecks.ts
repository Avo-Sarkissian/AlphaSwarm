import { parseHealth } from './health';

export type CheckState = 'ok' | 'err' | 'pending';

export interface SystemCheckRow {
  label: string;
  value: string;
  state: CheckState;
  fix: string | null;
}

const COMPONENT_LABELS: Record<string, string> = { neo4j: 'Neo4j', ollama: 'Ollama', aliases: 'Model aliases' };

function inferenceMode(raw: unknown): string | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const mode = (raw as { inference_mode?: unknown }).inference_mode;
  return typeof mode === 'string' && mode !== '' ? mode : null;
}

/** IdleState rows: the backend's readiness components plus the configured roster. */
export function systemChecks(
  raw: unknown,
  error: Error | null,
  roster: { personas: number; brackets: number },
): SystemCheckRow[] {
  const agents: SystemCheckRow = {
    label: 'Agents',
    value: `${roster.personas} personas · ${roster.brackets} brackets`,
    state: 'ok',
    fix: null,
  };
  if (error) {
    return [
      { label: 'Backend', value: error.message, state: 'err', fix: 'Start the backend from the repo root: uv run alphaswarm web' },
      agents,
    ];
  }
  if (raw === null || raw === undefined) {
    return [{ label: 'Backend', value: 'checking…', state: 'pending', fix: null }, agents];
  }

  const rows = parseHealth(raw).components.map((c): SystemCheckRow => {
    const label = COMPONENT_LABELS[c.name] ?? c.name;
    if (c.ok) return { label, value: 'ok', state: 'ok', fix: null };
    if (!c.required) return { label, value: `${c.detail ?? 'not available'} (not needed in this mode)`, state: 'ok', fix: null };
    return { label, value: c.detail ?? 'not ready', state: 'err', fix: c.fix };
  });
  const mode = inferenceMode(raw);
  const inference: SystemCheckRow[] = mode ? [{ label: 'Inference', value: mode, state: 'ok', fix: null }] : [];
  return [...inference, ...rows, agents];
}
