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
import { request, type FullConfig } from "@playwright/test";

export const E2E_ADMIN = { username: "e2e-admin", password: "e2e-password-not-secret" };

export default async function globalSetup(config: FullConfig) {
  const { baseURL, storageState } = config.projects[0].use;
  const api = await request.newContext({ baseURL });

  const notRunning = (why: string) =>
    new Error(
      `The e2e stack isn't answering at ${baseURL} (${why}). Start it with ` +
        "`make up-e2e` in platform/, or set E2E_BASE_URL.",
    );
  const status = await api.get("/api/setup/status", { timeout: 10_000 }).catch((error: Error) => {
    throw notRunning(error.message.split("\n")[0]);
  });
  if (!status.ok()) throw notRunning(`HTTP ${status.status()}`);
  const { needs_setup } = (await status.json()) as { needs_setup: boolean };
  const signIn = needs_setup
    ? await api.post("/api/setup/bootstrap", { data: E2E_ADMIN })
    : await api.post("/api/auth/login", { data: E2E_ADMIN });
  if (!signIn.ok()) {
    throw new Error(
      `Couldn't sign in as ${E2E_ADMIN.username} (${signIn.status()}): ${await signIn.text()}. ` +
        "The stack's first admin was made by someone else; use a fresh e2e stack.",
    );
  }

  await api.storageState({ path: storageState as string });
  await api.dispose();
}
