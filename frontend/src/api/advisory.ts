// Advisory endpoints: GET /api/advisory/{cycle_id} only.
// The POST path was removed in quick task 260507-19f — synthesis is now
// auto-fired by the backend on FINAL round (SimulationManager.on_complete
// → _auto_trigger_advisory). Frontend is a pure viewer; the manual brief
// icon must NEVER cause a ~17 GB orchestrator load.
// Mirrors report.ts on read: 404→null (pending), 500/503 propagate.
import { apiFetch, ApiError } from './client';

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
