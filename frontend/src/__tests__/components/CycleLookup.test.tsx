// @vitest-environment happy-dom
// Report and advisory views opened while the newest completed cycle is still
// being looked up (GET /api/replay/cycles in flight). The lookup's state is
// module-wide, so these tests run in order: a first open, then a reopen.
import { act, cleanup, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ReportModal } from '../../features/report/ReportModal';
import { AdvisoryV2 } from '../../components/v2';
import { renderAt } from '../helpers/lifecycleFrames';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

/** Stub fetch so /api/replay/cycles answers only when the returned function is called. */
function holdCyclesLookup(): (cycles: unknown[]) => Promise<void> {
  let release!: (cycles: unknown[]) => void;
  const answer = new Promise<unknown[]>((resolve) => {
    release = resolve;
  });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
      if (url.startsWith('/api/replay/cycles')) return json({ cycles: await answer });
      return json({ detail: { error: 'not_mocked', message: url } }, 404);
    }),
  );
  return async (cycles) => {
    await act(async () => {
      release(cycles);
      await answer;
    });
  };
}

describe('default cycle lookup', () => {
  it('report: the first open says it is looking, not that there is no cycle', async () => {
    const answer = holdCyclesLookup();
    renderAt(<ReportModal onClose={() => {}} />, 'idle');
    expect(screen.queryByText('Finding the latest completed cycle…')).not.toBeNull();
    expect(screen.queryByText('No completed cycle to report on.')).toBeNull();
    await answer([]);
    expect(await screen.findByText('No completed cycle to report on.')).toBeDefined();
    expect(screen.queryByText('Finding the latest completed cycle…')).toBeNull();
  });

  it('advisory: a later open looks again instead of trusting the old empty answer', async () => {
    const answer = holdCyclesLookup();
    renderAt(<AdvisoryV2 onClose={() => {}} />, 'idle');
    expect(screen.queryByText('Finding the latest completed cycle…')).not.toBeNull();
    expect(screen.queryByText('No completed cycle to advise on.')).toBeNull();
    await answer([]);
    expect(await screen.findByText('No completed cycle to advise on.')).toBeDefined();
  });
});
