// @vitest-environment happy-dom
// ModalHost renders exactly one overlay for each ActiveModal kind and maps the
// overlays' navigation callbacks onto the next ActiveModal.
import { cleanup, fireEvent, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ModalHost, type ActiveModal } from '../../app/ModalHost';
import { makeAgent } from '../helpers/agents';
import { renderWithFrame } from '../helpers/renderWithFrame';

vi.mock('../../features/settings/Settings', async () => {
  const { createElement } = await import('react');
  return { Settings: () => createElement('div', { 'data-testid': 'overlay' }, 'settings') };
});
vi.mock('../../features/report/ReportModal', async () => {
  const { createElement } = await import('react');
  return {
    ReportModal: ({ cycleId }: { cycleId: string | null }) =>
      createElement('div', { 'data-testid': 'overlay' }, `report:${cycleId ?? 'default'}`),
  };
});
vi.mock('../../features/advisory/AdvisoryPanel', async () => {
  const { createElement } = await import('react');
  return { AdvisoryPanel: () => createElement('div', { 'data-testid': 'overlay' }, 'advisory') };
});
vi.mock('../../features/wire/DataSourcesTakeover', async () => {
  const { createElement } = await import('react');
  return { DataSourcesTakeover: () => createElement('div', { 'data-testid': 'overlay' }, 'dataSources') };
});
vi.mock('../../features/dashboard/ShockDrawer', async () => {
  const { createElement } = await import('react');
  return { ShockDrawer: () => createElement('div', { 'data-testid': 'overlay' }, 'shock') };
});
vi.mock('../../features/cycles/CycleBrowser', async () => {
  const { createElement } = await import('react');
  return {
    CycleBrowser: ({ onOpenReport }: { onOpenReport: (c: { cycle_id: string }) => void }) =>
      createElement(
        'button',
        { 'data-testid': 'overlay', onClick: () => onOpenReport({ cycle_id: '00000000-0000-4000-8000-0000000000a1' }) },
        'cycles',
      ),
  };
});
vi.mock('../../features/interview/InterviewPanel', async () => {
  const { createElement } = await import('react');
  return {
    InterviewPanel: ({ agentId }: { agentId: string }) =>
      createElement('div', { 'data-testid': 'overlay' }, `interview:${agentId}`),
  };
});
vi.mock('../../features/dashboard/BracketDeepDive', async () => {
  const { createElement } = await import('react');
  return {
    BracketDeepDive: (p: {
      bracket: { bracket: string };
      agents: Array<{ id: string }>;
      onAgentInterview?: (agent: { id: string }) => void;
    }) =>
      createElement(
        'button',
        { 'data-testid': 'overlay', onClick: () => p.onAgentInterview?.(p.agents[0] ?? { id: 'none' }) },
        `bracket:${p.bracket.bracket}:${p.agents.map((a) => a.id).join(',')}`,
      ),
  };
});

const CYCLE = '00000000-0000-4000-8000-0000000000a1';
const AGENTS = [makeAgent('quants_01'), makeAgent('quants_02'), makeAgent('degens_01')];
const QUANTS = { bracket: 'quants', display_name: 'Quants' };

function renderHost(modal: ActiveModal) {
  const onOpen = vi.fn();
  const onClose = vi.fn();
  renderWithFrame(<ModalHost modal={modal} onOpen={onOpen} onClose={onClose} />, { frame: { agents: AGENTS } });
  return { onOpen, onClose };
}

afterEach(cleanup);

describe('ModalHost', () => {
  it('uses snake_case bracket keys on the test agents', () => {
    expect(AGENTS.map((a) => a.bracket)).toEqual(['quants', 'quants', 'degens']);
  });

  it('renders nothing when no overlay is open', () => {
    renderHost({ kind: 'none' });
    expect(screen.queryByTestId('overlay')).toBeNull();
  });

  it.each<[ActiveModal, string]>([
    [{ kind: 'settings' }, 'settings'],
    [{ kind: 'report', cycleId: CYCLE }, `report:${CYCLE}`],
    [{ kind: 'report', cycleId: null }, 'report:default'],
    [{ kind: 'advisory' }, 'advisory'],
    [{ kind: 'dataSources' }, 'dataSources'],
    [{ kind: 'shock' }, 'shock'],
    [{ kind: 'cycles' }, 'cycles'],
    [{ kind: 'interview', agentId: 'degens_01' }, 'interview:degens_01'],
  ])('renders exactly one overlay for %o', (modal, text) => {
    renderHost(modal);
    const overlays = screen.getAllByTestId('overlay');
    expect(overlays).toHaveLength(1);
    expect(overlays[0]?.textContent).toBe(text);
  });

  it('passes only the bracket members to the deep dive', () => {
    renderHost({ kind: 'bracket', bracket: QUANTS });
    expect(screen.getByTestId('overlay').textContent).toBe('bracket:quants:quants_01,quants_02');
  });

  it('opens the report chosen in the cycle browser', () => {
    const { onOpen } = renderHost({ kind: 'cycles' });
    fireEvent.click(screen.getByTestId('overlay'));
    expect(onOpen).toHaveBeenCalledWith({ kind: 'report', cycleId: CYCLE });
  });

  it('opens the interview chosen in the bracket deep dive', () => {
    const { onOpen } = renderHost({ kind: 'bracket', bracket: QUANTS });
    fireEvent.click(screen.getByTestId('overlay'));
    expect(onOpen).toHaveBeenCalledWith({ kind: 'interview', agentId: 'quants_01' });
  });

  it('renders nothing for an agent that is not in the roster', () => {
    renderHost({ kind: 'interview', agentId: 'macro_07' });
    expect(screen.queryByTestId('overlay')).toBeNull();
  });
});
