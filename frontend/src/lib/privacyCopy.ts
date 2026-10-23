// Privacy and isolation copy derived from the live inference settings.
//
// Every sentence the UI shows about where prompts and holdings go is built here
// from GET /api/settings, so the UI cannot claim "local only" while a role points
// at a cloud API (docs/DECISIONS.md#adr-local-first-inference). An Ollama role
// counts as off-machine the way the backend's advisory gate counts it: an Ollama
// cloud model or a non-loopback Ollama server (docs/DECISIONS.md#adr-advisory-pipeline).
// Pure functions, tested in src/__tests__/lib/privacyCopy.test.ts.
import type { ProviderType, RoleView, SettingsView } from '../api/settings';

export type Role = 'orchestrator' | 'worker';
export type InferenceMode = 'local' | 'cloud' | 'mixed';

export interface RoleFacts {
  provider: ProviderType;
  model: string;
  /**
   * Network host the role's prompts go to; null for a local (loopback) Ollama
   * server or an unparsable cloud URL.
   */
  host: string | null;
}

export interface PrivacyFacts {
  mode: InferenceMode;
  orchestrator: RoleFacts;
  worker: RoleFacts;
  allowCloudAdvisory: boolean;
}

/** GET /api/settings failed, so where prompts go is unknown. */
export const FACTS_UNAVAILABLE = 'unavailable';

/** The facts; null while GET /api/settings loads; FACTS_UNAVAILABLE when it failed. */
export type PrivacyStatus = PrivacyFacts | null | typeof FACTS_UNAVAILABLE;

export interface PrivacyLine {
  text: string;
  /** True when the sentence describes data that leaves, or may leave, this machine. */
  offMachine: boolean;
}

const ANTHROPIC_HOST = 'api.anthropic.com';
const OLLAMA_CLOUD_HOST = 'ollama.com';

export const CHECKING_LINE = 'Checking where prompts are sent…';
export const UNAVAILABLE_LINE =
  'Could not read the inference settings, so where prompts are sent is unknown; Settings → Model shows the error.';
export const MARKET_DATA_LINE =
  'Market data: yfinance prices and RSS headlines are fetched over the network; no API keys are needed.';
export const ONBOARDING_PRIVACY_LINE =
  'Inference runs on your local Ollama by default. Cloud models are optional and are configured per role in Settings.';

/** True for a provider that is a cloud API by definition (any provider but Ollama). */
export function isCloud(provider: ProviderType): boolean {
  return provider !== 'ollama';
}

/**
 * True for an Ollama cloud model name, which Ollama runs on ollama.com.
 *
 * Mirrors the backend's is_cloud_ollama_model: any dash- or colon-separated part
 * of the name or tag that is exactly "cloud" counts ("gpt-oss:120b-cloud",
 * "glm-4.6:cloud"), "cloudy-model" does not.
 */
export function isCloudOllamaModel(model: string): boolean {
  const lastSegment = model.trim().toLowerCase().split('/').pop() ?? '';
  const name = lastSegment.split('@')[0] ?? '';
  return name.split(/[-:]/).includes('cloud');
}

export function providerLabel(provider: ProviderType): string {
  switch (provider) {
    case 'ollama':
      return 'local Ollama';
    case 'anthropic':
      return 'Anthropic';
    case 'openai_compatible':
      return 'an OpenAI-compatible API';
  }
}

function safeHost(url: string): string | null {
  try {
    const host = new URL(url).host;
    return host === '' ? null : host;
  } catch {
    return null;
  }
}

/** localhost, 127.0.0.0/8, ::1 or an IPv4-mapped 127.x address (WHATWG-normalised). */
function isLoopbackHostname(hostname: string): boolean {
  const name = hostname.replace(/\.$/, '').replace(/^\[|\]$/g, '').toLowerCase();
  if (name === 'localhost' || name === '::1') return true;
  if (/^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(name)) return true;
  return /^::ffff:7f[0-9a-f]{2}:[0-9a-f]{1,4}$/.test(name);
}

/**
 * Host of an Ollama base_url, or null when it names this machine. Like the
 * backend, the scheme is optional; an unparsable URL fails closed and is
 * returned as written so the copy never calls it local.
 */
function ollamaHost(baseUrl: string): string | null {
  const text = baseUrl.trim();
  if (text === '') return null;
  try {
    const url = new URL(text.includes('://') ? text : `http://${text}`);
    return isLoopbackHostname(url.hostname) ? null : url.host;
  } catch {
    return text;
  }
}

export function hostOf(provider: ProviderType, baseUrl: string | null): string | null {
  if (provider === 'ollama') return baseUrl ? ollamaHost(baseUrl) : null;
  const parsed = baseUrl ? safeHost(baseUrl) : null;
  if (provider === 'anthropic') return parsed ?? ANTHROPIC_HOST;
  return parsed;
}

/**
 * True when the role's prompts leave this machine: a cloud provider, an Ollama
 * cloud model, or an Ollama server that is not on loopback.
 */
export function isOffMachine(facts: RoleFacts): boolean {
  return isCloud(facts.provider) || isCloudOllamaModel(facts.model) || facts.host !== null;
}

/** Facts for a stored role (GET /api/settings) or the role a Save sends (formToRolePut). */
export function roleFactsOf(role: Pick<RoleView, 'provider' | 'model' | 'base_url'>): RoleFacts {
  return { provider: role.provider, model: role.model, host: hostOf(role.provider, role.base_url) };
}

function modeOf(orchestrator: RoleFacts, worker: RoleFacts): InferenceMode {
  const orchestratorOff = isOffMachine(orchestrator);
  const workerOff = isOffMachine(worker);
  if (orchestratorOff && workerOff) return 'cloud';
  if (orchestratorOff || workerOff) return 'mixed';
  return 'local';
}

