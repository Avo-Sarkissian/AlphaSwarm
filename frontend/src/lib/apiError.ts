// Backend error envelope: {"detail": {"error": "<code>", "message": "<text>", ...}}.
// FastAPI still emits {"detail": "<text>"} for framework errors; both shapes are read.
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
