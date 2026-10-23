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

describe('Onboarding health gate', () => {
  // Cloud mode with Neo4j stopped: only Neo4j is required, so only Neo4j is down.
  const neo4jDown = {
    status: 'degraded',
    components: {
      neo4j: {
        ok: false,
        required: true,
        detail: 'unreachable (ServiceUnavailable)',
        fix: 'Start Neo4j (docker compose up -d neo4j)',
        missing: [],
      },
      ollama: { ok: false, required: false, detail: 'unreachable (ConnectError)', fix: null, missing: [] },
      aliases: {
        ok: false,
        required: false,
        detail: 'not checked: Ollama is not reachable',
        fix: null,
        missing: [],
      },
    },
  };

  it('reports a degraded backend as degraded, names what is down and keeps Run disabled', async () => {
    stubFetchRoutes({ 'GET /api/health': { body: neo4jDown } });
    render(<Onboarding onComplete={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /get started/i }));
    expect(await screen.findByText(/Backend degraded/)).toBeDefined();
    expect(screen.queryByText(/Backend unreachable/)).toBeNull();
    expect(screen.getAllByText(/neo4j/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/ollama|aliases/i)).toBeNull();
    fireEvent.change(screen.getByPlaceholderText(/Fed announces/), { target: { value: SEED } });
    const run = screen.getByRole('button', { name: /fix the items above first/i });
    expect((run as HTMLButtonElement).disabled).toBe(true);
  });
});

const HEALTH_DEGRADED = {
  status: 'degraded',
  components: {
    neo4j: { ok: true, required: true, detail: null, fix: null, missing: [] },
    ollama: { ok: true, required: true, detail: null, fix: null, missing: [] },
    aliases: {
      ok: false,
      required: true,
      detail: 'missing: alphaswarm-worker',
      fix: 'ollama create alphaswarm-worker -f modelfiles/Modelfile.worker',
      missing: ['alphaswarm-worker'],
    },
  },
};
const HEALTH_OK = {
  status: 'ok',
  components: {
    neo4j: { ok: true, required: true, detail: null, fix: null, missing: [] },
    ollama: { ok: true, required: true, detail: null, fix: null, missing: [] },
    aliases: { ok: true, required: true, detail: null, fix: null, missing: [] },
  },
};

describe('Onboarding component status', () => {
  it('names the component that is down, with the command that fixes it, and blocks Run', async () => {
    stubFetchRoutes({ 'GET /api/health': { body: HEALTH_DEGRADED } });
    render(<Onboarding onComplete={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /get started/i }));
    expect(await screen.findByText('ollama create alphaswarm-worker -f modelfiles/Modelfile.worker')).toBeDefined();
    expect(screen.queryByText('aliases')).not.toBeNull();
    fireEvent.change(screen.getByPlaceholderText(/Fed announces/), { target: { value: SEED } });
    const run = screen.getByRole('button', { name: /fix the items above first/i }) as HTMLButtonElement;
    expect(run.disabled).toBe(true);
  });

  it('re-checks without a reload and enables Run once healthy', async () => {
    stubFetchRoutes({
      'GET /api/health': (call) => ({ body: call === 1 ? HEALTH_DEGRADED : HEALTH_OK }),
    });
    render(<Onboarding onComplete={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /get started/i }));
    fireEvent.click(await screen.findByRole('button', { name: 'Re-check' }));
    await screen.findByText(/Backend ready/);
    fireEvent.change(screen.getByPlaceholderText(/Fed announces/), { target: { value: SEED } });
    expect((screen.getByRole('button', { name: /run first cycle/i }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('lets the user skip to the dashboard (Settings is reachable there)', async () => {
    stubFetchRoutes({ 'GET /api/health': { body: HEALTH_DEGRADED } });
    const onComplete = vi.fn();
    render(<Onboarding onComplete={onComplete} />);
    fireEvent.click(screen.getByRole('button', { name: /get started/i }));
    fireEvent.click(await screen.findByRole('button', { name: 'Skip to dashboard' }));
    expect(onComplete).toHaveBeenCalledWith('');
  });

  it('shows a reachability hint when the backend is down', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    render(<Onboarding onComplete={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /get started/i }));
    expect(await screen.findByText(/Cannot reach the backend/)).toBeDefined();
    expect(screen.queryByRole('button', { name: 'Re-check' })).not.toBeNull();
    fireEvent.change(screen.getByPlaceholderText(/Fed announces/), { target: { value: SEED } });
    const run = screen.getByRole('button', { name: /start backend first/i }) as HTMLButtonElement;
    expect(run.disabled).toBe(true);
  });
});

// What the Vite dev proxy answers when the backend is not running.
const UNREACHABLE = {
  status: 502,
  body: {
    detail: { error: 'backend_unreachable', message: 'Cannot reach the backend. Is it running on port 8000?' },
  },
};

function healthReply(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

// Opens the seed step on a ready backend in cloud mode, types a seed and presses
// Run: the cost confirmation stays open, so the run is pending until Cancel.
async function startPendingRun() {
  stubFetchRoutes({
    'GET /api/health': { body: HEALTH_OK },
    'GET /api/settings/estimate': { body: CLOUD_ESTIMATE },
  });
  render(<Onboarding onComplete={vi.fn()} />);
  await openSeedStep();
  fireEvent.change(screen.getByPlaceholderText(/Fed announces/), { target: { value: SEED } });
  fireEvent.click(screen.getByRole('button', { name: /run first cycle/i }));
  await screen.findByRole('button', { name: 'Cancel' });
}

describe('Onboarding re-check', () => {
  it('offers Re-check while the first answer is still outstanding', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => new Promise<Response>(() => {}))
      .mockImplementation(async () => healthReply(HEALTH_OK));
    vi.stubGlobal('fetch', fetchMock);
    render(<Onboarding onComplete={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /get started/i }));
    expect(screen.getByText('Checking backend…')).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: 'Re-check' }));
    expect(await screen.findByText(/Backend ready/)).toBeDefined();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('offers Re-check once the backend is ready, so a component that stopped shows up', async () => {
    stubFetchRoutes({
      'GET /api/health': (call) => ({ body: call === 1 ? HEALTH_OK : HEALTH_DEGRADED }),
    });
    render(<Onboarding onComplete={vi.fn()} />);
    await openSeedStep();
    fireEvent.change(screen.getByPlaceholderText(/Fed announces/), { target: { value: SEED } });
    fireEvent.click(screen.getByRole('button', { name: 'Re-check' }));
    expect(await screen.findByText(/Backend degraded/)).toBeDefined();
    const run = screen.getByRole('button', { name: /fix the items above first/i }) as HTMLButtonElement;
    expect(run.disabled).toBe(true);
  });

  it('checks again when a run fails, so the status no longer says ready', async () => {
    stubFetchRoutes({
      'GET /api/health': (call) => (call === 1 ? { body: HEALTH_OK } : UNREACHABLE),
      'GET /api/settings/estimate': UNREACHABLE,
    });
    render(<Onboarding onComplete={vi.fn()} />);
    await openSeedStep();
    fireEvent.change(screen.getByPlaceholderText(/Fed announces/), { target: { value: SEED } });
    fireEvent.click(screen.getByRole('button', { name: /run first cycle/i }));
    expect(await screen.findByText(/Backend unreachable/)).toBeDefined();
    const run = screen.getByRole('button', { name: /start backend first/i }) as HTMLButtonElement;
    expect(run.disabled).toBe(true);
  });

  it('disables Re-check while a run is pending', async () => {
    await startPendingRun();
    const recheck = screen.getByRole('button', { name: 'Re-check' }) as HTMLButtonElement;
    expect(recheck.disabled).toBe(true);
  });
});

