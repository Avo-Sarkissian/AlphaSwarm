// Canonical routes: POST /api/simulate/{start,stop,shock}.
// Shock body = {shock_text: string}. Plan 04's ShockDrawer builds the string.
import { apiPost } from './client';

export const simStart = () => apiPost<{ ok: boolean }>('/api/simulate/start');
export const simStop = () => apiPost<{ ok: boolean }>('/api/simulate/stop');
export const simShock = (shockText: string) =>
  apiPost<{ ok: boolean }>('/api/simulate/shock', { shock_text: shockText });
