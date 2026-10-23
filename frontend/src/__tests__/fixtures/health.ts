/** Local mode, worker alias missing: a fictional GET /api/health body. */
export const HEALTH_ALIAS_MISSING = {
  status: 'degraded',
  simulation_phase: 'idle',
  memory_percent: 61.2,
  is_simulation_running: false,
  inference_mode: 'local',
  spent_usd: null,
  version: '0.6.0',
  components: {
    neo4j: { ok: true, required: true, detail: null, fix: null },
    ollama: { ok: true, required: true, detail: null, fix: null },
    aliases: {
      ok: false,
      required: true,
      detail: 'missing: alphaswarm-worker',
      fix: 'ollama create alphaswarm-worker -f modelfiles/Modelfile.worker',
      missing: ['alphaswarm-worker'],
    },
  },
} as const;
