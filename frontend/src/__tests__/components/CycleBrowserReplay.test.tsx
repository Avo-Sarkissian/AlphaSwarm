// @vitest-environment happy-dom
// The cycle browser is the only cycle list: it opens reports and starts replays.
import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CycleBrowser } from '../../features/cycles/CycleBrowser';
import { renderWithFrame } from '../helpers/renderWithFrame';

const CYCLE = {
  cycle_id: '00000000-0000-4000-8000-0000000000a1',
  created_at: '2026-10-01T14:30:00.000000+00:00',
  seed_rumor: 'ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash.',
  round_count: 3,
  status: 'complete',
  final_buy: 41,
  final_sell: 37,
  final_hold: 22,
  total_flips: 18,
  total_seconds: 1520.5,
  agent_count: 100,
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

function stubBackend(replayStatus: 200 | 409) {
  const calls: Array<{ url: string; method: string }> = [];
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, 'http://localhost').pathname; // query string (?limit=20) dropped
    const method = init?.method ?? (input instanceof Request ? input.method : 'GET');
    calls.push({ url, method });
    if (url === '/api/replay/cycles') return json({ cycles: [CYCLE], next_before: null });
    if (url.startsWith('/api/replay/start/')) {
      return replayStatus === 200
        ? json({ status: 'ok', cycle_id: CYCLE.cycle_id, round_num: 1 })
        : json({ detail: { error: 'replay_already_active', message: 'A replay session is already active' } }, 409);
    }
    return json({ detail: { error: 'not_found', message: `unexpected ${url}` } }, 404);
  }));
  return calls;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('cycle browser replay action', () => {
  it('starts the replay for the row and closes', async () => {
    const calls = stubBackend(200);
    const onClose = vi.fn();
    renderWithFrame(<CycleBrowser onClose={onClose} onOpenReport={vi.fn()} />);
    fireEvent.click(await screen.findByTitle('Replay this cycle'));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(calls).toContainEqual({ url: `/api/replay/start/${CYCLE.cycle_id}`, method: 'POST' });
  });

  it('shows the backend message and stays open when the replay is refused', async () => {
    stubBackend(409);
    const onClose = vi.fn();
    renderWithFrame(<CycleBrowser onClose={onClose} onOpenReport={vi.fn()} />);
    fireEvent.click(await screen.findByTitle('Replay this cycle'));
    expect(await screen.findByText(/A replay session is already active/)).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
    expect((screen.getByTitle('Replay this cycle') as HTMLButtonElement).disabled).toBe(false);
  });

  it('still opens the report for the row', async () => {
    stubBackend(200);
    const onOpenReport = vi.fn();
    renderWithFrame(<CycleBrowser onClose={vi.fn()} onOpenReport={onOpenReport} />);
    fireEvent.click(await screen.findByTitle('Open report'));
    expect(onOpenReport).toHaveBeenCalledWith(expect.objectContaining({ cycle_id: CYCLE.cycle_id }));
  });
});
