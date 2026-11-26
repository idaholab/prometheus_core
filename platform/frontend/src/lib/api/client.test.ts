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
  const calls: [string, RequestInit | undefined][] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  });
  return calls;
}

test("getTurn reads GET /api/chat/turns/{turn_id} with the auth cookie", async () => {
  const state = { turn_id: "t-1", state: "running", response: null };
  const calls = stubFetch(200, state);
  assert.deepEqual(await api.getTurn("t-1"), state);
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], "/api/chat/turns/t-1");
  assert.equal(calls[0][1]?.method ?? "GET", "GET");
  assert.equal(calls[0][1]?.credentials, "include");
});

test("getTurn's 404 is an ApiError carrying the status", async () => {
  stubFetch(404, { detail: "No such turn." });
  await assert.rejects(
    api.getTurn("t-1"),
    (err: unknown) => err instanceof ApiError && err.status === 404 && err.message === "No such turn.",
  );
});
