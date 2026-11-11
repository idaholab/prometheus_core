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

/* The sign-in calls global-setup.ts makes, checked on their own. By the time a
 * test runs, global setup has created the admin, so signInAsAdmin takes the
 * branch it takes on a stack that already has users: sign in, not create. A
 * fresh CI stack never takes that branch in global setup itself. */
import { expect, test } from "./fixtures";
import { E2E_ADMIN, signInAsAdmin } from "./global-setup";

// Start with no session, so each call below is what signs in (or fails to)
test.use({ storageState: { cookies: [], origins: [] } });

test("signing in to a stack that already has its admin gives a session the backend accepts", async ({ request }) => {
  // The premise: the admin exists, so this is the sign-in branch, not the create one
  const setup = await request.get("/api/setup/status");
  expect(await setup.json()).toEqual({ needs_setup: false });

  const signIn = await signInAsAdmin(request);
  expect(signIn.status()).toBe(200);
  expect(await signIn.json()).toMatchObject({ user: { identifier: E2E_ADMIN.username, role: "admin" } });

  // The cookie from that response is what makes /me answer
  const me = await request.get("/api/auth/me");
  expect(me.status()).toBe(200);
  expect(await me.json()).toMatchObject({ identifier: E2E_ADMIN.username, role: "admin" });
});

test("a wrong password is refused and leaves no session", async ({ request }) => {
  // Posted directly: signInAsAdmin would create the admin with this password on a stack with no users
  const signIn = await request.post("/api/auth/login", { data: { ...E2E_ADMIN, password: "not-the-password" } });
  expect(signIn.status()).toBe(401);
  expect(await signIn.json()).toEqual({ detail: "Invalid credentials" });

  expect((await request.get("/api/auth/me")).status()).toBe(401);
});
