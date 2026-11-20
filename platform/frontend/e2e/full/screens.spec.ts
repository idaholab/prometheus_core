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

/* Feature: getting to each main screen of the app.
 *
 * A signed-in user reaches every main screen from the sidebar, and every
 * screen has an address of its own that loads straight into it, through the
 * production nginx that serves the app. These tests stand in for that
 * feature's behavior spec until the platform has one (TESTING.md, "Rules for
 * every test"). Where the Frontend Routing and Screen Structure spec
 * (Confluence) has a requirement for the behavior, the test's name starts
 * with its ID.
 *
 * What a screen shows is not checked here: each screen's own behavior belongs
 * in its component tests. These tests only prove the screen opened. Most
 * screens still show placeholder data, so each one is recognized by a part of
 * its layout that no other screen has, not by its data. Admin is the exception:
 * it lists the real users, so seeing the e2e admin there also proves the
 * screen reached the backend through nginx.
 *
 * Every test starts signed in as the e2e admin (global-setup.ts), who can see
 * every screen, Admin included. */
import type { Locator, Page } from "@playwright/test";
import { expect, test } from "./fixtures";
import { E2E_ADMIN } from "./global-setup";

interface Screen {
  /** The screen's link in the sidebar. */
  link: string;
  /** The screen's own address. */
  path: string;
  /** The page title in the header. */
  title: string;
  /** Something inside the screen that only that screen shows. */
  content: (main: Locator) => Locator;
}

const SCREENS: Screen[] = [
  {
    link: "Agent Registry",
    path: "/agent-registry",
    title: "Agent Registry",
    content: (main) => main.getByRole("region", { name: "Agents" }),
  },
  {
    link: "Workflows",
    path: "/workflows",
    title: "Workflow Console",
    content: (main) => main.getByRole("heading", { name: "Workflow Templates" }),
  },
  {
    link: "Approval Queue",
    path: "/approval-queue",
    title: "Human-in-the-Loop Checkpoint Console",
    content: (main) => main.getByRole("region", { name: "Checkpoint queue" }),
  },
  {
    link: "Project Management",
    path: "/project-management",
    title: "Access Control & Team Hub",
    content: (main) => main.getByRole("table", { name: "Team members" }),
  },
  {
    link: "Data Management",
    path: "/data-management",
    title: "Data Sources & Artifact Persistence",
    content: (main) => main.getByRole("table", { name: "Generated artifacts" }),
  },
  {
    link: "Jobs Console",
    path: "/jobs-console",
    title: "Jobs Console",
    // A placeholder screen until PPLT-103; its own heading is all it shows
    content: (main) => main.getByRole("heading", { level: 2, name: "Jobs Console" }),
  },
  {
    link: "Admin",
    path: "/admin",
    title: "Admin",
    // Real data from the backend: the admin every test signs in as
    content: (main) => main.getByRole("cell", { name: E2E_ADMIN.username, exact: true }),
  },
  {
    // Last, so the loop also comes back to Home after leaving it
    link: "Home",
    path: "/",
    title: "Home",
    content: (main) => main.getByRole("textbox", { name: "Message" }),
  },
];

/** Checks the app is showing `screen`: its address, its sidebar link marked
 * current, its title in the header, and its own content. */
async function expectScreen(page: Page, screen: Screen) {
  const what = `the ${screen.link} screen`;
  await expect(page, what).toHaveURL(screen.path);
  await expect(page.getByRole("link", { name: screen.link, exact: true }), what).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("heading", { level: 1 }), what).toHaveText(screen.title);
  await expect(screen.content(page.getByRole("main")), what).toBeVisible();
}

/**
 * Behavior: a signed-in user can open every main screen from the sidebar.
 * - Given a signed-in admin on Home,
 * - when they click each main screen's link in the sidebar in turn, and then
 *   Home again,
 * - then each click shows that screen: the address changes to the screen's
 *   own, its sidebar link is marked as the current page, the header shows its
 *   title, and the screen's own content appears,
 * - and nothing on the way throws or gets a failed /api request (fixtures.ts).
 */
test("ROUTE-1: a signed-in user opens each main screen from the sidebar", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("main").getByRole("textbox", { name: "Message" })).toBeVisible();

  for (const screen of SCREENS) {
    await page.getByRole("link", { name: screen.link, exact: true }).click();
    await expectScreen(page, screen);
  }
});

/**
 * Behavior: every main screen's address opens that screen when loaded
 * directly, as a bookmark, a shared link or a browser reload does.
 * - Given a signed-in admin,
 * - when the browser loads a main screen's address from the server (not by
 *   clicking inside the app),
 * - then nginx answers 200 with the app, not a 404 of its own,
 * - and the app opens on that screen, as above.
 *
 * Why end-to-end: the app's own routing is already tested with no server
 * behind it (e2e/routing.spec.ts). What only the full stack can show is that
 * the production nginx hands every app address to the app.
 */
test("ROUTE-1, ROUTE-5: loading a main screen's address directly opens that screen", async ({ page }) => {
  for (const screen of SCREENS) {
    const response = await page.goto(screen.path);
    expect(response?.status(), `nginx's answer for ${screen.path}`).toBe(200);
    await expectScreen(page, screen);
  }
});

/**
 * Behavior: an address the app doesn't know still opens the app, which says
 * the page doesn't exist and offers a way back.
 * - Given a signed-in admin,
 * - when the browser loads an address no screen has, several levels deep,
 * - then nginx still answers 200 with the app,
 * - and the app shows its "page not found" message inside the usual shell,
 *   with a link back to Home that works.
 */
test("ROUTE-3, ROUTE-5: loading an unknown address opens the app's page-not-found message", async ({ page }) => {
  const response = await page.goto("/no/such/screen");
  expect(response?.status(), "nginx's answer for an unknown address").toBe(200);

  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { name: "This page does not exist" })).toBeVisible();
  // The shell is still there around it
  await expect(page.getByRole("link", { name: "Agent Registry", exact: true })).toBeVisible();

  await main.getByRole("link", { name: "Go to Home" }).click();
  await expectScreen(page, SCREENS.find((screen) => screen.path === "/")!);
});
