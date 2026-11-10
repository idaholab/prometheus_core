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

const CI = !!process.env.CI;

/**
 * End-to-end tests in e2e/full/, run against the e2e stack: the whole platform,
 * started by `make up-e2e` in platform/. Nothing is faked in the browser;
 * requests go through nginx to the real backend.
 *
 * Unlike playwright.config.ts, this doesn't start a server. It expects the e2e
 * stack's nginx on port 8090; point it elsewhere with E2E_BASE_URL.
 */
export default defineConfig({
  testDir: "e2e/full",
  forbidOnly: CI,
  retries: CI ? 1 : 0,
  failOnFlakyTests: CI,
  // One signed-in admin, created once by global-setup.ts, is shared by every test
  workers: 1,
  reporter: CI ? [["list"], ["html", { open: "never", outputFolder: "playwright-report-full" }]] : "list",
  globalSetup: "./e2e/full/global-setup.ts",
  outputDir: "test-results-full",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8090",
    storageState: "test-results-full/.auth/admin.json",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
