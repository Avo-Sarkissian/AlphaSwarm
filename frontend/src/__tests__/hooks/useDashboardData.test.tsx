// @vitest-environment happy-dom
import type { ReactNode } from 'react';
import { cleanup, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useTopInfluencers } from '../../features/dashboard/useDashboardData';
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
