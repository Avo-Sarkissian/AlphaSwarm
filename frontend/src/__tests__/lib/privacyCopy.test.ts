// Privacy copy is derived from the live inference settings
// (docs/DECISIONS.md#adr-local-first-inference).
// Pure functions only: this suite runs in the node environment.
import { describe, expect, it } from 'vitest';
import type { RoleView, SettingsView } from '../../api/settings';
import {
  CHECKING_LINE,
  FACTS_UNAVAILABLE,
  ONBOARDING_PRIVACY_LINE,
  UNAVAILABLE_LINE,
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
  privacyMode,
  roleLine,
} from '../../lib/privacyCopy';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

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

  it('copy for unreadable settings says so instead of checking forever', () => {
    expect(privacyLines(FACTS_UNAVAILABLE)).toEqual([{ text: UNAVAILABLE_LINE, offMachine: true }]);
    expect(advisoryLine(FACTS_UNAVAILABLE)).toBe(UNAVAILABLE_LINE);
    expect(dataSourcesNote(FACTS_UNAVAILABLE)).toContain(UNAVAILABLE_LINE);
    expect(privacyMode(FACTS_UNAVAILABLE)).toBe(FACTS_UNAVAILABLE);
    expect(modeLabel(privacyMode(FACTS_UNAVAILABLE))).toBe('mode unknown');
    expect(cloudRolesSummary(FACTS_UNAVAILABLE)).toBe('unknown (settings could not be read)');
    expect(UNAVAILABLE_LINE).not.toContain('this machine');
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

// The opt-in also turns off the backend checks that catch what the settings cannot
// show (an alias of an Ollama cloud model, an off-machine OLLAMA_HOST), so with it on
// a local-looking orchestrator gets no "stays on this machine" promise.
describe('an opt-in left on with a local-looking orchestrator', () => {
  const facts = privacyFactsFromSettings(view(LOCAL_ROLE, LOCAL_ROLE, 'local', true));

  it('makes no local guarantee for the advisory', () => {
    const line = advisoryLine(facts);
    expect(line).not.toContain('never leave this machine');
    expect(line).toContain('Cloud advisory is on');
    expect(line).toContain('never quantities or cost basis');
    expect(privacyLines(facts)[2].offMachine).toBe(true);
  });

  it('the opt-in help says the checks are skipped, not that the advisory is', () => {
    const help = advisoryOptInHelp(facts.orchestrator);
    expect(help).not.toContain('the advisory is skipped');
    expect(help).toContain('skips the checks that keep it on this machine');
    expect(help).toContain('never quantities or cost basis');
  });

  it('without the opt-in the local claim stands', () => {
    const off = privacyFactsFromSettings(view(LOCAL_ROLE, LOCAL_ROLE, 'local', false));
    expect(advisoryLine(off)).toBe(
      'The advisory runs on local Ollama; your holdings never leave this machine.',
    );
    expect(privacyLines(off)[2].offMachine).toBe(false);
  });
});

const SRC_DIR = fileURLToPath(new URL('../../', import.meta.url));

// Claims the UI used to make that were never true. Each pattern is assembled
// from fragments so a grep for these claims over frontend/src finds nothing here.
function claim(flags: string, ...parts: string[]): RegExp {
  return new RegExp(parts.join(''), flags);
}

const FALSE_CLAIMS: ReadonlyArray<readonly [RegExp, string]> = [
  [claim('', 'keys', '\\.', 'toml'), 'cloud keys live in .secrets/inference.json'],
  [claim('', 'JSO', 'NL'), 'cycles are stored in Neo4j'],
  [claim('', 'No net', 'work calls'), 'the advisory can call a cloud orchestrator'],
  [claim('', '100', '% local'), 'cloud providers are opt-in, not absent'],
  [claim('i', 'No data leaves', ' your machine'), 'cloud roles send prompts off this machine'],
  [claim('', 'advisory', '-audit'), 'there is no advisory audit log'],
  [claim('', 'ALPHASWARM v', '\\d'), 'the version comes from /api/health'],
  [claim('', 'FRED, news', ', filings'), 'only yfinance and RSS providers exist'],
];

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === '__tests__' ? [] : sourceFiles(path);
    return /\.(tsx?|jsx?)$/.test(name) ? [path] : [];
  });
}

describe('the frontend makes no false privacy claims', () => {
  const files = sourceFiles(SRC_DIR);

  it('scans the whole source tree', () => {
    expect(files.length).toBeGreaterThan(20);
  });

  it.each(FALSE_CLAIMS)('nothing matches %s', (pattern, reason) => {
    const hits = files.flatMap((file) =>
      readFileSync(file, 'utf-8')
        .split('\n')
        .flatMap((line, index) => (pattern.test(line) ? [`${relative(SRC_DIR, file)}:${index + 1}`] : [])),
    );
    expect(hits, reason).toEqual([]);
  });
});
