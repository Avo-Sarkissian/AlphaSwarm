// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, screen } from '@testing-library/react';
import { ReportModal } from '../../components/ReportModal';
import { renderWithFrame } from '../helpers/renderWithFrame';

const CYCLE = '00000000-0000-4000-8000-0000000000a1';
const SECTIONS = {
  summary: 'Consensus ended BUY.',
  convergence: [
    { round_num: 1, buy_count: 40, sell_count: 30, hold_count: 28, parse_error_count: 2, total: 100 },
    { round_num: 2, buy_count: 48, sell_count: 24, hold_count: 26, parse_error_count: 2, total: 100 },
  ],
  influence: [
    { agent_id: 'sell_side_03', name: 'Sell-Side 3', bracket: 'sell_side', citation_count: 9, influence_share: 0.09 },
  ],
  moments: [],
  dissent: [],
  followups: [],
};
const MARKDOWN_WITH_FAKE_SECTION = '# Post-Simulation Analysis Report\n\n## Convergence\n| 1 | BUY | 0.65 |\n';

function stubFetch(report: unknown): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body = url.startsWith(`/api/report/${CYCLE}`) ? report : { cycles: [], next_before: null };
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }),
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('ReportModal sections', () => {
  it('renders the convergence and influence charts from sections', async () => {
    stubFetch({ cycle_id: CYCLE, content: '# Post-Simulation Analysis Report\n', generated_at: 't', sections: SECTIONS });
    renderWithFrame(<ReportModal cycleId={CYCLE} onClose={() => {}} />);
    expect(await screen.findByTestId('report-convergence-chart')).toBeTruthy();
    expect(screen.getByText('R1')).toBeTruthy();
    expect(screen.getByText('R2')).toBeTruthy();
    expect(screen.getByTestId('report-influence-chart').textContent).toContain('sell_side_03');
  });

  it('shows only the markdown for a legacy report without sections', async () => {
    stubFetch({ cycle_id: CYCLE, content: MARKDOWN_WITH_FAKE_SECTION, generated_at: 't', sections: null });
    renderWithFrame(<ReportModal cycleId={CYCLE} onClose={() => {}} />);
    expect(await screen.findByText(/Post-Simulation Analysis Report/)).toBeTruthy();
    expect(screen.queryByTestId('report-convergence-chart')).toBeNull();
    expect(screen.queryByTestId('report-influence-chart')).toBeNull();
  });
});
