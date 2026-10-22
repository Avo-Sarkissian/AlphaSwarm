// Test helper: render a component on a frame in one of the dashboard's
// lifecycle states. Built on renderWithFrame, whose `frame`
// overrides reach useFrameMeta(), useConnection().lastFrame and every other
// frame-derived context.
import type { ReactElement } from 'react';
import type { StateFrame } from '../../types';
import { TEST_CYCLE_ID } from './frameMeta';
import { renderWithFrame } from './renderWithFrame';

export { TEST_CYCLE_ID };

export type LifecycleName = 'idle' | 'seeding' | 'live' | 'complete' | 'replay';

const BASE: Record<LifecycleName, Partial<StateFrame>> = {
  idle: { mode: 'idle', phase: 'idle', roundNum: 0, cycleId: null, edgesVersion: 0 },
  seeding: { mode: 'live', phase: 'seeding', roundNum: 0, cycleId: TEST_CYCLE_ID, edgesVersion: 0 },
  live: { mode: 'live', phase: 'round_2', roundNum: 2, cycleId: TEST_CYCLE_ID, edgesVersion: 0 },
  complete: { mode: 'live', phase: 'complete', roundNum: 3, cycleId: TEST_CYCLE_ID, edgesVersion: 2 },
  replay: { mode: 'replay', phase: 'replay', roundNum: 2, cycleId: TEST_CYCLE_ID, edgesVersion: 1 },
};

export function frameAt(
  state: LifecycleName,
  overrides: Partial<StateFrame> = {},
): Partial<StateFrame> {
  return { numRounds: 3, ...BASE[state], ...overrides };
}

export function renderAt(
  ui: ReactElement,
  state: LifecycleName,
  overrides: Partial<StateFrame> = {},
) {
  return renderWithFrame(ui, { frame: frameAt(state, overrides) });
}
