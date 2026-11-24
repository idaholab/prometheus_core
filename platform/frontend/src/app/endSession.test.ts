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

/* Every way a session ends: what chat keeps, that the user is forgotten, and
 * that the server-data cache is dropped only after the caller has navigated
 * away (a reset refetches every mounted query, which would 401). */
import { beforeEach, expect, test, vi } from "vitest";

const calls: string[] = [];
vi.mock("@/features/auth", () => ({
  setCurrentUser: (user: unknown) => calls.push(`setCurrentUser(${String(user)})`),
}));
vi.mock("@/features/chat", () => ({
  chatStore: {
    clear: () => calls.push("chat.clear"),
    suspendForReauth: () => calls.push("chat.suspendForReauth"),
  },
}));

vi.mock("@/lib/api/baseApi", () => ({
  baseApi: { util: { resetApiState: () => ({ type: "api/resetApiState" }) } },
}));
vi.mock("@/lib/api/store", () => ({
  appStore: { dispatch: (action: { type: string }) => calls.push(`dispatch(${action.type})`) },
}));

const { endSession } = await import("./endSession.ts");

beforeEach(() => {
  calls.length = 0;
});

test("logging out forgets chat's conversation and the user, leaves, then drops the cache", async () => {
  await endSession("logout", () => void calls.push("leave"));
  expect(calls).toEqual(["chat.clear", "setCurrentUser(null)", "leave", "dispatch(api/resetApiState)"]);
});

test("a lost session keeps chat's conversation for after sign-in, and drops the cache after leaving", async () => {
  await endSession("lost", () => void calls.push("leave"));
  expect(calls).toEqual([
    "chat.suspendForReauth",
    "setCurrentUser(null)",
    "leave",
    "dispatch(api/resetApiState)",
  ]);
});

test("drops the cache only once the navigation has finished", async () => {
  await endSession("lost", async () => {
    await Promise.resolve();
    calls.push("left");
  });
  expect(calls.slice(-2)).toEqual(["left", "dispatch(api/resetApiState)"]);
});
