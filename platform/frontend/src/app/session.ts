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

/**
 * Works out who the visitor is, for the route guards. Moved from App.tsx's
 * boot sequence when the router landed. JSX-free, so it can be tested in Node.
 */
import { api, ApiError } from "@/lib/api/client";
import type { User } from "@/lib/api/types";
import { getCurrentUser, setCurrentUser } from "@/features/auth";

export type SessionStatus = { kind: "needs_setup" } | { kind: "unauthed" } | { kind: "authed"; user: User };

/** Retry schedule for the auth probe, in ms. Only a real 401/403 means "not
 * signed in"; a network failure or 5xx means "ask again shortly". Short and
 * finite: after the last attempt we give up and show Login, which is at least
 * an actionable screen. */
export const AUTH_PROBE_BACKOFF_MS = [500, 1500, 3000];

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

// Treating *any* me() failure as "unauthenticated" is what made a transient
// proxy blip look like being logged out: the dev log has several
// `http proxy error: /api/auth/me — getaddrinfo ENOTFOUND backend`, each of
// which dropped the user to Login and lost their chat. Only 401/403 is an
// answer about identity; everything else is a question to ask again.
async function probeAuth(): Promise<SessionStatus> {
  for (let attempt = 0; ; attempt++) {
    try {
      const user = await api.me();
      setCurrentUser(user);
      return { kind: "authed", user };
    } catch (err) {
      const definitive = err instanceof ApiError && (err.status === 401 || err.status === 403);
      if (definitive || attempt >= AUTH_PROBE_BACKOFF_MS.length) return { kind: "unauthed" };
      await wait(AUTH_PROBE_BACKOFF_MS[attempt]);
    }
  }
}

// Setup status goes first: while no admin exists, /api/auth/me would just 401
// regardless. If the setup probe itself fails (e.g. admin-db unreachable), fall
// through to the auth probe rather than getting stuck.
async function probe(): Promise<SessionStatus> {
  try {
    if ((await api.setupStatus()).needs_setup) return { kind: "needs_setup" };
  } catch {
    /* fall through to the auth probe */
  }
  return probeAuth();
}

let pending: Promise<SessionStatus> | null = null;

/**
 * The visitor's session. A known user answers at once, with no request; else
 * the server is asked. Guards on a parent and child route run at the same
 * time, so concurrent calls share one probe.
 */
export function resolveSession(): Promise<SessionStatus> {
  const user = getCurrentUser();
  if (user) return Promise.resolve({ kind: "authed", user });
  pending ??= probe().finally(() => {
    pending = null;
  });
  return pending;
}
