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

/** Remembers which conversation this tab has open, so a page reload lands back
 * in it instead of an empty new chat.
 *
 * `sessionStorage`, not `localStorage`, on purpose: it is **per-tab**, so each
 * tab reloads into the conversation it last showed. The tabs still share one
 * server session (keyed by the cookie's `sid`), so the next turn from any tab
 * goes to the conversation that was bound last. The id also dies with the tab,
 * which is the right lifetime — the id is a
 * convenience for surviving a reload, not a durable user preference (the
 * durable copy is Valkey's, reachable through the history sidebar).
 *
 * Every access is wrapped: Safari in private browsing, and any browser with
 * site data blocked, throw on `sessionStorage` rather than returning null.
 * Losing the id is a degraded-but-working experience (you get a new chat, like
 * before this existed), so it must never break bootstrap.
 */

const STORAGE_KEY = "prometheus.openConversationId";

export function readOpenConversationId(): string | null {
  try {
    const v = sessionStorage.getItem(STORAGE_KEY);
    return v ? v : null;
  } catch {
    return null;
  }
}

export function saveOpenConversationId(id: string | null): void {
  try {
    if (id) sessionStorage.setItem(STORAGE_KEY, id);
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Non-fatal: see the module comment.
  }
}
