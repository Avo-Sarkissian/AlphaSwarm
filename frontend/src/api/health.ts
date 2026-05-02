// Health probes (NR-7).
//
// GET /api/health/ollama returns 200 always; the backend never throws — a
// disconnected Ollama is encoded as { connected: false, models_loaded: [] }.
// useOllamaHealth (../hooks/useOllamaHealth) consumes this so the polling
// loop does not need exception handling at every tick.
import { apiFetch } from './client';

export interface OllamaHealth {
  connected: boolean;
  models_loaded: string[];
}

export const getOllamaHealth = (): Promise<OllamaHealth> =>
  apiFetch<OllamaHealth>('/api/health/ollama');
