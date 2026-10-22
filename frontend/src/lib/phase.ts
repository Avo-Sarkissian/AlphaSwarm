// Backend SimulationPhase string -> header round and label.
// 'finalizing' runs after the last round (narratives, metrics)
// and keeps the last round on screen. The round count is still the
// hard-coded 3 the header has always used; useRounds() replaces it later.

export function roundFromPhase(phase: string): number {
  if (phase === 'complete' || phase === 'finalizing') return 3;
  const m = phase.match(/^round[_-]?(\d+)$/i);
  if (m) return Number(m[1]);
  const n = Number(phase);
  if (Number.isFinite(n) && phase.trim() !== '') return n;
  return 1;
}

export function phaseLabelFor(phase: string, round: number): string {
  if (phase === 'complete') return 'COMPLETE';
  if (phase === 'finalizing') return 'FINALIZING';
  if (phase === 'idle') return 'IDLE';
  if (phase === 'initializing') return 'SEEDING';
  if (phase.startsWith('round')) return phase.toUpperCase();
  return `ROUND ${round}/3`;
}
