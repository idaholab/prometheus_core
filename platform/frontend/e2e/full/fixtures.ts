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

/* Shared setup for the full-stack specs. Import `test` and `expect` from here.
 *
 * Unlike ../fixtures.ts, nothing is faked: /api reaches the real backend. What
 * this adds is the same "fail on what nobody checked" idea: a test fails if
 * the page throws, or if an /api request fails or is refused (any status of 400
 * or more), even when the screen still looks fine. */
import { expect, test as base, type Page } from "@playwright/test";

/** A 401 before signing in, and an unknown chat's /resume, are expected answers, not faults. */
const EXPECTED = [/\/api\/auth\/me$/, /\/api\/conversations\/[^/]+\/resume$/];

function watch(page: Page): string[] {
  const problems: string[] = [];
  page.on("pageerror", (error) => problems.push(`page error: ${error.message}`));
  page.on("requestfailed", (request) => {
    const url = new URL(request.url());
    // The event stream is cut on purpose when a test ends or navigates
    if (url.pathname.startsWith("/api/") && url.pathname !== "/api/events") {
      problems.push(`request failed: ${request.method()} ${url.pathname} (${request.failure()?.errorText})`);
    }
  });
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (!url.pathname.startsWith("/api/") || EXPECTED.some((pattern) => pattern.test(url.pathname))) return;
    const status = response.status();
    if (status >= 400) problems.push(`${status >= 500 ? "server error" : "request refused"}: ${status} ${response.request().method()} ${url.pathname}`);
  });
  return problems;
}

export const test = base.extend({
  page: async ({ page }, provide) => {
    const problems = watch(page);
    await provide(page);
    expect(problems, "page errors or failed /api requests during the test").toEqual([]);
  },
});

export { expect };
