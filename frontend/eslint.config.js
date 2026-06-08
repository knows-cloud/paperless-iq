import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

// Minimal config: TypeScript-aware parsing + the react-hooks rules (missing
// dependency arrays, conditional hooks). TS strict + noUnusedLocals already
// cover unused code and types, so we don't duplicate those here.
export default tseslint.config(
  { ignores: ["dist", "node_modules", "*.config.js"] },
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: { parser: tseslint.parser },
    plugins: { "react-hooks": reactHooks },
    // The two classic, high-signal hook rules. We deliberately omit the newer
    // opinionated rules (e.g. set-state-in-effect) which flag the codebase's
    // established fetch-on-mount patterns as false positives.
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
    },
  },
);
