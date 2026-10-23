import type { DataSourceAuditView } from '../types';

export interface SourceSummary {
  source: string;
  calls: number;
  cached: number;
  errors: number;
  cited: number;
  lastTs: number;
}

/** Providers record 'ok', 'cached' or 'error: <msg>' (alphaswarm.data_audit). */
export function isErrorResult(result: string): boolean {
  return result.startsWith('error');
}

export function summarizeAudit(entries: readonly DataSourceAuditView[]): SourceSummary[] {
  const bySource = new Map<string, SourceSummary>();
  for (const e of entries) {
    const s = bySource.get(e.source) ?? { source: e.source, calls: 0, cached: 0, errors: 0, cited: 0, lastTs: 0 };
    s.calls += 1;
    if (e.result === 'cached') s.cached += 1;
    if (isErrorResult(e.result)) s.errors += 1;
    if (e.used) s.cited += 1;
    s.lastTs = Math.max(s.lastTs, e.ts);
    bySource.set(e.source, s);
  }
  return [...bySource.values()].sort((a, b) => b.calls - a.calls || a.source.localeCompare(b.source));
}

export function recentFor(entries: readonly DataSourceAuditView[], source: string, limit = 20): DataSourceAuditView[] {
  return entries
    .filter((e) => e.source === source)
    .sort((a, b) => b.ts - a.ts)
    .slice(0, limit);
}
