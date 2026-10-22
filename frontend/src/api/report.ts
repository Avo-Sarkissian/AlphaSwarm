// Report endpoints: POST /api/report/{cycle_id}/generate + GET /api/report/{cycle_id}.
import { apiFetch, apiPost, ApiError } from './client';
import { parseErrorEnvelope } from '../lib/apiError';
import { shouldKeepPolling } from '../lib/reportPolling';

export interface ReportContent {
  cycle_id: string;
  content: string;
  generated_at: string;
}

export interface ReportGenerateResponse {
  status: string;
  cycle_id: string;
}

const reportPath = (cycleId: string) => `/api/report/${encodeURIComponent(cycleId)}`;

// POST: 202 on accept; 409 report_generation_in_progress when a job already runs
// for a cycle; 404 cycle_not_found / 422 cycle_not_ready otherwise.
export async function reportGenerate(cycleId: string): Promise<ReportGenerateResponse> {
  return apiPost<ReportGenerateResponse>(`${reportPath(cycleId)}/generate`, {});
}

// GET when the modal opens: 404 report_not_found -> null ("no report yet").
// Everything else propagates (409 means a job is running: the modal starts polling).
export async function reportFetch(cycleId: string): Promise<ReportContent | null> {
  try {
    return await apiFetch<ReportContent>(reportPath(cycleId));
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

// GET while polling after a generation started: 409 report_generation_in_progress
// -> null (keep polling); every other error, 404 included, ends the poll.
export async function reportPoll(cycleId: string): Promise<ReportContent | null> {
  try {
    return await apiFetch<ReportContent>(reportPath(cycleId));
  } catch (e) {
    if (
      e instanceof ApiError &&
      shouldKeepPolling({ status: e.status, code: parseErrorEnvelope(e.body).code })
    ) {
      return null;
    }
    throw e;
  }
}
