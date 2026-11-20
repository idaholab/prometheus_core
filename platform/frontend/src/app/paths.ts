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
 * Every URL in the app, in one place. Links, redirects and the route table
 * all read from here, so a workspace prefix (e.g. /org/:org/project/:project)
 * can be added later by changing this file alone. JSX-free, so it can be
 * tested in Node.
 */
import type { NavId } from "@/features/shell";

export const PATHS = {
  login: "/login",
  setup: "/setup",
  home: "/",
  agentRegistry: "/agent-registry",
  workflows: "/workflows",
  approvalQueue: "/approval-queue",
  projectManagement: "/project-management",
  dataManagement: "/data-management",
  jobsConsole: "/jobs-console",
  admin: "/admin",
} as const;

/** The URL of each sidebar destination. */
export const NAV_PATHS: Record<NavId, string> = {
  home: PATHS.home,
  "agent-registry": PATHS.agentRegistry,
  workflows: PATHS.workflows,
  "approval-queue": PATHS.approvalQueue,
  "project-management": PATHS.projectManagement,
  "data-management": PATHS.dataManagement,
  "jobs-console": PATHS.jobsConsole,
  admin: PATHS.admin,
};

/** The sidebar destination a URL belongs to, or null for one outside the nav
 * (e.g. a not-found URL). A nested URL such as /workflows/builder belongs to
 * its section. */
export function navIdForPath(pathname: string): NavId | null {
  let match: NavId | null = null;
  let matchLength = -1;
  for (const [id, path] of Object.entries(NAV_PATHS) as [NavId, string][]) {
    const hit = path === "/" ? pathname === "/" : pathname === path || pathname.startsWith(`${path}/`);
    if (hit && path.length > matchLength) {
      match = id;
      matchLength = path.length;
    }
  }
  return match;
}

/**
 * Where to go after signing in: the `next` query value when it names a page
 * inside the app, else Home. Anything else (another origin, a protocol-relative
 * `//host` URL, or the auth screens themselves) falls back to Home, so a
 * crafted link can't bounce a user off-site.
 */
export function safeNextPath(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return PATHS.home;
  const pathname = next.split(/[?#]/)[0];
  if (pathname === PATHS.login || pathname === PATHS.setup) return PATHS.home;
  return next;
}

/** The login URL that returns to `from` (path + search + hash) once signed in. */
export function loginPathFor(from: string): string {
  const next = safeNextPath(from);
  return next === PATHS.home ? PATHS.login : `${PATHS.login}?next=${encodeURIComponent(next)}`;
}
