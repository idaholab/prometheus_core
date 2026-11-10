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
 * Holds the currently authenticated user, mainly so `role` is available
 * somewhere (App.tsx's boot probe used to just discard it). Same
 * useSyncExternalStore pattern as store/chat.ts, much smaller surface.
 *
 * Set from the three places identity is resolved: App.tsx's /api/auth/me
 * boot probe, Login.tsx's successful login, SetupWizard.tsx's successful
 * bootstrap. Cleared on logout (App.tsx's handleLogout).
 */
import { useSyncExternalStore } from "react";
import type { User } from "@/lib/api/types";

let state: User | null = null;
const listeners = new Set<() => void>();

function emit(): void {
  for (const l of listeners) l();
}

export function setCurrentUser(user: User | null): void {
  state = user;
  emit();
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}
function getSnapshot(): User | null {
  return state;
}

/** Subscribe a component to the current user (null while unauthenticated). */
export function useCurrentUser(): User | null {
  return useSyncExternalStore(subscribe, getSnapshot);
}
