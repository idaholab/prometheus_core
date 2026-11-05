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

/* Shared setup for every e2e spec. Import `test` and `expect` from here rather
 * than from @playwright/test, so each test starts as a signed-out visitor with
 * /api stubbed and fails if it makes a call no stub answers. */
import { expect, test as base } from "@playwright/test";
import type { AuthProvider, SetupStatus } from "../src/lib/api/types";

/* Stub bodies are typed with the app's own API types, so a change to a
 * response shape fails `npm run typecheck` until the stubs match it. */
export type ErrorBody = { detail: string };

export const test = base.extend({
  page: async ({ page }, provide) => {
    // The /api calls no stub answered. The app shrugs off a 404 in several
    // places, so without this a missing stub would go unnoticed
    const unstubbed: string[] = [];

    // A signed-out visitor on a set-up install: setup is done, there's no
    // session and no OIDC provider. Anything else under /api is a 404, and is
    // recorded so the test fails. A test adds or overrides stubs with its own
    // page.route; the most recently added route wins
    await page.route("/api/**", (route) => {
      const request = route.request();
      unstubbed.push(`${request.method()} ${new URL(request.url()).pathname}`);
      return route.fulfill({ status: 404, json: { detail: "Not stubbed" } satisfies ErrorBody });
    });
    await page.route("/api/setup/status", (route) => route.fulfill({ json: { needs_setup: false } satisfies SetupStatus }));
    await page.route("/api/auth/me", (route) =>
      route.fulfill({ status: 401, json: { detail: "Not authenticated" } satisfies ErrorBody }),
    );
    await page.route("/api/auth/providers", (route) => route.fulfill({ json: [] satisfies AuthProvider[] }));

    await provide(page);

    expect(unstubbed, "/api calls with no stub; add a page.route for each").toEqual([]);
  },
});

export { expect };
