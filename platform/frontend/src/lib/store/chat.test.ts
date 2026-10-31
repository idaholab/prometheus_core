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

/* Turn recovery: a long turn whose POST reply is dropped is settled from the
 * stored transcript (turnRecovery.ts). Fake timers skip the grace period. */
const msgs = (assistants: number) => [
  { role: "user", content: "run it" },
  ...Array.from({ length: assistants }, (_, i) => ({ role: "assistant", content: `reply ${i}` })),
];

async function bootToConversation(id: string, api: Api): Promise<void> {
  installStorage(id);
  g.__chatTestApi = { getConfig: async () => ({}), resumeConversation: async () => detail(id), ...api };
  await chatStore.bootstrap("p");
}

test("a turn whose reply was dropped is settled from the stored transcript", async () => {
  vi.useFakeTimers();
  try {
    let stored = msgs(0);
    const post = deferred<unknown>(); // the POST reply never arrives
    await bootToConversation("conv-R", {
      getConversation: async () => ({ ...detail("conv-R"), messages: stored }),
      sendMessage: () => post.promise,
      getRecentConversations: async () => ({ conversations: [] }),
    });

    void chatStore.sendTurn("run it");
    await vi.advanceTimersByTimeAsync(0);
    assert.equal(readState().awaiting, true);

    await vi.advanceTimersByTimeAsync(60_000); // grace: first poll, nothing stored yet
    assert.equal(readState().awaiting, true);

    stored = msgs(1); // the backend finished and stored the reply
    await vi.advanceTimersByTimeAsync(15_000);
    assert.equal(readState().awaiting, false);
    const items = readState().items as { kind: string }[];
    assert.ok(items.some((it) => it.kind === "assistant"), "the stored reply is rendered");
  } finally {
    vi.useRealTimers();
  }
});

test("a turn answered by its POST reply never polls the transcript", async () => {
  vi.useFakeTimers();
  try {
    let polls = 0;
    await bootToConversation("conv-Q", {
      getConversation: async () => {
        polls += 1;
        return { ...detail("conv-Q"), messages: msgs(0) };
      },
      sendMessage: async () => ({ status: "message", message: "done", turn_id: "t1", artifacts: [] }),
      getRecentConversations: async () => ({ conversations: [] }),
    });

    await chatStore.sendTurn("quick");
    const baselineReads = polls; // the send-time baseline read
    await vi.advanceTimersByTimeAsync(120_000);
    assert.equal(polls, baselineReads, "no poll after the turn settled");
    assert.equal(readState().awaiting, false);
  } finally {
    vi.useRealTimers();
  }
});

test("a brand-new chat (404 baseline) still recovers its first reply", async () => {
  vi.useFakeTimers();
  try {
    let stored: ReturnType<typeof msgs> | null = null; // 404 until the first turn is stored
    const post = deferred<unknown>();
    await bootToConversation("conv-N", {
      getConversation: async () => {
        if (stored === null) throw new ApiError(404, "not found");
        return { ...detail("conv-N"), messages: stored };
      },
      sendMessage: () => post.promise,
      getRecentConversations: async () => ({ conversations: [] }),
    });

    void chatStore.sendTurn("first");
    await vi.advanceTimersByTimeAsync(60_000);
    assert.equal(readState().awaiting, true);
    stored = msgs(1);
    await vi.advanceTimersByTimeAsync(15_000);
    assert.equal(readState().awaiting, false);
  } finally {
    vi.useRealTimers();
  }
});

