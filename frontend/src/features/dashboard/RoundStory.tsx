// Canvas overlay for the round story: Round 1 has no peer influence yet, and a
// finished live run can be replayed as a cascade
// (docs/DECISIONS.md#adr-replaystore-separate).
import { useState } from 'react';
import { replayStart } from '../../api/replay';
import { InlineError } from '../../components/InlineError';
import { useFrameMeta } from '../../context/FrameMetaContext';
import { formatApiError } from '../../lib/apiError';
import { requestCascadeAutoplay, takeCascadeAutoplay } from '../../lib/cascadeIntent';

export const R1_NOTE = 'Round 1: agents decide independently. Peer influence starts in Round 2.';

export function RoundStory() {
  const { mode, phase, cycleId, roundNum } = useFrameMeta();
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const showNote = (mode === 'replay' && roundNum === 1) || (mode === 'live' && phase === 'round_1');
  const canReplay = mode === 'live' && phase === 'complete' && cycleId !== null;

  async function playCascade() {
    if (cycleId === null || starting) return;
    setStarting(true);
    setError(null);
    requestCascadeAutoplay(cycleId);
    try {
      await replayStart(cycleId);
    } catch (e) {
      takeCascadeAutoplay(cycleId);
      setError(formatApiError(e));
    } finally {
      setStarting(false);
    }
  }

  if (!showNote && !canReplay && error === null) return null;
  return (
    <div className="round-story">
      {showNote ? (
        <p className="round-story-note" role="note">
          {R1_NOTE}
        </p>
      ) : null}
      {canReplay ? (
        <button type="button" className="btn" onClick={playCascade} disabled={starting}>
          Play cascade
        </button>
      ) : null}
      <InlineError error={error} onDismiss={() => setError(null)} />
    </div>
  );
}
