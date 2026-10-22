// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Onboarding } from '../../components/onboarding';
import { stubFetchRoutes } from '../helpers/fetchRoutes';

const SEED = 'ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash.';
const CLOUD_ESTIMATE = { calls: 300, low_usd: '0.12', high_usd: '0.45', mode: 'cloud' };

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function openSeedStep() {
  fireEvent.click(screen.getByRole('button', { name: /get started/i }));
  await screen.findByText(/Backend (OK|ready)/);
}

describe('Onboarding run', () => {
  it('returns to a usable Run button after cancelling the cloud confirm', async () => {
    stubFetchRoutes({
      'GET /api/health': { body: { status: 'ok' } },
      'GET /api/settings/estimate': { body: CLOUD_ESTIMATE },
    });
    const onComplete = vi.fn();
    render(<Onboarding onComplete={onComplete} />);
    await openSeedStep();
    fireEvent.change(screen.getByPlaceholderText(/Fed announces/), { target: { value: SEED } });
    fireEvent.click(screen.getByRole('button', { name: /run first cycle/i }));
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }));
    const run = await screen.findByRole('button', { name: /run first cycle/i });
    expect((run as HTMLButtonElement).disabled).toBe(false);
    expect(onComplete).not.toHaveBeenCalled();
  });
});
