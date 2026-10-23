// @vitest-environment happy-dom
// The topbar mode chip shows what GET /api/health reports and never guesses
// "Local" before an answer arrives or after the request fails.
import { cleanup, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ModelStatus } from '../../features/advisory/AdvisoryPanel';
import { stubFetchRoutes } from '../helpers/fetchRoutes';
import { renderAt } from '../helpers/lifecycleFrames';
import { renderWithFrame } from '../helpers/renderWithFrame';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function chipText(): string {
  return document.querySelector('.ms-name')?.textContent ?? '';
}

describe('ModelStatus mode chip', () => {
  it('says it is checking, not Local, until /api/health answers', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => undefined)));
    renderWithFrame(<ModelStatus />);
    expect(chipText()).toBe('Checking…');
  });

  it('says the mode is unknown, not Local, when /api/health fails', async () => {
    stubFetchRoutes({
      'GET /api/health': {
        status: 502,
        body: { detail: { error: 'backend_unreachable', message: 'Backend unreachable' } },
      },
    });
    renderWithFrame(<ModelStatus />);
    await waitFor(() => expect(chipText()).toBe('Mode unknown'));
  });

  it('shows the mode /api/health reports', async () => {
    stubFetchRoutes({ 'GET /api/health': { body: { inference_mode: 'mixed', spent_usd: null } } });
    renderWithFrame(<ModelStatus />);
    await waitFor(() => expect(chipText()).toBe('Mixed'));
  });
});

describe('ModelStatus round', () => {
  it('shows the round against num_rounds', async () => {
    stubFetchRoutes({ 'GET /api/health': { body: { status: 'ok', inference_mode: 'local', spent_usd: null } } });
    renderAt(<ModelStatus />, 'live', { numRounds: 2, roundNum: 2 });
    expect(await screen.findByText('round 2/2')).toBeDefined();
  });
});
