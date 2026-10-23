// @vitest-environment happy-dom
// The shock drawer names the round a shock lands before from the frame's phase
// and num_rounds, so a 2-round run never shows a round 3.
import { cleanup } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ShockDrawer } from '../../components/modals';
import { renderAt } from '../helpers/lifecycleFrames';

afterEach(cleanup);

function drawerText(): string {
  return document.querySelector('.shock-drawer')?.textContent ?? '';
}

describe('ShockDrawer round label', () => {
  it('names round 2 during round 1 of a 2-round run (vitest with num_rounds=2)', () => {
    renderAt(<ShockDrawer onClose={vi.fn()} />, 'live', {
      numRounds: 2,
      phase: 'round_1',
      roundNum: 1,
      shockWindowOpen: true,
    });
    expect(drawerText()).toMatch(/lands before round 2/i);
    expect(drawerText()).not.toMatch(/round 3|rounds 2 & 3/i);
  });

  it('says the window is closed in the last round of a 2-round run', () => {
    renderAt(<ShockDrawer onClose={vi.fn()} />, 'live', {
      numRounds: 2,
      phase: 'round_2',
      roundNum: 2,
      shockWindowOpen: false,
    });
    expect(drawerText()).toMatch(/window closed/i);
    expect(drawerText()).not.toMatch(/round 3|rounds 2 & 3/i);
  });

  it('names round 3 during round 2 of a 3-round run', () => {
    renderAt(<ShockDrawer onClose={vi.fn()} />, 'live', { shockWindowOpen: true });
    expect(drawerText()).toMatch(/lands before round 3/i);
  });

  it("names round 2 while seeding, though round_num still holds the previous run's last round", () => {
    renderAt(<ShockDrawer onClose={vi.fn()} />, 'seeding', { roundNum: 3, shockWindowOpen: true });
    expect(drawerText()).toMatch(/lands before round 2/i);
  });

  it('says the window is closed while idle', () => {
    renderAt(<ShockDrawer onClose={vi.fn()} />, 'idle', { shockWindowOpen: false });
    expect(drawerText()).toMatch(/window closed/i);
  });
});
