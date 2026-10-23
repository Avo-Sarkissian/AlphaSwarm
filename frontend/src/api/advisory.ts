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

export type AdvisorySignal = 'BUY' | 'SELL' | 'HOLD';

export interface AdvisoryItemPayload {
  ticker: string;
  consensus_signal: AdvisorySignal;
  confidence: number;
  rationale_summary: string;
  position_exposure: string | number;
  source?: 'swarm' | 'placeholder'; // absent in files written before placeholders were marked
  risk?: string | null;
  upside?: string | null;
}

export interface AdvisoryStatsPayload {
  conviction_count: number;
  placeholder_count: number;
  buy_count: number;
  sell_count: number;
  hold_count: number;
  avg_confidence: number | null;
  dominant_signal: AdvisorySignal | null;
  dominant_share: number | null;
}

export interface AdvisoryReportPayload extends AdvisoryContent {
  items?: AdvisoryItemPayload[];
  portfolio_outlook?: string;
  total_holdings?: number;
  affected_holdings?: number;
  stats?: AdvisoryStatsPayload | null; // null for files written before backend stats
  holdings_as_of?: string | null;
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
