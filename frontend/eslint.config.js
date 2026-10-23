// ESLint flat config.
// - typescript-eslint and react-hooks rules are errors, except the two React
//   Compiler rules below: they flag legacy components that are rewritten later.
// - jsx-a11y runs at `warn` until the accessibility pass promotes it to `error`.
// - ESLint stays on 9.x because eslint-plugin-jsx-a11y 6.10 supports eslint <= 9.
import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';
import jsxA11y from 'eslint-plugin-jsx-a11y';

const a11yAsWarnings = Object.fromEntries(
  Object.keys(jsxA11y.flatConfigs.recommended.rules ?? {}).map((rule) => [rule, 'warn']),
);

export default tseslint.config(
  { ignores: ['dist/**', 'design-reference/**', 'reports/**', '**/* [0-9].*'] },
  {
    files: ['src/**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { 'react-hooks': reactHooks, 'jsx-a11y': jsxA11y },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-hooks/exhaustive-deps': 'error',
      'react-hooks/set-state-in-effect': 'warn',
      'react-hooks/refs': 'warn',
      ...a11yAsWarnings,
      'no-console': 'warn',
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_' },
      ],
    },
  },
  // Placebo controls are deleted, not disabled: every <button> needs a handler.
  {
    files: ['src/**/*.tsx'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector:
            "JSXOpeningElement[name.name='button']:not(:has(JSXAttribute[name.name='onClick'])):not(:has(JSXSpreadAttribute)):not(:has(JSXAttribute[name.name='type'][value.value='submit']))",
          message:
            'Every <button> needs an onClick handler (or type="submit"). Delete placebo controls instead of disabling them.',
        },
      ],
    },
  },
);
