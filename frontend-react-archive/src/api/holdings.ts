// GET /api/holdings — production AdvisoryModal data path.
// Backend response: { account_number_hash, as_of, holdings: [{ ticker, qty, cost_basis }] }.
// qty + cost_basis arrive as decimal strings (backend preserves precision);
// the UI keeps them as strings for display (no float precision loss).
// Tolerates 404/503 by returning an empty snapshot — endpoint may not yet be
// wired or holdings CSV may be missing.
import { apiFetch, ApiError } from './client';

export interface Holding {
  ticker: string;
  qty: string; // decimal string, e.g. "1200.000"
  cost_basis: string | null; // decimal string or null
}

export interface HoldingsSnapshot {
  account_number_hash: string;
  as_of: string; // ISO-8601
  holdings: Holding[];
}

export async function fetchHoldings(): Promise<HoldingsSnapshot> {
  try {
    return await apiFetch<HoldingsSnapshot>('/api/holdings');
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 503)) {
      return { account_number_hash: '', as_of: '', holdings: [] };
    }
    throw e;
  }
}
