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
import { ApiError } from "@/lib/api/client";
import { chatStore, useChatState as tapChatState } from "./chat.ts";

/* The real chat store, with the API client, the SSE client and React stubbed out.
 * Each test sets the API it needs on globalThis.__chatTestApi; the React stub
 * leaves the store's getSnapshot on globalThis.__chatTestTap. */
vi.mock("react", () => ({
  useSyncExternalStore: (_sub: unknown, get: () => unknown) => {
    (globalThis as Record<string, unknown>).__chatTestTap = get;
    return get();
  },
}));
vi.mock("@/lib/api/events", () => ({
  openEventStream: (handlers: unknown) => {
    (globalThis as Record<string, unknown>).__chatTestStream = handlers;
    return () => {};
  },
}));
vi.mock("@/lib/api/client", () => {
  class StubApiError extends Error {
    constructor(
      public status: number,
      message: string,
    ) {
      super(message);
      this.name = "ApiError";
    }
  }
  const api = new Proxy(
    {},
    { get: (_t, k: string) => (...a: unknown[]) => (globalThis as unknown as { __chatTestApi: Api }).__chatTestApi[k](...a) },
  );
  return { ApiError: StubApiError, api };
});

type Api = Record<string, (...a: unknown[]) => Promise<unknown>>;
const g = globalThis as unknown as {
  __chatTestApi: Api;
  __chatTestTap: () => Record<string, unknown>;
  __chatTestStream: {
    onStatus: (e: { type: "status"; turn_id: string; message: string; history?: string[] }) => void;
    onTaskProgress: (e: { type: "task_progress"; task_id: string; message: string }) => void;
  };
  sessionStorage: unknown;
};

tapChatState(); // not a render: the stubbed hook hands back the store's getSnapshot
const readState = () => g.__chatTestTap();
afterEach(() => chatStore.clear()); // the store is a module singleton

