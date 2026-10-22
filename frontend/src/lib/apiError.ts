// Backend error envelope: {"detail": {"error": "<code>", "message": "<text>", ...}}.
// FastAPI still emits {"detail": "<text>"} for framework errors; both shapes are read.
import { ApiError } from '../api/client';
import { BACKEND_UNREACHABLE_CODE, BACKEND_UNREACHABLE_MESSAGE } from './backendUnreachable';

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

// Any {status, body} value (an ApiError or the same shape) is an HTTP failure.
function httpFailure(err: unknown): { status: unknown; body: unknown } | null {
  if (typeof err === 'object' && err !== null && 'status' in err && 'body' in err) {
    return err as { status: unknown; body: unknown };
  }
  return null;
}

/**
 * True when the request never reached the backend: fetch rejected with a
 * TypeError, or the Vite dev proxy answered backend_unreachable
 * (lib/backendUnreachable.ts).
 */
export function isBackendUnreachable(err: unknown): boolean {
  if (err instanceof TypeError) return true;
  const failure = httpFailure(err);
  return failure !== null && parseErrorEnvelope(failure.body).code === BACKEND_UNREACHABLE_CODE;
}

/**
 * One readable sentence for any failed API call: the backend envelope's
 * message, else its code and status. An unreachable backend becomes the
 * reachability hint, whether fetch failed or the dev proxy answered.
 */
export function formatApiError(err: unknown): string {
  if (isBackendUnreachable(err)) return BACKEND_UNREACHABLE_MESSAGE;
  const failure = httpFailure(err);
  if (failure) {
    const { code, message } = parseErrorEnvelope(failure.body);
    if (message) return message;
    const statusText = typeof failure.status === 'number' ? ` (HTTP ${failure.status})` : '';
    if (code) return `${code.replace(/_/g, ' ')}${statusText}`;
    return `Request failed${statusText}`;
  }
  if (err instanceof Error && err.message) return err.message;
  return 'Something went wrong.';
}
