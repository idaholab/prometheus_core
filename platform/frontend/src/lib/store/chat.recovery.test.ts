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

const detail = (id: string) => ({
  conversation_id: id,
  auto_approve_steps: false,
  messages: [{ role: "user", content: "hi" }],
  artifacts: [],
});

/* Turn recovery: a long turn whose POST reply is dropped is settled from the
 * stored transcript (turnRecovery.ts). Fake timers skip the grace period. */
type Msg = { role: "user" | "assistant"; content: string; artifact_ids?: string[] };
const user = (content: string): Msg => ({ role: "user", content });
const reply = (content: string, artifact_ids: string[] = []): Msg => ({ role: "assistant", content, artifact_ids });

type Item = { kind: string; text?: string; done?: boolean; turnId?: string; artifacts?: { artifact_id: string }[] };
const items = () => readState().items as Item[];

async function bootToConversation(id: string, api: Api): Promise<void> {
  installStorage(id);
  g.__chatTestApi = {
    getConfig: async () => ({}),
    resumeConversation: async () => ({ ...detail(id), messages: [] }),
    getRecentConversations: async () => ({ available: true, conversations: [] }),
    ...api,
  };
  await chatStore.bootstrap("p");
  chatStore.connect(); // capture the SSE handlers; tests here feed status events
}

async function withFakeTimers(body: () => Promise<void>): Promise<void> {
  vi.useFakeTimers();
  try {
    await body();
  } finally {
    vi.useRealTimers();
  }
}

test("a turn whose reply was dropped is settled from the stored transcript", () =>
  withFakeTimers(async () => {
    let stored: Msg[] = [];
    const post = deferred<unknown>(); // the POST reply never arrives
    await bootToConversation("conv-R", {
      getConversation: async () => ({ ...detail("conv-R"), messages: stored, artifacts: [{ artifact_id: "a1" }] }),
      sendMessage: () => post.promise,
    });

    void chatStore.sendTurn("run it");
    await vi.advanceTimersByTimeAsync(0);
    assert.equal(readState().awaiting, true);

    stored = [user("run it")]; // stored as the turn starts
    await vi.advanceTimersByTimeAsync(60_000); // grace: first poll, no reply yet
    assert.equal(readState().awaiting, true);

    stored = [user("run it"), reply("the result", ["a1"])]; // the backend finished
    await vi.advanceTimersByTimeAsync(15_000);
    assert.equal(readState().awaiting, false);
    const last = items().at(-1)!;
    assert.equal(last.kind, "assistant");
    assert.equal(last.text, "the result");
    assert.deepEqual(last.artifacts?.map((a) => a.artifact_id), ["a1"], "the turn's artifacts come with it");
  }));

test("recovery appends the reply and keeps every item already on screen", () =>
  withFakeTimers(async () => {
    const earlier = [user("q1"), reply("which mesh?")];
    let stored: Msg[] = earlier;
    const post = deferred<unknown>();
    await bootToConversation("conv-K", {
      resumeConversation: async () => ({ ...detail("conv-K"), messages: earlier }),
      getConversation: async () => ({ ...detail("conv-K"), messages: stored }),
      sendMessage: () => post.promise,
    });
    void chatStore.sendTurn("run it");
    await vi.advanceTimersByTimeAsync(0);
    // A live progress trace on screen; the transcript can't rebuild it.
    g.__chatTestStream.onStatus({ type: "status", turn_id: "t1", message: "Invoking 'solver'." });
    const before = items().map((it) => it.kind);

    stored = [...earlier, user("run it"), reply("done")];
    await vi.advanceTimersByTimeAsync(60_000);

    assert.deepEqual(items().map((it) => it.kind), [...before, "assistant"], "nothing dropped, one reply added");
    assert.equal(items().find((it) => it.kind === "tool")?.done, true, "the trace is closed, not removed");
  }));

