// @vitest-environment happy-dom
// Settings → Model's cloud-advisory opt-in and the privacy copy it feeds
// (docs/DECISIONS.md#adr-advisory-pipeline). The backend is stubbed per route.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { RoleView, SettingsView } from '../../api/settings';
import { InferenceSettings } from '../../components/settings_inference';
import { stubFetchRoutes } from '../helpers/fetchRoutes';

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
});
