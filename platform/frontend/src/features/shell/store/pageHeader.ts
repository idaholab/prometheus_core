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
 * Lets the active page override the app header's title and breadcrumb. Header
 * reads it; pages set it with `usePageHeader`. Same useSyncExternalStore
 * pattern as store/session.ts.
 */
import { useEffect, useSyncExternalStore } from "react";

export interface PageHeaderOverride {
  /** Page title, when it differs from the nav label (e.g. Approval Queue's
   * "Human-in-the-Loop Checkpoint Console"). The breadcrumb keeps the nav label. */
  title?: string;
  /** Breadcrumb segments after the nav label, for screens reached from a nav
   * section (e.g. ["Workflow Builder"] under Workflows). The last one is the
   * current page. Also used as the title when `title` is unset. */
  trail?: string[];
}

let state: PageHeaderOverride | null = null;
const listeners = new Set<() => void>();

function set(next: PageHeaderOverride | null): void {
  state = next;
  for (const l of listeners) l();
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}
function getSnapshot(): PageHeaderOverride | null {
  return state;
}

/** The current page's override, or null when it hasn't set one. Read by Header. */
export function usePageHeaderOverride(): PageHeaderOverride | null {
  return useSyncExternalStore(subscribe, getSnapshot);
}

/**
 * Set the header title and/or breadcrumb trail for the calling page. Clears
 * the override when the page unmounts, so it relies on the page unmounting
 * on navigation. Don't call it from Home, which stays mounted while hidden.
 */
export function usePageHeader({ title, trail }: PageHeaderOverride): void {
  // Serialise the trail so a fresh array literal on every render doesn't
  // re-fire the effect.
  const trailKey = trail ? JSON.stringify(trail) : undefined;

  useEffect(() => {
    set({ title, trail: trailKey ? (JSON.parse(trailKey) as string[]) : undefined });
    return () => set(null);
  }, [title, trailKey]);
}
