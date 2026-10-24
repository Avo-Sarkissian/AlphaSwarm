// @vitest-environment node
// jsx-a11y runs its recommended rule set at the recommended levels (errors),
// so an accessibility regression fails `npm run lint`.
import { describe, expect, it } from 'vitest';

type FlatConfig = { plugins?: Record<string, unknown>; rules?: Record<string, unknown> };
type A11yPlugin = { flatConfigs: { recommended: { rules: Record<string, unknown> } } };

// Loaded by URL/name at runtime: neither module ships TypeScript declarations.
const CONFIG_URL = new URL('../../../eslint.config.js', import.meta.url).href;
const A11Y_PLUGIN = 'eslint-plugin-jsx-a11y';

describe('eslint.config.js', () => {
  it('applies every jsx-a11y recommended rule at its recommended level', async () => {
    const config = ((await import(/* @vite-ignore */ CONFIG_URL)) as { default: FlatConfig[] }).default;
    const plugin = ((await import(/* @vite-ignore */ A11Y_PLUGIN)) as { default: A11yPlugin }).default;
    const blocks = config.filter((c) => c.plugins !== undefined && 'jsx-a11y' in c.plugins);
    expect(blocks.length).toBeGreaterThan(0);
    const rules: Record<string, unknown> = Object.assign({}, ...blocks.map((c) => c.rules ?? {}));
    const drift = Object.entries(plugin.flatConfigs.recommended.rules)
      .filter(([rule, level]) => JSON.stringify(rules[rule]) !== JSON.stringify(level))
      .map(([rule]) => rule);
    expect(drift).toEqual([]);
  });
});
