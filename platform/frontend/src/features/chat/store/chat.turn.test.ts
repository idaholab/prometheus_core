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
import { MAX_RECHECKS, TURN_LEASE_MS, chatStore, useChatState as tapChatState } from "./chat.ts";

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
    {
      get:
        (_t, k: string) =>
        (...a: unknown[]) =>
          (globalThis as unknown as { __chatTestApi: Api }).__chatTestApi[k](...a),
    },
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
const kinds = () =>
  items().map((it) => (it.kind === "assistant" || it.kind === "user" ? `${it.kind}:${it.text}` : it.kind));
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
  let sessions = 0;
  g.__chatTestApi = {
    getConfig: async () => ({}),
    // The first session is conv-A; each New chat after it is a fresh conversation.
    createSession: async () => {
      sessions += 1;
      return {
        conversation_id: sessions === 1 ? "conv-A" : `conv-new-${sessions}`,
        auto_approve_steps: false,
      };
    },
    getRecentConversations: async () => ({ conversations: [] }),
    resumeConversation: async (id) => ({
      conversation_id: id,
      auto_approve_steps: false,
      messages: [],
      artifacts: [],
    }),
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

test("a 409 (turn id already sent) keeps waiting for the running copy's turn_done", async () => {
  const id = await send("q");
  getTurn = async () => ({ turn_id: id, state: "running" });
  sends[0].reply.reject(new ApiError(409, "This session already sent a turn with this turn_id"));
  await tick();
  assert.deepEqual(kinds(), ["user:q"]);
  assert.equal(readState().awaiting, true);
  stream().onTurnDone?.({ type: "turn_done", turn_id: id, response: answer(id, "a") });
  assert.deepEqual(kinds(), ["user:q", "assistant:a"]);
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

test("a reconnect lookup that reads 404 while the POST is in flight leaves the turn to the POST", async () => {
  const id = await send("q");
  getTurn = async () => {
    throw new ApiError(404, "No such turn."); // not started yet, or a backend without the route
  };
  stream().onOpen?.();
  await tick();
  assert.deepEqual(kinds(), ["user:q"]);
  assert.equal(readState().awaiting, true);

  sends[0].reply.resolve(answer(id, "a"));
  await tick();
  assert.deepEqual(kinds(), ["user:q", "assistant:a"]);
});

test("a stream (re)connect with no turn in flight reads nothing", async () => {
  stream().onOpen?.(); // getTurn would reject the test
  await tick();
  assert.deepEqual(kinds(), []);
});

test("another turn's turn_done (another tab) is ignored", async () => {
  await send("q");
  stream().onTurnDone?.({
    type: "turn_done",
    turn_id: "other-tab-turn",
    response: answer("other-tab-turn", "x"),
  });
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

/* --- the re-checks after the lease (backend/CONTRACT.md, GET /api/chat/turns) -------- */

/** Settle pending promises (and any 0 ms timer) under fake timers. */
const flush = () => vi.advanceTimersByTimeAsync(0);

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

test("re-checks are capped: a live turn answering 'running' again isn't polled", async () => {
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
    assert.equal(looked.length, 1 + MAX_RECHECKS, "one lookup, the capped re-checks, nothing more");
    assert.equal(readState().awaiting, true);

    stream().onTurnDone?.({ type: "turn_done", turn_id: id, response: answer(id, "a") });
    assert.deepEqual(kinds(), ["user:q", "assistant:a"]);
  } finally {
    vi.useRealTimers();
  }
});

test("a worker that dies after a late renewal still ends the turn at the next re-check", async () => {
  const id = await send("q");
  vi.useFakeTimers();
  try {
    let reads = 0;
    getTurn = async () => {
      reads += 1;
      if (reads >= 3) throw new ApiError(404, "No such turn."); // the lease finally ran out
      return { turn_id: id, state: "running" };
    };
    sends[0].reply.reject(new TypeError("Failed to fetch"));
    await flush();
    await vi.advanceTimersByTimeAsync(TURN_LEASE_MS + 10_000);
    assert.equal(reads, 2);
    assert.equal(readState().awaiting, true, "the first re-check still read 'running'");
    await vi.advanceTimersByTimeAsync(TURN_LEASE_MS + 10_000);
    assert.equal(reads, 3);
    assert.deepEqual(kinds(), ["user:q", "error"]);
    assert.equal(readState().awaiting, false);
  } finally {
    vi.useRealTimers();
  }
});

test("a lookup that fails outright after a dropped POST is retried after the lease", async () => {
  const id = await send("q");
  vi.useFakeTimers();
  try {
    let reads = 0;
    getTurn = async () => {
      reads += 1;
      if (reads === 1) throw new TypeError("Failed to fetch"); // backend briefly unreachable
      return { turn_id: id, state: "done", response: answer(id, "a") };
    };
    sends[0].reply.reject(new TypeError("Failed to fetch"));
    await flush();
    assert.equal(readState().awaiting, true);
    await vi.advanceTimersByTimeAsync(TURN_LEASE_MS + 10_000);
    assert.equal(reads, 2);
    assert.deepEqual(kinds(), ["user:q", "assistant:a"]);
  } finally {
    vi.useRealTimers();
  }
});

test("no re-check is armed while the POST is in flight", async () => {
  const id = await send("q");
  vi.useFakeTimers();
  try {
    let reads = 0;
    getTurn = async () => {
      reads += 1;
      return { turn_id: id, state: "running" };
    };
    stream().onOpen?.(); // a reconnect mid-turn reads once
    await flush();
    await vi.advanceTimersByTimeAsync(3 * TURN_LEASE_MS);
    assert.equal(reads, 1, "the pending POST settles the turn, not a timer");
    sends[0].reply.resolve(answer(id, "a"));
    await flush();
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
    await flush(); // the POST failure's lookup arms the re-check
    await vi.advanceTimersByTimeAsync(30_000);
    stream().onOpen?.();
    await flush();
    await vi.advanceTimersByTimeAsync(10_000);
    stream().onOpen?.();
    await flush();
    assert.equal(looked.length, 3, "each reconnect reads once");
    // Still the first one: due 65 s after the first lookup, not after a reconnect.
    await vi.advanceTimersByTimeAsync(TURN_LEASE_MS + 5_000 - 40_000 - 1);
    assert.equal(looked.length, 3, "not before it is due");
    await vi.advanceTimersByTimeAsync(1);
    assert.equal(looked.length, 4, "the one re-check, on time");
    // A reconnect that armed its own timer would fire at 30 s + 65 s = 95 s. The next
    // re-check comes 65 s after the first one (130 s), and it is the last.
    await vi.advanceTimersByTimeAsync(TURN_LEASE_MS);
    assert.equal(looked.length, 4, "no second timer from the reconnects");
    await vi.advanceTimersByTimeAsync(10 * TURN_LEASE_MS);
    assert.equal(looked.length, 5, "one lookup per reconnect, plus the capped re-checks");
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

test("a second send while a turn is running is refused, so the first reply still lands", async () => {
  const first = await send("first");
  void chatStore.sendTurn("second");
  await tick();
  assert.equal(sends.length, 1, "no second POST");
  assert.deepEqual(kinds(), ["user:first"]);

  sends[0].reply.resolve(answer(first, "R1"));
  await tick();
  assert.deepEqual(kinds(), ["user:first", "assistant:R1"]);
  assert.equal(readState().awaiting, false);
});

test("stop finishes the turn's progress step, and the stopped turn's later status is ignored", async () => {
  const id = await send("q");
  const tools = () => items().filter((it) => it.kind === "tool") as { done?: boolean; name?: string }[];
  stream().onStatus?.({ type: "status", turn_id: id, message: "Calling an agent" });
  assert.deepEqual(
    tools().map((t) => t.done),
    [false],
  );

  chatStore.stop();
  assert.deepEqual(
    tools().map((t) => t.done),
    [true],
  );
  stream().onStatus?.({ type: "status", turn_id: id, message: "Still going" });
  assert.deepEqual(
    tools().map((t) => [t.name, t.done]),
    [["Calling an agent", true]],
  );
});

test("another tab's status events add no progress step", async () => {
  await send("q");
  stream().onStatus?.({ type: "status", turn_id: "other-tab-turn", message: "x" });
  assert.deepEqual(kinds(), ["user:q"]);
});

/* --- the other ways a wait ends, and a stopped turn's pause ------------------------- */

test("switching away and back to a running turn waits for it again, and shows its reply", async () => {
  const id = await send("q");
  await chatStore.loadConversation("conv-B");
  assert.equal(readState().awaiting, false, "conv-B has no turn running");
  await chatStore.loadConversation("conv-A");
  assert.equal(readState().awaiting, true, "conv-A's turn is still running");
  stream().onTurnDone?.({ type: "turn_done", turn_id: id, response: answer(id, "a") });
  assert.deepEqual(kinds(), ["assistant:a"]);
  assert.equal(readState().awaiting, false);
});

test("a turn that ends while its conversation is away only refreshes the history list", async () => {
  const id = await send("q");
  await chatStore.loadConversation("conv-B");
  const version = readState().historyVersion as number;
  stream().onTurnDone?.({ type: "turn_done", turn_id: id, response: answer(id, "a") });
  assert.deepEqual(kinds(), []);
  assert.equal(readState().historyVersion, version + 1);
  await chatStore.loadConversation("conv-A");
  assert.equal(readState().awaiting, false, "its reply comes from the transcript now");
});

test("a new chat can send while the previous conversation's turn runs", async () => {
  const first = await send("q");
  await chatStore.reset();
  assert.equal(readState().awaiting, false);
  const second = await send("q2");
  assert.equal(sends.length, 2);
  stream().onTurnDone?.({ type: "turn_done", turn_id: first, response: answer(first, "a") });
  assert.deepEqual(kinds(), ["user:q2"], "conv-A's reply doesn't land in the new chat");
  assert.equal(readState().awaiting, true, "the new chat's own turn still runs");
  sends[1].reply.resolve(answer(second, "a2"));
  await tick();
  assert.deepEqual(kinds(), ["user:q2", "assistant:a2"]);
});

test("each conversation waits on its own turn", async () => {
  const a = await send("qa");
  await chatStore.loadConversation("conv-B");
  const b = await send("qb");
  assert.equal(sends.length, 2, "sending in conv-B isn't blocked by conv-A's turn");

  sends[0].reply.resolve(answer(a, "ra"));
  await tick();
  assert.deepEqual(kinds(), ["user:qb"]);
  assert.equal(readState().awaiting, true);

  sends[1].reply.resolve(answer(b, "rb"));
  await tick();
  assert.deepEqual(kinds(), ["user:qb", "assistant:rb"]);
  assert.equal(readState().awaiting, false);
});

test("stop ends only the turn of the conversation on screen", async () => {
  await send("qa");
  await chatStore.loadConversation("conv-B");
  await send("qb");
  chatStore.stop();
  assert.equal(readState().awaiting, false);
  await chatStore.loadConversation("conv-A");
  assert.equal(readState().awaiting, true, "conv-A's turn is still awaited");
});

test("a reconnect looks up every awaited turn", async () => {
  const a = await send("qa");
  await chatStore.loadConversation("conv-B");
  const b = await send("qb");
  const looked: string[] = [];
  getTurn = async (t) => {
    looked.push(t);
    return { turn_id: t, state: "running" };
  };
  stream().onOpen?.();
  await tick();
  assert.deepEqual(looked.sort(), [a, b].sort());
});

test("another conversation's status adds no step; back on it, the next status does", async () => {
  const a = await send("qa");
  await chatStore.loadConversation("conv-B");
  stream().onStatus?.({ type: "status", turn_id: a, message: "Calling an agent" });
  assert.deepEqual(kinds(), []);
  await chatStore.loadConversation("conv-A");
  stream().onStatus?.({
    type: "status",
    turn_id: a,
    message: "Still going",
    history: ["Calling an agent", "Still going"],
  });
  assert.deepEqual(kinds(), ["tool"]);
});

test("after suspendForReauth the old turn is no longer awaited", async () => {
  await send("q");
  const handlers = stream();
  chatStore.suspendForReauth();
  assert.equal(readState().awaiting, false);
  handlers.onOpen?.(); // a late reconnect of the old stream: getTurn would reject the test
  await tick();
  assert.deepEqual(kinds(), []);
});

test("after clear (logout) the old turn is no longer awaited", async () => {
  const id = await send("q");
  const handlers = stream();
  chatStore.clear();
  handlers.onTurnDone?.({ type: "turn_done", turn_id: id, response: answer(id, "a") });
  handlers.onOpen?.();
  await tick();
  assert.deepEqual(kinds(), []);
  assert.equal(readState().awaiting, false);
});

test("a stopped turn that paused at a form adds no form; the next message is sent as usual", async () => {
  const id = await send("q");
  chatStore.stop();
  stream().onTurnDone?.({
    type: "turn_done",
    turn_id: id,
    response: {
      turn_id: id,
      status: "needs_info",
      message: "Which material?",
      followup_questions: [{ id: "m", label: "Material", input_type: "text", required: true }],
    },
  });
  sends[0].reply.resolve({ turn_id: id, status: "needs_info", message: "Which material?" });
  await tick();
  assert.deepEqual(kinds(), ["user:q"]);

  await send("steel");
  assert.equal(sends.length, 2);
  assert.equal(sends[1].body.query, "steel");
});