test("another tab's reply in the same conversation does not settle this turn", () =>
  withFakeTimers(async () => {
    const earlier = [user("q1"), reply("a1")];
    let stored: Msg[] = earlier;
    const post = deferred<unknown>();
    await bootToConversation("conv-T2", {
      getConversation: async () => ({ ...detail("conv-T2"), messages: stored }),
      sendMessage: () => post.promise,
    });
    void chatStore.sendTurn("mine");
    await vi.advanceTimersByTimeAsync(0);

    stored = [...earlier, user("mine"), user("theirs"), reply("their reply")];
    await vi.advanceTimersByTimeAsync(75_000);
    assert.equal(readState().awaiting, true, "an unattributable reply is not taken");
    assert.ok(!items().some((it) => it.text === "their reply"));

    post.resolve({ status: "answer", turn_id: "t1", response_text: "my reply", artifacts: [] });
    await vi.advanceTimersByTimeAsync(0);
    assert.equal(readState().awaiting, false);
    assert.equal(items().at(-1)?.text, "my reply");
  }));

test("a recovered reply that asked for input says its form was not recovered", () =>
  withFakeTimers(async () => {
    let stored: Msg[] = [];
    const post = deferred<unknown>();
    await bootToConversation("conv-F", {
      getConversation: async () => ({ ...detail("conv-F"), messages: stored }),
      getRecentConversations: async () => ({
        available: true,
        conversations: [{ conversation_id: "conv-F", status: "needs_info" }],
      }),
      sendMessage: () => post.promise,
    });
    void chatStore.sendTurn("set up a run");
    await vi.advanceTimersByTimeAsync(0);
    stored = [user("set up a run"), reply("Which solver?")];
    await vi.advanceTimersByTimeAsync(60_000);

    const text = items().at(-1)?.text ?? "";
    assert.ok(text.startsWith("Which solver?"));
    assert.match(text, /form could not be recovered/);
    assert.equal(readState().awaiting, false);
  }));

test("a recovered final answer carries no input notice", () =>
  withFakeTimers(async () => {
    let stored: Msg[] = [];
    await bootToConversation("conv-C", {
      getConversation: async () => ({ ...detail("conv-C"), messages: stored }),
      getRecentConversations: async () => ({
        available: true,
        conversations: [{ conversation_id: "conv-C", status: "completed" }],
      }),
      sendMessage: () => deferred<unknown>().promise,
    });
    void chatStore.sendTurn("go");
    await vi.advanceTimersByTimeAsync(0);
    stored = [user("go"), reply("Report ready.")];
    await vi.advanceTimersByTimeAsync(60_000);
    assert.equal(items().at(-1)?.text, "Report ready.");
  }));

test("a turn answered by its POST reply never polls the transcript", () =>
  withFakeTimers(async () => {
    let reads = 0;
    await bootToConversation("conv-Q", {
      getConversation: async () => {
        reads += 1;
        return { ...detail("conv-Q"), messages: [] };
      },
      sendMessage: async () => ({ status: "answer", response_text: "done", turn_id: "t1", artifacts: [] }),
    });
    await chatStore.sendTurn("quick");
    const baselineReads = reads;
    await vi.advanceTimersByTimeAsync(120_000);
    assert.equal(reads, baselineReads, "no poll after the turn settled");
    assert.equal(readState().awaiting, false);
  }));

test("a brand-new chat (404 baseline) still recovers its first reply", () =>
  withFakeTimers(async () => {
    let stored: Msg[] | null = null; // 404 until the first turn is stored
    await bootToConversation("conv-N", {
      getConversation: async () => {
        if (stored === null) throw new ApiError(404, "not found");
        return { ...detail("conv-N"), messages: stored };
      },
      sendMessage: () => deferred<unknown>().promise,
    });
    void chatStore.sendTurn("first");
    await vi.advanceTimersByTimeAsync(60_000);
    assert.equal(readState().awaiting, true);
    stored = [user("first"), reply("hello")];
    await vi.advanceTimersByTimeAsync(15_000);
    assert.equal(readState().awaiting, false);
    assert.equal(items().at(-1)?.text, "hello");
  }));

