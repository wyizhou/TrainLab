import js from '@eslint/js'
import globals from 'globals'
import tseslint from 'typescript-eslint'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import prettier from 'eslint-config-prettier'

// G-token: bare color literals are banned everywhere except the token module.
// esquery attribute-regex matching lets us catch #hex and color-function calls
// wherever they appear in JS/TS source (string literals + template chunks).
const bareColorRules = [
  {
    selector: 'Literal[value=/#[0-9a-fA-F]{3,8}\\b/]',
    message: 'Bare hex color banned — reference a token from src/styles (G-token).',
  },
  {
    selector: 'Literal[value=/(?:rgb|rgba|hsl|hsla|oklch|oklab)\\(/]',
    message: 'Bare color function banned — reference a token from src/styles (G-token).',
  },
  {
    selector: 'TemplateElement[value.raw=/#[0-9a-fA-F]{3,8}\\b/]',
    message: 'Bare hex color banned — reference a token from src/styles (G-token).',
  },
  {
    selector: 'TemplateElement[value.raw=/(?:rgb|rgba|hsl|hsla|oklch|oklab)\\(/]',
    message: 'Bare color function banned — reference a token from src/styles (G-token).',
  },
]

export default tseslint.config(
  {
    ignores: ['dist', 'coverage', 'playwright-report', 'test-results', 'node_modules'],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      'no-restricted-syntax': ['error', ...bareColorRules],
    },
  },
  {
    // The token module is the single source of raw color values; tests may pin
    // literal token values to guard against drift. e2e pixel-contract specs
    // (AC-001c-*, design_rev 3) likewise pin computed rgb values from §A. None of
    // these ship styling code, so the bare-color ban does not apply.
    files: ['src/styles/tokens.ts', '**/*.test.{ts,tsx}', 'tests/e2e/**/*.spec.ts'],
    rules: { 'no-restricted-syntax': 'off' },
  },
  {
    files: ['tests/**', '**/*.config.{ts,js}', 'eslint.config.js'],
    languageOptions: { globals: { ...globals.node } },
  },
  prettier,
)
