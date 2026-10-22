// Privacy copy is derived from the live inference settings
// (docs/DECISIONS.md#adr-local-first-inference).
// Pure functions only: this suite runs in the node environment.
import { describe, expect, it } from 'vitest';
import type { RoleView, SettingsView } from '../../api/settings';
import {
  CHECKING_LINE,
  ONBOARDING_PRIVACY_LINE,
  advisoryLine,
  advisoryOptInHelp,
  cloudRolesSummary,
  dataSourcesNote,
  hostOf,
  isCloudOllamaModel,
  isOffMachine,
  modeLabel,
  privacyFactsFromSettings,
  privacyLines,
  roleLine,
} from '../../lib/privacyCopy';

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
const OPENROUTER_ROLE: RoleView = {
  provider: 'openai_compatible',
  model: 'meta-llama/llama-3.3-70b-instruct',
  base_url: 'https://openrouter.ai/api/v1',
  api_key: { set: true, last4: '1111' },
};

function view(
  orchestrator: RoleView,
  worker: RoleView,
  mode: SettingsView['mode'],
  allowCloudAdvisory?: boolean,
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
    mode,
    available_local_models: [],
    known_api_models: [],
    provider_presets: [],
  };
}

describe('privacyFactsFromSettings + privacyLines', () => {
  it('local mode keeps every role and the advisory on this machine', () => {
    const facts = privacyFactsFromSettings(view(LOCAL_ROLE, LOCAL_ROLE, 'local'));
    expect(privacyLines(facts).map((l) => l.text)).toEqual([
      'Prompts for the orchestrator role stay on this machine (local Ollama).',
      'Prompts for the worker role stay on this machine (local Ollama).',
      'The advisory runs on local Ollama; your holdings never leave this machine.',
    ]);
    expect(privacyLines(facts).every((l) => !l.offMachine)).toBe(true);
  });

  it('mixed mode names the cloud host for the cloud role', () => {
    const facts = privacyFactsFromSettings(view(LOCAL_ROLE, OPENROUTER_ROLE, 'mixed'));
    expect(roleLine('worker', facts.worker)).toBe(
      'Prompts for the worker role are sent to an OpenAI-compatible API (openrouter.ai).',
    );
    expect(privacyLines(facts)[1].offMachine).toBe(true);
    expect(advisoryLine(facts)).toBe(
      'The advisory runs on local Ollama; your holdings never leave this machine.',
    );
  });

  it('a cloud orchestrator without the opt-in says the advisory is off', () => {
    const facts = privacyFactsFromSettings(view(ANTHROPIC_ROLE, LOCAL_ROLE, 'mixed', false));
    const line = advisoryLine(facts);
    expect(line).toContain('The advisory is off');
    expect(line).toContain('Anthropic (api.anthropic.com)');
    expect(line).not.toContain('never leave this machine');
    expect(privacyLines(facts)[2].offMachine).toBe(false);
  });

  it('a cloud orchestrator with the opt-in says exactly what is sent', () => {
    const facts = privacyFactsFromSettings(view(ANTHROPIC_ROLE, ANTHROPIC_ROLE, 'cloud', true));
    expect(advisoryLine(facts)).toBe(
      'The advisory sends your held tickers (never quantities or cost basis) to Anthropic (api.anthropic.com).',
    );
    expect(privacyLines(facts).every((l) => l.offMachine)).toBe(true);
    expect(privacyLines(facts).some((l) => l.text.includes('this machine'))).toBe(false);
  });

  it('a missing opt-in flag counts as off', () => {
    const facts = privacyFactsFromSettings(view(ANTHROPIC_ROLE, LOCAL_ROLE, 'mixed'));
    expect(facts.allowCloudAdvisory).toBe(false);
  });
});

