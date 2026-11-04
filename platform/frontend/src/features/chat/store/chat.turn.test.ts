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

/* A chat turn settles exactly once, from its POST reply or its `turn_done` event,
 * whichever arrives first, and only while it is still the turn this tab waits on
 * (issue #334; `backend/CONTRACT.md`, "Delivery"). The harness is chat.test.ts's, plus
 * a stream stub that hands the test the store's event handlers. */

import assert from "node:assert/strict";
import { afterEach, beforeEach, test, vi } from "vitest";
import { ApiError } from "@/lib/api/client";
import type { EventStreamHandlers } from "@/lib/api/events";
import type { ChatMessageRequest, ChatMessageResponse } from "@/lib/api/types";
import { TURN_LEASE_MS, chatStore, useChatState as tapChatState } from "./chat.ts";

vi.mock("react", () => ({
  useSyncExternalStore: (_sub: unknown, get: () => unknown) => {
    (globalThis as Record<string, unknown>).__chatTestTap = get;
    return get();
  },
}));
vi.mock("@/lib/api/events", () => ({
  openEventStream: (h: unknown) => {
    (globalThis as Record<string, unknown>).__chatTestStream = h;
    return () => {
      (globalThis as Record<string, unknown>).__chatTestStream = null;
    };
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
type Item = { kind: string; text?: string };
const g = globalThis as unknown as {
  __chatTestApi: Api;
  __chatTestTap: () => Record<string, unknown>;
  __chatTestStream: EventStreamHandlers | null;
  sessionStorage: unknown;
};

tapChatState();
const readState = () => g.__chatTestTap();
const items = () => readState().items as Item[];
const kinds = () => items().map((it) => (it.kind === "assistant" || it.kind === "user" ? `${it.kind}:${it.text}` : it.kind));
const stream = () => {
  assert.ok(g.__chatTestStream, "stream not connected");
  return g.__chatTestStream;
};

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
const answer = (turnId: string, text: string): ChatMessageResponse => ({
  turn_id: turnId,
  status: "answer",
  response_text: text,
});

/** The POSTs this test's turns send, each held until the test settles it. */
let sends: { body: ChatMessageRequest; reply: ReturnType<typeof deferred<ChatMessageResponse>> }[];
let getTurn: (id: string) => Promise<unknown>;

beforeEach(async () => {
  const backing = new Map<string, string>();
  g.sessionStorage = {
    getItem: (k: string) => backing.get(k) ?? null,
    setItem: (k: string, v: string) => void backing.set(k, v),
    removeItem: (k: string) => void backing.delete(k),
  };
  sends = [];
  getTurn = () => Promise.reject(new Error("getTurn not expected"));
  g.__chatTestApi = {
    getConfig: async () => ({}),
    createSession: async () => ({ conversation_id: "conv-A", auto_approve_steps: false }),
    getRecentConversations: async () => ({ conversations: [] }),
    resumeConversation: async (id) => ({ conversation_id: id, auto_approve_steps: false, messages: [], artifacts: [] }),
    sendMessage: (body) => {
      const reply = deferred<ChatMessageResponse>();
      sends.push({ body: body as ChatMessageRequest, reply });
      return reply.promise;
    },
    getTurn: (id) => getTurn(id as string),
  };
  await chatStore.bootstrap();
  chatStore.connect();
});
afterEach(() => chatStore.clear());

/** Send `text` and return its turn id. */
async function send(text: string): Promise<string> {
  void chatStore.sendTurn(text);
  await tick();
  const id = sends.at(-1)?.body.turn_id;
  assert.ok(id, "the POST carries a turn id");
  return id;
}

test("each turn sends a fresh turn id and settles from its POST reply", async () => {
  const id = await send("q1");
  assert.equal(readState().awaiting, true);
  sends[0].reply.resolve(answer(id, "a1"));
  await tick();
  assert.deepEqual(kinds(), ["user:q1", "assistant:a1"]);
  assert.equal(readState().awaiting, false);

  const id2 = await send("q2");
  assert.notEqual(id2, id);
});

test("turn_done first, then the POST reply: one answer", async () => {
  const id = await send("q");
  stream().onTurnDone?.({ type: "turn_done", turn_id: id, response: answer(id, "a") });
  assert.equal(readState().awaiting, false);
  sends[0].reply.resolve(answer(id, "a"));
  await tick();
  assert.deepEqual(kinds(), ["user:q", "assistant:a"]);
});

test("POST reply first, then turn_done: one answer", async () => {
  const id = await send("q");
  sends[0].reply.resolve(answer(id, "a"));
  await tick();
  stream().onTurnDone?.({ type: "turn_done", turn_id: id, response: answer(id, "a") });
  assert.deepEqual(kinds(), ["user:q", "assistant:a"]);
});

test("a dropped POST is settled by turn_done", async () => {
  const id = await send("q");
  getTurn = async () => ({ turn_id: id, state: "running" });
  sends[0].reply.reject(new TypeError("Failed to fetch"));
  await tick();
  assert.equal(readState().awaiting, true, "still running server-side");
  stream().onTurnDone?.({ type: "turn_done", turn_id: id, response: answer(id, "a") });
  assert.deepEqual(kinds(), ["user:q", "assistant:a"]);
  assert.equal(readState().awaiting, false);
});

test("a dropped POST of a turn that already finished is settled by one lookup", async () => {
  const id = await send("q");
  const looked: string[] = [];
  getTurn = async (t) => {
    looked.push(t);
    return { turn_id: id, state: "done", response: answer(id, "a") };
  };
  sends[0].reply.reject(new TypeError("Failed to fetch"));
  await tick();
  assert.deepEqual(looked, [id]);
  assert.deepEqual(kinds(), ["user:q", "assistant:a"]);
});

test("a gateway timeout is treated like a dropped POST", async () => {
  const id = await send("q");
  getTurn = async () => ({ turn_id: id, state: "done", response: answer(id, "a") });
  sends[0].reply.reject(new ApiError(504, "Gateway Timeout"));
  await tick();
  assert.deepEqual(kinds(), ["user:q", "assistant:a"]);
});

test("a dropped POST the backend never saw ends the turn with an error", async () => {
  const id = await send("q");
  getTurn = async () => {
    throw new ApiError(404, "No such turn.");
  };
  sends[0].reply.reject(new TypeError("Failed to fetch"));
  await tick();
  assert.deepEqual(kinds(), ["user:q", "error"]);
  assert.equal(readState().awaiting, false);
  void id;
});

test("a backend error reply is shown as is, with no lookup", async () => {
  await send("q");
  sends[0].reply.reject(new ApiError(422, "bad request"));
  await tick();
  assert.deepEqual(kinds(), ["user:q", "error"]);
  assert.equal(readState().awaiting, false);
});

test("a stream reconnect asks once where the awaited turn stands", async () => {
  const id = await send("q");
  getTurn = async () => ({ turn_id: id, state: "running" });
  sends[0].reply.reject(new TypeError("Failed to fetch"));
  await tick();
  assert.equal(readState().awaiting, true);

  getTurn = async () => ({ turn_id: id, state: "done", response: answer(id, "a") });
  stream().onOpen?.();
  await tick();
  assert.deepEqual(kinds(), ["user:q", "assistant:a"]);
  assert.equal(readState().awaiting, false);
});

test("a stream (re)connect with no turn in flight reads nothing", async () => {
  stream().onOpen?.(); // getTurn would reject the test
  await tick();
  assert.deepEqual(kinds(), []);
});

test("another turn's turn_done (another tab) is ignored", async () => {
  await send("q");
  stream().onTurnDone?.({ type: "turn_done", turn_id: "other-tab-turn", response: answer("other-tab-turn", "x") });
  assert.deepEqual(kinds(), ["user:q"]);
  assert.equal(readState().awaiting, true);
});

test("stop, then resend: the stopped turn's late reply and turn_done are ignored", async () => {
  const first = await send("first");
  chatStore.stop();
  const second = await send("second");

  sends[0].reply.resolve(answer(first, "R1"));
  stream().onTurnDone?.({ type: "turn_done", turn_id: first, response: answer(first, "R1") });
  await tick();
  assert.deepEqual(kinds(), ["user:first", "user:second"]);
  assert.equal(readState().awaiting, true, "the second turn is still running");

  sends[1].reply.resolve(answer(second, "R2"));
  await tick();
  assert.deepEqual(kinds(), ["user:first", "user:second", "assistant:R2"]);
  assert.equal(readState().awaiting, false);
});

test("a settled turn's late POST failure doesn't end the next turn", async () => {
  const first = await send("first");
  stream().onTurnDone?.({ type: "turn_done", turn_id: first, response: answer(first, "R1") });
  await send("second");

  sends[0].reply.reject(new ApiError(500, "late"));
  await tick();
  assert.equal(readState().awaiting, true);
  assert.deepEqual(kinds(), ["user:first", "assistant:R1", "user:second"]);
});

test("a turn_done after switching conversation adds nothing to the one on screen", async () => {
  const id = await send("q");
  await chatStore.loadConversation("conv-B");
  stream().onTurnDone?.({ type: "turn_done", turn_id: id, response: answer(id, "a") });
  sends[0].reply.resolve(answer(id, "a"));
  await tick();
  assert.deepEqual(kinds(), []);
  assert.equal(readState().awaiting, false);
});

test("an auto-approved plan delivered by turn_done starts the next turn", async () => {
  const id = await send("q");
  stream().onTurnDone?.({
    type: "turn_done",
    turn_id: id,
    response: { turn_id: id, status: "plan_ready", plan: { steps: [] }, auto_approve: true },
  });
  await tick();
  assert.equal(sends.length, 2);
  assert.equal(sends[1].body.plan_approved, true);
  assert.equal(readState().awaiting, true, "the approval turn is in flight");
});

/* --- the one re-check after the lease (backend/CONTRACT.md, GET /api/chat/turns) -------- */

/** Flush the promise chain a timer callback starts. */
const flush = async () => {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
};

test("a 'running' lookup is checked once more after the lease; a dead worker's turn then ends", async () => {
  const id = await send("q");
  vi.useFakeTimers();
  try {
    const looked: string[] = [];
    let answer: "running" | "gone" = "running";
    getTurn = async (t) => {
      looked.push(t);
      if (answer === "gone") throw new ApiError(404, "No such turn.");
      return { turn_id: id, state: "running" };
    };
    sends[0].reply.reject(new TypeError("Failed to fetch"));
    await flush();
    assert.deepEqual(looked, [id]);
    assert.equal(readState().awaiting, true);

    answer = "gone"; // the worker died; its lease ran out
    await vi.advanceTimersByTimeAsync(TURN_LEASE_MS - 1);
    assert.deepEqual(looked, [id], "not before the lease");
    await vi.advanceTimersByTimeAsync(10_000);
    await flush();
    assert.deepEqual(looked, [id, id]);
    assert.deepEqual(kinds(), ["user:q", "error"]);
    assert.equal(readState().awaiting, false);
  } finally {
    vi.useRealTimers();
  }
});

test("the re-check happens once: a live turn answering 'running' again isn't polled", async () => {
  const id = await send("q");
  vi.useFakeTimers();
  try {
    const looked: string[] = [];
    getTurn = async (t) => {
      looked.push(t);
      return { turn_id: id, state: "running" };
    };
    sends[0].reply.reject(new TypeError("Failed to fetch"));
    await flush();
    await vi.advanceTimersByTimeAsync(10 * TURN_LEASE_MS);
    await flush();
    assert.deepEqual(looked, [id, id], "one lookup, one re-check, nothing more");
    assert.equal(readState().awaiting, true);

    stream().onTurnDone?.({ type: "turn_done", turn_id: id, response: answer(id, "a") });
    assert.deepEqual(kinds(), ["user:q", "assistant:a"]);
  } finally {
    vi.useRealTimers();
  }
});

test("repeated reconnects keep a single pending re-check", async () => {
  const id = await send("q");
  vi.useFakeTimers();
  try {
    const looked: string[] = [];
    getTurn = async (t) => {
      looked.push(t);
      return { turn_id: id, state: "running" };
    };
    sends[0].reply.reject(new TypeError("Failed to fetch"));
    await flush();
    stream().onOpen?.();
    stream().onOpen?.();
    await flush();
    assert.equal(looked.length, 3, "each reconnect reads once");
    await vi.advanceTimersByTimeAsync(2 * TURN_LEASE_MS);
    await flush();
    assert.equal(looked.length, 4, "but only one re-check is scheduled");
  } finally {
    vi.useRealTimers();
  }
});

test("a turn settled before the re-check is due cancels it", async () => {
  const id = await send("q");
  vi.useFakeTimers();
  try {
    const looked: string[] = [];
    getTurn = async (t) => {
      looked.push(t);
      return { turn_id: id, state: "running" };
    };
    sends[0].reply.reject(new TypeError("Failed to fetch"));
    await flush();
    stream().onTurnDone?.({ type: "turn_done", turn_id: id, response: answer(id, "a") });
    await vi.advanceTimersByTimeAsync(2 * TURN_LEASE_MS);
    await flush();
    assert.deepEqual(looked, [id]);
    assert.deepEqual(kinds(), ["user:q", "assistant:a"]);
  } finally {
    vi.useRealTimers();
  }
});

// Covers the outcome, not the mechanism: stop() cancels the timer, and the timer's own
// activeTurn check would also make it a no-op, so either alone keeps this passing.
test("a stopped turn's pending re-check can't end the next turn", async () => {
  const first = await send("first");
  vi.useFakeTimers();
  try {
    const looked: string[] = [];
    getTurn = async (t) => {
      looked.push(t as string);
      if (looked.length > 1) throw new ApiError(404, "No such turn.");
      return { turn_id: first, state: "running" };
    };
    sends[0].reply.reject(new TypeError("Failed to fetch"));
    await flush();
    chatStore.stop();
    void chatStore.sendTurn("second");
    await flush();
    await vi.advanceTimersByTimeAsync(2 * TURN_LEASE_MS);
    await flush();
    assert.deepEqual(looked, [first]);
    assert.equal(readState().awaiting, true, "the second turn is still running");
  } finally {
    vi.useRealTimers();
  }
});
