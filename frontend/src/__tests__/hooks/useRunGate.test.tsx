// @vitest-environment happy-dom
// useRunGate drives the real RunConfirmModal; getEstimate and simStart are mocked.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../api/client';
import { getEstimate, type RunEstimate } from '../../api/settings';
import { simStart } from '../../api/simulation';
import { useRunGate } from '../../hooks/useRunGate';

vi.mock('../../api/settings', () => ({ getEstimate: vi.fn() }));
vi.mock('../../api/simulation', () => ({ simStart: vi.fn() }));

const getEstimateMock = vi.mocked(getEstimate);
const simStartMock = vi.mocked(simStart);

const SEED = 'ZZZT Holdings is in late-stage talks to acquire QQQX Robotics for $4.2B in cash.';
const LOCAL: RunEstimate = { calls: 300, low_usd: '0.00', high_usd: '0.00', mode: 'local' };
const CLOUD: RunEstimate = { calls: 300, low_usd: '0.12', high_usd: '0.45', mode: 'cloud' };

function Harness({ onSettled }: { onSettled: (ok: boolean) => void }) {
  const gate = useRunGate({ onSettled });
  return (
    <div>
      <button type="button" onClick={() => gate.requestRun(SEED)}>request</button>
      <span data-testid="pending">{String(gate.pending)}</span>
      <span data-testid="error">{gate.error ?? ''}</span>
      {gate.modal}
    </div>
  );
}

function setup() {
  const onSettled = vi.fn();
  render(<Harness onSettled={onSettled} />);
  return onSettled;
}

beforeEach(() => {
  getEstimateMock.mockReset();
  simStartMock.mockReset();
});

afterEach(cleanup);

describe('useRunGate', () => {
  it('starts a local run directly and settles ok', async () => {
    getEstimateMock.mockResolvedValue(LOCAL);
    simStartMock.mockResolvedValue({ status: 'accepted', message: 'Simulation started' });
    const onSettled = setup();
    fireEvent.click(screen.getByText('request'));
    await waitFor(() => expect(onSettled).toHaveBeenCalledWith(true));
    expect(simStartMock).toHaveBeenCalledWith(SEED);
    expect(screen.getByTestId('pending').textContent).toBe('false');
    expect(screen.getByTestId('error').textContent).toBe('');
  });

  it('surfaces post_run_jobs_in_progress and settles', async () => {
    getEstimateMock.mockResolvedValue(LOCAL);
    simStartMock.mockRejectedValue(
      new ApiError(
        409,
        { detail: { error: 'post_run_jobs_in_progress', message: 'The advisory/report jobs are using the orchestrator; retry when they finish' } },
        '/api/simulate/start',
      ),
    );
    const onSettled = setup();
    fireEvent.click(screen.getByText('request'));
    await waitFor(() => expect(onSettled).toHaveBeenCalledWith(false));
    expect(screen.getByTestId('error').textContent).toBe(
      'The advisory/report jobs are using the orchestrator; retry when they finish',
    );
    expect(screen.getByTestId('pending').textContent).toBe('false');
  });

  it('turns a network failure into a reachability hint', async () => {
    getEstimateMock.mockResolvedValue(LOCAL);
    simStartMock.mockRejectedValue(new TypeError('Failed to fetch'));
    const onSettled = setup();
    fireEvent.click(screen.getByText('request'));
    await waitFor(() => expect(onSettled).toHaveBeenCalledWith(false));
    expect(screen.getByTestId('error').textContent).toBe(
      'Cannot reach the backend. Is it running on port 8000?',
    );
  });

  it('settles with false on cancel and never starts', async () => {
    getEstimateMock.mockResolvedValue(CLOUD);
    const onSettled = setup();
    fireEvent.click(screen.getByText('request'));
    await screen.findByRole('button', { name: /confirm & run/i });
    expect(screen.getByTestId('pending').textContent).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onSettled).toHaveBeenCalledWith(false);
    expect(screen.getByTestId('pending').textContent).toBe('false');
    expect(screen.queryByRole('button', { name: /confirm & run/i })).toBeNull();
    expect(simStartMock).not.toHaveBeenCalled();
  });

  it('reports a failed confirm instead of leaking a rejection', async () => {
    getEstimateMock.mockResolvedValue(CLOUD);
    simStartMock.mockRejectedValue(
      new ApiError(409, { detail: { error: 'simulation_already_running', message: 'Simulation already running' } }, '/api/simulate/start'),
    );
    const onSettled = setup();
    fireEvent.click(screen.getByText('request'));
    fireEvent.click(await screen.findByRole('button', { name: /confirm & run/i }));
    await waitFor(() => expect(onSettled).toHaveBeenCalledWith(false));
    expect(screen.getByTestId('error').textContent).toBe('Simulation already running');
    expect(screen.queryByRole('button', { name: /confirm & run/i })).toBeNull();
  });

  it('still asks for confirmation when the estimate fails', async () => {
    getEstimateMock.mockRejectedValue(new Error('estimate down'));
    simStartMock.mockResolvedValue({ status: 'accepted', message: 'Simulation started' });
    const onSettled = setup();
    fireEvent.click(screen.getByText('request'));
    expect(await screen.findByText(/Cost estimate unavailable/)).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: /confirm & run/i }));
    await waitFor(() => expect(onSettled).toHaveBeenCalledWith(true));
  });

  it('starts once on a double click', async () => {
    getEstimateMock.mockResolvedValue(LOCAL);
    simStartMock.mockResolvedValue({ status: 'accepted', message: 'Simulation started' });
    const onSettled = setup();
    fireEvent.click(screen.getByText('request'));
    fireEvent.click(screen.getByText('request'));
    await waitFor(() => expect(onSettled).toHaveBeenCalledTimes(1));
    expect(getEstimateMock).toHaveBeenCalledTimes(1);
    expect(simStartMock).toHaveBeenCalledTimes(1);
  });
});
