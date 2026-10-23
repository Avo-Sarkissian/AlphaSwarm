// Replay endpoints. GET /api/replay/cycles returns one page of complete cycles,
// newest first, with the run metrics stored on each Cycle.
import { apiFetch, apiPost } from './client';

export interface CycleItem {
  cycle_id: string;
  created_at: string; // ISO-8601 with offset, up to 9 fractional digits; also the paging cursor
  seed_rumor: string;
  round_count: number; // actual cascade depth (2 or 3)
  status: string;
  final_buy: number | null; // null: recorded before run metrics existed
  final_sell: number | null;
  final_hold: number | null;
  total_flips: number | null;
  total_seconds: number | null;
  agent_count: number | null;
}

export interface CyclePage {
  cycles: CycleItem[];
  nextBefore: string | null;
}

export const CYCLE_PAGE_SIZE = 20;

export async function listCycles(opts: { limit?: number; before?: string | null } = {}): Promise<CyclePage> {
  // URLSearchParams encodes '+' and ':' in the cursor; a raw '+' would decode as a space.
  const params = new URLSearchParams({ limit: String(opts.limit ?? CYCLE_PAGE_SIZE) });
  if (opts.before) params.set('before', opts.before);
  const body = await apiFetch<{ cycles: CycleItem[]; next_before: string | null }>(
    `/api/replay/cycles?${params.toString()}`,
  );
  return { cycles: body.cycles ?? [], nextBefore: body.next_before ?? null };
}

export interface ReplayStartResponse {
  status: string;
  cycle_id: string;
  round_num: number;
}

export interface ReplayAdvanceResponse {
  status: string;
  round_num: number;
}

export interface ReplayStopResponse {
  status: string;
}

export async function replayStart(cycleId: string): Promise<ReplayStartResponse> {
  return apiPost<ReplayStartResponse>(
    `/api/replay/start/${encodeURIComponent(cycleId)}`,
    {},
  );
}

export async function replayAdvance(): Promise<ReplayAdvanceResponse> {
  return apiPost<ReplayAdvanceResponse>('/api/replay/advance', {});
}

export async function replayStop(): Promise<ReplayStopResponse> {
  return apiPost<ReplayStopResponse>('/api/replay/stop', {});
}