test("switching conversation stops the recovery poll", async () => {
  vi.useFakeTimers();
  try {
    let polls = 0;
    const post = deferred<unknown>();
    await bootToConversation("conv-S", {
      getConversation: async () => {
        polls += 1;
        return { ...detail("conv-S"), messages: msgs(0) };
      },
      sendMessage: () => post.promise,
      getRecentConversations: async () => ({ conversations: [] }),
    });
    void chatStore.sendTurn("long");
    await vi.advanceTimersByTimeAsync(0);
    g.__chatTestApi.resumeConversation = async () => detail("conv-T");
    await chatStore.loadConversation("conv-T");
    const before = polls;
    await vi.advanceTimersByTimeAsync(120_000);
    assert.equal(polls, before, "no poll for a conversation no longer on screen");
  } finally {
    vi.useRealTimers();
  }
});

type Item = { kind: string; text?: string; history?: string[]; taskId?: string; name?: string; done?: boolean };
const items = () => readState().items as Item[];
const tools = () => items().filter((it) => it.kind === "tool");

test("a backgrounded turn carries the turn's status log into its progress step", async () => {
  const reply = deferred<unknown>();
  await bootToConversation("conv-B1", {
    getConversation: async () => ({ ...detail("conv-B1"), messages: msgs(0) }),
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

  const step = tools().at(-1)!;
  assert.equal(step.taskId, "bg-1");
  assert.equal(step.name, "Running in the background.");
  assert.equal(step.done, false);
  assert.deepEqual(step.history, ["Next step: 'forward_sampling_uq'.", "Invoking 'forward_sampling_uq'."]);

  g.__chatTestStream.onTaskProgress({
    type: "task_progress",
    task_id: "bg-1",
    message: "waiting on forward_sampling_uq - Pipeline 7: running",
  });
  assert.deepEqual(tools().at(-1)!.history, [
    "Next step: 'forward_sampling_uq'.",
    "Invoking 'forward_sampling_uq'.",
    "waiting on forward_sampling_uq - Pipeline 7: running",
  ]);
});

test("a backgrounded turn with no status yet starts an empty progress step", async () => {
  await bootToConversation("conv-B2", {
    getConversation: async () => ({ ...detail("conv-B2"), messages: msgs(0) }),
    sendMessage: async () => ({ status: "backgrounded", turn_id: "t2", task_id: null, message: null }),
    getRecentConversations: async () => ({ conversations: [] }),
  });
  await chatStore.sendTurn("go");

  const step = tools().at(-1)!;
  assert.equal(step.taskId, undefined);
  assert.equal(step.name, "Running in the background…");
  assert.deepEqual(step.history, []);
});

test("a failed send shows the API error in the transcript", async () => {
  await bootToConversation("conv-E", {
    getConversation: async () => ({ ...detail("conv-E"), messages: msgs(0) }),
    sendMessage: async () => {
      throw new ApiError(502, "Bad gateway");
    },
    getRecentConversations: async () => ({ conversations: [] }),
  });
  await chatStore.sendTurn("hello");

  assert.equal(readState().awaiting, false);
  const last = items().at(-1);
  assert.equal(last?.kind, "error");
  assert.equal(last?.text, "Error communicating with agent: Bad gateway");
});

test("a send with no conversation yet renders the reply without watching the transcript", async () => {
  let reads = 0;
  g.__chatTestApi = {
    getConversation: async () => {
      reads += 1;
      return detail("x");
    },
    sendMessage: async () => ({ status: "answer", turn_id: "t3", response_text: "42", artifacts: [] }),
    getRecentConversations: async () => ({ conversations: [] }),
  };
  await chatStore.sendTurn("question");

  assert.equal(reads, 0);
  assert.equal(items().at(-1)?.kind, "assistant");
  assert.equal(items().at(-1)?.text, "42");
});

test("a POST reply that arrives after recovery settled the turn is ignored", async () => {
  vi.useFakeTimers();
  try {
    let stored = msgs(0);
    const post = deferred<unknown>();
    await bootToConversation("conv-L", {
      getConversation: async () => ({ ...detail("conv-L"), messages: stored }),
      sendMessage: () => post.promise,
      getRecentConversations: async () => ({ conversations: [] }),
    });
    const sent = chatStore.sendTurn("long run");
    await vi.advanceTimersByTimeAsync(0);
    stored = msgs(1);
    await vi.advanceTimersByTimeAsync(60_000);
    assert.equal(readState().awaiting, false);
    const before = items().length;

    post.resolve({ status: "answer", turn_id: "t4", response_text: "late copy", artifacts: [] });
    await sent;
    assert.equal(items().length, before, "the late reply adds no second answer");
  } finally {
    vi.useRealTimers();
  }
});

test("a POST failure that arrives after recovery settled the turn adds no error", async () => {
  vi.useFakeTimers();
  try {
    let stored = msgs(0);
    const post = deferred<unknown>();
    await bootToConversation("conv-L2", {
      getConversation: async () => ({ ...detail("conv-L2"), messages: stored }),
      sendMessage: () => post.promise,
      getRecentConversations: async () => ({ conversations: [] }),
    });
    const sent = chatStore.sendTurn("long run");
    await vi.advanceTimersByTimeAsync(0);
    stored = msgs(1);
    await vi.advanceTimersByTimeAsync(60_000);

    post.reject(new ApiError(504, "Gateway timeout"));
    await sent;
    assert.ok(!items().some((it) => it.kind === "error"));
  } finally {
    vi.useRealTimers();
  }
});

test("an unreadable baseline (not a 404) turns recovery off", async () => {
  vi.useFakeTimers();
  try {
    let reads = 0;
    const post = deferred<unknown>();
    await bootToConversation("conv-U", {
      getConversation: async () => {
        reads += 1;
        throw new ApiError(500, "Internal error");
      },
      sendMessage: () => post.promise,
      getRecentConversations: async () => ({ conversations: [] }),
    });
    void chatStore.sendTurn("run");
    await vi.advanceTimersByTimeAsync(180_000);
    assert.equal(reads, 1, "only the baseline read, no polls");
    assert.equal(readState().awaiting, true);
  } finally {
    vi.useRealTimers();
  }
});

test("pressing stop while a recovery read is in flight discards its result", async () => {
  vi.useFakeTimers();
  try {
    let reads = 0;
    const inFlight = deferred<unknown>();
    await bootToConversation("conv-P", {
      getConversation: () => {
        reads += 1;
        return reads === 1 ? Promise.resolve({ ...detail("conv-P"), messages: msgs(0) }) : inFlight.promise;
      },
      sendMessage: () => deferred<unknown>().promise,
      getRecentConversations: async () => ({ conversations: [] }),
    });
    void chatStore.sendTurn("run");
    await vi.advanceTimersByTimeAsync(60_000); // the first poll is now waiting on inFlight
    chatStore.stop();
    inFlight.resolve({ ...detail("conv-P"), messages: msgs(1) });
    await vi.advanceTimersByTimeAsync(60_000);

    assert.ok(!items().some((it) => it.kind === "assistant"), "the stopped turn is not filled in");
    assert.equal(reads, 2);
  } finally {
    vi.useRealTimers();
  }
});

test("pressing stop while a failing recovery read is in flight stops the retries", async () => {
  vi.useFakeTimers();
  try {
    let reads = 0;
    const inFlight = deferred<unknown>();
    await bootToConversation("conv-P2", {
      getConversation: () => {
        reads += 1;
        return reads === 1 ? Promise.resolve({ ...detail("conv-P2"), messages: msgs(0) }) : inFlight.promise;
      },
      sendMessage: () => deferred<unknown>().promise,
      getRecentConversations: async () => ({ conversations: [] }),
    });
    void chatStore.sendTurn("run");
    await vi.advanceTimersByTimeAsync(60_000);
    chatStore.stop();
    inFlight.reject(new Error("backend restarting"));
    await vi.advanceTimersByTimeAsync(120_000);

    assert.equal(reads, 2, "no retry after stop");
  } finally {
    vi.useRealTimers();
  }
});
