// src/api/client.ts — the one HTTP helper. Every call gets a timeout, an
// optional caller AbortSignal and an ApiError whose message and code come from
// the backend's error envelope (docs/DECISIONS.md#adr-background-tasks).
import { parseErrorEnvelope } from '../lib/apiError';
import { BACKEND_UNREACHABLE_MESSAGE } from '../lib/backendUnreachable';

export const DEFAULT_TIMEOUT_MS = 30_000;

export type RequestOptions = RequestInit & { timeoutMs?: number; signal?: AbortSignal };

export class ApiError extends Error {
  /** Envelope code, or 'timeout' / 'network_error' for transport failures (status 0). */
  readonly code: string | null;

  constructor(
    public readonly status: number,
    public readonly body: unknown,
    public readonly path: string,
    message?: string,
    code?: string | null,
  ) {
    super(message ?? parseErrorEnvelope(body).message ?? `HTTP ${status} ${path}`);
    this.name = 'ApiError';
    this.code = code ?? parseErrorEnvelope(body).code;
  }
}

async function safeBody(res: Response): Promise<unknown> {
  try {
    return await res.json();
  } catch {
    return await res.text().catch(() => null);
  }
}

export async function request<T>(path: string, init: RequestOptions = {}): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, signal: callerSignal, ...rest } = init;
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const forwardAbort = () => controller.abort();
  if (callerSignal?.aborted) controller.abort();
  else callerSignal?.addEventListener('abort', forwardAbort, { once: true });

  let res: Response;
  try {
    res = await fetch(path, { ...rest, signal: controller.signal });
  } catch (e) {
    if (timedOut) {
      throw new ApiError(0, null, path, `No response from ${path} after ${Math.round(timeoutMs / 1000)} s`, 'timeout');
    }
    if (callerSignal?.aborted) throw e;
    throw new ApiError(0, null, path, BACKEND_UNREACHABLE_MESSAGE, 'network_error');
  } finally {
    clearTimeout(timer);
    callerSignal?.removeEventListener('abort', forwardAbort);
  }
  if (!res.ok) throw new ApiError(res.status, await safeBody(res), path);
  return (await res.json()) as T;
}

export function apiFetch<T>(path: string, init?: RequestOptions): Promise<T> {
  return request<T>(path, init);
}

export function apiPost<T>(path: string, body?: unknown, init?: RequestOptions): Promise<T> {
  return request<T>(path, {
    ...init,
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}