test("a plan decision is not watched: its turn stores no user message to match", () =>
  withFakeTimers(async () => {
    let reads = 0;
    await bootToConversation("conv-D", {
      getConversation: async () => {
        reads += 1;
        return { ...detail("conv-D"), messages: [] };
      },
      sendMessage: () => deferred<unknown>().promise,
    });
    void chatStore.decidePlan("none", true);
    await vi.advanceTimersByTimeAsync(120_000);
    assert.equal(reads, 0);
  }));

test("switching conversation stops the recovery poll", () =>
  withFakeTimers(async () => {
    let reads = 0;
    await bootToConversation("conv-S", {
      getConversation: async () => {
        reads += 1;
        return { ...detail("conv-S"), messages: [] };
      },
      sendMessage: () => deferred<unknown>().promise,
    });
    void chatStore.sendTurn("long");
    await vi.advanceTimersByTimeAsync(0);
    g.__chatTestApi.resumeConversation = async () => detail("conv-T");
    await chatStore.loadConversation("conv-T");
    const before = reads;
    await vi.advanceTimersByTimeAsync(120_000);
    assert.equal(reads, before, "no poll for a conversation no longer on screen");
  }));

test("a failed send shows the API error in the transcript", async () => {
  await bootToConversation("conv-E", {
    getConversation: async () => ({ ...detail("conv-E"), messages: [] }),
    sendMessage: async () => {
      throw new ApiError(502, "Bad gateway");
    },
  });
  await chatStore.sendTurn("hello");
  assert.equal(readState().awaiting, false);
  assert.equal(items().at(-1)?.kind, "error");
  assert.equal(items().at(-1)?.text, "Error communicating with agent: Bad gateway");
});

test("a send with no conversation yet renders the reply without watching the transcript", async () => {
  let reads = 0;
  g.__chatTestApi = {
    getConversation: async () => {
      reads += 1;
      return detail("x");
    },
    sendMessage: async () => ({ status: "answer", turn_id: "t3", response_text: "42", artifacts: [] }),
    getRecentConversations: async () => ({ available: true, conversations: [] }),
  };
  await chatStore.sendTurn("question");
  assert.equal(reads, 0);
  assert.equal(items().at(-1)?.text, "42");
});

test("a POST reply that arrives after recovery settled the turn is ignored", () =>
  withFakeTimers(async () => {
    let stored: Msg[] = [];
    const post = deferred<unknown>();
    await bootToConversation("conv-L", {
      getConversation: async () => ({ ...detail("conv-L"), messages: stored }),
      sendMessage: () => post.promise,
    });
    const sent = chatStore.sendTurn("long run");
    await vi.advanceTimersByTimeAsync(0);
    stored = [user("long run"), reply("stored copy")];
    await vi.advanceTimersByTimeAsync(60_000);
    assert.equal(readState().awaiting, false);
    const before = items().length;

    post.resolve({ status: "answer", turn_id: "t4", response_text: "late copy", artifacts: [] });
    await sent;
    assert.equal(items().length, before, "the late reply adds no second answer");
  }));

test("a POST failure that arrives after recovery settled the turn adds no error", () =>
  withFakeTimers(async () => {
    let stored: Msg[] = [];
    const post = deferred<unknown>();
    await bootToConversation("conv-L2", {
      getConversation: async () => ({ ...detail("conv-L2"), messages: stored }),
      sendMessage: () => post.promise,
    });
    const sent = chatStore.sendTurn("long run");
    await vi.advanceTimersByTimeAsync(0);
    stored = [user("long run"), reply("stored copy")];
    await vi.advanceTimersByTimeAsync(60_000);
    post.reject(new ApiError(504, "Gateway timeout"));
    await sent;
    assert.ok(!items().some((it) => it.kind === "error"));
  }));

