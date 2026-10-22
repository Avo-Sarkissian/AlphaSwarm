// @vitest-environment happy-dom
// usePrivacyFacts: one GET /api/settings per mount, plus a setter for settings the
// caller already holds (the config a Settings save returned). getSettings is mocked.
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { getSettings, type RoleView, type SettingsView } from '../../api/settings';
import { usePrivacyFacts } from '../../hooks/usePrivacyFacts';

vi.mock('../../api/settings', () => ({ getSettings: vi.fn() }));

const getSettingsMock = vi.mocked(getSettings);

const LOCAL_ROLE: RoleView = {
  provider: 'ollama',
  model: 'alphaswarm-worker',
  base_url: null,
  api_key: { set: false, last4: null },
};
const ANTHROPIC_ROLE: RoleView = {
  provider: 'anthropic',
  model: 'claude-test',
  base_url: null,
  api_key: { set: true, last4: '0000' },
};

function settingsView(worker: RoleView): SettingsView {
  return {
    config: {
      orchestrator: LOCAL_ROLE,
      worker,
      limits: {},
      spend_cap_usd: null,
      pricing_overrides: {},
      allow_cloud_advisory: false,
    },
    mode: worker === LOCAL_ROLE ? 'local' : 'mixed',
    available_local_models: [],
    known_api_models: [],
    provider_presets: [],
  };
}

afterEach(() => {
  cleanup();
  getSettingsMock.mockReset();
});

describe('usePrivacyFacts', () => {
  it('maps the fetched settings to facts', async () => {
    getSettingsMock.mockResolvedValue(settingsView(LOCAL_ROLE));
    const { result } = renderHook(() => usePrivacyFacts());
    expect(result.current[0]).toBeNull();
    await waitFor(() => expect(result.current[0]?.mode).toBe('local'));
  });

  it('keeps settings set by the caller over a slower first fetch', async () => {
    let answer: (view: SettingsView) => void = () => undefined;
    getSettingsMock.mockReturnValue(
      new Promise<SettingsView>((resolve) => {
        answer = resolve;
      }),
    );
    const { result } = renderHook(() => usePrivacyFacts());

    act(() => result.current[1](settingsView(ANTHROPIC_ROLE)));
    expect(result.current[0]?.mode).toBe('mixed');

    await act(async () => answer(settingsView(LOCAL_ROLE)));
    expect(result.current[0]?.mode).toBe('mixed');
    expect(getSettingsMock).toHaveBeenCalledTimes(1);
  });
});
