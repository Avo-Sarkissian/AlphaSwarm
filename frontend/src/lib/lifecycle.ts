// Dashboard lifecycle derived from the frame (mode + phase), and the topbar
// run control it implies. Everything comes from the frame and the frame's
// post-run job status, never from local UI state, so a reload shows the same
// controls (docs/DECISIONS.md#adr-frontend-quant-terminal).
import type { FrameMode } from '../types';
import { seedProblem } from './seed';

export type Lifecycle = 'idle' | 'seeding' | 'live' | 'complete' | 'replay';

export function lifecycleOf(meta: { mode: FrameMode; phase: string }): Lifecycle {
  if (meta.mode === 'replay') return 'replay';
  if (meta.mode === 'idle') return 'idle';
  if (meta.phase === 'seeding' || meta.phase === 'initializing') return 'seeding';
  if (meta.phase === 'complete') return 'complete';
  return 'live';
}

/** The part of the frame's `jobs` this module reads. */
export interface JobsLike {
  advisory: { state: string };
  report: { state: string };
}

export type RunControlState =
  | { kind: 'hidden' }
  | { kind: 'stop' }
  | { kind: 'run'; disabled: boolean; label: string; title: string | null };

const JOB_BUSY_TITLE =
  'The orchestrator is busy with the post-run jobs. Run becomes available when they finish.';

export function runControlState(input: {
  lifecycle: Lifecycle;
  jobs: JobsLike | null;
  seed: string;
  pending: boolean;
}): RunControlState {
  const { lifecycle, jobs, seed, pending } = input;
  if (lifecycle === 'replay') return { kind: 'hidden' };
  if (lifecycle === 'seeding' || lifecycle === 'live') return { kind: 'stop' };
  // A new run would evict the orchestrator mid-report, so Run waits for the
  // post-run jobs (docs/DECISIONS.md#adr-frontend-quant-terminal).
  if (jobs?.report.state === 'running') {
    return { kind: 'run', disabled: true, label: 'Report generating…', title: JOB_BUSY_TITLE };
  }
  if (jobs?.advisory.state === 'running') {
    return { kind: 'run', disabled: true, label: 'Advisory generating…', title: JOB_BUSY_TITLE };
  }
  if (pending) return { kind: 'run', disabled: true, label: 'Starting…', title: null };
  const problem = seedProblem(seed);
  return { kind: 'run', disabled: problem !== null, label: 'Run', title: problem };
}