/**
 * The mode is derived from the roles rather than copied from view.mode: the
 * backend's mode looks at providers only, so it calls an Ollama cloud model
 * "local". Whenever no Ollama role is off-machine the two agree.
 */
export function privacyFactsFromSettings(view: SettingsView): PrivacyFacts {
  const orchestrator = roleFactsOf(view.config.orchestrator);
  const worker = roleFactsOf(view.config.worker);
  return {
    mode: modeOf(orchestrator, worker),
    orchestrator,
    worker,
    allowCloudAdvisory: view.config.allow_cloud_advisory === true,
  };
}

function destination(facts: RoleFacts): string {
  if (facts.provider === 'ollama') {
    if (isCloudOllamaModel(facts.model)) return `Ollama cloud (${OLLAMA_CLOUD_HOST})`;
    if (facts.host) return `a remote Ollama server (${facts.host})`;
    return providerLabel(facts.provider);
  }
  return facts.host ? `${providerLabel(facts.provider)} (${facts.host})` : providerLabel(facts.provider);
}

/** What to say while the facts are unknown: still loading, or the load failed. */
function unknownLine(status: null | typeof FACTS_UNAVAILABLE): string {
  return status === null ? CHECKING_LINE : UNAVAILABLE_LINE;
}

export function roleLine(role: Role, facts: RoleFacts): string {
  if (!isOffMachine(facts)) {
    return `Prompts for the ${role} role stay on this machine (local Ollama).`;
  }
  return `Prompts for the ${role} role are sent to ${destination(facts)}.`;
}

export function advisoryLine(facts: PrivacyStatus): string {
  if (facts === null || facts === FACTS_UNAVAILABLE) return unknownLine(facts);
  const orchestrator = facts.orchestrator;
  if (!isOffMachine(orchestrator)) {
    // The opt-in also skips the backend checks that catch what the settings cannot
    // show (an alias of an Ollama cloud model, an off-machine OLLAMA_HOST), so the
    // local claim holds only without it (docs/DECISIONS.md#adr-advisory-pipeline).
    return facts.allowCloudAdvisory
      ? 'Cloud advisory is on, so the checks that keep the advisory on this machine are skipped: your held tickers (never quantities or cost basis) go to wherever the orchestrator model runs.'
      : 'The advisory runs on local Ollama; your holdings never leave this machine.';
  }
  if (!facts.allowCloudAdvisory) {
    const where =
      orchestrator.provider === 'ollama' && !isCloudOllamaModel(orchestrator.model)
        ? `runs on ${destination(orchestrator)}`
        : `is a cloud model (${destination(orchestrator)})`;
    return `The advisory is off: the orchestrator ${where} and cloud advisory is not enabled in Settings.`;
  }
  return `The advisory sends your held tickers (never quantities or cost basis) to ${destination(orchestrator)}.`;
}

export function advisoryOptInHelp(orchestrator: RoleFacts): string {
  if (!isOffMachine(orchestrator)) {
    return 'The orchestrator looks local, so the advisory does not need this. When on, the advisory skips the checks that keep it on this machine (they catch an Ollama model that runs in the cloud and an Ollama server elsewhere) and sends your held tickers — never quantities or cost basis — to wherever the orchestrator model runs. When off, those checks run before every advisory.';
  }
  return `When on, the advisory sends your held tickers — never quantities or cost basis — to ${destination(orchestrator)}. When off, the advisory is skipped and the report still runs.`;
}

export function privacyLines(facts: PrivacyStatus): PrivacyLine[] {
  if (facts === null || facts === FACTS_UNAVAILABLE) {
    // Unreadable settings may send prompts anywhere, so that line is not marked local.
    return [{ text: unknownLine(facts), offMachine: facts === FACTS_UNAVAILABLE }];
  }
  const orchestratorOff = isOffMachine(facts.orchestrator);
  return [
    { text: roleLine('orchestrator', facts.orchestrator), offMachine: orchestratorOff },
    { text: roleLine('worker', facts.worker), offMachine: isOffMachine(facts.worker) },
    { text: advisoryLine(facts), offMachine: facts.allowCloudAdvisory },
  ];
}

export function dataSourcesNote(facts: PrivacyStatus): string {
  if (facts === null || facts === FACTS_UNAVAILABLE) {
    return `${MARKET_DATA_LINE} ${unknownLine(facts)}`;
  }
  return `${MARKET_DATA_LINE} ${roleLine('worker', facts.worker)}`;
}

export function cloudRolesSummary(facts: PrivacyStatus): string {
  if (facts === null) return 'checking…';
  if (facts === FACTS_UNAVAILABLE) return 'unknown (settings could not be read)';
  const roles: Role[] = [];
  if (isOffMachine(facts.orchestrator)) roles.push('orchestrator');
  if (isOffMachine(facts.worker)) roles.push('worker');
  return roles.length === 0 ? 'none (local only)' : roles.join(', ');
}

export function privacyMode(facts: PrivacyStatus): InferenceMode | null | typeof FACTS_UNAVAILABLE {
  return facts === null || facts === FACTS_UNAVAILABLE ? facts : facts.mode;
}

export function modeLabel(mode: InferenceMode | null | typeof FACTS_UNAVAILABLE): string {
  switch (mode) {
    case 'local':
      return 'local only';
    case 'cloud':
      return 'cloud inference';
    case 'mixed':
      return 'local + cloud';
    case FACTS_UNAVAILABLE:
      return 'mode unknown';
    default:
      return 'checking…';
  }
}
