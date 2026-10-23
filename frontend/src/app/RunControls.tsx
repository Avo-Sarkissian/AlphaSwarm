// Topbar Run/Stop control. Which one shows, and whether Run is enabled, comes
// from the frame (lifecycle, post-run jobs) and the seed; see lib/lifecycle.ts.
import { Icon } from '../components/Icon';
import { useConnection } from '../context/ConnectionContext';
import { useFrameMeta } from '../context/FrameMetaContext';
import { lifecycleOf, runControlState } from '../lib/lifecycle';

export interface RunControlsProps {
  seed: string;
  pending: boolean;
  onRun: () => void;
  onStop: () => void;
}

export function RunControls({ seed, pending, onRun, onStop }: RunControlsProps) {
  const meta = useFrameMeta();
  const { lastFrame } = useConnection();
  const state = runControlState({
    lifecycle: lifecycleOf(meta),
    jobs: lastFrame?.jobs ?? null,
    seed,
    pending,
  });
  if (state.kind === 'hidden') return null;
  if (state.kind === 'stop') {
    return (
      <button type="button" className="btn danger" onClick={onStop}>
        <Icon name="stop" /> Stop
      </button>
    );
  }
  return (
    <button
      type="button"
      className="btn primary"
      onClick={onRun}
      disabled={state.disabled}
      title={state.title ?? undefined}
    >
      <Icon name="play" /> {state.label}
    </button>
  );
}
