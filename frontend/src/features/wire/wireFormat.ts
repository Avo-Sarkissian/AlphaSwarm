// Signal Wire formatting: provider labels and colours, query subjects, source interleaving.

// Labels and colors for the providers that exist (alphaswarm.ingestion).
export const SOURCE_LABEL: Record<string, string> = { yfinance: 'YAHOO', rss: 'RSS' };
export const SOURCE_COLOR: Record<string, string> = { yfinance: '#f5a524', rss: '#5be7b8' };

// Pull the subject of a provider call out of the audit `query` string so
// the ticker shows e.g. ZZZT / MSFT / QQQX in the agent slot instead of
// repeating the source name. Mirrors the two query shapes in
// alphaswarm/ingestion/{yfinance,rss}_provider.py:
//   "ZZZT OHLCV"     → "ZZZT"
//   "headlines:ZZZT" → "ZZZT"
export function extractSubject(query: string, source: string): string {
  const after = query.includes(':') ? query.slice(query.indexOf(':') + 1) : query;
  const head = after.trim().split(/\s+/)[0] ?? '';
  return head ? head.toUpperCase() : (SOURCE_LABEL[source] ?? source.toUpperCase());
}

// Drop the subject token from the query so the post-arrow `sw-q` slot
// doesn't echo what's already in the agent slot. "ZZZT OHLCV" → "OHLCV";
// "headlines:ZZZT" → "headlines".
export function stripSubject(query: string): string {
  if (query.includes(':')) return query.slice(0, query.indexOf(':'));
  const parts = query.trim().split(/\s+/);
  return parts.length > 1 ? parts.slice(1).join(' ') : query;
}

// Round-robin entries across distinct sources so consecutive ticker items
// alternate yfinance / rss / fred / … instead of all-yfinance-then-all-rss
// (which made news-heavy seeds read as a wall of green RSS). Recency
// within a source is preserved — only the cross-source ORDERING changes.
// Insertion order of the Map drives the round-robin order, so the source
// that appeared first in the chronological audit anchors the rotation.
export function interleaveBySource<T extends { source: string }>(entries: readonly T[]): T[] {
  const groups = new Map<string, T[]>();
  for (const e of entries) {
    const arr = groups.get(e.source);
    if (arr) arr.push(e);
    else groups.set(e.source, [e]);
  }
  const queues = Array.from(groups.values());
  const result: T[] = [];
  let added = true;
  while (added) {
    added = false;
    for (const q of queues) {
      const next = q.shift();
      if (next !== undefined) {
        result.push(next);
        added = true;
      }
    }
  }
  return result;
}
