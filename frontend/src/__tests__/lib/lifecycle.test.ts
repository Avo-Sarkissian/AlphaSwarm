import { describe, expect, it } from 'vitest';
import { lifecycleOf, runControlState, type JobsLike } from '../../lib/lifecycle';

const SEED = 'ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash.';
const IDLE_JOBS: JobsLike = { advisory: { state: 'idle' }, report: { state: 'idle' } };

describe('lifecycleOf', () => {
  it.each([
    ['idle', 'idle', 'idle'],
    ['live', 'seeding', 'seeding'],
    ['live', 'initializing', 'seeding'],
    ['live', 'round_1', 'live'],
    ['live', 'finalizing', 'live'],
    ['live', 'complete', 'complete'],
    ['replay', 'replay', 'replay'],
  ] as const)('mode %s + phase %s → %s', (mode, phase, expected) => {
    expect(lifecycleOf({ mode, phase })).toBe(expected);
  });
});

describe('runControlState', () => {
  const base = { jobs: IDLE_JOBS, seed: SEED, pending: false };

  it('hides Run and Stop during replay', () => {
    expect(runControlState({ ...base, lifecycle: 'replay' })).toEqual({ kind: 'hidden' });
  });

  it('offers Stop while seeding and while rounds run', () => {
    expect(runControlState({ ...base, lifecycle: 'seeding' })).toEqual({ kind: 'stop' });
    expect(runControlState({ ...base, lifecycle: 'live' })).toEqual({ kind: 'stop' });
  });

  it('offers an enabled Run when idle or complete', () => {
    const run = { kind: 'run', disabled: false, label: 'Run', title: null };
    expect(runControlState({ ...base, lifecycle: 'idle' })).toEqual(run);
    expect(runControlState({ ...base, lifecycle: 'complete' })).toEqual(run);
  });

  it('disables Run with the reason for a seed the backend would reject', () => {
    const state = runControlState({ ...base, lifecycle: 'idle', seed: 'short' });
    expect(state).toEqual({
      kind: 'run',
      disabled: true,
      label: 'Run',
      title: 'The seed needs at least 10 characters.',
    });
  });

  it('disables Run while the report holds the orchestrator', () => {
    const jobs: JobsLike = { advisory: { state: 'idle' }, report: { state: 'running' } };
    const state = runControlState({ ...base, lifecycle: 'complete', jobs });
    expect(state).toMatchObject({ kind: 'run', disabled: true, label: 'Report generating…' });
  });

  it('names the advisory job when it is the one running', () => {
    const jobs: JobsLike = { advisory: { state: 'running' }, report: { state: 'idle' } };
    expect(runControlState({ ...base, lifecycle: 'complete', jobs })).toMatchObject({
      disabled: true,
      label: 'Advisory generating…',
    });
  });

  it('shows Starting… while a start is pending', () => {
    expect(runControlState({ ...base, lifecycle: 'idle', pending: true })).toEqual({
      kind: 'run',
      disabled: true,
      label: 'Starting…',
      title: null,
    });
  });

  it('treats missing job status as idle', () => {
    expect(runControlState({ ...base, lifecycle: 'idle', jobs: null })).toMatchObject({ disabled: false });
  });
});
