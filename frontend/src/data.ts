// src/data.ts — the single bracket registry (docs/DECISIONS.md#p41-6-d-14).
// Keys, order, display names and counts mirror DEFAULT_BRACKETS in the backend;
// src/__tests__/lib/data.test.ts checks them against the backend-generated
// fixtures/brackets.json. Colors are presentation only.
import type { BracketKey } from './types';

export interface BracketSpec {
  key: BracketKey;
  display: string;
  count: number;
  color: string;
}

export const BRACKETS: readonly BracketSpec[] = [
  { key: 'institutions', display: 'Institutions', count: 18, color: '#ffb84d' },
  { key: 'sell_side', display: 'Sell-Side', count: 10, color: '#42d690' },
  { key: 'event_driven', display: 'Event-Driven', count: 10, color: '#ff9d5c' },
  { key: 'quants', display: 'Quants', count: 12, color: '#6aa9ff' },
  { key: 'degens', display: 'Degens', count: 15, color: '#ff5b6b' },
  { key: 'narrators', display: 'Narrators', count: 8, color: '#b080ff' },
  { key: 'algos', display: 'Algos', count: 8, color: '#8a93a0' },
  { key: 'macro', display: 'Macro', count: 7, color: '#5be7b8' },
  { key: 'shorts', display: 'Shorts', count: 7, color: '#ff4d7a' },
  { key: 'allocators', display: 'Allocators', count: 5, color: '#d4a843' },
];

const BY_KEY: ReadonlyMap<string, BracketSpec> = new Map(BRACKETS.map((b) => [b.key, b]));

export function isBracketKey(value: unknown): value is BracketKey {
  return typeof value === 'string' && BY_KEY.has(value);
}

export function bracketSpec(key: string): BracketSpec | undefined {
  return BY_KEY.get(key);
}

const warned = new Set<string>();
function warnUnknown(kind: string, value: string): void {
  if (!import.meta.env.DEV || warned.has(value)) return;
  warned.add(value);
  // eslint-disable-next-line no-console
  console.warn(`[brackets] unknown ${kind} "${value}" mapped to 'unknown'`);
}

/** Agent ids are `{bracket}_{NN}` (e.g. 'sell_side_03'). */
export function bracketOf(agentId: string): BracketKey | 'unknown' {
  const key = (agentId ?? '').replace(/_\d+$/, '');
  if (isBracketKey(key)) return key;
  warnUnknown('agent id', agentId);
  return 'unknown';
}

export function toBracketKey(value: unknown): BracketKey | 'unknown' {
  if (isBracketKey(value)) return value;
  warnUnknown('bracket', String(value));
  return 'unknown';
}
