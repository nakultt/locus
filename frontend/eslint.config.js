import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import nextPlugin from "@next/eslint-plugin-next";
import tseslint from "typescript-eslint";

/**
 * Flat config, using `@next/eslint-plugin-next` directly.
 *
 * `eslint-config-next` is eslintrc-only, so consuming it here would mean
 * pulling in `@eslint/eslintrc` and FlatCompat — and it pins
 * eslint-plugin-react-hooks to v5, which would silently shadow the v7 rules
 * this project lints with. The plugin underneath it is flat-native and is
 * where the Next-specific rules actually live.
 */
export default tseslint.config([
  { ignores: [".next/**", "node_modules/**", "next-env.d.ts"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    plugins: {
      "react-hooks": reactHooks,
      "@next/next": nextPlugin,
    },
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      ...nextPlugin.configs.recommended.rules,
      ...nextPlugin.configs["core-web-vitals"].rules,

      // Off deliberately, and only this rule.
      //
      // It arrived in eslint-plugin-react-hooks 7 and fires on the pattern
      // every data-backed view here uses: fetch on mount, set state when the
      // response lands. The setState is inside an awaited callback rather than
      // the effect body, but the rule cannot see through the async hop and
      // reports the call site. Rewriting ~15 views around it is a
      // data-fetching refactor, not part of moving the app to Next.
      "react-hooks/set-state-in-effect": "off",
    },
  },
]);
