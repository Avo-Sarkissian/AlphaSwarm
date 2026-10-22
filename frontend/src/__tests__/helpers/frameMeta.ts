// Test helper: a complete useFrameMeta() value with overrides.
import type { useFrameMeta } from '../../context/FrameMetaContext';

export type FrameMeta = ReturnType<typeof useFrameMeta>;

export const TEST_CYCLE_ID = '00000000-0000-4000-8000-000000000001';

const BASE = {
  mode: 'live',
  phase: 'round_2',
  cycleId: TEST_CYCLE_ID,
  numRounds: 3,
  roundNum: 2,
  edgesVersion: 0,
  schemaVersion: 1,
};

export function makeMeta(overrides: Partial<FrameMeta> = {}): FrameMeta {
  return { ...BASE, ...overrides } as FrameMeta;
}
