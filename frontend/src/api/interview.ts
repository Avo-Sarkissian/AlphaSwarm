// POST /api/interview/{agent_id} — single-shot JSON response.
// KR-41.1-11: non-streaming — backend returns { response: string } in one body,
// not SSE. Plan 04 modals render the full response as one block.
import { apiPost } from './client';

/** A local interview turn (lazy narrative + answer) can take minutes; match the backend's 600 s. */
const INTERVIEW_TIMEOUT_MS = 600_000;

export interface InterviewResponse {
  response: string;
}

// message must be 1..4000 chars (backend enforces). Trim client-side for UX.
export async function askAgent(
  agentId: string,
  message: string,
  cycleId?: string | null,
): Promise<InterviewResponse> {
  const trimmed = message.trim();
  if (!trimmed) throw new Error('message required');
  const body: { message: string; cycle_id?: string } = { message: trimmed };
  if (cycleId) body.cycle_id = cycleId;
  return apiPost<InterviewResponse>(`/api/interview/${encodeURIComponent(agentId)}`, body, {
    timeoutMs: INTERVIEW_TIMEOUT_MS,
  });
}
