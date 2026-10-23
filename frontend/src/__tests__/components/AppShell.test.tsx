// @vitest-environment happy-dom
// Dashboard shell (app_v2) with the heavy children stubbed: the graph, the v2
// widgets that poll or load DEV mocks, and Settings. Edges come from a
// controllable EdgesContext stub.
import type { ReactNode } from 'react';
import { act, cleanup, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App as DashboardShell } from '../../components/app_v2';
import { makeAgent } from '../helpers/agents';
import { stubFetchRoutes } from '../helpers/fetchRoutes';
import { renderAt, rerenderAt } from '../helpers/lifecycleFrames';
import type { StateFrame } from '../../types';

const SEED = 'ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash.';
const LOCAL_ESTIMATE = { calls: 300, low_usd: '0.00', high_usd: '0.00', mode: 'local' };
const ALREADY_RUNNING = {
  status: 409,
  body: { detail: { error: 'simulation_already_running', message: 'Simulation already running' } },
};

function pressRun() {
  fireEvent.change(screen.getByLabelText('Seed rumor'), { target: { value: SEED } });
  fireEvent.click(screen.getByRole('button', { name: /^run$/i }));
}

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
    const row = screen.getByText('Sell-Side', { selector: '.bracket-name' }).closest('.bracket-row') as HTMLElement;
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

describe('run failures', () => {
  it('shows last_error on the idle dashboard after a failed run', () => {
    renderAt(<DashboardShell />, 'idle', {
      lastError: {
        code: 'graph_unavailable',
        message: 'Neo4j is not reachable. Start it with docker compose up -d neo4j.',
        roundNum: null,
        ts: 1765432100,
      } as StateFrame['lastError'],
    });
    expect(screen.getByRole('alert').textContent).toContain('Neo4j is not reachable');
  });

  it('shows a refused start inline, and Dismiss clears it', async () => {
    stubFetchRoutes({
      'GET /api/settings/estimate': { body: LOCAL_ESTIMATE },
      'POST /api/simulate/start': ALREADY_RUNNING,
    });
    renderAt(<DashboardShell />, 'idle');
    pressRun();
    const row = (await screen.findByText('Simulation already running')).closest('[role="alert"]');
    expect(row).not.toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss error' }));
    expect(screen.queryByText('Simulation already running')).toBeNull();
    expect(screen.getByRole('button', { name: /^run$/i })).toHaveProperty('disabled', false);
  });

  it('clears a Run error once a run reaches SEEDING', async () => {
    stubFetchRoutes({
      'GET /api/settings/estimate': { body: LOCAL_ESTIMATE },
      'POST /api/simulate/start': ALREADY_RUNNING,
    });
    const view = renderAt(<DashboardShell />, 'idle');
    pressRun();
    await screen.findByText('Simulation already running');
    rerenderAt(view, <DashboardShell />, 'seeding');
    expect(screen.queryByText('Simulation already running')).toBeNull();
  });
});

describe('starting a run', () => {
  it('keeps Run on Starting… until the run reaches the frame', async () => {
    const fetchMock = stubFetchRoutes({
      'GET /api/settings/estimate': { body: LOCAL_ESTIMATE },
      'POST /api/simulate/start': { body: { status: 'accepted', message: 'Simulation started' } },
    });
    const starts = () => fetchMock.mock.calls.filter(([url]) => url === '/api/simulate/start');
    const view = renderAt(<DashboardShell />, 'idle');
    pressRun();
    await waitFor(() => expect(starts()).toHaveLength(1));
    // Flush the accepted answer into the gate (one macrotask; no time passes)
    // while the frame still says idle.
    await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
    const button = screen.getByRole('button', { name: /starting/i });
    expect(button).toHaveProperty('disabled', true);
    fireEvent.click(button);
    rerenderAt(view, <DashboardShell />, 'seeding');
    expect(screen.queryByRole('button', { name: /stop/i })).not.toBeNull();
    expect(starts()).toHaveLength(1);
    // A run that fails at SEEDING drops back to idle: Run is usable at once.
    rerenderAt(view, <DashboardShell />, 'idle');
    expect(screen.getByRole('button', { name: /^run$/i })).toHaveProperty('disabled', false);
  });
});
