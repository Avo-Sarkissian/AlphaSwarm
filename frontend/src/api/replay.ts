// Replay endpoints: listCycles + replayStart/advance/stop.
// GET /api/replay/cycles returns only { cycle_id, created_at, seed_rumor, round_count }.
// KR-41.1-07 is the parity deviation — consensus/flips/duration/shocks
// columns are not on this list endpoint and the UI renders em-dash placeholders.
import { apiFetch, apiPost } from './client';

export interface CycleItem {
  cycle_id: string;
  created_at: string; // ISO-8601
  seed_rumor: string;
  round_count: number; // the cycle's num_rounds, 2 or 3 (docs/DECISIONS.md#adr-num-rounds)
}

export async function listCycles(): Promise<CycleItem[]> {
  const { cycles } = await apiFetch<{ cycles: CycleItem[] }>(
    '/api/replay/cycles',
  );
  return cycles;
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
