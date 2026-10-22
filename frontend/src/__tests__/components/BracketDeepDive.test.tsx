// @vitest-environment happy-dom
import type { ReactNode } from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BracketDeepDive } from '../../components/bracket_deep';
import { makeAgent } from '../helpers/agents';

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

const SELL_SIDE = { bracket: 'sell_side', display_name: 'Sell-Side' };

afterEach(() => {
  cleanup();
  h.edges = [];
});

describe('BracketDeepDive edges', () => {
  it('counts citations made and received from the shared edges', () => {
    h.edges = [
      { source_id: 'quants_01', target_id: 'sell_side_01', weight: 0.02 },
      { source_id: 'degens_02', target_id: 'sell_side_01', weight: 0.02 },
      { source_id: 'sell_side_01', target_id: 'macro_01', weight: 0.01 },
    ];
    render(
      <BracketDeepDive
        bracket={SELL_SIDE}
        agents={[makeAgent('sell_side_01', 'buy', 0.8), makeAgent('sell_side_02', 'sell', 0.6)]}
        onClose={vi.fn()}
      />,
    );
    expect(screen.queryByText('↗1')).not.toBeNull();
    expect(screen.queryByText('↙2')).not.toBeNull();
    expect(screen.getAllByText('↙0')).toHaveLength(1);
  });

  it('shows dashes until the round on screen has edges', () => {
    render(
      <BracketDeepDive
        bracket={SELL_SIDE}
        agents={[makeAgent('sell_side_01', 'buy'), makeAgent('sell_side_02', 'sell')]}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getAllByText('↗—')).toHaveLength(2);
  });
});
