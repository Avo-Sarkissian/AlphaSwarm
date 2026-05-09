// Report endpoints: POST /api/report/{cycle_id}/generate + GET /api/report/{cycle_id}.
// Key-based polling convention: reportFetch returns null on 404 (still pending);
// 500/503 propagate to stop the usePolling loop.
import { apiFetch, apiPost, ApiError } from './client';

export interface ReportContent {
  cycle_id: string;
  content: string;
  generated_at: string;
}

export interface ReportGenerateResponse {
  status: string;
  cycle_id: string;
}

// POST /api/report/{cycle_id}/generate — 202 on accept, 409 when another
// generation is in flight. Callers branch on ApiError.status === 409.
export async function reportGenerate(
  cycleId: string,
): Promise<ReportGenerateResponse> {
  return apiPost<ReportGenerateResponse>(
    `/api/report/${encodeURIComponent(cycleId)}/generate`,
    {},
  );
}

// GET /api/report/{cycle_id} — 404 means still generating (returns null);
// 500/503 propagate as ApiError so the polling loop stops with status=error.
export async function reportFetch(
  cycleId: string,
): Promise<ReportContent | null> {
  try {
    return await apiFetch<ReportContent>(
      `/api/report/${encodeURIComponent(cycleId)}`,
    );
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}
