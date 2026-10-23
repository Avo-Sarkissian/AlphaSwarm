// @vitest-environment happy-dom
import { cleanup, fireEvent, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { RunControls, type RunControlsProps } from '../../app/RunControls';
import type { JobStatusView, JobsView } from '../../types';
import { renderAt } from '../helpers/lifecycleFrames';

const SEED = 'ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash.';

function jobs(report: JobStatusView['state'], advisory: JobStatusView['state'] = 'idle'): JobsView {
  return {
    advisory: { state: advisory, cycleId: null, errorCode: null },
    report: { state: report, cycleId: null, errorCode: null },
  };
}

function controls(overrides: Partial<RunControlsProps> = {}) {
  const props: RunControlsProps = { seed: SEED, pending: false, onRun: vi.fn(), onStop: vi.fn(), ...overrides };
  return { props, el: <RunControls {...props} /> };
}

afterEach(cleanup);

describe('RunControls', () => {
  it('idle: Run is disabled, with the reason, until the seed has 10 characters', () => {
    renderAt(controls({ seed: 'short' }).el, 'idle', { jobs: jobs('idle') });
    const run = screen.getByRole('button', { name: /run/i }) as HTMLButtonElement;
    expect(run.disabled).toBe(true);
    expect(run.title).toBe('The seed needs at least 10 characters.');
  });

  it('idle: Run calls onRun', () => {
    const { props, el } = controls();
    renderAt(el, 'idle', { jobs: jobs('idle') });
    fireEvent.click(screen.getByRole('button', { name: /run/i }));
    expect(props.onRun).toHaveBeenCalledTimes(1);
  });

  it.each(['seeding', 'live'] as const)('%s: offers Stop only', (state) => {
    const { props, el } = controls();
    renderAt(el, state, { jobs: jobs('idle') });
    expect(screen.queryByRole('button', { name: /run/i })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /stop/i }));
    expect(props.onStop).toHaveBeenCalledTimes(1);
  });

  it('replay: renders neither Run nor Stop', () => {
    renderAt(controls().el, 'replay', { jobs: jobs('idle') });
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('complete: Run waits while the report holds the orchestrator', () => {
    renderAt(controls().el, 'complete', { jobs: jobs('running') });
    const run = screen.getByRole('button', { name: /report generating/i }) as HTMLButtonElement;
    expect(run.disabled).toBe(true);
  });

  it('shows Starting… while a start is pending', () => {
    renderAt(controls({ pending: true }).el, 'idle', { jobs: jobs('idle') });
    expect((screen.getByRole('button', { name: /starting/i }) as HTMLButtonElement).disabled).toBe(true);
  });
});
