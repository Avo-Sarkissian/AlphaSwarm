// Which cycle a report or advisory view opens when the caller did not pick
// one: the cycle on screen when it is finished (a completed live run or a
// replay), otherwise the newest completed cycle. A running cycle has no report.
import type { useFrameMeta } from '../context/FrameMetaContext';

type FrameMeta = ReturnType<typeof useFrameMeta>;

export function defaultCycleId(
  meta: Pick<FrameMeta, 'mode' | 'phase' | 'cycleId'>,
  latestCompleted: string | null,
): string | null {
  const onScreenFinished =
    meta.mode === 'replay' || (meta.mode === 'live' && meta.phase === 'complete');
  if (onScreenFinished && meta.cycleId) return meta.cycleId;
  return latestCompleted;
}
