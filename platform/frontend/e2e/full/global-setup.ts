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

/* Runs once before the full-stack tests: makes sure the e2e stack has the test
 * admin and saves a signed-in session that every test starts from.
 *
 * On a fresh stack, the setup wizard's endpoint creates the admin. On a stack
 * that already has users, it signs in instead, so a rerun against the same
 * stack works. The credentials are made up and only exist in the e2e stack. */
import { request, type APIRequestContext, type FullConfig } from "@playwright/test";

export const E2E_ADMIN = { username: "e2e-admin", password: "e2e-password-not-secret" };

/** Signs in as the test admin, creating it first if the stack has no users yet.
 * Returns the response; the caller decides what a failure means. Throws if the
 * stack's setup status can't be read. Once the admin exists it only takes the
 * sign-in branch, which e2e/full/sign-in-api.spec.ts covers. */
export async function signInAsAdmin(api: APIRequestContext) {
  const status = await api.get("/api/setup/status", { timeout: 10_000 });
  if (!status.ok()) throw new Error(`HTTP ${status.status()}`);
  const { needs_setup } = (await status.json()) as { needs_setup: boolean };
  return needs_setup
    ? api.post("/api/setup/bootstrap", { data: E2E_ADMIN })
    : api.post("/api/auth/login", { data: E2E_ADMIN });
}

export default async function globalSetup(config: FullConfig) {
  const { baseURL, storageState } = config.projects[0].use;
  const api = await request.newContext({ baseURL });

  const signIn = await signInAsAdmin(api).catch((error: Error) => {
    throw new Error(
      `The e2e stack isn't answering at ${baseURL} (${error.message.split("\n")[0]}). Start it with ` +
        "`make up-e2e` in platform/, or set E2E_BASE_URL.",
    );
  });
  if (!signIn.ok()) {
    throw new Error(
      `Couldn't sign in as ${E2E_ADMIN.username} (${signIn.status()}): ${await signIn.text()}. ` +
        "The stack's first admin was made by someone else; use a fresh e2e stack.",
    );
  }

  await api.storageState({ path: storageState as string });
  await api.dispose();
}
