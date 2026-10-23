// @vitest-environment happy-dom
import type { ReactNode } from 'react';
import { cleanup, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { InterviewV2 } from '../../components/interview_v2';
import { makeAgent } from '../helpers/agents';
import { stubFetchRoutes } from '../helpers/fetchRoutes';
import { renderAt } from '../helpers/lifecycleFrames';
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

beforeEach(() => {
  stubFetchRoutes({});
});

afterEach(() => {
  cleanup();
  h.edges = [];
  vi.unstubAllGlobals();
});

describe('InterviewV2 citations', () => {
  it('lists the citations of the round on screen', () => {
    h.edges = [
      { source_id: 'quants_01', target_id: 'macro_01', weight: 0.01 },
      { source_id: 'degens_02', target_id: 'quants_01', weight: 0.02 },
      { source_id: 'sell_side_03', target_id: 'quants_01', weight: 0.02 },
    ];
    renderWithFrame(<InterviewV2 agentId="quants_01" onClose={vi.fn()} />, {
      frame: { agents: [makeAgent('quants_01', 'buy', 0.7)] },
    });
    expect(screen.queryByText('cites 1')).not.toBeNull();
    expect(screen.queryByText('cited by 2')).not.toBeNull();
  });
});

describe('InterviewV2 rounds', () => {
  it('renders two rounds for a 2-round run (vitest with num_rounds=2)', () => {
    renderAt(<InterviewV2 agentId="quants_01" onClose={vi.fn()} />, 'live', {
      numRounds: 2,
      roundNum: 2,
      agents: [makeAgent('quants_01', 'buy', 0.7)],
    });
    const labels = Array.from(document.querySelectorAll('.iv2-traj-label')).map((el) => el.textContent);
    expect(labels).toEqual(['R1', 'R2 · live']);
    expect(screen.queryByText(/Round 2 of 2 so far: BUY/)).not.toBeNull();
  });
});
