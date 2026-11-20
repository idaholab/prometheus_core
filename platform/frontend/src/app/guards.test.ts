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

import { beforeEach, expect, test, vi } from "vitest";
import type { LoaderFunctionArgs } from "react-router";
import type { User } from "@/lib/api/types";
import type { SessionStatus } from "./session.ts";

const resolveSession = vi.hoisted(() => vi.fn<() => Promise<SessionStatus>>());
vi.mock("./session.ts", () => ({ resolveSession }));
const { guestOnly, requireAdmin, requireUser, setupOnly } = await import("./guards.ts");

const USER: User = { identifier: "someone", role: "user", provider: "local" };
const ADMIN: User = { ...USER, role: "admin" };

const args = (url: string) => ({ request: new Request(`http://app${url}`), params: {}, context: {} }) as LoaderFunctionArgs;
const as = (session: SessionStatus) => resolveSession.mockResolvedValue(session);

/** Where a guard sends the visitor, or null when it lets them in. */
async function outcome(run: () => Promise<unknown>): Promise<string | null> {
  try {
    await run();
    return null;
  } catch (thrown) {
    if (thrown instanceof Response) return thrown.headers.get("Location");
    throw thrown;
  }
}

beforeEach(() => resolveSession.mockReset());

test("requireUser lets a signed-in user in", async () => {
  as({ kind: "authed", user: USER });
  expect(await outcome(() => requireUser(args("/workflows")))).toBeNull();
});

test("requireUser sends a signed-out visitor to Login, remembering the page", async () => {
  as({ kind: "unauthed" });
  expect(await outcome(() => requireUser(args("/workflows?x=1")))).toBe("/login?next=%2Fworkflows%3Fx%3D1");
});

test("requireUser sends a fresh install to Setup", async () => {
  as({ kind: "needs_setup" });
  expect(await outcome(() => requireUser(args("/")))).toBe("/setup");
});

test("requireAdmin lets an admin in and sends anyone else Home", async () => {
  as({ kind: "authed", user: ADMIN });
  expect(await outcome(() => requireAdmin(args("/admin")))).toBeNull();
  as({ kind: "authed", user: USER });
  expect(await outcome(() => requireAdmin(args("/admin")))).toBe("/");
  as({ kind: "unauthed" });
  expect(await outcome(() => requireAdmin(args("/admin")))).toBe("/login?next=%2Fadmin");
});

test("guestOnly shows Login to a signed-out visitor", async () => {
  as({ kind: "unauthed" });
  expect(await outcome(() => guestOnly(args("/login")))).toBeNull();
});

test("guestOnly sends a signed-in visitor on, but never off-site", async () => {
  as({ kind: "authed", user: USER });
  expect(await outcome(() => guestOnly(args("/login?next=%2Fworkflows")))).toBe("/workflows");
  expect(await outcome(() => guestOnly(args("/login?next=https%3A%2F%2Fevil.example")))).toBe("/");
  as({ kind: "needs_setup" });
  expect(await outcome(() => guestOnly(args("/login")))).toBe("/setup");
});

test("setupOnly is open only while setup is needed", async () => {
  as({ kind: "needs_setup" });
  expect(await outcome(() => setupOnly())).toBeNull();
  as({ kind: "unauthed" });
  expect(await outcome(() => setupOnly())).toBe("/login");
  as({ kind: "authed", user: USER });
  expect(await outcome(() => setupOnly())).toBe("/");
});
