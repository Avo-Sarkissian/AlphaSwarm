// @vitest-environment happy-dom
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CycleItem } from '../../api/replay';
import { useCyclePages } from '../../hooks/useCyclePages';
import { jsonResponse, stubFetch } from '../helpers/fetchStub';

const row = (cycle_id: string, created_at: string): CycleItem => ({
  cycle_id,
  created_at,
  seed_rumor: 'ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash.',
  round_count: 3,
  status: 'complete',
  final_buy: 60,
  final_sell: 25,
  final_hold: 10,
  total_flips: 7,
  total_seconds: 754.3,
  agent_count: 100,
});
const A = row('a', '2026-10-03T03:00:00.000000000+00:00');
const B = row('b', '2026-10-02T03:00:00.000000000+00:00');
const C = row('c', '2026-10-01T03:00:00.000000000+00:00');

afterEach(() => vi.unstubAllGlobals());

describe('useCyclePages', () => {
  it('loads pages, drops the repeated boundary row and stops at the last page', async () => {
    const pages: Record<string, unknown> = {
      '/api/replay/cycles?limit=2': { cycles: [A, B], next_before: B.created_at },
      '/api/replay/cycles?limit=2&before=2026-10-02T03%3A00%3A00.000000000%2B00%3A00': { cycles: [B, C], next_before: null },
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const body = pages[String(input)];
        return body ? jsonResponse(body) : jsonResponse({ detail: { error: 'not_found', message: String(input) } }, 404);
      }),
    );
    const { result } = renderHook(() => useCyclePages(2));
    await waitFor(() => expect(result.current.cycles?.map((c) => c.cycle_id)).toEqual(['a', 'b']));
    expect(result.current.hasMore).toBe(true);

    act(() => result.current.loadMore());

    await waitFor(() => expect(result.current.cycles?.map((c) => c.cycle_id)).toEqual(['a', 'b', 'c']));
    expect(result.current.hasMore).toBe(false);
  });

  it('reports a readable error and an empty list', async () => {
    stubFetch([
      {
        path: '/api/replay/cycles',
        status: 503,
        body: { detail: { error: 'graph_unavailable', message: 'Neo4j is not configured for this server' } },
      },
    ]);
    const { result } = renderHook(() => useCyclePages());
    await waitFor(() => expect(result.current.error).toContain('Neo4j is not configured'));
    expect(result.current.cycles).toEqual([]);
  });
});
