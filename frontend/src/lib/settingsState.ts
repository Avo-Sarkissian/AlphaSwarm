// src/lib/settingsState.ts — codex MEDIUM-8 normalize helper.
//
// Allowlist of UI-only keys that are safe to persist. Backend-touching keys
// (model, inferenceSlots, memoryThreshold, agentCount, bracketWeights, keysTomlPath)
// per CONTEXT.md D-23 are NOT in the allowlist and will be dropped silently.
//
// The previous setItem-only grep gate caught backend keys appearing as the
// LITERAL key argument in `setItem(...)` but missed backend keys nested inside
// a persisted JSON object (e.g.,
// `localStorage.setItem('as_settings_ui_v1', JSON.stringify({theme:'dark', model:'qwen3:8b'}))`).
// The normalize helper drops non-allowlist keys BEFORE the JSON is written AND
// after it is read — so backend keys cannot leak into localStorage even via
// nested objects.

export const SETTINGS_UI_ALLOWLIST = [
  'density',
  'layout',
  'theme',
  'hintVisibility',
] as const;
export type SettingsUiKey = (typeof SETTINGS_UI_ALLOWLIST)[number];

export interface SettingsUiState {
  density?: 'compact' | 'cozy' | 'spacious';
  layout?: 'grid' | 'rows';
  theme?: 'dark' | 'light';
  hintVisibility?: boolean;
}

// Allowed enum values per UI key. Anything else is dropped.
const ENUMS: Record<SettingsUiKey, ReadonlySet<unknown>> = {
  density: new Set(['compact', 'cozy', 'spacious']),
  layout: new Set(['grid', 'rows']),
  theme: new Set(['dark', 'light']),
  hintVisibility: new Set([true, false]),
};

/**
 * Drop any keys NOT in SETTINGS_UI_ALLOWLIST and validate enum values.
 * Apply on BOTH read (defensive against stale localStorage) and write
 * (defensive against future code drift accidentally including backend keys).
 */
export function normalizeSettingsUiState(input: unknown): SettingsUiState {
  if (!input || typeof input !== 'object') return {};
  const obj = input as Record<string, unknown>;
  const out: SettingsUiState = {};
  for (const k of SETTINGS_UI_ALLOWLIST) {
    if (k in obj && ENUMS[k].has(obj[k])) {
      (out as Record<string, unknown>)[k] = obj[k];
    }
  }
  return out;
}
