// Replay bar: shown whenever the frame's mode is 'replay'. Round buttons,
// rewind and forward seek the replay; Play cascade steps from Round 1 to the
// last round (docs/DECISIONS.md#adr-replaystore-separate). Driven entirely by
// the frame, so it survives a page reload: the backend replay is the source of
// truth, not local UI state.
import { useEffect, useState } from 'react';
import { replaySeek, replayStop } from '../../api/replay';
import { Icon } from '../../components/Icon';
import { InlineError } from '../../components/InlineError';
import { useFrameMeta } from '../../context/FrameMetaContext';
import { demoLock } from '../../data-source';
import { useCascadePlayer } from '../../hooks/useCascadePlayer';
import { useRounds } from '../../hooks/useRounds';
import { formatApiError } from '../../lib/apiError';
import { takeCascadeAutoplay } from '../../lib/cascadeIntent';

export function ReplayBar() {
  const { cycleId } = useFrameMeta();
  const { rounds, numRounds, currentRound } = useRounds();
  const round = currentRound ?? 1;
  const cascade = useCascadePlayer({ roundNum: currentRound, numRounds, seek: replaySeek });
  const { play } = cascade;
  const [exitError, setExitError] = useState<string | null>(null);
  const [exiting, setExiting] = useState(false);
  const lock = demoLock();

  useEffect(() => {
    if (takeCascadeAutoplay(cycleId)) play();
  }, [cycleId, play]);

  async function exit() {
    if (exiting) return;
    cascade.stop();
    setExiting(true);
    setExitError(null);
    try {
      await replayStop();
    } catch (e) {
      setExitError(formatApiError(e));
    } finally {
      setExiting(false);
    }
  }

  return (
    <div className="replay-bar" data-cascade={cascade.playing ? 'playing' : 'idle'}>
      <div className="label u-accent">
        <Icon name="replay" size={11} /> REPLAY · {cycleId ?? ''}
      </div>
      <button
        type="button"
        className="btn ghost"
        aria-label="Previous round"
        onClick={() => cascade.seek(round - 1)}
        disabled={round <= 1}
      >
        <Icon name="rewind" />
      </button>
      <div className="replay-track">
        <div className="replay-fill" style={{ width: `${(round / numRounds) * 100}%` }} />
        <div className="replay-ticks">
          <span className="replay-tick is-reached">SEED</span>
          {rounds.map((r) => (
            <button
              key={r}
              type="button"
              className={`replay-tick${r <= round ? ' is-reached' : ''}`}
              aria-label={`Show round ${r}`}
              aria-pressed={r === round}
              onClick={() => cascade.seek(r)}
            >
              R{r}
            </button>
          ))}
        </div>
      </div>
      <button
        type="button"
        className="btn ghost"
        aria-label="Next round"
        onClick={() => cascade.seek(round + 1)}
        disabled={round >= numRounds}
      >
        <Icon name="forward" />
      </button>
      <button type="button" className="btn" onClick={cascade.playing ? cascade.stop : play}>
        {cascade.playing ? 'Pause cascade' : 'Play cascade'}
      </button>
      {lock.locked ? null : (
        <button type="button" className="btn" onClick={exit} disabled={exiting}>
          Exit replay
        </button>
      )}
      <InlineError
        error={exitError ?? cascade.error}
        onDismiss={() => {
          setExitError(null);
          cascade.dismissError();
        }}
      />
    </div>
  );
}
