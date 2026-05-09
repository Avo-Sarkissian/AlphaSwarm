// POST /api/interview/{agent_id} — single-shot JSON response.
// KR-41.1-11: non-streaming — backend returns { response: string } in one body,
// not SSE. Plan 04 modals render the full response as one block.
import { apiPost } from './client';

export interface InterviewResponse {
  response: string;
}

// message must be 1..4000 chars (backend enforces). Trim client-side for UX.
export async function askAgent(
  agentId: string,
  message: string,
): Promise<InterviewResponse> {
  const trimmed = message.trim();
  if (!trimmed) throw new Error('message required');
  return apiPost<InterviewResponse>(
    `/api/interview/${encodeURIComponent(agentId)}`,
    { message: trimmed },
  );
}
