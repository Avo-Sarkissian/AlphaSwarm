// Report endpoints: POST /api/report/{cycle_id}/generate + GET /api/report/{cycle_id}.
import { apiFetch, apiPost, ApiError } from './client';
import { parseErrorEnvelope } from '../lib/apiError';
import { shouldKeepPolling } from '../lib/reportPolling';

// Structured report view served next to the markdown. Rows mirror the backend
// read models; shares are computed in the UI over decided agents.
export interface ConvergenceRow {
  round_num: number;
  buy_count: number;
  sell_count: number;
  hold_count: number;
  parse_error_count: number;
  total: number;
}

export interface InfluenceRow {
  agent_id: string;
  name: string;
  bracket: string;
  citation_count: number;
  influence_share: number;
}

export interface ReportSections {
  summary: string;
  convergence: ConvergenceRow[];
  influence: InfluenceRow[];
  moments: string[];
  dissent: string[];
  followups: string[];
}

export interface ReportContent {
  cycle_id: string;
  content: string;
  generated_at: string;
  sections?: ReportSections | null; // null for reports written before sections existed
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
