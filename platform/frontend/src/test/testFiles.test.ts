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

/* Vitest only runs files named *.test.ts (in Node) or *.test.tsx (in jsdom),
 * as set in vite.config.ts. A test file named anything else never runs, and
 * nothing would say so. This fails on any file under src/ that reads like a
 * test but isn't named like one. */
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "vitest";

const SRC_DIR = fileURLToPath(new URL("..", import.meta.url));
const RUNS = /\.test\.tsx?$/;
// Imports only a test file makes. src/test/setup.ts is Vitest's setup file
const TEST_IMPORT = /from\s+["'](vitest|@testing-library\/[^"']+)["']/;
const SETUP_FILES = new Set(["test/setup.ts"]);

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return /\.(ts|tsx)$/.test(entry.name) ? [relative(SRC_DIR, path)] : [];
  });
}

test("every_test_file_under_src_is_named_so_vitest_runs_it", () => {
  const misnamed = sourceFiles(SRC_DIR).filter(
    (file) =>
      !RUNS.test(file) &&
      !SETUP_FILES.has(file) &&
      (/\.(spec|tests?)\.|\.test$/.test(file) || TEST_IMPORT.test(readFileSync(join(SRC_DIR, file), "utf8"))),
  );

  assert.deepEqual(
    misnamed,
    [],
    "Name these *.test.ts (Node) or *.test.tsx (jsdom) so Vitest runs them; Playwright tests go in e2e/",
  );
});
