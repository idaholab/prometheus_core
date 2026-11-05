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

import { defineConfig, devices } from "@playwright/test";

// Not 5150, so the tests can run while the dev server is up
const PORT = 5160;
const CI = !!process.env.CI;

/**
 * End-to-end tests in e2e/, run against the built app served by `vite preview`.
 * They run apart from Vitest, which only picks up src/**\/*.test.{ts,tsx}.
 * There is no backend here: each test answers /api itself with page.route.
 */
export default defineConfig({
  testDir: "e2e",
  forbidOnly: CI,
  // One retry in CI tells a flaky test apart from a broken one in the report,
  // but a test that only passes on its retry still fails the run
  retries: CI ? 1 : 0,
  failOnFlakyTests: CI,
  reporter: CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://localhost:${PORT}`,
    // Kept for a failed test only; CI uploads them with the report
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `npm run build && npm run preview -- --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    // vite preview proxies /api to VITE_BACKEND_URL, which defaults to the
    // local backend on 8600. Port 9 has nothing listening, so a call a test
    // forgot to stub fails with a 502 instead of reaching a real backend
    env: { VITE_BACKEND_URL: "http://127.0.0.1:9" },
    // Never reuse a server already on the port: vite preview serves the last
    // build, so a leftover one would test old code. --strictPort fails instead
    reuseExistingServer: false,
    timeout: 180_000,
  },
});
