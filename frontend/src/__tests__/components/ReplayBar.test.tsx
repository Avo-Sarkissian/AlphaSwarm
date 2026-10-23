// @vitest-environment happy-dom
// The ReplayBar renders from a replay frame alone, so it is there after a reload.
import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../api/client';
import { replayAdvance, replayStop } from '../../api/replay';
import { ReplayBar } from '../../features/dashboard/ReplayBar';
import { renderAt, TEST_CYCLE_ID } from '../helpers/lifecycleFrames';

vi.mock('../../api/replay', () => ({
  listCycles: vi.fn(),
  replayStart: vi.fn(),
  replayAdvance: vi.fn(),
  replayStop: vi.fn(),
}));

const replayStopMock = vi.mocked(replayStop);
const replayAdvanceMock = vi.mocked(replayAdvance);

beforeEach(() => {
  replayStopMock.mockReset();
  replayAdvanceMock.mockReset();
});

afterEach(cleanup);

function ticks(): string[] {
  return Array.from(document.querySelectorAll('.replay-ticks span')).map((s) => s.textContent ?? '');
}

describe('ReplayBar', () => {
  it('renders from a replay frame alone, as after a page reload', () => {
    renderAt(<ReplayBar />, 'replay');
    expect(screen.queryByText(new RegExp(TEST_CYCLE_ID))).not.toBeNull();
    expect(screen.queryByRole('button', { name: 'Exit replay' })).not.toBeNull();
    expect(ticks()).toEqual(['SEED', 'R1', 'R2', 'R3']);
  });

  it('exit calls POST /api/replay/stop', async () => {
    replayStopMock.mockResolvedValue({ status: 'stopped' });
    renderAt(<ReplayBar />, 'replay');
    fireEvent.click(screen.getByRole('button', { name: 'Exit replay' }));
    await waitFor(() => expect(replayStopMock).toHaveBeenCalledTimes(1));
  });

  it('shows the error when exit fails and lets the user retry', async () => {
    replayStopMock.mockRejectedValue(
      new ApiError(409, { detail: { error: 'no_replay_active', message: 'No replay active' } }, '/api/replay/stop'),
    );
    renderAt(<ReplayBar />, 'replay');
    fireEvent.click(screen.getByRole('button', { name: 'Exit replay' }));
    expect((await screen.findByRole('alert')).textContent).toContain('No replay active');
    expect((screen.getByRole('button', { name: 'Exit replay' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('stops Forward at the final round of a 2-round cycle', () => {
    renderAt(<ReplayBar />, 'replay', { numRounds: 2, roundNum: 2 });
    expect(ticks()).toEqual(['SEED', 'R1', 'R2']);
    expect((screen.getByRole('button', { name: 'Next round' }) as HTMLButtonElement).disabled).toBe(true);
  });
});
