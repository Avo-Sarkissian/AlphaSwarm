// @vitest-environment happy-dom
// Settings → Model's cloud-advisory opt-in and the privacy copy it feeds
// (docs/DECISIONS.md#adr-advisory-pipeline). The backend is stubbed per route.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { RoleView, SettingsView } from '../../api/settings';
import { Settings } from '../../components/settings';
import { InferenceSettings } from '../../components/settings_inference';
import { stubFetchRoutes } from '../helpers/fetchRoutes';
import { renderWithFrame } from '../helpers/renderWithFrame';

const LOCAL_ROLE: RoleView = {
  provider: 'ollama',
  model: 'alphaswarm-orchestrator',
  base_url: null,
  api_key: { set: false, last4: null },
};
const ANTHROPIC_ROLE: RoleView = {
  provider: 'anthropic',
  model: 'claude-test',
  base_url: null,
  api_key: { set: true, last4: '0000' },
};
const OPENROUTER_ROLE: RoleView = {
  provider: 'openai_compatible',
  model: 'meta-llama/llama-3.3-70b-instruct',
  base_url: 'https://openrouter.ai/api/v1',
  api_key: { set: true, last4: '1111' },
};

function settingsView(
  orchestrator: RoleView,
  worker: RoleView,
  allowCloudAdvisory: boolean,
): SettingsView {
  return {
    config: {
      orchestrator,
      worker,
      limits: {},
      spend_cap_usd: null,
      pricing_overrides: {},
      allow_cloud_advisory: allowCloudAdvisory,
    },
    mode: 'local',
    available_local_models: [],
    known_api_models: [],
    provider_presets: [],
  };
}

/** The Provider select of one role form (no presets, so it is the only select). */
function providerSelect(role: 'Orchestrator' | 'Worker'): HTMLSelectElement {
  const block = screen.getByText(role).closest('.st-inf-role') as HTMLElement;
  return block.querySelector('select') as HTMLSelectElement;
}

const HEALTH = {
  status: 'ok',
  inference_mode: 'local',
  spent_usd: null,
  version: '0.0.0-test',
  components: {},
};

/** Open one Settings section from the side nav. */
function openSection(name: 'Runtime' | 'Model' | 'API keys' | 'Storage' | 'Privacy') {
  fireEvent.click(screen.getByRole('button', { name }));
}

/** The parsed JSON bodies of every PUT the component sent. */
function putBodies(fetchMock: ReturnType<typeof stubFetchRoutes>): Array<Record<string, unknown>> {
  return fetchMock.mock.calls
    .filter(([, init]) => init?.method === 'PUT')
    .map(([, init]) => JSON.parse(String(init?.body)) as Record<string, unknown>);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('the cloud-advisory opt-in', () => {
  it('stays visible with a local orchestrator while it is stored, so it can be cleared', async () => {
    const stored = settingsView(LOCAL_ROLE, LOCAL_ROLE, true);
    const fetchMock = stubFetchRoutes({
      'GET /api/settings': { body: stored },
      'PUT /api/settings': {
        body: { config: settingsView(LOCAL_ROLE, LOCAL_ROLE, false).config, mode: 'local' },
      },
    });
    render(<InferenceSettings />);

    const box = (await screen.findByLabelText('Allow cloud advisory')) as HTMLInputElement;
    expect(box.checked).toBe(true);
    expect(screen.getByText(/skips the checks that keep it on this machine/)).toBeDefined();
    expect(screen.queryByText(/the advisory is skipped/)).toBeNull();

    // Unticked but not yet saved: the stored opt-in keeps the box on screen.
    fireEvent.click(box);
    expect(screen.queryByLabelText('Allow cloud advisory')).not.toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await screen.findByText('Saved.');
    expect(putBodies(fetchMock)[0]?.allow_cloud_advisory).toBe(false);
    await waitFor(() => expect(screen.queryByLabelText('Allow cloud advisory')).toBeNull());
  });

  it('stays visible when a ticked box meets an orchestrator switched to local', async () => {
    stubFetchRoutes({ 'GET /api/settings': { body: settingsView(ANTHROPIC_ROLE, LOCAL_ROLE, false) } });
    render(<InferenceSettings />);

    fireEvent.click(await screen.findByLabelText('Allow cloud advisory'));
    fireEvent.change(providerSelect('Orchestrator'), { target: { value: 'ollama' } });

    const box = screen.getByLabelText('Allow cloud advisory') as HTMLInputElement;
    expect(box.checked).toBe(true);
    expect(screen.getByText(/The orchestrator looks local/)).toBeDefined();
  });

  it('describes the orchestrator Save will store, not a base URL it drops', async () => {
    // Save sends base_url only for an OpenAI-compatible role (formToRolePut), so a
    // URL left in the form after a provider switch is not where prompts go.
    stubFetchRoutes({ 'GET /api/settings': { body: settingsView(OPENROUTER_ROLE, LOCAL_ROLE, false) } });
    render(<InferenceSettings />);
    expect(await screen.findByText(/openrouter\.ai/)).toBeDefined();

    fireEvent.change(providerSelect('Orchestrator'), { target: { value: 'anthropic' } });
    expect(screen.getByText(/to Anthropic \(api\.anthropic\.com\)/)).toBeDefined();
    expect(screen.queryByText(/openrouter\.ai/)).toBeNull();

    fireEvent.change(providerSelect('Orchestrator'), { target: { value: 'ollama' } });
    expect(screen.queryByLabelText('Allow cloud advisory')).toBeNull();
  });
});

describe('the opt-in in the PUT body', () => {
  // The backend keeps the stored value when the field is missing, so a body without
  // it would make unticking the box do nothing.
  it('sends the box state with every save of a cloud orchestrator', async () => {
    const fetchMock = stubFetchRoutes({
      'GET /api/settings': { body: settingsView(ANTHROPIC_ROLE, LOCAL_ROLE, true) },
      'PUT /api/settings': (call) => ({
        body: { config: settingsView(ANTHROPIC_ROLE, LOCAL_ROLE, call !== 1).config, mode: 'mixed' },
      }),
    });
    render(<InferenceSettings />);
    const box = (await screen.findByLabelText('Allow cloud advisory')) as HTMLInputElement;
    expect(box.checked).toBe(true);

    fireEvent.click(box);
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(putBodies(fetchMock)).toHaveLength(1));
    await waitFor(() => expect(box.checked).toBe(false));

    fireEvent.click(box);
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(putBodies(fetchMock)).toHaveLength(2));
    await waitFor(() => expect(box.checked).toBe(true));

    expect(putBodies(fetchMock).map((body) => body.allow_cloud_advisory)).toEqual([false, true]);
  });
});

