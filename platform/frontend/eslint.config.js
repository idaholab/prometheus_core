// This file is part of Prometheus
// https://inl.gov/super-intelligence/prometheus/
//
// Copyright 2026 Battelle Energy Alliance, LLC
// All rights reserved, see NOTICE.txt for full restrictions
// https://github.com/idaholab/prometheus_core/blob/main/NOTICE.txt
//
// Licensed under the MIT License, please see LICENSE for details
// https://github.com/idaholab/prometheus_core/blob/main/LICENSE
//
// SPDX-License-Identifier: MIT

import { readdirSync } from "node:fs";
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import { defineConfig, globalIgnores } from "eslint/config";
import globals from "globals";
import tseslint from "typescript-eslint";

/* Folder rules (see the README's "Where code and tests go"):
 * - code outside a feature imports it only through its index.ts, so
 *   @/features/chat is fine and @/features/chat/store/chat is not
 * - anything outside the importer's own folder is imported with @/, never ../
 * A file inside a feature may import that feature's own files directly. */
const FEATURES = readdirSync(new URL("./src/features", import.meta.url), { withFileTypes: true })
  .filter((entry) => entry.isDirectory())
  .map((entry) => entry.name);

const NO_PARENT_IMPORTS = {
  group: ["../*"],
  message: "Import code outside this folder with @/ instead of ../",
};

/** Deep imports into every feature except `own`, which may import its own files. */
function featureBoundary(own) {
  return FEATURES.filter((name) => name !== own).map((name) => ({
    group: [`@/features/${name}/*`],
    message: `Import from @/features/${name} (its index.ts); the files inside it are internal to that feature`,
  }));
}

export default defineConfig([
  globalIgnores(["dist", "coverage", "public", "test-results", "test-results-full", "playwright-report", "playwright-report-full", "blob-report"]),
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, tseslint.configs.recommended, reactHooks.configs.flat["recommended-latest"]],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: { "react-refresh": reactRefresh },
    rules: {
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      // react-hooks 7 adds rules for the React Compiler, which this app doesn't
      // use. This one flags setState called directly in an effect, which costs
      // an extra render but is correct; the five existing cases (auth reset,
      // chat prefill, viewer resets, text loading) work as intended. Rewriting
      // them changes behaviour, so it's left for when the compiler is adopted
      "react-hooks/set-state-in-effect": "off",
    },
  },
  {
    files: ["src/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": ["error", { patterns: [NO_PARENT_IMPORTS, ...featureBoundary(null)] }],
    },
  },
  ...FEATURES.map((name) => ({
    files: [`src/features/${name}/**/*.{ts,tsx}`],
    rules: {
      "no-restricted-imports": ["error", { patterns: [NO_PARENT_IMPORTS, ...featureBoundary(name)] }],
    },
  })),
  // Playwright tests and their config run in Node, not the browser
  {
    files: ["e2e/**/*.ts", "playwright.config.ts", "playwright.full.config.ts"],
    languageOptions: { globals: globals.node },
  },
]);
