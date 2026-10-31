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

import assert from "node:assert/strict";
import { afterEach, test, vi } from "vitest";
import { ApiError, api } from "./client.ts";

afterEach(() => vi.unstubAllGlobals());

function stubFetch(status: number, body: unknown) {
  const calls: { url: string; init: RequestInit }[] = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  });
  return calls;
}

test("getConversation reads the transcript without rebinding the session", async () => {
  const transcript = { conversation_id: "a b", auto_approve_steps: false, messages: [], artifacts: [] };
  const calls = stubFetch(200, transcript);

  assert.deepEqual(await api.getConversation("a b"), transcript);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/conversations/a%20b"); // the id is URL-encoded
  assert.equal(calls[0].init.method ?? "GET", "GET"); // a read, not resumeConversation's POST
  assert.equal(calls[0].init.credentials, "include");
});

test("getConversation surfaces a missing conversation as ApiError 404", async () => {
  stubFetch(404, { detail: "Conversation not found" });

  const err = await api.getConversation("gone").catch((e: unknown) => e);
  assert.ok(err instanceof ApiError);
  assert.equal(err.status, 404);
  assert.equal(err.message, "Conversation not found");
});

test("getConversationTasks reads the conversation's Task Graph", async () => {
  const body = { available: true, conversation_id: "c 1", tasks: [] };
  const calls = stubFetch(200, body);

  assert.deepEqual(await api.getConversationTasks("c 1"), body);
  assert.equal(calls[0].url, "/api/conversations/c%201/tasks");
  assert.equal(calls[0].init.method ?? "GET", "GET");
});
