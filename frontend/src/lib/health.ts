// GET /api/health → what onboarding shows. A required component
// that is not ok makes the backend "degraded"; a component that is down
// usually carries a fix, either a command or a one-line instruction.
export interface HealthComponentView {
  name: string;
  ok: boolean;
  required: boolean;
  detail: string | null;
  fix: string | null;
  missing: string[];
}

export interface HealthSummary {
  status: 'ok' | 'degraded' | 'unknown';
  components: HealthComponentView[];
  down: HealthComponentView[];
}

const text = (v: unknown): string | null => (typeof v === 'string' && v !== '' ? v : null);

export function parseHealth(raw: unknown): HealthSummary {
  const r = (typeof raw === 'object' && raw !== null ? raw : {}) as Record<string, unknown>;
  const status = r.status === 'ok' || r.status === 'degraded' ? r.status : 'unknown';
  const componentsRaw =
    typeof r.components === 'object' && r.components !== null
      ? (r.components as Record<string, unknown>)
      : {};
  const components = Object.entries(componentsRaw).map(([name, value]): HealthComponentView => {
    const c = (typeof value === 'object' && value !== null ? value : {}) as Record<string, unknown>;
    return {
      name,
      ok: c.ok === true,
      required: c.required !== false,
      detail: text(c.detail),
      fix: text(c.fix),
      missing: Array.isArray(c.missing)
        ? c.missing.filter((m): m is string => typeof m === 'string')
        : [],
    };
  });
  return { status, components, down: components.filter((c) => c.required && !c.ok) };
}
