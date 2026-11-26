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

/* `openEventStream` against a fake `EventSource`: the event names it listens for are the
 * backend's `type` discriminators (`backend/CONTRACT.md`), and close() removes them all. */

import assert from "node:assert/strict";
import { afterEach, beforeEach, test, vi } from "vitest";
import { openEventStream } from "./events.ts";

class FakeEventSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  static last: FakeEventSource | null = null;
  readyState = FakeEventSource.CONNECTING;
  closed = false;
  listeners = new Map<string, Set<(ev: Event) => void>>();
  constructor(
    public url: string,
    public init?: EventSourceInit,
  ) {
    FakeEventSource.last = this;
  }
  addEventListener(type: string, fn: (ev: Event) => void) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)!.add(fn);
  }
  removeEventListener(type: string, fn: (ev: Event) => void) {
    this.listeners.get(type)?.delete(fn);
  }
  close() {
    this.closed = true;
    this.readyState = FakeEventSource.CLOSED;
  }
  emit(type: string, data?: unknown) {
    const ev = (data === undefined ? { type } : { type, data: JSON.stringify(data) }) as unknown as Event;
    for (const fn of this.listeners.get(type) ?? []) fn(ev);
  }
  count() {
    let n = 0;
    for (const set of this.listeners.values()) n += set.size;
    return n;
  }
}

const source = () => {
  assert.ok(FakeEventSource.last, "no EventSource opened");
  return FakeEventSource.last;
};

beforeEach(() => {
  FakeEventSource.last = null;
  vi.stubGlobal("EventSource", FakeEventSource);
});
afterEach(() => vi.unstubAllGlobals());

test("opens /api/events with the auth cookie", () => {
  openEventStream({});
  assert.equal(source().url, "/api/events");
  assert.equal(source().init?.withCredentials, true);
});

test("each backend event type reaches its handler, parsed", () => {
  const got: [string, unknown][] = [];
  openEventStream({
    onStatus: (e) => got.push(["status", e]),
    onTaskProgress: (e) => got.push(["task_progress", e]),
    onTaskDone: (e) => got.push(["task_done", e]),
    onTurnDone: (e) => got.push(["turn_done", e]),
  });
  const turnDone = { type: "turn_done", turn_id: "t1", response: { turn_id: "t1", status: "answer" } };
  source().emit("status", { type: "status", turn_id: "t1", message: "m" });
  source().emit("task_progress", { type: "task_progress", task_id: "k", message: "p" });
  source().emit("task_done", { type: "task_done", task_id: "k" });
  source().emit("turn_done", turnDone);
  assert.deepEqual(
    got.map(([k]) => k),
    ["status", "task_progress", "task_done", "turn_done"],
  );
  assert.deepEqual(got[3][1], turnDone);
});

test("an event whose data isn't JSON is dropped", () => {
  const got: unknown[] = [];
  openEventStream({ onTurnDone: (e) => got.push(e) });
  for (const fn of source().listeners.get("turn_done") ?? []) fn({ data: "not json" } as unknown as Event);
  assert.deepEqual(got, []);
});

test("onOpen fires on every (re)connect", () => {
  let opens = 0;
  openEventStream({ onOpen: () => (opens += 1) });
  source().emit("open");
  source().emit("open");
  assert.equal(opens, 2);
});

test("onError says whether the stream is closed for good", () => {
  const got: boolean[] = [];
  openEventStream({ onError: ({ closed }) => got.push(closed) });
  source().emit("error");
  source().readyState = FakeEventSource.CLOSED;
  source().emit("error");
  assert.deepEqual(got, [false, true]);
});

test("close() removes every listener and closes the source", () => {
  const close = openEventStream({
    onStatus: () => {},
    onTaskProgress: () => {},
    onTaskDone: () => {},
    onTurnDone: () => {},
    onOpen: () => {},
    onError: () => {},
  });
  assert.equal(source().count(), 6);
  close();
  assert.equal(source().count(), 0);
  assert.equal(source().closed, true);
});
