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
 * accessible name the way the component tests do. The shared stubs and the
 * unstubbed-call check come from ./fixtures. */
import type { Request } from "@playwright/test";
import type { ConfigResponse, ConversationHistoryResponse, SessionResponse, User } from "../src/lib/api/types";
import { expect, test, type ErrorBody } from "./fixtures";

/** Checks the sign-in request carries what was typed, as the backend expects it. */
function expectLogin(request: Request, username: string, password: string) {
  expect(request.method()).toBe("POST");
  expect(request.postDataJSON()).toEqual({ username, password });
}

test("a signed-out visitor sees the sign-in form", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  const logo = page.getByRole("img", { name: "Prometheus" });
  await expect(logo).toBeVisible();
  // A broken image still shows its alt text in a visible box, so also check
  // the file loaded
  expect(await logo.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth)).toBeGreaterThan(0);
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
