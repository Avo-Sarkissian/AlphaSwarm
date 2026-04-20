// Advisory endpoints: POST /api/advisory/{cycle_id} + GET /api/advisory/{cycle_id}.
// Mirrors report.ts: 404→null (pending), 500/503 propagate.
import { apiFetch, apiPost, ApiError } from './client';

export interface AdvisoryContent {
  cycle_id: string;
  // Backend returns the AdvisoryReport JSON payload. The raw markdown lives on
  // the `content` field if present; callers render it through DOMPurify+marked.
  content?: string;
  generated_at?: string;
  // Additional fields (narrative, recommendations, affected_holdings) are
  // passed through as unknown[] to allow future rendering without breaking
  // this client.
  [key: string]: unknown;
}

export interface AdvisoryGenerateResponse {
  status: string;
  cycle_id: string;
}

// POST /api/advisory/{cycle_id} — 202 on accept, 409 when either a report OR
// an advisory is in flight (backend serializes orchestrator model consumers).
export async function advisoryGenerate(
  cycleId: string,
): Promise<AdvisoryGenerateResponse> {
  return apiPost<AdvisoryGenerateResponse>(
    `/api/advisory/${encodeURIComponent(cycleId)}`,
    {},
  );
}

// GET /api/advisory/{cycle_id} — 404 means still generating (returns null).
export async function advisoryFetch(
  cycleId: string,
): Promise<AdvisoryContent | null> {
  try {
    return await apiFetch<AdvisoryContent>(
      `/api/advisory/${encodeURIComponent(cycleId)}`,
    );
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}
