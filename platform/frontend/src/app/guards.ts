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
 * Route loaders that decide whether a route may open, and where to send the
 * visitor if not. They gate access only: pages load their own data. JSX-free,
 * so they can be tested in Node.
 */
import { redirect, type LoaderFunctionArgs } from "react-router";
import { loginPathFor, PATHS, safeNextPath } from "./paths";
import { resolveSession } from "./session";

function fromUrl(request: Request): { path: string; next: string | null } {
  const url = new URL(request.url);
  return { path: url.pathname + url.search, next: url.searchParams.get("next") };
}

/** Signed-in routes. A signed-out visitor goes to Login, which returns them
 * here; a fresh install goes to Setup. */
export async function requireUser({ request }: LoaderFunctionArgs) {
  const session = await resolveSession();
  if (session.kind === "needs_setup") throw redirect(PATHS.setup);
  if (session.kind === "unauthed") throw redirect(loginPathFor(fromUrl(request).path));
  return null;
}

/** Admin-only routes. Anyone else is sent Home and never sees the page. Runs
 * alongside requireUser on the parent route, so it checks sign-in itself. */
export async function requireAdmin(args: LoaderFunctionArgs) {
  await requireUser(args);
  const session = await resolveSession();
  if (session.kind === "authed" && session.user.role !== "admin") throw redirect(PATHS.home);
  return null;
}

/** Login. A signed-in visitor goes on to where they were headed. */
export async function guestOnly({ request }: LoaderFunctionArgs) {
  const session = await resolveSession();
  if (session.kind === "authed") throw redirect(safeNextPath(fromUrl(request).next));
  if (session.kind === "needs_setup") throw redirect(PATHS.setup);
  return null;
}

/** First-run setup. Once an admin exists it's closed: signed-in visitors go
 * Home, everyone else to Login. */
export async function setupOnly() {
  const session = await resolveSession();
  if (session.kind === "authed") throw redirect(PATHS.home);
  if (session.kind === "unauthed") throw redirect(PATHS.login);
  return null;
}