function installStorage(openId: string | null): void {
  const backing = new Map<string, string>();
  if (openId) backing.set("prometheus.openConversationId", openId);
  g.sessionStorage = {
    getItem: (k: string) => backing.get(k) ?? null,
    setItem: (k: string, v: string) => void backing.set(k, v),
    removeItem: (k: string) => void backing.delete(k),
  };
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const tick = () => new Promise((r) => setTimeout(r, 0));
const detail = (id: string) => ({
  conversation_id: id,
  auto_approve_steps: false,
  messages: [{ role: "user", content: "hi" }],
  artifacts: [],
});

test("a resume that lands after suspendForReauth() leaves the store unready, so sign-in resumes again", async () => {
  installStorage("conv-A");
  const stale = deferred<unknown>();
  let resumeCalls = 0;
  g.__chatTestApi = {
    getConfig: async () => ({}),
    resumeConversation: () => {
      resumeCalls += 1;
      return resumeCalls === 1 ? stale.promise : Promise.resolve(detail("conv-A"));
    },
    createSession: async () => ({ conversation_id: "conv-new", auto_approve_steps: false }),
  };

  const boot = chatStore.bootstrap("p");
  await tick();
  chatStore.suspendForReauth();
  stale.resolve(detail("conv-A"));
  await boot;
  assert.equal(readState().ready, false);

  await chatStore.bootstrap("p");
  assert.equal(resumeCalls, 2);
  assert.equal(readState().ready, true);
  assert.equal(readState().conversationId, "conv-A");
});

test("a resume that fails after suspendForReauth() adds no error and leaves the store unready", async () => {
  installStorage("conv-A");
  const stale = deferred<unknown>();
  g.__chatTestApi = {
    getConfig: async () => ({}),
    resumeConversation: () => stale.promise,
    createSession: async () => ({ conversation_id: "conv-new", auto_approve_steps: false }),
  };

  const boot = chatStore.bootstrap("p");
  await tick();
  chatStore.suspendForReauth();
  stale.reject(new ApiError(401, "Not authenticated"));
  await boot;

  assert.equal(readState().ready, false);
  assert.deepEqual(readState().items, []);
});

test("a bootstrap createSession superseded by a sidebar click does not take the conversation", async () => {
  installStorage(null);
  const create = deferred<unknown>();
  g.__chatTestApi = {
    getConfig: async () => ({}),
    createSession: () => create.promise,
    resumeConversation: async () => detail("conv-B"),
  };

  const boot = chatStore.bootstrap("p");
  await tick();
  await chatStore.loadConversation("conv-B");
  create.resolve({ conversation_id: "conv-new", auto_approve_steps: false });
  await boot;

  assert.equal(readState().ready, true);
  assert.equal(readState().conversationId, "conv-B");
});

test("a reload shows the resume marker during getConfig() and drops it when getConfig() fails", async () => {
  installStorage("conv-A");
  const config = deferred<unknown>();
  g.__chatTestApi = { getConfig: () => config.promise };

  const boot = chatStore.bootstrap("p");
  assert.equal(readState().resumingConversationId, "conv-A");
  config.reject(new Error("offline"));
  await boot;

  assert.equal(readState().resumingConversationId, null);
  assert.equal(readState().ready, true);
});

/* backgrounded: the detached task continues the turn's progress step (FE-10). */
type BgItem = { kind: string; history?: string[]; taskId?: string; turnId?: string; name?: string; done?: boolean };
const bgItems = () => readState().items as BgItem[];
const tools = () => bgItems().filter((it) => it.kind === "tool");

async function bootBackgroundConversation(id: string, api: Api): Promise<void> {
  installStorage(id);
  g.__chatTestApi = { getConfig: async () => ({}), resumeConversation: async () => detail(id), ...api };
  await chatStore.bootstrap("p");
}

test("a backgrounded turn reuses its progress step instead of adding a second row", async () => {
  const reply = deferred<unknown>();
  await bootBackgroundConversation("conv-B1", {
    sendMessage: () => reply.promise,
    getRecentConversations: async () => ({ conversations: [] }),
  });
  const sent = chatStore.sendTurn("run the UQ study");
  g.__chatTestStream.onStatus({
    type: "status",
    turn_id: "t1",
    message: "Invoking 'forward_sampling_uq'.",
    history: ["Next step: 'forward_sampling_uq'.", "Invoking 'forward_sampling_uq'."],
  });
  reply.resolve({ status: "backgrounded", turn_id: "t1", task_id: "bg-1", message: "Running in the background." });
  await sent;

  assert.equal(tools().length, 1, "one progress row for the turn");
  const step = tools()[0];
  assert.equal(step.turnId, "t1");
  assert.equal(step.taskId, "bg-1");
  assert.equal(step.name, "Running in the background.");
  assert.equal(step.done, false, "re-opened: the task is still running");
  assert.deepEqual(step.history, ["Next step: 'forward_sampling_uq'.", "Invoking 'forward_sampling_uq'."]);

  g.__chatTestStream.onTaskProgress({
    type: "task_progress",
    task_id: "bg-1",
    message: "waiting on forward_sampling_uq - Pipeline 7: running",
  });
  assert.equal(tools().length, 1);
  assert.deepEqual(tools()[0].history, [
    "Next step: 'forward_sampling_uq'.",
    "Invoking 'forward_sampling_uq'.",
    "waiting on forward_sampling_uq - Pipeline 7: running",
  ]);
});

test("a backgrounded turn with no status yet starts an empty progress step", async () => {
  await bootBackgroundConversation("conv-B2", {
    sendMessage: async () => ({ status: "backgrounded", turn_id: "t2", task_id: null, message: null }),
    getRecentConversations: async () => ({ conversations: [] }),
  });
  await chatStore.sendTurn("go");

  assert.equal(tools().length, 1);
  const step = tools()[0];
  assert.equal(step.turnId, "t2");
  assert.equal(step.taskId, undefined);
  assert.equal(step.name, "Running in the background…");
  assert.deepEqual(step.history, []);
  assert.equal(step.done, false);
});
