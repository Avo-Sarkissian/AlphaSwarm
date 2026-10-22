// Which round's influence edges the dashboard can show for a frame.
//
// INFLUENCED_BY edges for round r are written after round r ends (round 1 has
// no citations, so it never gets edges), and edges_version counts those writes
// for the current cycle: it equals r - 1 once round r's edges exist. Live
// frames therefore show round edgesVersion + 1, replay frames the replayed
// round, and idle frames nothing (docs/DECISIONS.md#adr-neo4j-schema).
import type { useFrameMeta } from '../context/FrameMetaContext';

type FrameMeta = ReturnType<typeof useFrameMeta>;

export interface EdgesTarget {
  cycleId: string;
  round: number;
}

export function edgesTarget(meta: FrameMeta): EdgesTarget | null {
  if (!meta.cycleId) return null;
  const clamp = (round: number): number =>
    meta.numRounds >= 1 ? Math.min(round, meta.numRounds) : round;
  if (meta.mode === 'live') {
    if (meta.edgesVersion < 1) return null;
    return { cycleId: meta.cycleId, round: clamp(meta.edgesVersion + 1) };
  }
  if (meta.mode === 'replay') {
    if (typeof meta.roundNum !== 'number' || meta.roundNum < 2) return null;
    return { cycleId: meta.cycleId, round: clamp(meta.roundNum) };
  }
  return null;
}
