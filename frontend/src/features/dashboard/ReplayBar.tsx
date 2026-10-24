// Replay bar: shown whenever the frame's mode is 'replay'; steps or exits the replay.
import { useState } from 'react';
import { Icon } from '../../components/Icon';
import { InlineError } from '../../components/InlineError';
import { replayAdvance, replayStop } from '../../api/replay';
import { useFrameMeta } from '../../context/FrameMetaContext';
import { useRounds } from '../../hooks/useRounds';
import { formatApiError } from '../../lib/apiError';

// ─── ReplayBar ───────────────────────────────────────────────────────────
// Driven entirely by the frame (mode === 'replay' decides whether the app
// mounts it), so it survives a page reload: the backend replay is the source
// of truth, not local UI state. Forward and exit only; there is no rewind
// endpoint (docs/DECISIONS.md#kr-41-1-06).
export function ReplayBar() {
  const { cycleId } = useFrameMeta();
  const { rounds, numRounds, currentRound } = useRounds();
  const round = currentRound ?? 1;
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function run(action: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true);
    setErr(null);
    try {
      await action();
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="replay-bar">
      <div className="label u-accent">
        <Icon name="replay" size={11} /> REPLAY · {cycleId ?? ''}
      </div>
      <div className="replay-track">
        <div className="replay-fill" style={{ width: `${(round / numRounds) * 100}%` }} />
        <div className="replay-ticks">
          {['SEED', ...rounds.map((r) => `R${r}`)].map((t, i) => (
            <span key={t} style={{ color: i <= round ? 'var(--accent)' : 'var(--text-3)' }}>
              {t}
            </span>
          ))}
        </div>
      </div>
      <button
        className="btn ghost"
        aria-label="Next round"
        onClick={() => run(replayAdvance)}
        disabled={busy || round >= numRounds}
      >
        <Icon name="forward" />
      </button>
      <button className="btn" onClick={() => run(replayStop)} disabled={busy}>
        Exit replay
      </button>
      <InlineError error={err} onDismiss={() => setErr(null)} />
    </div>
  );
}