test("an unreadable baseline (not a 404) turns recovery off", () =>
  withFakeTimers(async () => {
    let reads = 0;
    await bootToConversation("conv-U", {
      getConversation: async () => {
        reads += 1;
        throw new ApiError(500, "Internal error");
      },
      sendMessage: () => deferred<unknown>().promise,
    });
    void chatStore.sendTurn("run");
    await vi.advanceTimersByTimeAsync(180_000);
    assert.equal(reads, 1, "only the baseline read, no polls");
    assert.equal(readState().awaiting, true);
  }));

test("pressing stop while a recovery read is in flight discards its result", () =>
  withFakeTimers(async () => {
    let reads = 0;
    const inFlight = deferred<unknown>();
    await bootToConversation("conv-P", {
      getConversation: () => {
        reads += 1;
        return reads === 1 ? Promise.resolve({ ...detail("conv-P"), messages: [] }) : inFlight.promise;
      },
      sendMessage: () => deferred<unknown>().promise,
    });
    void chatStore.sendTurn("run");
    await vi.advanceTimersByTimeAsync(60_000); // the first poll is now waiting on inFlight
    chatStore.stop();
    inFlight.resolve({ ...detail("conv-P"), messages: [user("run"), reply("late")] });
    await vi.advanceTimersByTimeAsync(60_000);
    assert.ok(!items().some((it) => it.kind === "assistant"), "the stopped turn is not filled in");
    assert.equal(reads, 2);
  }));

test("pressing stop while a failing recovery read is in flight stops the retries", () =>
  withFakeTimers(async () => {
    let reads = 0;
    const inFlight = deferred<unknown>();
    await bootToConversation("conv-P2", {
      getConversation: () => {
        reads += 1;
        return reads === 1 ? Promise.resolve({ ...detail("conv-P2"), messages: [] }) : inFlight.promise;
      },
      sendMessage: () => deferred<unknown>().promise,
    });
    void chatStore.sendTurn("run");
    await vi.advanceTimersByTimeAsync(60_000);
    chatStore.stop();
    inFlight.reject(new Error("backend restarting"));
    await vi.advanceTimersByTimeAsync(120_000);
    assert.equal(reads, 2, "no retry after stop");
  }));

test("pressing stop while the input-status read is in flight leaves the turn unfilled", () =>
  withFakeTimers(async () => {
    let stored: Msg[] = [];
    const recent = deferred<unknown>();
    await bootToConversation("conv-I", {
      getConversation: async () => ({ ...detail("conv-I"), messages: stored }),
      sendMessage: () => deferred<unknown>().promise,
    });
    void chatStore.sendTurn("set up a run");
    await vi.advanceTimersByTimeAsync(0);
    // Only the recovery's input-status read waits; the boot read already returned.
    g.__chatTestApi.getRecentConversations = () => recent.promise;
    stored = [user("set up a run"), reply("Which solver?")];
    await vi.advanceTimersByTimeAsync(60_000); // the poll found the reply, now reading the status
    chatStore.stop();
    recent.resolve({ available: true, conversations: [{ conversation_id: "conv-I", status: "needs_info" }] });
    await vi.advanceTimersByTimeAsync(0);
    assert.ok(!items().some((it) => it.kind === "assistant"), "the stopped turn is not filled in");
    assert.equal(readState().awaiting, false);
  }));

test("an unreadable history list recovers the reply with no input notice", () =>
  withFakeTimers(async () => {
    let stored: Msg[] = [];
    await bootToConversation("conv-H", {
      getConversation: async () => ({ ...detail("conv-H"), messages: stored }),
      sendMessage: () => deferred<unknown>().promise,
    });
    void chatStore.sendTurn("go");
    await vi.advanceTimersByTimeAsync(0);
    g.__chatTestApi.getRecentConversations = async () => {
      throw new ApiError(503, "unavailable");
    };
    stored = [user("go"), reply("Which solver?")];
    await vi.advanceTimersByTimeAsync(60_000);
    assert.equal(items().at(-1)?.text, "Which solver?", "best effort: treated as not waiting on input");
    assert.equal(readState().awaiting, false);
  }));
