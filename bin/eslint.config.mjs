import security from "eslint-plugin-security";
import globals from "globals";

export default [
  {
    files: ["canvas.js"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "script",
      globals: {
        ...globals.browser,
        __GRAPH_DATA__: "readonly",
        d3: "readonly",
      },
    },
    plugins: {
      security,
    },
    rules: {
      ...security.configs.recommended.rules,
      "no-eval": "error",
      "no-implied-eval": "error",
      "no-new-func": "error",
      "no-script-url": "error",
      "no-undef": "error",
      // Canvas lookups use fixed maps or bounds-checked result indexes. This
      // heuristic flags all of them without identifying an executable sink.
      "security/detect-object-injection": "off",
    },
  },
];
