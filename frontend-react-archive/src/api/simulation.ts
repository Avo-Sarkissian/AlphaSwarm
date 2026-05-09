// Canonical routes: POST /api/simulate/{start,stop,shock}.
// Start body = {seed: string}, Shock body = {shock_text: string}.
// Plan 04's ShockDrawer builds the shock string.
import { apiPost } from './client';

export interface SimStartResponse {
  status: string;
  message: string;
}

export interface SimStopResponse {
  status: string;
}

export interface SimShockResponse {
  status: string;
  message: string;
}

// Plan 41.1-03 deviation (Rule 1): backend requires {seed: string} body.
// Plan 02 shipped a no-arg wrapper which always 422s against FastAPI.
export const simStart = (seed: string) =>
  apiPost<SimStartResponse>('/api/simulate/start', { seed });

export const simStop = () => apiPost<SimStopResponse>('/api/simulate/stop');

export const simShock = (shockText: string) =>
  apiPost<SimShockResponse>('/api/simulate/shock', { shock_text: shockText });
