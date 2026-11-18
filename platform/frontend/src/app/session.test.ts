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

import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ApiError } from "@/lib/api/client";
import type { User } from "@/lib/api/types";

const api = vi.hoisted(() => ({ setupStatus: vi.fn(), me: vi.fn() }));
vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  api,
}));

const { setCurrentUser, getCurrentUser } = await import("@/features/auth");
const { AUTH_PROBE_BACKOFF_MS, resolveSession } = await import("./session.ts");

const USER: User = { identifier: "someone", role: "user", provider: "local" };
const denied = () => new ApiError(401, "Not authenticated");

beforeEach(() => {
  setCurrentUser(null);
  api.setupStatus.mockResolvedValue({ needs_setup: false });
});
afterEach(() => {
  vi.useRealTimers();
  vi.resetAllMocks();
});

test("a known user answers without asking the server", async () => {
  setCurrentUser(USER);
  expect(await resolveSession()).toEqual({ kind: "authed", user: USER });
  expect(api.setupStatus).not.toHaveBeenCalled();
});

test("a fresh install needs setup, and auth is not probed", async () => {
  api.setupStatus.mockResolvedValue({ needs_setup: true });
  expect(await resolveSession()).toEqual({ kind: "needs_setup" });
  expect(api.me).not.toHaveBeenCalled();
});

test("a live session is remembered as the current user", async () => {
  api.me.mockResolvedValue(USER);
  expect(await resolveSession()).toEqual({ kind: "authed", user: USER });
  expect(getCurrentUser()).toEqual(USER);
});

test("a 401 means signed out, at once", async () => {
  api.me.mockRejectedValue(denied());
  expect(await resolveSession()).toEqual({ kind: "unauthed" });
  expect(api.me).toHaveBeenCalledOnce();
});

test("a failed setup probe falls through to the auth probe", async () => {
  api.setupStatus.mockRejectedValue(new Error("admin-db down"));
  api.me.mockResolvedValue(USER);
  expect(await resolveSession()).toEqual({ kind: "authed", user: USER });
});

test("a network failure is retried on the backoff schedule, then gives up", async () => {
  vi.useFakeTimers();
  api.me.mockRejectedValue(new Error("proxy blip"));
  const session = resolveSession();
  for (const ms of AUTH_PROBE_BACKOFF_MS) await vi.advanceTimersByTimeAsync(ms);
  expect(await session).toEqual({ kind: "unauthed" });
  expect(api.me).toHaveBeenCalledTimes(AUTH_PROBE_BACKOFF_MS.length + 1);
});

test("a retry that succeeds signs the user in", async () => {
  vi.useFakeTimers();
  api.me.mockRejectedValueOnce(new ApiError(502, "Bad gateway")).mockResolvedValue(USER);
  const session = resolveSession();
  await vi.advanceTimersByTimeAsync(AUTH_PROBE_BACKOFF_MS[0]);
  expect(await session).toEqual({ kind: "authed", user: USER });
});

test("concurrent calls share one probe", async () => {
  api.me.mockRejectedValue(denied());
  await Promise.all([resolveSession(), resolveSession()]);
  expect(api.setupStatus).toHaveBeenCalledOnce();
});
