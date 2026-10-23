// @vitest-environment happy-dom
// The advisory view takes the round count from the frame and never names a
// fixed round, so a 2-round run does not read "3 rounds" or "post-R3".
import { cleanup, fireEvent, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AdvisoryV2 } from '../../components/v2';
import { renderAt } from '../helpers/lifecycleFrames';

beforeEach(() => {
  // Every request stays pending, so the advisory for the finished cycle is still generating.
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => undefined)));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('AdvisoryV2 rounds', () => {
  it('describes the swarm layer with the run round count', () => {
    renderAt(<AdvisoryV2 onClose={vi.fn()} />, 'complete', { numRounds: 2, roundNum: 2 });
    fireEvent.click(screen.getByRole('button', { name: 'Isolation' }));
    expect(screen.queryByText('100 agents · 2 rounds · real market data')).not.toBeNull();
  });

  it('waits for the advisory without naming a round', () => {
    renderAt(<AdvisoryV2 onClose={vi.fn()} />, 'complete', { numRounds: 2, roundNum: 2 });
    const card = screen.getByText(/Generating advisory/).closest('.advisory-card');
    expect(card?.textContent).toMatch(/post-run narrative generation/);
    expect(card?.textContent).not.toMatch(/\bR\d\b/);
  });
});