describe('Onboarding status row', () => {
  // The row's data-ok and the dot's class drive the colours in styles.css.
  it('stays neutral while a check is outstanding, then marks the answer', async () => {
    stubFetchRoutes({
      'GET /api/health': (call) => ({ body: call === 1 ? HEALTH_DEGRADED : HEALTH_OK }),
    });
    render(<Onboarding onComplete={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /get started/i }));
    const row = screen.getByText('Checking backend…').parentElement as HTMLElement;
    const dot = row.querySelector('.ob-status-dot') as HTMLElement;
    expect(row.hasAttribute('data-ok')).toBe(false);
    expect(dot.classList.contains('ok') || dot.classList.contains('err')).toBe(false);

    await screen.findByText(/Backend degraded/);
    expect(row.getAttribute('data-ok')).toBe('false');
    expect(dot.classList.contains('err')).toBe(true);

    fireEvent.click(screen.getByRole('button', { name: 'Re-check' }));
    expect(row.hasAttribute('data-ok')).toBe(false);
    await screen.findByText(/Backend ready/);
    expect(row.getAttribute('data-ok')).toBe('true');
    expect(dot.classList.contains('ok')).toBe(true);
  });
});

describe('Onboarding run gate', () => {
  it('keeps Run disabled for a seed under 10 characters and says why', async () => {
    stubFetchRoutes({ 'GET /api/health': { body: HEALTH_OK } });
    render(<Onboarding onComplete={vi.fn()} />);
    await openSeedStep();
    const input = screen.getByLabelText('Seed rumor') as HTMLInputElement;
    // Mirrors the backend's SeedText bounds: 10 to 2000 characters after stripping.
    expect(input.maxLength).toBe(2000);
    fireEvent.change(input, { target: { value: '  ZZZT up  ' } });
    const run = screen.getByRole('button', { name: /run first cycle/i }) as HTMLButtonElement;
    expect(run.disabled).toBe(true);
    expect(run.title).toMatch(/at least 10 characters/);
    fireEvent.change(input, { target: { value: SEED } });
    expect(run.disabled).toBe(false);
    expect(run.title).toBe('');
  });

  it('keeps Back and Skip to dashboard disabled while a run is pending', async () => {
    await startPendingRun();
    expect((screen.getByRole('button', { name: '← Back' }) as HTMLButtonElement).disabled).toBe(true);
    const skip = screen.getByRole('button', { name: 'Skip to dashboard' }) as HTMLButtonElement;
    expect(skip.disabled).toBe(true);
  });
});

describe('Onboarding round count', () => {
  it('names the round count the frame reports', () => {
    render(<Onboarding onComplete={vi.fn()} numRounds={2} />);
    expect(screen.queryByText('2 rounds')).not.toBeNull();
    expect(screen.queryByText(/across 2 rounds/)).not.toBeNull();
    expect(screen.queryAllByText(/3 rounds/)).toHaveLength(0);
  });

  it('names no round count before the first frame', () => {
    render(<Onboarding onComplete={vi.fn()} />);
    expect(screen.queryAllByText(/\d rounds/)).toHaveLength(0);
  });
});
