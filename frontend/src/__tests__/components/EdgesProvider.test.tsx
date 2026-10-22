// @vitest-environment happy-dom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchEdges } from '../../api/edges';
import { EdgesProvider, useEdgesCtx } from '../../context/EdgesContext';
import { makeMeta } from '../helpers/frameMeta';

const h = vi.hoisted(() => ({ meta: null as unknown }));
vi.mock('../../context/FrameMetaContext', () => ({ useFrameMeta: () => h.meta }));
vi.mock('../../api/edges', () => ({ fetchEdges: vi.fn() }));

const fetchEdgesMock = vi.mocked(fetchEdges);

function Consumer() {
  const { target, edges, status } = useEdgesCtx();
  const where = target ? `${target.cycleId}:${target.round}` : 'none';
  return <output>{`${where}|${edges.length}|${status}`}</output>;
}

beforeEach(() => {
  fetchEdgesMock.mockReset();
});

afterEach(cleanup);

describe('EdgesProvider', () => {
  it('loads the live target round for the frame cycle', async () => {
    h.meta = makeMeta({ phase: 'round_3', roundNum: 3, edgesVersion: 1, cycleId: 'cyc-provider-live' });
    fetchEdgesMock.mockResolvedValue([{ source_id: 'quants_01', target_id: 'macro_01', weight: 0.01 }]);
    render(
      <EdgesProvider>
        <Consumer />
      </EdgesProvider>,
    );
    await waitFor(() =>
      expect(screen.getByRole('status').textContent).toBe('cyc-provider-live:2|1|ready'),
    );
    expect(fetchEdgesMock).toHaveBeenCalledWith('cyc-provider-live', 2);
  });

  it('fetches nothing while idle', () => {
    h.meta = makeMeta({ mode: 'idle', phase: 'idle', edgesVersion: 2 });
    render(
      <EdgesProvider>
        <Consumer />
      </EdgesProvider>,
    );
    expect(screen.getByRole('status').textContent).toBe('none|0|idle');
    expect(fetchEdgesMock).not.toHaveBeenCalled();
  });
});
