// @vitest-environment happy-dom
import type { ReactNode } from 'react';
import { cleanup, fireEvent, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AppShell } from '../../app/AppShell';
import { DEMO_LOCK_TITLE } from '../../data-source';
import { ReplayBar } from '../../features/dashboard/ReplayBar';
import { InterviewPanel } from '../../features/interview/InterviewPanel';
import { ensureResizeObserver, stubFetch } from '../helpers/fetchStub';
import { renderAt, TEST_CYCLE_ID } from '../helpers/lifecycleFrames';

vi.mock('../../data-source', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../data-source')>();
  return { ...actual, demoLock: () => ({ locked: true, title: actual.DEMO_LOCK_TITLE }) };
});
vi.mock('../../context/EdgesContext', async () => {
  const { indexEdges } = await import('../../hooks/useCycleEdges');
  return {
    EdgesProvider: ({ children }: { children: ReactNode }) => children,
    useEdgesCtx: () => ({ ...indexEdges([]), target: null }),
  };
});
vi.mock('../../features/wire/SignalWire', () => ({ SignalWire: () => null }));
vi.mock('../../features/dashboard/ModelStatus', () => ({ ModelStatus: () => null }));
vi.mock('../../viz/InfluenceGraph', async () => {
  const { createElement } = await import('react');
  return { DEFAULT_ALL_EDGES: false, InfluenceGraph: () => createElement('svg', { 'data-testid': 'viz' }) };
});

beforeEach(() => ensureResizeObserver());

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('read-only demo', () => {
  it('disables every locked control in the shell and explains why', () => {
    stubFetch([]);
    renderAt(<AppShell />, 'replay');
    const controls = Array.from(document.querySelectorAll<HTMLButtonElement>('[data-demo-lock]'));
    expect(controls.map((c) => c.dataset.demoLock)).toContain('settings');
    for (const control of controls) {
      expect(control.disabled).toBe(true);
      expect(control.getAttribute('title')).toBe(DEMO_LOCK_TITLE);
    }
  });

  it('opens the interview on the stored rationales and offers no way to ask', async () => {
    stubFetch([
      {
        path: '/api/agents/quants_01/decisions',
        body: {
          agent_id: 'quants_01',
          cycle_id: TEST_CYCLE_ID,
          decisions: [
            { round_num: 1, signal: 'buy', confidence: 0.8, sentiment: 0.4, rationale: 'ZZZT deal looks accretive', cited_agents: [] },
          ],
        },
      },
    ]);
    renderAt(<InterviewPanel agentId="quants_01" onClose={() => undefined} />, 'replay');
    expect(await screen.findByText(/ZZZT deal looks accretive/)).not.toBeNull();
    fireEvent.click(screen.getByText('Interview'));
    const send = document.querySelector<HTMLButtonElement>('[data-demo-lock="interview"]');
    expect(send?.disabled).toBe(true);
    expect(send?.getAttribute('title')).toBe(DEMO_LOCK_TITLE);
  });

  it('keeps Play cascade but offers no way out of the demo replay', () => {
    renderAt(<ReplayBar />, 'replay');
    expect(screen.queryByRole('button', { name: 'Exit replay' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Play cascade' })).not.toBeNull();
  });
});
