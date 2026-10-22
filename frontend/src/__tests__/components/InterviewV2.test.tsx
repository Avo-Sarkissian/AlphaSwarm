// @vitest-environment happy-dom
import type { ReactNode } from 'react';
import { cleanup, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { InterviewV2 } from '../../components/interview_v2';
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

afterEach(() => {
  cleanup();
  h.edges = [];
});

describe('InterviewV2 citations', () => {
  it('lists the citations of the round on screen', () => {
    h.edges = [
      { source_id: 'quants_01', target_id: 'macro_01', weight: 0.01 },
      { source_id: 'degens_02', target_id: 'quants_01', weight: 0.02 },
      { source_id: 'sell_side_03', target_id: 'quants_01', weight: 0.02 },
    ];
    renderWithFrame(<InterviewV2 agent={makeAgent('quants_01', 'buy', 0.7)} onClose={vi.fn()} />);
    expect(screen.queryByText('cites 1')).not.toBeNull();
    expect(screen.queryByText('cited by 2')).not.toBeNull();
  });
});
