// The one-line note the graph shows when it has no citations to draw
// (docs/DECISIONS.md#adr-hero-graph).
export interface CaptionInput {
  agentCount: number;
  edgeCount: number;
  /** Round the edges belong to; null when no round has edges yet. */
  edgesRound: number | null;
  /** Round on screen; null or 0 before the first round. */
  roundNum: number | null;
  loading: boolean;
}

export function graphCaption(input: CaptionInput): string | null {
  if (input.agentCount === 0 || input.edgeCount > 0) return null;
  const round = input.roundNum ?? 0;
  if (round <= 1) return 'Round 1: agents decide independently. Peer influence starts in round 2.';
  if (input.edgesRound === null) return `Waiting for round ${round}'s citations…`;
  if (input.loading) return `Loading round ${input.edgesRound} citations…`;
  return `No citations in round ${input.edgesRound}.`;
}
