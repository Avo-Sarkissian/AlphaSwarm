// Header label for the backend SimulationPhase string. The round comes from
// the frame (useRound), never from parsing the phase string, so replay and
// 2-round runs label correctly (docs/DECISIONS.md#adr-num-rounds).

export function phaseLabelFor(phase: string, round: number | null, numRounds: number): string {
  if (phase === 'complete') return 'COMPLETE';
  if (phase === 'finalizing') return 'FINALIZING';
  if (phase === 'idle') return 'IDLE';
  if (phase === 'seeding' || phase === 'initializing') return 'SEEDING';
  if (phase === 'replay') return round === null ? 'REPLAY' : `REPLAY · R${round}/${numRounds}`;
  const match = /^round_(\d+)$/.exec(phase);
  if (match) return `ROUND ${round ?? Number(match[1])}/${numRounds}`;
  return phase.toUpperCase();
}
