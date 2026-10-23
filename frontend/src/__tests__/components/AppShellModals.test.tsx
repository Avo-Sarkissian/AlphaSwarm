// @vitest-environment happy-dom
// The real shell keeps at most one overlay open; heavy children are stubbed.
import type { ReactNode } from 'react';
import { cleanup, fireEvent, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AppShell } from '../../app/AppShell';
import { makeAgent } from '../helpers/agents';
import { renderAt } from '../helpers/lifecycleFrames';

vi.mock('../../context/EdgesContext', async () => {
  const { indexEdges } = await import('../../hooks/useCycleEdges');
  return {
    EdgesProvider: ({ children }: { children: ReactNode }) => children,
    useEdgesCtx: () => ({ ...indexEdges([]), target: null }),
  };
});
vi.mock('../../features/wire/SignalWire', () => ({ SignalWire: () => null }));
vi.mock('../../features/dashboard/ModelStatus', () => ({ ModelStatus: () => null }));
vi.mock('../../features/dashboard/Viz', async () => {
  const { createElement, Fragment } = await import('react');
  return {
    Viz: ({ agents, onAgentClick }: { agents: Array<{ id: string }>; onAgentClick?: (a: { id: string }) => void }) =>
      createElement(
        Fragment,
        null,
        agents.map((a) =>
          createElement('button', { key: a.id, 'data-testid': `node-${a.id}`, onClick: () => onAgentClick?.(a) }, a.id),
        ),
      ),
  };
});
vi.mock('../../features/settings/Settings', async () => {
  const { createElement } = await import('react');
  return { Settings: () => createElement('div', { 'data-testid': 'overlay' }, 'settings') };
});
vi.mock('../../features/report/ReportModal', async () => {
  const { createElement } = await import('react');
  return { ReportModal: () => createElement('div', { 'data-testid': 'overlay' }, 'report') };
});
vi.mock('../../features/cycles/CycleBrowser', async () => {
  const { createElement } = await import('react');
  return { CycleBrowser: () => createElement('div', { 'data-testid': 'overlay' }, 'cycles') };
});
vi.mock('../../features/interview/InterviewPanel', async () => {
  const { createElement } = await import('react');
  return {
    InterviewPanel: ({ agentId }: { agentId: string }) =>
      createElement('div', { 'data-testid': 'overlay' }, `interview:${agentId}`),
  };
});

const ROSTER = [makeAgent('institutions_01', 'hold', 0.9), makeAgent('sell_side_03', 'buy', 0.4)];
const overlays = () => screen.queryAllByTestId('overlay').map((el) => el.textContent);

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(
    JSON.stringify({ detail: { error: 'not_found', message: 'stubbed' } }),
    { status: 404, headers: { 'content-type': 'application/json' } },
  )));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('AppShell overlays', () => {
  it('replaces Settings with the report instead of stacking them', () => {
    renderAt(<AppShell />, 'complete', { agents: ROSTER });
    fireEvent.click(screen.getByTitle('Settings'));
    expect(overlays()).toEqual(['settings']);
    fireEvent.click(screen.getByTitle('Simulation report'));
    expect(overlays()).toEqual(['report']);
  });

  it('opens the cycle browser from Watch / replay', () => {
    renderAt(<AppShell />, 'complete', { agents: ROSTER });
    fireEvent.click(screen.getByTitle('Watch / replay'));
    expect(overlays()).toEqual(['cycles']);
  });

  it('opens the interview for a clicked node and closes Settings', () => {
    renderAt(<AppShell />, 'complete', { agents: ROSTER });
    fireEvent.click(screen.getByTitle('Settings'));
    fireEvent.click(screen.getByTestId('node-sell_side_03'));
    expect(overlays()).toEqual(['interview:sell_side_03']);
  });
});
