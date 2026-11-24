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

/* Feature: managing local users from Admin.
 *
 * An admin creates, edits and deletes local user accounts from Admin > Users.
 * Each change goes through nginx to the backend, which writes it to Postgres
 * (the admin database), and the list shows the result. A reload proves the
 * change was saved, not just shown. This test stands in for the feature's
 * behavior spec until the platform has one (TESTING.md, "Rules for every test").
 *
 * The user it creates has a made-up name that's unique per run, and the test
 * deletes it, so the e2e stack ends as it started. If the test fails before
 * then, afterEach deletes that user through the API. Every test starts signed
 * in as the e2e admin (global-setup.ts). */
import type { Page } from "@playwright/test";
import type { AdminUser } from "../../src/lib/api/types";
import { expect, test } from "./fixtures";

// Unique per run, so a rerun against the same stack never finds an old user
const username = `e2e-user-${Date.now()}`;

// Deletes this run's user if the test stopped before its own delete. Only this
// run's name, so it can't touch anyone else's. `request` shares the page's
// signed-in session
test.afterEach(async ({ request }) => {
  const users = await request.get("/api/admin/users");
  if (!users.ok()) return;
  const leftover = ((await users.json()) as AdminUser[]).find((user) => user.username === username);
  if (leftover) await request.delete(`/api/admin/users/${encodeURIComponent(leftover.id)}`);
});

/** The Users table row for `username`. */
function userRow(page: Page, username: string) {
  return page.getByRole("row").filter({ has: page.getByRole("cell", { name: username, exact: true }) });
}

/**
 * Behavior: an admin creates, edits and deletes a local user, and each change is saved.
 * - Given the e2e admin on Admin > Users,
 * - when they create a user with a role of "user",
 * - then it appears in the list without a reload, as a user,
 * - and when they change its role to "admin",
 * - then the list shows it as an admin, also after a reload,
 * - and when they delete it and confirm,
 * - then it's gone from the list, also after a reload,
 * - and nothing on the way throws or gets a failed /api request (fixtures.ts).
 */
test("an admin creates, edits and deletes a local user", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Admin", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Users" })).toBeVisible();
  // The list has loaded once the e2e admin's own row is there
  await expect(page.getByRole("cell", { name: "e2e-admin", exact: true })).toBeVisible();

  // Create
  await page.getByRole("button", { name: "New user" }).click();
  const createDialog = page.getByRole("dialog", { name: "New user" });
  await createDialog.getByRole("textbox", { name: "Username" }).fill(username);
  await createDialog.getByLabel("Password").fill("e2e-password-not-secret");
  await createDialog.getByRole("combobox", { name: "Role" }).selectOption("user");
  await createDialog.getByRole("button", { name: "Create" }).click();
  await expect(createDialog).toBeHidden();

  const row = userRow(page, username);
  await expect(row).toBeVisible();
  await expect(row.getByText("user", { exact: true })).toBeVisible();

  // Edit the role
  await row.getByRole("button", { name: `Edit ${username}` }).click();
  const editDialog = page.getByRole("dialog", { name: `Edit ${username}` });
  await editDialog.getByRole("combobox", { name: "Role" }).selectOption("admin");
  await editDialog.getByRole("button", { name: "Save" }).click();
  await expect(editDialog).toBeHidden();
  await expect(row.getByText("admin", { exact: true })).toBeVisible();

  await page.reload();
  await expect(userRow(page, username).getByText("admin", { exact: true })).toBeVisible();

  // Delete, accepting the browser's "Delete user ...?" confirmation
  page.once("dialog", (confirm) => confirm.accept());
  await userRow(page, username)
    .getByRole("button", { name: `Delete ${username}` })
    .click();
  await expect(userRow(page, username)).toHaveCount(0);

  await page.reload();
  await expect(page.getByRole("cell", { name: "e2e-admin", exact: true })).toBeVisible();
  await expect(userRow(page, username)).toHaveCount(0);
});
