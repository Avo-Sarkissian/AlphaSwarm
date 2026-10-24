// @vitest-environment happy-dom
import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../api/client';
import { replayStart } from '../../api/replay';
import { R1_NOTE, RoundStory } from '../../features/dashboard/RoundStory';
import { takeCascadeAutoplay } from '../../lib/cascadeIntent';
import { renderAt, TEST_CYCLE_ID } from '../helpers/lifecycleFrames';

vi.mock('../../api/replay', () => ({
  listCycles: vi.fn(),
  replayStart: vi.fn(),
  replaySeek: vi.fn(),
  replayStop: vi.fn(),
}));

const startMock = vi.mocked(replayStart);

// Braces matter: a function returned from beforeEach runs as teardown.
beforeEach(() => {
  startMock.mockReset();
});
afterEach(cleanup);

describe('RoundStory', () => {
  it('explains Round 1 in a replay', () => {
    renderAt(<RoundStory />, 'replay', { roundNum: 1 });
    expect(screen.getByRole('note').textContent).toBe(R1_NOTE);
  });

  it('explains Round 1 during a live first round', () => {
    renderAt(<RoundStory />, 'live', { phase: 'round_1', roundNum: 1 });
    expect(screen.getByRole('note').textContent).toBe(R1_NOTE);
  });

  it('says nothing from Round 2 on', () => {
    const { container } = renderAt(<RoundStory />, 'replay', { roundNum: 2 });
    expect(container.textContent).toBe('');
  });

  it('replays a finished live run as a cascade', async () => {
    startMock.mockResolvedValue({ status: 'ok', cycle_id: TEST_CYCLE_ID, round_num: 1 });
    renderAt(<RoundStory />, 'complete');
    fireEvent.click(screen.getByRole('button', { name: 'Play cascade' }));
    await waitFor(() => expect(startMock).toHaveBeenCalledWith(TEST_CYCLE_ID));
    expect(takeCascadeAutoplay(TEST_CYCLE_ID)).toBe(true);
  });

  it('shows a failed start and drops the autoplay request', async () => {
    startMock.mockRejectedValue(
      new ApiError(
        409,
        { detail: { error: 'simulation_in_progress', message: 'A simulation is running' } },
        '/api/replay/start',
      ),
    );
    renderAt(<RoundStory />, 'complete');
    fireEvent.click(screen.getByRole('button', { name: 'Play cascade' }));
    expect((await screen.findByRole('alert')).textContent).toContain('A simulation is running');
    expect(takeCascadeAutoplay(TEST_CYCLE_ID)).toBe(false);
  });
});
