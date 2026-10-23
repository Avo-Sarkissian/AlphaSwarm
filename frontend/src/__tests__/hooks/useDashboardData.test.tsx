// @vitest-environment happy-dom
import type { ReactNode } from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { adaptSnapshot } from '../../adapter/frame';
import { FrameProviders } from '../../context/FrameProviders';
import { useBracketRows, useFeedRows, useTopInfluencers } from '../../features/dashboard/useDashboardData';
import liveFrame from '../fixtures/ws_snapshot.json';
import { makeAgent } from '../helpers/agents';
import { renderWithFrame } from '../helpers/renderWithFrame';

const h = vi.hoisted(() => ({
  edges: [] as Array<{ source_id: string; target_id: string; weight: number }>,
}));

vi.mock('../../context/EdgesContext', async () => {
  const { indexEdges } = await import('../../hooks/useCycleEdges');
  return {
    EdgesProvider: ({ children }: { children: ReactNode }) => children,
    useEdgesCtx: () => ({ ...indexEdges(h.edges), target: null }),
  };
});

function Probe({ limit }: { limit?: number }) {
  const rows = useTopInfluencers(limit);
  return <ol>{rows.map((r) => <li key={r.id}>{`${r.id}:${r.citedBy}:${r.barPct}:${r.bracket}`}</li>)}</ol>;
}

const AGENTS = [makeAgent('quants_01'), makeAgent('sell_side_03'), makeAgent('macro_02')];
const items = () => screen.queryAllByRole('listitem').map((li) => li.textContent);

afterEach(() => {
  cleanup();
  h.edges = [];
});

describe('useTopInfluencers', () => {
  it('ranks by citations received and scales bars to the leader', () => {
    h.edges = [
      { source_id: 'quants_01', target_id: 'sell_side_03', weight: 0.01 },
      { source_id: 'macro_02', target_id: 'sell_side_03', weight: 0.01 },
      { source_id: 'sell_side_03', target_id: 'quants_01', weight: 0.01 },
    ];
    renderWithFrame(<Probe />, { frame: { agents: AGENTS } });
    expect(items()).toEqual([
      `sell_side_03:2:100:${AGENTS[1]?.bracketDisplay ?? ''}`,
      `quants_01:1:50:${AGENTS[0]?.bracketDisplay ?? ''}`,
    ]);
  });

  it('honours the limit', () => {
    h.edges = [
      { source_id: 'quants_01', target_id: 'sell_side_03', weight: 0.01 },
      { source_id: 'sell_side_03', target_id: 'quants_01', weight: 0.01 },
    ];
    renderWithFrame(<Probe limit={1} />, { frame: { agents: AGENTS } });
    expect(items()).toHaveLength(1);
  });

  it('is empty before any citation edges exist', () => {
    renderWithFrame(<Probe />, { frame: { agents: AGENTS } });
    expect(items()).toEqual([]);
  });
});

describe('panel rows across frames', () => {
  it('keep their identity when only telemetry changed', () => {
    const seen: Array<{ brackets: unknown; feed: unknown }> = [];
    function RowsProbe() {
      seen.push({ brackets: useBracketRows(), feed: useFeedRows() });
      return null;
    }
    const first = adaptSnapshot(liveFrame);
    const changed = structuredClone(liveFrame) as unknown as { governor_metrics: { memory_percent: number } };
    changed.governor_metrics.memory_percent += 1;
    const second = adaptSnapshot(changed, first);
    // Connection props: the same ones renderWithFrame passes to FrameProviders.
    const { rerender } = render(
      <FrameProviders frame={first} connected status="open">
        <RowsProbe />
      </FrameProviders>,
    );
    rerender(
      <FrameProviders frame={second} connected status="open">
        <RowsProbe />
      </FrameProviders>,
    );
    const a = seen[0];
    const b = seen[seen.length - 1];
    expect(seen.length).toBeGreaterThan(1);
    expect(b?.brackets).toBe(a?.brackets);
    expect(b?.feed).toBe(a?.feed);
  });
});