describe('helpers', () => {
  it('hostOf handles defaults and bad URLs', () => {
    expect(hostOf('ollama', 'http://localhost:11434')).toBeNull();
    expect(hostOf('anthropic', null)).toBe('api.anthropic.com');
    expect(hostOf('openai_compatible', null)).toBeNull();
    expect(hostOf('openai_compatible', 'not a url')).toBeNull();
    expect(hostOf('openai_compatible', 'https://integrate.api.nvidia.com/v1')).toBe(
      'integrate.api.nvidia.com',
    );
  });

  it('copy that is still loading never claims "local"', () => {
    expect(privacyLines(null).map((l) => l.text)).toEqual([CHECKING_LINE]);
    expect(advisoryLine(null)).toBe(CHECKING_LINE);
    expect(dataSourcesNote(null)).toContain(CHECKING_LINE);
    expect(modeLabel(null)).toBe('checking…');
    expect(cloudRolesSummary(null)).toBe('checking…');
  });

  it('labels modes and cloud roles', () => {
    expect(modeLabel('local')).toBe('local only');
    expect(modeLabel('mixed')).toBe('local + cloud');
    expect(modeLabel('cloud')).toBe('cloud inference');
    const mixed = privacyFactsFromSettings(view(LOCAL_ROLE, OPENROUTER_ROLE, 'mixed'));
    expect(cloudRolesSummary(mixed)).toBe('worker');
    const local = privacyFactsFromSettings(view(LOCAL_ROLE, LOCAL_ROLE, 'local'));
    expect(cloudRolesSummary(local)).toBe('none (local only)');
  });

  it('the onboarding line makes no absolute local claim', () => {
    // Phrases are assembled from fragments so a grep for the old claims finds nothing here.
    const absolute = ['no cloud', 'no api keys', 'leaves your machine', ['100', '% local'].join('')];
    for (const phrase of absolute) {
      expect(ONBOARDING_PRIVACY_LINE.toLowerCase()).not.toContain(phrase);
    }
    expect(ONBOARDING_PRIVACY_LINE).toContain('local Ollama by default');
  });

  it('the opt-in help names what is and is not sent', () => {
    const facts = privacyFactsFromSettings(view(OPENROUTER_ROLE, LOCAL_ROLE, 'mixed'));
    const help = advisoryOptInHelp(facts.orchestrator);
    expect(help).toContain('never quantities or cost basis');
    expect(help).toContain('openrouter.ai');
  });
});

// The backend treats an Ollama cloud model and a non-loopback Ollama server as
// off-machine and refuses the advisory without the opt-in
// (docs/DECISIONS.md#adr-advisory-pipeline); the copy must not call them local.
describe('off-machine Ollama roles', () => {
  const CLOUD_OLLAMA_ROLE: RoleView = { ...LOCAL_ROLE, model: 'gpt-oss:120b-cloud' };
  const REMOTE_OLLAMA_ROLE: RoleView = { ...LOCAL_ROLE, base_url: 'http://192.0.2.10:11434' };

  it('recognises Ollama cloud model names like the backend', () => {
    expect(isCloudOllamaModel('gpt-oss:120b-cloud')).toBe(true);
    expect(isCloudOllamaModel('glm-4.6:cloud')).toBe(true);
    expect(isCloudOllamaModel('My-Model-Cloud:latest')).toBe(true);
    expect(isCloudOllamaModel('qwen3:cloud-preview')).toBe(true);
    expect(isCloudOllamaModel('library/glm-4.6:cloud@sha256')).toBe(true);
    expect(isCloudOllamaModel('cloudy-model')).toBe(false);
    expect(isCloudOllamaModel('alphaswarm-worker')).toBe(false);
  });

  it('hostOf keeps loopback Ollama local and names a remote one', () => {
    expect(hostOf('ollama', null)).toBeNull();
    expect(hostOf('ollama', 'http://127.0.0.1:11434')).toBeNull();
    expect(hostOf('ollama', 'http://[::1]:11434')).toBeNull();
    expect(hostOf('ollama', 'localhost:11434')).toBeNull();
    expect(hostOf('ollama', 'http://[::ffff:127.0.0.1]:11434')).toBeNull();
    expect(hostOf('ollama', 'http://192.0.2.10:11434')).toBe('192.0.2.10:11434');
    expect(hostOf('ollama', 'http://0.0.0.0:11434')).toBe('0.0.0.0:11434');
  });

  it('an Ollama cloud-model orchestrator blocks the advisory without the opt-in', () => {
    const facts = privacyFactsFromSettings(view(CLOUD_OLLAMA_ROLE, LOCAL_ROLE, 'local'));
    expect(isOffMachine(facts.orchestrator)).toBe(true);
    expect(facts.mode).toBe('mixed');
    expect(roleLine('orchestrator', facts.orchestrator)).toBe(
      'Prompts for the orchestrator role are sent to Ollama cloud (ollama.com).',
    );
    const line = advisoryLine(facts);
    expect(line).toContain('The advisory is off');
    expect(line).not.toContain('never leave this machine');
    expect(cloudRolesSummary(facts)).toBe('orchestrator');
  });

  it('a remote Ollama worker is named and never called local', () => {
    const facts = privacyFactsFromSettings(view(LOCAL_ROLE, REMOTE_OLLAMA_ROLE, 'local'));
    expect(roleLine('worker', facts.worker)).toBe(
      'Prompts for the worker role are sent to a remote Ollama server (192.0.2.10:11434).',
    );
    expect(privacyLines(facts)[1].offMachine).toBe(true);
    expect(dataSourcesNote(facts)).not.toContain('this machine');
  });

  it('a remote Ollama orchestrator blocks the advisory without the opt-in', () => {
    const facts = privacyFactsFromSettings(view(REMOTE_OLLAMA_ROLE, LOCAL_ROLE, 'local'));
    expect(advisoryLine(facts)).toBe(
      'The advisory is off: the orchestrator runs on a remote Ollama server (192.0.2.10:11434) and cloud advisory is not enabled in Settings.',
    );
    expect(privacyLines(facts)[2].offMachine).toBe(false);
  });
});