describe('Settings privacy copy', () => {
  it('follows a save in Settings → Model without reopening Settings', async () => {
    stubFetchRoutes({
      'GET /api/settings': { body: settingsView(LOCAL_ROLE, LOCAL_ROLE, false) },
      'GET /api/health': { body: HEALTH },
      'PUT /api/settings': {
        body: { config: settingsView(LOCAL_ROLE, ANTHROPIC_ROLE, false).config, mode: 'mixed' },
      },
    });
    renderWithFrame(<Settings onClose={vi.fn()} />);
    expect(await screen.findByText('local only')).toBeDefined();
    openSection('Privacy');
    expect(
      screen.getByText('Prompts for the worker role stay on this machine (local Ollama).'),
    ).toBeDefined();

    openSection('Model');
    await screen.findByText('Worker');
    fireEvent.change(providerSelect('Worker'), { target: { value: 'anthropic' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await screen.findByText('Saved.');

    openSection('Privacy');
    expect(
      screen.getByText('Prompts for the worker role are sent to Anthropic (api.anthropic.com).'),
    ).toBeDefined();
    expect(screen.getByText('local + cloud')).toBeDefined();
    openSection('API keys');
    expect(screen.getByDisplayValue('worker')).toBeDefined();
  });

  it('says the settings could not be read instead of checking forever', async () => {
    stubFetchRoutes({
      'GET /api/settings': {
        status: 422,
        body: { detail: { error: 'inference_config_invalid', message: 'Inference config is invalid' } },
      },
      'GET /api/health': { body: HEALTH },
    });
    renderWithFrame(<Settings onClose={vi.fn()} />);
    expect(await screen.findByText('mode unknown')).toBeDefined();
    openSection('Privacy');
    expect(screen.getByText(/Could not read the inference settings/)).toBeDefined();
    expect(screen.queryByText(/Checking where prompts are sent/)).toBeNull();
  });
});

describe('Settings rows the backend can override', () => {
  // This page cannot see the backend's environment, so these rows show the
  // default and name the variable that changes it instead of posing as live.
  it('label storage paths and addresses as defaults with their variables', async () => {
    stubFetchRoutes({
      'GET /api/settings': { body: settingsView(LOCAL_ROLE, LOCAL_ROLE, false) },
      'GET /api/health': { body: HEALTH },
    });
    renderWithFrame(<Settings onClose={vi.fn()} />);
    await screen.findByText('local only');

    openSection('Storage');
    expect((screen.getByLabelText('Graph database') as HTMLInputElement).value).toBe(
      'bolt://localhost:7687',
    );
    expect(screen.getByText(/ALPHASWARM_NEO4J__URI/)).toBeDefined();
    expect(screen.getByText(/ALPHASWARM_REPORTS_DIR/)).toBeDefined();
    expect(screen.getByText(/ALPHASWARM_ADVISORY_DIR/)).toBeDefined();
    expect(screen.queryByText(/loopback only/)).toBeNull();

    openSection('API keys');
    expect((screen.getByLabelText('Key file') as HTMLInputElement).value).toBe(
      '.secrets/inference.json',
    );
    expect(screen.getByText(/ALPHASWARM_INFERENCE_CONFIG_PATH/)).toBeDefined();
  });
});

describe('Settings inference slots row', () => {
  function stubBackend() {
    stubFetchRoutes({
      'GET /api/settings': { body: settingsView(LOCAL_ROLE, LOCAL_ROLE, false) },
      'GET /api/health': { body: HEALTH },
    });
  }

  it('shows the governor slots once the governor has reported', async () => {
    stubBackend();
    renderWithFrame(<Settings onClose={vi.fn()} />); // live fixture: 12 of 16 slots
    await screen.findByText('local only');
    expect(screen.getByDisplayValue('12 in use / 16 allowed now')).toBeDefined();
  });

  it('says the governor has not reported instead of "0 allowed"', async () => {
    // The wire's placeholder before the governor first reports (idle, replay, cloud).
    stubBackend();
    renderWithFrame(<Settings onClose={vi.fn()} />, {
      frame: {
        telemetry: {
          memMb: 61.2,
          slotsUsed: 0,
          slotsMax: 0,
          governorState: 'idle',
          tps: 0,
          ts: 0,
          elapsedSeconds: 0,
        },
      },
    });
    await screen.findByText('local only');
    expect(screen.queryByDisplayValue(/0 allowed/)).toBeNull();
    expect(screen.getByDisplayValue(/not reported yet/)).toBeDefined();
  });
});
