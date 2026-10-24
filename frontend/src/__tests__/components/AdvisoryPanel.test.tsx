// @vitest-environment happy-dom
// The advisory view takes the round count from the frame and never names a
// fixed round, so a 2-round run does not read "3 rounds" or "post-R3".
import { cleanup, fireEvent, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AdvisoryPanel } from '../../features/advisory/AdvisoryPanel';
import { renderAt } from '../helpers/lifecycleFrames';

beforeEach(() => {
  // Every request stays pending, so the advisory for the finished cycle is still generating.
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => undefined)));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('AdvisoryPanel rounds', () => {
  it('describes the swarm layer with the run round count', () => {
    renderAt(<AdvisoryPanel onClose={vi.fn()} />, 'complete', { numRounds: 2, roundNum: 2 });
    fireEvent.click(screen.getByRole('button', { name: 'Isolation' }));
    expect(screen.queryByText('100 agents · 2 rounds · real market data')).not.toBeNull();
  });

  it('waits for the advisory without naming a round', () => {
    renderAt(<AdvisoryPanel onClose={vi.fn()} />, 'complete', { numRounds: 2, roundNum: 2 });
    const card = screen.getByText(/Generating advisory/).closest('.advisory-card');
    expect(card?.textContent).toMatch(/post-run narrative generation/);
    expect(card?.textContent).not.toMatch(/\bR\d\b/);
  });
});

const ADVISORY = {
  cycle_id: '00000000-0000-4000-8000-000000000001',
  generated_at: '2026-01-01T00:00:00Z',
  portfolio_outlook: '## Outlook\nSteady.',
  total_holdings: 2,
  affected_holdings: 1,
  items: [
    { ticker: 'ZZZT', consensus_signal: 'SELL', confidence: 0.8, rationale_summary: 'x',
      cost_basis_exposure: '2000', source: 'swarm', risk: 'guidance cut', upside: null },
    { ticker: 'QQQX', consensus_signal: 'HOLD', confidence: 0.3, rationale_summary: 'y',
      cost_basis_exposure: '1000', source: 'placeholder', risk: null, upside: null },
  ],
  stats: { conviction_count: 1, placeholder_count: 1, buy_count: 0, sell_count: 1, hold_count: 0,
    avg_confidence: 0.8, dominant_signal: 'SELL', dominant_share: 1 },
  holdings_as_of: null,
};

describe('AdvisoryPanel backend stats', () => {
  it('shows the backend swarm view and tags placeholder holdings', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify(ADVISORY), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      ),
    );
    renderAt(<AdvisoryPanel onClose={vi.fn()} />, 'complete', { numRounds: 2, roundNum: 2 });
    expect(await screen.findByText('SELL 100%')).toBeTruthy();
    expect(screen.getByText('dominant of 1 conviction items')).toBeTruthy();
    const tags = screen.getAllByText('PLACEHOLDER');
    expect(tags).toHaveLength(1);
    expect(tags[0]?.closest('.adv-qh-row')?.textContent).toContain('QQQX');
    // A file without swarm fields renders "no swarm evidence"; values are cost basis.
    expect(screen.getAllByText('no swarm evidence')).toHaveLength(2);
    expect(screen.getByText('cost basis · 2 holdings')).toBeTruthy();
    expect(screen.queryByText('DIVERGES')).toBeNull();
  });
});
