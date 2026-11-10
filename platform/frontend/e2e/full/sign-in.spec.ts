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

/* Signing in through the whole platform: the browser loads the app from nginx,
 * posts the form through nginx's /api proxy to the real backend, which checks
 * the password against Postgres and sets the session cookie, and the app then
 * loads as that user. global-setup.ts makes sure the user exists. */
import { expect, test } from "./fixtures";
import { E2E_ADMIN } from "./global-setup";

// Start signed out, so the test signs in through the form itself
test.use({ storageState: { cookies: [], origins: [] } });

test("a user signs in through the sign-in form and the app opens as them", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();

  await page.getByRole("textbox", { name: "Username" }).fill(E2E_ADMIN.username);
  await page.getByLabel("Password").fill(E2E_ADMIN.password);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByPlaceholder("Message...")).toBeVisible();
  await expect(page.getByText(E2E_ADMIN.username, { exact: true })).toBeVisible();
  // Only an admin sees Admin, so this also checks the role came from the backend
  await expect(page.getByRole("button", { name: "Admin", exact: true })).toBeVisible();
});
