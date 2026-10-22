// @vitest-environment happy-dom
// Dashboard shell (app_v2) with the heavy children stubbed: the graph, the v2
// widgets that poll or load DEV mocks, and Settings. Edges come from a
// controllable EdgesContext stub.
import type { ReactNode } from 'react';
import { cleanup, fireEvent, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App as DashboardShell } from '../../components/app_v2';
import { makeAgent } from '../helpers/agents';
import { renderAt } from '../helpers/lifecycleFrames';

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
vi.mock('../../components/v2', () => ({
  SignalWire: () => null,
  ModelStatus: () => null,
  DataSourcesTakeover: () => null,
  AdvisoryV2: () => null,
}));
vi.mock('../../components/viz', async () => {
  const { createElement } = await import('react');
  return { Viz: () => createElement('svg', { 'data-testid': 'viz' }) };
});
vi.mock('../../components/settings', async () => {
  const { createElement } = await import('react');
  return {
    Settings: () => createElement('div', { role: 'dialog', 'aria-label': 'Settings dialog' }),
  };
});

afterEach(() => {
  cleanup();
  h.edges = [];
  vi.unstubAllGlobals();
});

const ROSTER = [
  makeAgent('institutions_01', 'hold', 0.9),
  makeAgent('sell_side_03', 'buy', 0.4),
  makeAgent('event_driven_05', 'sell', 0.7),
];

describe('Top Influencers', () => {
  it('ranks by citations received and labels the column CITED BY', () => {
    h.edges = [
      { source_id: 'institutions_01', target_id: 'sell_side_03', weight: 0.02 },
      { source_id: 'event_driven_05', target_id: 'sell_side_03', weight: 0.02 },
      { source_id: 'sell_side_03', target_id: 'institutions_01', weight: 0.01 },
    ];
    renderAt(<DashboardShell />, 'complete', { agents: ROSTER });
    const panel = screen.getByText('Top Influencers').closest('.panel') as HTMLElement;
    expect(panel.textContent).toContain('CITED BY');
    const ids = Array.from(panel.querySelectorAll('.infl-id')).map((el) => el.textContent);
    expect(ids).toEqual(['sell_side_03', 'institutions_01']);
  });

  it('says when there is nothing to rank yet instead of ranking by confidence', () => {
    renderAt(<DashboardShell />, 'live', { agents: ROSTER });
    const panel = screen.getByText('Top Influencers').closest('.panel') as HTMLElement;
    expect(panel.querySelectorAll('.infl-id')).toHaveLength(0);
    expect(panel.textContent).toContain('influence appears once round 2');
  });
});

describe('Brackets panel', () => {
  it('derives the bars from the agents on screen, leaving pending agents blank', () => {
    renderAt(<DashboardShell />, 'live', {
      agents: [makeAgent('sell_side_01', 'buy'), makeAgent('sell_side_02', null)],
    });
    const row = screen.getByText('sell_side').closest('.bracket-row') as HTMLElement;
    expect(row.querySelector('.bracket-count')?.textContent).toBe('2');
    expect((row.querySelector('.b-buy') as HTMLElement).style.width).toBe('50%');
    expect((row.querySelector('.b-hold') as HTMLElement).style.width).toBe('0%');
  });
});

describe('dashboard lifecycle', () => {
  it('keeps the topbar and Settings reachable while idle (exit criterion)', () => {
    renderAt(<DashboardShell />, 'idle');
    expect(screen.queryByText('Swarm is dormant.')).not.toBeNull();
    expect(screen.queryByRole('button', { name: /^run$/i })).not.toBeNull();
    fireEvent.click(screen.getByTitle('Settings'));
    expect(screen.queryByRole('dialog', { name: 'Settings dialog' })).not.toBeNull();
  });

  it('shows the seeding overlay, the SEEDING label and Stop while seeding', () => {
    renderAt(<DashboardShell />, 'seeding');
    expect(screen.queryByText('Spawning agents…')).not.toBeNull();
    expect(screen.queryByText('SEEDING')).not.toBeNull();
    expect(screen.queryByRole('button', { name: /stop/i })).not.toBeNull();
  });

  it('shows the graph without overlays during a live round', () => {
    renderAt(<DashboardShell />, 'live');
    expect(screen.queryByText('Swarm is dormant.')).toBeNull();
    expect(screen.queryByText('Spawning agents…')).toBeNull();
    expect(screen.queryByText('ROUND 2/3')).not.toBeNull();
  });

  it('shows the replay bar and hides Run/Stop in replay, with no local state', () => {
    renderAt(<DashboardShell />, 'replay');
    expect(screen.queryByRole('button', { name: 'Exit replay' })).not.toBeNull();
    expect(screen.queryByRole('button', { name: /^run$/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /stop/i })).toBeNull();
    expect(screen.queryByText('REPLAY · R2/3')).not.toBeNull();
  });

  it('caps the seed input at the backend maximum', () => {
    renderAt(<DashboardShell />, 'idle');
    expect((screen.getByLabelText('Seed rumor') as HTMLInputElement).maxLength).toBe(2000);
  });
});
