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
 * that the caller's navigation runs last. */
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

const { endSession } = await import("./endSession.ts");

beforeEach(() => {
  calls.length = 0;
});

test("logging out forgets chat's conversation and the user, then leaves", async () => {
  await endSession("logout", () => void calls.push("leave"));
  expect(calls).toEqual(["chat.clear", "setCurrentUser(null)", "leave"]);
});

test("a lost session keeps chat's conversation for after sign-in, forgets the user, then leaves", async () => {
  await endSession("lost", () => void calls.push("leave"));
  expect(calls).toEqual(["chat.suspendForReauth", "setCurrentUser(null)", "leave"]);
});

test("waits for the navigation to finish", async () => {
  let left = false;
  await endSession("lost", async () => {
    await Promise.resolve();
    left = true;
  });
  expect(left).toBe(true);
});
