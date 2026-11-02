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
import { expect, test, type Request } from "@playwright/test";
import type {
  AuthProvider,
  ConfigResponse,
  ConversationHistoryResponse,
  SessionResponse,
  SetupStatus,
  User,
} from "../src/lib/api/types";

/* Stub bodies are typed with the app's own API types, so a change to a
 * response shape fails `npm run typecheck` until the stubs match it. */
type ErrorBody = { detail: string };

/** Checks the sign-in request carries what was typed, as the backend expects it. */
function expectLogin(request: Request, username: string, password: string) {
  expect(request.method()).toBe("POST");
  expect(request.postDataJSON()).toEqual({ username, password });
}

/* The /api calls no stub answered in the current test. The app shrugs off a
 * 404 in several places, so without this a missing stub would go unnoticed. */
let unstubbed: string[] = [];

test.beforeEach(async ({ page }) => {
  unstubbed = [];
  // A signed-out visitor on a set-up install: setup is done, there's no
  // session and no OIDC provider. Anything else under /api is a 404, and is
  // recorded so the test fails
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
});

test.afterEach(() => {
  expect(unstubbed, "/api calls with no stub; add a page.route for each").toEqual([]);
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
  const login = page.waitForRequest("/api/auth/login");
  await page.getByRole("button", { name: "Sign in" }).click();

  expectLogin(await login, "someone", "not-the-password");
  await expect(page.getByRole("alert")).toHaveText("Invalid credentials");
});

test("signing in opens the app as the user the server returned", async ({ page }) => {
  // An admin, because only an admin sees the Admin entry, so the test fails
  // if the app doesn't read the user out of the login response
  const user: User = { identifier: "someone", role: "admin", provider: "local" };
  await page.route("/api/auth/login", (route) => route.fulfill({ json: { user } }));
  // What the app loads once signed in: its config, a new chat session, an
  // empty chat history, and the live event stream, which stays open with no
  // events
  await page.route("/api/config", (route) =>
    route.fulfill({
      json: {
        profiles: [],
        chat_intro: "Welcome",
        chat_suggestion_title: "What would you like to do today?",
        workflow_suggestions: [],
        auto_approve_steps: false,
        max_upload_bytes: 10_000_000,
      } satisfies ConfigResponse,
    }),
  );
  await page.route("/api/sessions", (route) =>
    route.fulfill({
      json: {
        conversation_id: "conversation-1",
        profile: "",
        chat_intro: "Welcome",
        chat_suggestion_title: "What would you like to do today?",
        workflow_suggestions: [],
        auto_approve_steps: false,
      } satisfies SessionResponse,
    }),
  );
  await page.route("/api/conversations/recent*", (route) =>
    route.fulfill({ json: { available: true, conversations: [] } satisfies ConversationHistoryResponse }),
  );
  await page.route("/api/events", (route) =>
    route.fulfill({ headers: { "content-type": "text/event-stream" }, body: "" }),
  );
  await page.goto("/");

  await page.getByRole("textbox", { name: "Username" }).fill("someone");
  await page.getByLabel("Password").fill("the-password");
  const login = page.waitForRequest("/api/auth/login");
  await page.getByRole("button", { name: "Sign in" }).click();

  expectLogin(await login, "someone", "the-password");

  await expect(page.getByRole("button", { name: "New chat" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Admin", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Sign in" })).toHaveCount(0);
});
