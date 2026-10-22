// Advisory endpoints: GET /api/advisory/{cycle_id} only.
// The backend's post-run pipeline starts the advisory after a completed run
// (when holdings are loaded); the frontend is a pure viewer, so the brief icon
// never causes a ~17 GB orchestrator load.
// 404 and 409 advisory_generation_in_progress -> null (pending); 500/503 propagate.
import { apiFetch, ApiError } from './client';
import { parseErrorEnvelope } from '../lib/apiError';

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

// GET /api/advisory/{cycle_id} — 404 / 409 in progress mean pending (returns null).
export async function advisoryFetch(
  cycleId: string,
): Promise<AdvisoryContent | null> {
  try {
    return await apiFetch<AdvisoryContent>(
      `/api/advisory/${encodeURIComponent(cycleId)}`,
    );
  } catch (e) {
    // 404: not generated yet; 409 advisory_generation_in_progress: generating now.
    if (
      e instanceof ApiError &&
      (e.status === 404 || parseErrorEnvelope(e.body).code === 'advisory_generation_in_progress')
    ) {
      return null;
    }
    throw e;
  }
}
