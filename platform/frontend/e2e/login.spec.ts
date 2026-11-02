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

/* The example for end-to-end tests: load the built app in a real browser,
 * answer its /api calls with page.route, and find elements by role and
 * accessible name the way the component tests do. */
import { expect, test } from "@playwright/test";
import type { AuthProvider, SetupStatus } from "../src/lib/api/types";

/* Stub bodies are typed with the app's own API types, so a change to a
 * response shape fails `npm run typecheck` until the stubs match it. */
type ErrorBody = { detail: string };

test.beforeEach(async ({ page }) => {
  // A signed-out visitor on a set-up install: setup is done, there's no
  // session and no OIDC provider. Anything else under /api is a 404
  await page.route("/api/**", (route) => route.fulfill({ status: 404, json: { detail: "Not stubbed" } satisfies ErrorBody }));
  await page.route("/api/setup/status", (route) => route.fulfill({ json: { needs_setup: false } satisfies SetupStatus }));
  await page.route("/api/auth/me", (route) =>
    route.fulfill({ status: 401, json: { detail: "Not authenticated" } satisfies ErrorBody }),
  );
  await page.route("/api/auth/providers", (route) => route.fulfill({ json: [] satisfies AuthProvider[] }));
});

test("a signed-out visitor sees the sign-in form", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Prometheus" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Username" })).toBeFocused();
  await expect(page.getByLabel("Password")).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeEnabled();
});

test("wrong credentials show an error", async ({ page }) => {
  await page.route("/api/auth/login", (route) =>
    route.fulfill({ status: 401, json: { detail: "Invalid credentials" } satisfies ErrorBody }),
  );
  await page.goto("/");

  await page.getByRole("textbox", { name: "Username" }).fill("someone");
  await page.getByLabel("Password").fill("not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByRole("alert")).toHaveText("Invalid credentials");
});
