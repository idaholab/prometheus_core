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

/* Feature: chatting with the platform's agent.
 *
 * A signed-in user sends a message from Home and gets the agent's reply in the
 * transcript. On the way, the message crosses every part of the platform: the
 * browser posts it through nginx to the backend, the backend sends it to the
 * client agent over A2A, and the reply comes back over the backend's event
 * stream (SSE). These tests stand in for that feature's behavior spec until the
 * platform has one (TESTING.md, "Rules for every test").
 *
 * In the e2e stack, the stub agent (platform/e2e/stub-client-agent) takes the
 * client agent's place. It gives the same answer to every message and never
 * calls an LLM, so a test knows the reply in advance. What the real agent says
 * is not checked here, and neither is chat history: the real client agent saves
 * each chat itself (client-agent/conversation_store.py), and the stub doesn't,
 * so a chat in this stack is not listed under Chat History after a reload.
 *
 * Known bug: with the real client agent, about one turn in three hangs with
 * the reply sent but the chat never settling, until PR 382 ("Settle a chat
 * turn from its POST reply or turn_done") merges. The stub answers at once and
 * hasn't hit it in 25 runs, but a failure here that shows the reply in the
 * backend log and not on screen is most likely that bug, not this test.
 *
 * Every test starts signed in as the e2e admin (global-setup.ts). */
import { expect, test } from "./fixtures";

// The stub's fixed answer (TEXT_ANSWER in platform/e2e/stub-client-agent/agent.py)
const STUB_ANSWER = "This is the e2e stub agent. It gives this same answer to every message.";

/**
 * Behavior: a message sent from Home gets the agent's reply in the transcript.
 * - Given a signed-in user on Home, with a new chat,
 * - when they type a message and press Enter,
 * - then their message appears in the transcript,
 * - and the agent's reply appears after it,
 * - and the chat settles: the "Assistant is thinking" indicator goes away and
 *   the message box takes input again,
 * - and nothing on the way throws or gets a failed /api request (fixtures.ts).
 */
test("a user sends a message and gets the agent's reply", async ({ page }) => {
  await page.goto("/");
  const main = page.getByRole("main");
  const message = main.getByRole("textbox", { name: "Message" });
  // Unique per run, so a rerun against the same stack can't match an old chat
  const prompt = `Hello from the e2e chat test ${Date.now()}`;

  await message.fill(prompt);
  await message.press("Enter");

  await expect(main.getByText(prompt, { exact: true })).toBeVisible();
  await expect(main.getByText(STUB_ANSWER, { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(main.getByLabel("Assistant is thinking")).toHaveCount(0);
  await expect(message).toBeEditable();
});
