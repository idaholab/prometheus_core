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

/* Routing in a real browser: URLs survive a reload, and a signed-out deep
 * link comes back to its page after sign-in. */
import type {
  ConfigResponse,
  ConversationDetailResponse,
  ConversationHistoryResponse,
  SessionResponse,
  User,
} from "../src/lib/api/types";
import { expect, test } from "./fixtures";
import type { Page } from "@playwright/test";

const USER: User = { identifier: "someone", role: "user", provider: "local" };

/** What a signed-in app loads: config, a chat session, history and the event stream. */
async function stubSignedInApp(page: Page) {
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
  // After a reload, chat resumes the conversation this tab remembers
  await page.route("/api/conversations/*/resume", (route) =>
    route.fulfill({
      json: {
        conversation_id: "conversation-1",
        title: "",
        profile: "",
        auto_approve_steps: false,
        messages: [],
        artifacts: [],
      } satisfies ConversationDetailResponse,
    }),
  );
  await page.route("/api/events", (route) => route.fulfill({ headers: { "content-type": "text/event-stream" }, body: "" }));
}

test("a page keeps its URL across a reload", async ({ page }) => {
  await stubSignedInApp(page);
  await page.route("/api/auth/me", (route) => route.fulfill({ json: USER }));
  await page.goto("/");

  await page.getByRole("link", { name: "Approval Queue" }).click();
  await expect(page).toHaveURL("/approval-queue");
  await page.reload();

  await expect(page).toHaveURL("/approval-queue");
  await expect(page.getByRole("link", { name: "Approval Queue" })).toHaveAttribute("aria-current", "page");
});

test("a signed-out deep link returns to its page after sign-in", async ({ page }) => {
  await stubSignedInApp(page);
  await page.route("/api/auth/login", (route) => route.fulfill({ json: { user: USER } }));
  await page.goto("/approval-queue");

  await expect(page).toHaveURL("/login?next=%2Fapproval-queue");
  await page.getByRole("textbox", { name: "Username" }).fill("someone");
  await page.getByLabel("Password").fill("the-password");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL("/approval-queue");
  await expect(page.getByRole("link", { name: "Approval Queue" })).toHaveAttribute("aria-current", "page");
});
