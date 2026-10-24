// @vitest-environment happy-dom
// The ReplayBar is the round scrubber: it renders from a replay frame alone
// (so it survives a reload), seeks any round and plays the cascade.
import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../api/client';
import { replaySeek, replayStop } from '../../api/replay';
import { ReplayBar } from '../../features/dashboard/ReplayBar';
import { requestCascadeAutoplay } from '../../lib/cascadeIntent';
import { renderAt, TEST_CYCLE_ID } from '../helpers/lifecycleFrames';

vi.mock('../../api/replay', () => ({
  listCycles: vi.fn(),
  replayStart: vi.fn(),
  replaySeek: vi.fn(),
  replayStop: vi.fn(),
}));

const seekMock = vi.mocked(replaySeek);
const stopMock = vi.mocked(replayStop);

beforeEach(() => {
  seekMock.mockReset();
  stopMock.mockReset();
  seekMock.mockResolvedValue({ status: 'ok', round_num: 1 });
});

afterEach(cleanup);

function roundButtons(): HTMLButtonElement[] {
  return screen.getAllByRole('button', { name: /^Show round \d$/ }) as HTMLButtonElement[];
}

describe('ReplayBar scrubber', () => {
  it('renders from a replay frame alone with one button per round', () => {
    renderAt(<ReplayBar />, 'replay');
    expect(screen.queryByText(new RegExp(TEST_CYCLE_ID))).not.toBeNull();
    expect(roundButtons().map((b) => b.textContent)).toEqual(['R1', 'R2', 'R3']);
    expect(roundButtons().map((b) => b.getAttribute('aria-pressed'))).toEqual(['false', 'true', 'false']);
    expect(screen.queryByRole('button', { name: 'Exit replay' })).not.toBeNull();
  });

  it('seeks the round a viewer picks', async () => {
    renderAt(<ReplayBar />, 'replay');
    fireEvent.click(screen.getByRole('button', { name: 'Show round 1' }));
    await waitFor(() => expect(seekMock).toHaveBeenCalledWith(1));
  });

  it('rewinds and advances one round, disabled at the ends', async () => {
    renderAt(<ReplayBar />, 'replay', { numRounds: 2, roundNum: 2 });
    expect((screen.getByRole('button', { name: 'Next round' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Previous round' }));
    await waitFor(() => expect(seekMock).toHaveBeenCalledWith(1));
  });

  it('plays the cascade from Round 1', async () => {
    const { container } = renderAt(<ReplayBar />, 'replay');
    fireEvent.click(screen.getByRole('button', { name: 'Play cascade' }));
    await waitFor(() => expect(seekMock).toHaveBeenCalledWith(1));
    expect(screen.queryByRole('button', { name: 'Pause cascade' })).not.toBeNull();
    expect(container.querySelector('.replay-bar')?.getAttribute('data-cascade')).toBe('playing');
  });

  it('autoplays once when a replay was started for that purpose', async () => {
    requestCascadeAutoplay(TEST_CYCLE_ID);
    renderAt(<ReplayBar />, 'replay');
    await waitFor(() => expect(seekMock).toHaveBeenCalledWith(1));
  });

  it('exits through POST /api/replay/stop and shows a failure', async () => {
    stopMock.mockRejectedValue(
      new ApiError(409, { detail: { error: 'no_replay_active', message: 'No replay active' } }, '/api/replay/stop'),
    );
    renderAt(<ReplayBar />, 'replay');
    fireEvent.click(screen.getByRole('button', { name: 'Exit replay' }));
    expect((await screen.findByRole('alert')).textContent).toContain('No replay active');
    expect(stopMock).toHaveBeenCalledTimes(1);
  });
});
