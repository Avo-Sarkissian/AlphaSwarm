// @vitest-environment happy-dom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CycleItem } from '../../api/replay';
import { CycleHistory } from '../../components/history';
import { jsonResponse, stubFetch } from '../helpers/fetchStub';

const RUMOR = 'ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash.';
const base = { seed_rumor: RUMOR, round_count: 3, status: 'complete' };
// Built from local wall-clock values so the test passes in any time zone.
const TODAY: CycleItem = {
  ...base,
  cycle_id: 'c-with-metrics',
  created_at: new Date(2026, 9, 3, 1, 0).toISOString(),
  final_buy: 60,
  final_sell: 25,
  final_hold: 10,
  total_flips: 7,
  total_seconds: 754.3,
  agent_count: 100,
};
const YESTERDAY: CycleItem = {
  ...base,
  cycle_id: 'c-legacy',
  created_at: new Date(2026, 9, 2, 23, 0).toISOString(),
  final_buy: null,
  final_sell: null,
  final_hold: null,
  total_flips: null,
  total_seconds: null,
  agent_count: null,
};
const OLDER: CycleItem = { ...TODAY, cycle_id: 'c-older', created_at: new Date(2026, 8, 30, 9, 0).toISOString() };

const rowOf = (id: string) => screen.getByText(id).closest('.ch-row') as HTMLElement;
const cell = (row: HTMLElement, cls: string) => row.querySelector(cls)?.textContent?.trim();

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date(2026, 9, 3, 15, 0));
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('CycleHistory', () => {
  it('shows consensus, flips and duration from the stored metrics, and dashes when not recorded', async () => {
    stubFetch([{ path: '/api/replay/cycles', body: { cycles: [TODAY, YESTERDAY], next_before: null } }]);
    render(<CycleHistory onClose={() => {}} onOpenReport={() => {}} />);
    await screen.findByText('c-with-metrics');

    const row = rowOf('c-with-metrics');
    expect([cell(row, '.ch-consensus'), cell(row, '.ch-flips'), cell(row, '.ch-dur')]).toEqual(['BUY 63%', '7', '12:34']);
    const legacy = rowOf('c-legacy');
    expect([cell(legacy, '.ch-consensus'), cell(legacy, '.ch-flips'), cell(legacy, '.ch-dur')]).toEqual(['—', '—', '—']);

    expect(screen.getByText('AVG FLIPS').nextElementSibling?.textContent).toBe('7.0');
    expect(screen.getByText('AVG DURATION').nextElementSibling?.textContent).toBe('12:34');
  });

  it('has no Starred filter, selection checkboxes, Compare or shocks column', async () => {
    stubFetch([{ path: '/api/replay/cycles', body: { cycles: [TODAY], next_before: null } }]);
    const { container } = render(<CycleHistory onClose={() => {}} onOpenReport={() => {}} />);
    await screen.findByText('c-with-metrics');
    expect(screen.queryByText('Starred')).toBeNull();
    expect(screen.queryByText(/compare/i)).toBeNull();
    expect(screen.queryByText('SHOCKS')).toBeNull();
    expect(container.querySelector('.ch-check')).toBeNull();
  });

  it('filters Today by the local calendar day', async () => {
    stubFetch([{ path: '/api/replay/cycles', body: { cycles: [TODAY, YESTERDAY], next_before: null } }]);
    render(<CycleHistory onClose={() => {}} onOpenReport={() => {}} />);
    await screen.findByText('c-with-metrics');
    fireEvent.click(screen.getByText('Today'));
    expect(screen.queryByText('c-with-metrics')).not.toBeNull();
    expect(screen.queryByText('c-legacy')).toBeNull();
  });

  it('loads older cycles on demand', async () => {
    const pages: Record<string, unknown> = {
      '/api/replay/cycles?limit=20': { cycles: [TODAY, YESTERDAY], next_before: YESTERDAY.created_at },
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes('before=')) return jsonResponse({ cycles: [OLDER], next_before: null });
        return jsonResponse(pages[url]);
      }),
    );
    render(<CycleHistory onClose={() => {}} onOpenReport={() => {}} />);
    fireEvent.click(await screen.findByText('Load older cycles'));
    await waitFor(() => expect(screen.queryByText('c-older')).not.toBeNull());
    expect(screen.queryByText('Load older cycles')).toBeNull();
  });
});
