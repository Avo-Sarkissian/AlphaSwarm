// GET /api/health with a short timeout: the route caches its probes
// for 5 s and answers fast, so a slow reply means the backend is in trouble.
import { apiFetch } from './client';

export const HEALTH_TIMEOUT_MS = 5_000;

/** Raw health JSON; parse it with lib/health.ts parseHealth. */
export function fetchHealth(): Promise<unknown> {
  return apiFetch<unknown>('/api/health', { timeoutMs: HEALTH_TIMEOUT_MS });
}
