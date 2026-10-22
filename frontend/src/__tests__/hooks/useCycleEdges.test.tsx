// @vitest-environment happy-dom
// useCycleEdges: one module-level cache per (cycle, round, edges_version).
// The cache outlives each test, so every test uses its own cycle id.
import { cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchEdges, type Edge } from '../../api/edges';
import { useCycleEdges } from '../../hooks/useCycleEdges';
import { makeMeta, type FrameMeta } from '../helpers/frameMeta';

const h = vi.hoisted(() => ({ meta: null as unknown }));
vi.mock('../../context/FrameMetaContext', () => ({ useFrameMeta: () => h.meta }));
vi.mock('../../api/edges', () => ({ fetchEdges: vi.fn() }));

const fetchEdgesMock = vi.mocked(fetchEdges);

const edge = (source_id: string, target_id: string): Edge => ({ source_id, target_id, weight: 0.1 });

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function setMeta(overrides: Partial<FrameMeta>): void {
  h.meta = makeMeta(overrides);
}

beforeEach(() => {
  fetchEdgesMock.mockReset();
  setMeta({ edgesVersion: 1 });
});

afterEach(cleanup);

describe('useCycleEdges', () => {
  it('stays idle and never fetches without a target', () => {
    const { result } = renderHook(() => useCycleEdges(null, null));
    expect(result.current.status).toBe('idle');
    expect(result.current.edges).toEqual([]);
    expect(fetchEdgesMock).not.toHaveBeenCalled();
  });

  it('fetches once and indexes edges by direction (source cites target)', async () => {
    fetchEdgesMock.mockResolvedValue([
      edge('quants_01', 'sell_side_03'),
      edge('degens_02', 'sell_side_03'),
      edge('sell_side_03', 'macro_01'),
    ]);
    const { result } = renderHook(() => useCycleEdges('cyc-index', 2));
    expect(result.current.status).toBe('loading');
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(fetchEdgesMock).toHaveBeenCalledWith('cyc-index', 2);
    expect(result.current.inDegree.get('sell_side_03')).toBe(2);
    expect(result.current.citedBy.get('sell_side_03')).toEqual(['quants_01', 'degens_02']);
    expect(result.current.cites.get('sell_side_03')).toEqual(['macro_01']);
    expect(result.current.outDegree.get('quants_01')).toBe(1);
  });

  it('serves a second consumer from the module cache', async () => {
    fetchEdgesMock.mockResolvedValue([edge('quants_01', 'macro_01')]);
    const first = renderHook(() => useCycleEdges('cyc-cache', 2));
    await waitFor(() => expect(first.result.current.status).toBe('ready'));
    const second = renderHook(() => useCycleEdges('cyc-cache', 2));
    expect(second.result.current.status).toBe('ready');
    expect(second.result.current.edges).toHaveLength(1);
    expect(fetchEdgesMock).toHaveBeenCalledTimes(1);
  });

  it('refetches when edges_version changes for the same cycle and round', async () => {
    fetchEdgesMock.mockResolvedValue([]);
    const { result, rerender } = renderHook(() => useCycleEdges('cyc-version', 2));
    await waitFor(() => expect(result.current.status).toBe('ready'));
    setMeta({ edgesVersion: 2 });
    rerender();
    await waitFor(() => expect(fetchEdgesMock).toHaveBeenCalledTimes(2));
  });

  it('never shows a late response from the previous key', async () => {
    const late = deferred<Edge[]>();
    fetchEdgesMock.mockReturnValueOnce(late.promise);
    fetchEdgesMock.mockResolvedValueOnce([edge('degens_02', 'quants_01')]);
    const { result, rerender } = renderHook(
      ({ round }: { round: number }) => useCycleEdges('cyc-race', round),
      { initialProps: { round: 2 } },
    );
    setMeta({ edgesVersion: 2 });
    rerender({ round: 3 });
    await waitFor(() => expect(result.current.status).toBe('ready'));
    late.resolve([edge('quants_01', 'macro_01')]);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(result.current.edges).toEqual([edge('degens_02', 'quants_01')]);
  });

  it('reports an error without caching it', async () => {
    fetchEdgesMock.mockRejectedValueOnce(new Error('boom'));
    const failing = renderHook(() => useCycleEdges('cyc-error', 2));
    await waitFor(() => expect(failing.result.current.status).toBe('error'));
    expect(failing.result.current.edges).toEqual([]);
    failing.unmount();
    fetchEdgesMock.mockResolvedValueOnce([edge('quants_01', 'macro_01')]);
    const retry = renderHook(() => useCycleEdges('cyc-error', 2));
    await waitFor(() => expect(retry.result.current.status).toBe('ready'));
    expect(fetchEdgesMock).toHaveBeenCalledTimes(2);
  });
});
