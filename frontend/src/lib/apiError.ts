// Backend error envelope: {"detail": {"error": "<code>", "message": "<text>", ...}}.
// FastAPI still emits {"detail": "<text>"} for framework errors; both shapes are read.
import { ApiError } from '../api/client';

export interface ErrorEnvelope {
  code: string | null;
  message: string | null;
}

export function parseErrorEnvelope(body: unknown): ErrorEnvelope {
  if (typeof body !== 'object' || body === null) return { code: null, message: null };
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === 'string') return { code: null, message: detail };
  if (typeof detail !== 'object' || detail === null || Array.isArray(detail)) {
    return { code: null, message: null };
  }
  const fields = detail as Record<string, unknown>;
  return {
    code: typeof fields.error === 'string' ? fields.error : null,
    message: typeof fields.message === 'string' ? fields.message : null,
  };
}

// The text to show for a failed request: the envelope's message, else the HTTP
// status; for anything that is not an ApiError, its own message.
export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return parseErrorEnvelope(e.body).message ?? `HTTP ${e.status}`;
  return e instanceof Error ? e.message : String(e);
}

/**
 * One readable sentence for any failed API call: the backend
 * envelope's message, else its code and status; a network failure (fetch
 * rejects with TypeError) becomes a reachability hint. Duck-typed on
 * {status, body} instead of importing ApiError, so api/client.ts can import
 * this module later without an import cycle.
 */
export function formatApiError(err: unknown): string {
  if (typeof err === 'object' && err !== null && 'status' in err && 'body' in err) {
    const status = (err as { status: unknown }).status;
    const { code, message } = parseErrorEnvelope((err as { body: unknown }).body);
    if (message) return message;
    const statusText = typeof status === 'number' ? ` (HTTP ${status})` : '';
    if (code) return `${code.replace(/_/g, ' ')}${statusText}`;
    return `Request failed${statusText}`;
  }
  if (err instanceof TypeError) return 'Cannot reach the backend. Is it running on port 8000?';
  if (err instanceof Error && err.message) return err.message;
  return 'Something went wrong.';
}
