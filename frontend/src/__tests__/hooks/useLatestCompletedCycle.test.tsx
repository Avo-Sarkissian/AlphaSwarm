// @vitest-environment happy-dom
import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CycleItem } from '../../api/replay';
import { useLatestCompletedCycle } from '../../hooks/useLatestCompletedCycle';
import { requestedUrls, stubFetch } from '../helpers/fetchStub';

const NEWEST: CycleItem = {
  cycle_id: 'newest',
  created_at: '2026-10-03T03:00:00.000000000+00:00',
  seed_rumor: 'ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash.',
  round_count: 3,
  status: 'complete',
  final_buy: 60,
  final_sell: 25,
  final_hold: 10,
  total_flips: 7,
  total_seconds: 754.3,
  agent_count: 100,
};

afterEach(() => vi.unstubAllGlobals());

describe('useLatestCompletedCycle', () => {
  it('asks for the newest row only and returns its cycle id', async () => {
    const mock = stubFetch([
      { path: '/api/replay/cycles', body: { cycles: [NEWEST], next_before: NEWEST.created_at } },
    ]);
    const { result, unmount } = renderHook(() => useLatestCompletedCycle());
    await waitFor(() => expect(result.current.cycleId).toBe('newest'));
    expect(result.current.loading).toBe(false);
    expect(requestedUrls(mock)).toEqual(['/api/replay/cycles?limit=1']);
    unmount();
  });
});
