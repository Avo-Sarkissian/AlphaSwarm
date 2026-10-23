// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { adaptSnapshot } from '../../adapter/frame';
import { RunErrorBanner } from '../../components/RunErrorBanner';
import { ConnectionProvider } from '../../context/ConnectionContext';
import type { StateFrame } from '../../types';
import snapshot from '../fixtures/ws_snapshot.json';

type RunErrorView = NonNullable<StateFrame['lastError']>;

const base = adaptSnapshot(snapshot);
const ROUND_FAILED = {
  code: 'round_failed',
  message: 'Round 2 failed: 61 of 100 agents returned no decision.',
  roundNum: 2,
  ts: 1765432100,
} as RunErrorView;

function banner(lastError: RunErrorView | null) {
  const frame: StateFrame = { ...base, lastError };
  return (
    <ConnectionProvider connected status="open" lastFrame={frame}>
      <RunErrorBanner />
    </ConnectionProvider>
  );
}

afterEach(cleanup);

describe('RunErrorBanner', () => {
  it('renders nothing without an error', () => {
    render(banner(null));
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('shows the failure with its round, message and code', () => {
    render(banner(ROUND_FAILED));
    const text = screen.getByRole('alert').textContent ?? '';
    expect(text).toContain('RUN FAILED · ROUND 2');
    expect(text).toContain('61 of 100 agents returned no decision');
    expect(text).toContain('round_failed');
  });

  it('can be dismissed and comes back for a new failure', () => {
    const { rerender } = render(banner(ROUND_FAILED));
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByRole('alert')).toBeNull();
    rerender(banner({ ...ROUND_FAILED, ts: ROUND_FAILED.ts + 60 }));
    expect(screen.queryByRole('alert')).not.toBeNull();
  });
});
