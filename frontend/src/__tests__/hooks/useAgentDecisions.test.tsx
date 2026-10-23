// @vitest-environment happy-dom
import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useAgentDecisions } from '../../hooks/useAgentDecisions';
import { requestedUrls, stubFetch } from '../helpers/fetchStub';

const CYCLE = '00000000-0000-4000-8000-0000000000a1';
const ROWS = [
  { round_num: 1, signal: 'buy', confidence: 0.8, sentiment: 0.4, rationale: 'ZZZT deal looks accretive', cited_agents: [] },
  { round_num: 2, signal: 'sell', confidence: 0.6, sentiment: -0.2, rationale: 'Financing risk on QQQX', cited_agents: [] },
];

afterEach(() => vi.unstubAllGlobals());

describe('useAgentDecisions', () => {
  it('refetches when the refresh key changes and keeps the rows meanwhile', async () => {
    const mock = stubFetch([
      { path: '/api/agents/quants_01/decisions', body: { agent_id: 'quants_01', cycle_id: CYCLE, decisions: ROWS } },
    ]);
    const { result, rerender } = renderHook(({ k }: { k: string }) => useAgentDecisions('quants_01', CYCLE, k), {
      initialProps: { k: '1:round_1' },
    });
    await waitFor(() => expect(result.current.decisions).toHaveLength(2));

    rerender({ k: '2:round_2' });

    expect(result.current.decisions).toHaveLength(2);
    await waitFor(() => expect(mock).toHaveBeenCalledTimes(2));
    expect(requestedUrls(mock)[0]).toBe(`/api/agents/quants_01/decisions?cycle_id=${CYCLE}`);
  });

  it('does nothing without a cycle', () => {
    const mock = stubFetch([]);
    const { result } = renderHook(() => useAgentDecisions('quants_01', null, 'x'));
    expect(mock).not.toHaveBeenCalled();
    expect(result.current).toEqual({ decisions: [], error: null, loading: false });
  });
});
